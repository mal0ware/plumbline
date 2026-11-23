"""Synthetic markets with a known answer, for tests and for the fast run.

Each market follows a Brownian motion X on [0, T] and settles to 1 if X_T > 0.
The fair price at time t is

    q_t = Phi( X_t / sqrt(T - t) )

which is a martingale and calibrated by construction. A bias is planted by
quoting p_t = sigmoid( logit(q_t) / slope ) instead: with slope > 1 quoted
prices are pulled towards one half, so longshots are overpriced and outcomes
follow sigmoid( slope * logit(p) ). That is a favourite-longshot bias of known
size, and logistic recalibration should return the slope.
"""

from __future__ import annotations

from math import erf, sqrt

import numpy as np

from plumbline import config
from plumbline.markets import CATEGORIES, Market, Quote

START_TS = 1_700_000_000


def _phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def distort(q: float, slope: float) -> float:
    """Quoted price for a fair probability ``q`` under a planted bias ``slope``."""
    clipped = min(max(q, 1e-9), 1.0 - 1e-9)
    odds = np.log(clipped / (1.0 - clipped)) / slope
    return float(1.0 / (1.0 + np.exp(-odds)))


def simulate_markets(
    n_events: int,
    *,
    seed: int,
    slope: float = 1.0,
    venue: str = "synthetic",
    markets_per_event: int = 2,
    spread: float = 0.0,
    fee_rate: float = 0.0,
) -> list[tuple[Market, list[Quote]]]:
    """Simulate ``n_events`` events, each with correlated markets and daily quotes.

    Markets in one event share half of their Brownian increments, so their
    outcomes are correlated and the event is the right unit to resample.
    """
    rng = np.random.default_rng(seed)
    pairs: list[tuple[Market, list[Quote]]] = []
    for event in range(n_events):
        life = int(rng.integers(3, 61))
        common = rng.standard_normal(life)
        for member in range(markets_per_event):
            own = rng.standard_normal(life)
            steps = (common + own) / sqrt(2.0)
            start = float(rng.standard_normal()) * sqrt(life) * 0.5
            path = start + np.cumsum(steps)
            open_ts = START_TS + int(rng.integers(0, 400)) * config.DAY
            close_ts = open_ts + life * config.DAY
            quotes: list[Quote] = []
            for day in range(life):
                level = start if day == 0 else float(path[day - 1])
                fair = _phi(level / sqrt(life - day))
                price = distort(fair, slope)
                bid = max(price - spread / 2.0, 0.0)
                ask = min(price + spread / 2.0, 1.0)
                quotes.append(
                    Quote(
                        ts=open_ts + day * config.DAY,
                        price=price,
                        bid=bid if spread > 0 else None,
                        ask=ask if spread > 0 else None,
                    )
                )
            market = Market(
                venue=venue,
                market_id=f"{venue}-{event}-{member}",
                cluster=f"{venue}-{event}",
                title=f"synthetic event {event}, market {member}",
                category=CATEGORIES[event % len(CATEGORIES)],
                open_ts=open_ts,
                close_ts=close_ts,
                outcome=int(path[-1] > 0.0),
                volume=1_000_000.0,
                yes_no=True,
                fee_rate=fee_rate,
            )
            pairs.append((market, quotes))
    return pairs
