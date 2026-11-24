"""Reading one price per market at a fixed moment, without looking ahead.

An observation pairs a price that was visible at some moment with the outcome
that settled later. Two rules keep the pairing honest:

1. Only a market with a settled outcome of 0 or 1 produces an observation.
2. The price is the latest quote at or before the chosen moment, and no older
   than a staleness limit. A quote from after that moment is never used.

``cluster`` is the market's event. ``unit`` is what the bootstrap resamples:
the series where the sample was drawn by series, the event otherwise.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass

import pandas as pd

from plumbline import config
from plumbline.markets import Market, Quote


@dataclass(frozen=True)
class Observation:
    venue: str
    market_id: str
    cluster: str
    unit: str
    category: str
    yes_no: bool
    kind: str
    days: int
    close_ts: int
    quote_ts: int
    price: float
    bid: float
    ask: float
    fee_rate: float
    volume: float
    outcome: int


def price_at(quotes: list[Quote], when: int, max_age: float) -> Quote | None:
    """The latest quote with ``when - max_age <= ts <= when``, or ``None``.

    ``quotes`` must be sorted by time.
    """
    position = bisect_right([quote.ts for quote in quotes], when)
    if position == 0:
        return None
    quote = quotes[position - 1]
    if when - quote.ts > max_age:
        return None
    return quote


def _observation(market: Market, quote: Quote, kind: str, days: int) -> Observation:
    assert market.outcome is not None
    return Observation(
        venue=market.venue,
        market_id=market.market_id,
        cluster=market.cluster,
        unit=market.series or market.cluster,
        category=market.category,
        yes_no=market.yes_no,
        kind=kind,
        days=days,
        close_ts=market.close_ts,
        quote_ts=quote.ts,
        price=quote.price,
        bid=float("nan") if quote.bid is None else quote.bid,
        ask=float("nan") if quote.ask is None else quote.ask,
        fee_rate=market.fee_rate,
        volume=market.volume,
        outcome=market.outcome,
    )


def before_close(market: Market, quotes: list[Quote], days: int) -> Observation | None:
    """The price ``days`` before the close, if the market was open and quoted then."""
    if market.outcome not in (0, 1):
        return None
    when = market.close_ts - days * config.DAY
    if when < market.open_ts:
        return None
    quote = price_at(quotes, when, config.MAX_STALENESS_HOURS * 3600.0)
    if quote is None or not 0.0 <= quote.price <= 1.0:
        return None
    return _observation(market, quote, "before_close", days)


def after_open(market: Market, quotes: list[Quote], days: int) -> Observation | None:
    """The price ``days`` after the open, if the market then had a day or more left.

    This moment is known in real time, unlike a distance from a close that may
    come early, so it serves as a check on the before-close results.
    """
    if market.outcome not in (0, 1):
        return None
    when = market.open_ts + days * config.DAY
    if when > market.close_ts - config.DAY:
        return None
    quote = price_at(quotes, when, config.MAX_STALENESS_HOURS * 3600.0)
    if quote is None or not 0.0 <= quote.price <= 1.0:
        return None
    return _observation(market, quote, "after_open", days)


COLUMNS = list(Observation.__dataclass_fields__)


def build_table(pairs: list[tuple[Market, list[Quote]]]) -> pd.DataFrame:
    """Every observation from every market: each horizon before close, and one after open."""
    rows: list[Observation] = []
    for market, quotes in pairs:
        for days in config.HORIZONS_DAYS:
            seen = before_close(market, quotes, days)
            if seen is not None:
                rows.append(seen)
        opened = after_open(market, quotes, config.PRIMARY_HORIZON_DAYS)
        if opened is not None:
            rows.append(opened)
    frame = pd.DataFrame([asdict(row) for row in rows], columns=COLUMNS)
    return frame.sort_values(["venue", "kind", "days", "market_id"], ignore_index=True)
