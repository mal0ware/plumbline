"""Every table in results/, computed from the table of observations."""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from zlib import crc32

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from plumbline import calibration as cal
from plumbline import config, fees
from plumbline.markets import CATEGORIES

Array = NDArray[np.float64]

MIN_CATEGORY_ROWS = 100
LONGSHOT_BELOW = 0.2
FAVOURITE_FROM = 0.8

# The logistic fit uses prices from 1 to 99 cents only. A single upset at a
# price of a tenth of a cent would otherwise move the slope more than
# thousands of ordinary markets do. Selecting on the price does not bias a
# model of the outcome given the price.
LOGIT_PRICE_FLOOR = 0.01


def _seed(seed: int, *parts: object) -> int:
    """A seed that depends on the table and group, but not on the order of the work."""
    return seed + crc32("|".join(str(part) for part in parts).encode()) % 1_000_000


def _xy(frame: pd.DataFrame) -> tuple[Array, Array, NDArray[np.intp]]:
    p = frame["price"].to_numpy(dtype=np.float64)
    y = frame["outcome"].to_numpy(dtype=np.float64)
    codes = cal.cluster_codes(frame["cluster"].to_numpy(dtype=str))
    return p, y, codes


def _interval(
    statistic: Callable[[Array], Array], codes: NDArray[np.intp], n_boot: int, seed: int
) -> tuple[Array, Array]:
    draws = cal.cluster_bootstrap(statistic, codes, n_boot, seed)
    return cal.percentile_interval(draws)


def _groups(obs: pd.DataFrame, kind: str) -> list[tuple[str, int, pd.DataFrame]]:
    subset = obs[obs["kind"] == kind]
    out = []
    for (venue, days), frame in subset.groupby(["venue", "days"], sort=True):
        out.append((str(venue), int(days), frame.reset_index(drop=True)))
    return out


def curve_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """Calibration curve by venue and horizon: win rate against mean price in ten bins."""
    rows = []
    edges = cal.DECILE_EDGES
    for venue, days, frame in _groups(obs, "before_close"):
        p, y, codes = _xy(frame)
        curve = cal.reliability(p, y, edges)

        def gap(weights: Array, p: Array = p, y: Array = y) -> Array:
            c = cal.reliability(p, y, edges, weights)
            return c.win_rate - c.mean_price

        low, high = _interval(gap, codes, n_boot, _seed(seed, "curve", venue, days))
        index = cal.bin_index(p, edges)
        for k in range(edges.size - 1):
            n = int(curve.weight[k])
            if n == 0:
                continue
            rows.append(
                {
                    "venue": venue,
                    "days_before_close": days,
                    "price_bin": f"{edges[k]:.1f}-{edges[k + 1]:.1f}",
                    "markets": n,
                    "events": int(np.unique(codes[index == k]).size),
                    "mean_price": curve.mean_price[k],
                    "win_rate": curve.win_rate[k],
                    "gap": curve.win_rate[k] - curve.mean_price[k],
                    "gap_low": low[k],
                    "gap_high": high[k],
                }
            )
    return pd.DataFrame(rows)


_BIAS_NAMES = (
    "mean_gap",
    "mz_alpha",
    "mz_psi",
    "logit_intercept",
    "logit_slope",
    "longshot_gap",
    "favourite_gap",
)


def _bias_vector(p: Array, y: Array, weights: Array | None) -> Array:
    alpha, psi = cal.mincer_zarnowitz(p, y, weights)
    inside = ((p >= LOGIT_PRICE_FLOOR) & (p <= 1.0 - LOGIT_PRICE_FLOOR)).astype(np.float64)
    a, b = cal.logistic_recalibration(p, y, inside if weights is None else weights * inside)
    everything = np.ones(p.size, dtype=np.bool_)
    return np.array(
        [
            cal.mean_gap(p, y, everything, weights),
            alpha,
            psi,
            a,
            b,
            cal.mean_gap(p, y, p < LONGSHOT_BELOW, weights),
            cal.mean_gap(p, y, p >= FAVOURITE_FROM, weights),
        ]
    )


def _bias_row(frame: pd.DataFrame, n_boot: int, seed: int) -> dict[str, float | int]:
    p, y, codes = _xy(frame)
    point = _bias_vector(p, y, None)
    low, high = _interval(lambda w: _bias_vector(p, y, w), codes, n_boot, seed)
    row: dict[str, float | int] = {
        "markets": int(p.size),
        "events": int(codes.max()) + 1,
        "longshots": int(np.sum(p < LONGSHOT_BELOW)),
        "favourites": int(np.sum(p >= FAVOURITE_FROM)),
        "in_logit_fit": int(np.sum((p >= LOGIT_PRICE_FLOOR) & (p <= 1.0 - LOGIT_PRICE_FLOOR))),
    }
    for i, name in enumerate(_BIAS_NAMES):
        row[name] = float(point[i])
        row[f"{name}_low"] = float(low[i])
        row[f"{name}_high"] = float(high[i])
    return row


def bias_table(
    obs: pd.DataFrame, n_boot: int, seed: int, kind: str = "before_close"
) -> pd.DataFrame:
    """The favourite-longshot bias by venue and horizon, measured four ways.

    ``mean_gap`` is the mean of outcome minus price. ``mz_alpha`` and ``mz_psi``
    are the Mincer-Zarnowitz coefficients. ``logit_slope`` is the logistic
    recalibration slope, fitted on prices from 1 to 99 cents. ``longshot_gap``
    and ``favourite_gap`` are the mean of outcome minus price for prices under
    0.2 and from 0.8 up.
    """
    label = "days_before_close" if kind == "before_close" else "days_after_open"
    rows = []
    for venue, days, frame in _groups(obs, kind):
        row = _bias_row(frame, n_boot, _seed(seed, "bias", kind, venue, days))
        rows.append({"venue": venue, label: days, **row})
    return pd.DataFrame(rows)


ALL_MARKETS = "every market with a price"
SAME_MARKETS = "markets with a price at every horizon"


def _seen_at_every_horizon(obs: pd.DataFrame) -> pd.DataFrame:
    """Rows of markets that have a before-close price at each horizon."""
    before = obs[obs["kind"] == "before_close"]
    seen = before.groupby(["venue", "market_id"])["days"].nunique()
    full = seen[seen == before["days"].nunique()].index
    keep = pd.MultiIndex.from_frame(before[["venue", "market_id"]]).isin(full)
    return before[keep]


def brier_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """Brier score by venue and horizon against two naive forecasts, with its parts.

    Longer horizons can only include longer-lived markets, so the rows for
    different horizons hold different markets. The second sample keeps only
    markets priced at every horizon, which makes the horizons comparable.
    """
    rows = []
    samples = [(ALL_MARKETS, obs), (SAME_MARKETS, _seen_at_every_horizon(obs))]
    for sample, subset in samples:
        rows.extend(_brier_rows(sample, subset, n_boot, seed))
    return pd.DataFrame(rows)


def _brier_rows(
    sample: str, obs: pd.DataFrame, n_boot: int, seed: int
) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for venue, days, frame in _groups(obs, "before_close"):
        p, y, codes = _xy(frame)

        def scores(weights: Array | None, p: Array = p, y: Array = y) -> Array:
            score = cal.brier(p, y, weights)
            naive = cal.climatology(y, weights)
            return np.array([score, 1.0 - score / naive if naive > 0 else np.nan])

        point = scores(None)
        low, high = _interval(scores, codes, n_boot, _seed(seed, "brier", sample, venue, days))
        parts = cal.brier_decomposition(p, y)
        rows.append(
            {
                "sample": sample,
                "venue": venue,
                "days_before_close": days,
                "markets": int(p.size),
                "events": int(codes.max()) + 1,
                "base_rate": float(y.mean()),
                "brier": point[0],
                "brier_low": low[0],
                "brier_high": high[0],
                "brier_coin_flip": 0.25,
                "brier_base_rate": cal.climatology(y),
                "skill_vs_base_rate": point[1],
                "skill_low": low[1],
                "skill_high": high[1],
                "reliability": parts.reliability,
                "resolution": parts.resolution,
                "uncertainty": parts.uncertainty,
                "within_bin": parts.within_bin,
            }
        )
    return rows


def category_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """Brier score and bias by category at the primary horizon."""
    rows = []
    subset = obs[(obs["kind"] == "before_close") & (obs["days"] == config.PRIMARY_HORIZON_DAYS)]
    for venue in sorted(subset["venue"].unique()):
        for category in CATEGORIES:
            frame = subset[(subset["venue"] == venue) & (subset["category"] == category)]
            frame = frame.reset_index(drop=True)
            if len(frame) < MIN_CATEGORY_ROWS:
                continue
            p, y, _ = _xy(frame)
            row = _bias_row(frame, n_boot, _seed(seed, "category", venue, category))
            naive = cal.climatology(y)
            score = cal.brier(p, y)
            rows.append(
                {
                    "venue": venue,
                    "category": category,
                    "markets": row["markets"],
                    "events": row["events"],
                    "base_rate": float(y.mean()),
                    "brier": score,
                    "skill_vs_base_rate": 1.0 - score / naive if naive > 0 else float("nan"),
                    **{
                        k: v
                        for k, v in row.items()
                        if k.startswith(("mean_gap", "mz_psi", "logit_slope"))
                    },
                }
            )
    return pd.DataFrame(rows)


# Lower edges of the Polymarket volume tiers, in dollars. The lowest is the floor.
VOLUME_TIERS_USD = (100_000.0, 200_000.0, 500_000.0, 2_000_000.0)
MIN_SPLIT_ROWS = 50


def split_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """Bias by market type on both venues, and by volume tier on Polymarket.

    These two splits were chosen after the main tables had been read, to see
    where the Polymarket deviation sits. They are exploratory.
    """
    rows = []
    for venue, days, frame in _groups(obs, "before_close"):
        parts: list[tuple[str, str, pd.DataFrame]] = [
            ("market type", "yes or no", frame[frame["yes_no"]]),
            ("market type", "two named sides", frame[~frame["yes_no"]]),
        ]
        if venue == "polymarket":
            bounds = [*VOLUME_TIERS_USD, float("inf")]
            for low, high in pairwise(bounds):
                label = f"from ${low:,.0f}" + ("" if high == float("inf") else f" to ${high:,.0f}")
                tier = frame[(frame["volume"] >= low) & (frame["volume"] < high)]
                parts.append(("volume", label, tier))
        for split, group, part in parts:
            if len(part) < MIN_SPLIT_ROWS:
                continue
            row = _bias_row(
                part.reset_index(drop=True), n_boot, _seed(seed, "split", venue, days, group)
            )
            kept = {
                key: value
                for key, value in row.items()
                if key in ("markets", "events")
                or key.startswith(("mean_gap", "mz_psi", "logit_slope"))
            }
            rows.append(
                {"venue": venue, "days_before_close": days, "split": split, "group": group, **kept}
            )
    return pd.DataFrame(rows)


def _cost_models(venue: str, frame: pd.DataFrame) -> list[tuple[str, Array, Array, Array | float]]:
    """(name, cost of the priced side, sale price of the priced side, fee rate)."""
    price = frame["price"].to_numpy(dtype=np.float64)
    bid = frame["bid"].to_numpy(dtype=np.float64)
    ask = frame["ask"].to_numpy(dtype=np.float64)
    if np.all(np.isfinite(bid)) and np.all(np.isfinite(ask)):
        rate = frame["fee_rate"].to_numpy(dtype=np.float64)
        return [("midpoint, no fee", price, price, 0.0), ("quoted side, with fee", ask, bid, rate)]
    return [
        ("reported price, no fee", price, price, 0.0),
        ("reported price, top fee rate", price, price, fees.POLYMARKET_MAX_RATE),
    ]


def edge_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """What a taker would have made per contract, by price bin, side and cost model.

    A row is one way to trade a price bin: buy the priced side or buy the other
    side, at the stated cost, and hold to settlement. ``edge`` is the mean
    profit per contract in dollars. A gap in the calibration curve is larger
    than the cost of trading it only if ``edge_low`` is above zero.
    """
    rows = []
    edges = cal.DECILE_EDGES
    bins = edges.size - 1
    for venue, days, frame in _groups(obs, "before_close"):
        p, y, codes = _xy(frame)
        index = cal.bin_index(p, edges)
        count = np.bincount(index, minlength=bins)
        for model, cost, sale, rate in _cost_models(venue, frame):
            profit = {
                "buy priced side": fees.taker_edge_yes(y, cost, rate),
                "buy other side": fees.taker_edge_no(y, sale, rate),
            }
            outlay = {"buy priced side": cost, "buy other side": 1.0 - sale}
            for side, values in profit.items():

                def means(
                    weights: Array,
                    values: Array = values,
                    index: NDArray[np.intp] = index,
                ) -> Array:
                    total = np.bincount(index, weights=weights, minlength=bins)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        return np.asarray(
                            np.bincount(index, weights=weights * values, minlength=bins) / total
                        )

                point = means(np.ones(p.size))
                low, high = _interval(
                    means, codes, n_boot, _seed(seed, "edge", venue, days, model, side)
                )
                spend = np.bincount(index, weights=outlay[side], minlength=bins)
                for k in range(bins):
                    if count[k] == 0:
                        continue
                    mean_cost = spend[k] / count[k]
                    rows.append(
                        {
                            "venue": venue,
                            "days_before_close": days,
                            "cost_model": model,
                            "side": side,
                            "price_bin": f"{edges[k]:.1f}-{edges[k + 1]:.1f}",
                            "markets": int(count[k]),
                            "mean_cost": mean_cost,
                            "edge": point[k],
                            "edge_low": low[k],
                            "edge_high": high[k],
                            "return_on_cost": point[k] / mean_cost if mean_cost > 0 else np.nan,
                        }
                    )
    return pd.DataFrame(rows)


def extremes_table(obs: pd.DataFrame) -> pd.DataFrame:
    """How many prices were already near 0 or 1, and how wide Kalshi quotes were."""
    rows = []
    for venue, days, frame in _groups(obs, "before_close"):
        p = frame["price"].to_numpy(dtype=np.float64)
        spread = (frame["ask"] - frame["bid"]).to_numpy(dtype=np.float64)
        rows.append(
            {
                "venue": venue,
                "days_before_close": days,
                "markets": int(p.size),
                "share_within_2c_of_0_or_1": float(np.mean((p <= 0.02) | (p >= 0.98))),
                "share_within_5c_of_0_or_1": float(np.mean((p <= 0.05) | (p >= 0.95))),
                "median_spread": float(np.nanmedian(spread))
                if np.isfinite(spread).any()
                else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def coverage_table(obs: pd.DataFrame, fetched: dict[str, int]) -> pd.DataFrame:
    """Of the markets fetched, how many give a usable price at each horizon."""
    rows = []
    for kind in ("before_close", "after_open"):
        for venue, days, frame in _groups(obs, kind):
            total = fetched.get(venue, 0)
            rows.append(
                {
                    "venue": venue,
                    "moment": f"{days} days {kind.replace('_', ' ')}",
                    "markets_fetched": total,
                    "with_usable_price": len(frame),
                    "share": len(frame) / total if total else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def run_all(obs: pd.DataFrame, n_boot: int, seed: int) -> dict[str, pd.DataFrame]:
    """Every table that depends only on the observations."""
    return {
        "calibration_curve": curve_table(obs, n_boot, seed),
        "longshot_bias": bias_table(obs, n_boot, seed),
        "longshot_bias_after_open": bias_table(obs, n_boot, seed, kind="after_open"),
        "brier": brier_table(obs, n_boot, seed),
        "by_category": category_table(obs, n_boot, seed),
        "edge_after_costs": edge_table(obs, n_boot, seed),
        "splits": split_table(obs, n_boot, seed),
        "extremes": extremes_table(obs),
    }
