"""Every table in results/, computed from the table of observations.

Most tables are computed twice: on prices from 5 to 95 cents, called live, and
on all prices. A price within a few cents of 0 or 1 usually belongs to a market
that is already decided or has no trading, and such rows pull every summary
towards "calibrated". Selecting on the price does not bias a statement about
the outcome given the price, so the live rows are the main ones.

Intervals for slopes, gaps and scores come from a bootstrap that resamples
whole clusters. Intervals for a win rate in one price bin are Wilson intervals
with the sample size cut for clustering, because a bootstrap gives a zero-width
interval when every market in a bin won.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from itertools import pairwise
from zlib import crc32

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from plumbline import calibration as cal
from plumbline import config, fees
from plumbline.markets import CATEGORIES

Array = NDArray[np.float64]
Codes = NDArray[np.intp]

MIN_CATEGORY_ROWS = 100
LONGSHOT_BELOW = 0.2
FAVOURITE_FROM = 0.8

# On all prices the logistic fit uses prices from 1 to 99 cents only. A single
# upset at a price of a tenth of a cent would otherwise move the slope more
# than thousands of ordinary markets do.
LOGIT_PRICE_FLOOR = 0.01

LIVE = "prices from 5c to 95c"
ALL = "all prices"
SAMPLES = (LIVE, ALL)

LIVE_EDGES: Array = np.array([config.LIVE_LOW, *np.linspace(0.1, 0.9, 9), config.LIVE_HIGH])


def _seed(seed: int, *parts: object) -> int:
    """A seed that depends on the table and group, but not on the order of the work."""
    return seed + crc32("|".join(str(part) for part in parts).encode()) % 1_000_000


def is_live(p: Array) -> NDArray[np.bool_]:
    return np.asarray((p >= config.LIVE_LOW) & (p <= config.LIVE_HIGH))


def take(frame: pd.DataFrame, sample: str) -> pd.DataFrame:
    """The rows of ``frame`` that belong to a price sample."""
    if sample == ALL:
        return frame.reset_index(drop=True)
    return frame[is_live(frame["price"].to_numpy(dtype=np.float64))].reset_index(drop=True)


def _edges(sample: str) -> Array:
    return cal.DECILE_EDGES if sample == ALL else LIVE_EDGES


def _bin_label(edges: Array, k: int) -> str:
    return f"{edges[k]:.2f}-{edges[k + 1]:.2f}"


def _xy(frame: pd.DataFrame, by: str = "unit") -> tuple[Array, Array, Codes]:
    p = frame["price"].to_numpy(dtype=np.float64)
    y = frame["outcome"].to_numpy(dtype=np.float64)
    codes = cal.cluster_codes(frame[by].to_numpy(dtype=str))
    return p, y, codes


def _interval(
    statistic: Callable[[Array], Array], codes: Codes, n_boot: int, seed: int
) -> tuple[Array, Array]:
    draws = cal.cluster_bootstrap(statistic, codes, n_boot, seed)
    return cal.percentile_interval(draws)


def _groups(obs: pd.DataFrame, kind: str) -> list[tuple[str, int, pd.DataFrame]]:
    subset = obs[obs["kind"] == kind]
    out = []
    for (venue, days), frame in subset.groupby(["venue", "days"], sort=True):
        out.append((str(venue), int(days), frame.reset_index(drop=True)))
    return out


def _counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        "markets": len(frame),
        "events": int(frame["cluster"].nunique()),
        "clusters": int(frame["unit"].nunique()),
    }


# ------------------------------------------------------------ win rate by bin


def bin_win_rates(
    p: Array, y: Array, codes: Codes, edges: Array
) -> tuple[Array, Array, Array, Array, Array]:
    """Per bin: markets, mean price, win rate, and the Wilson interval of the win rate."""
    bins = edges.size - 1
    index = cal.bin_index(p, edges)
    rows = np.bincount(index, minlength=bins).astype(np.float64)
    wins = np.bincount(index, weights=y, minlength=bins)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_price = np.bincount(index, weights=p, minlength=bins) / rows
        rate = wins / rows
    span = int(codes.max()) + 1 if codes.size else 1
    _, first, inverse = np.unique(index * span + codes, return_index=True, return_inverse=True)
    group_bin = index[first]
    group_wins = np.bincount(inverse, weights=y)
    group_rows = np.bincount(inverse).astype(np.float64)
    deviation = group_wins - np.nan_to_num(rate)[group_bin] * group_rows
    squares = np.bincount(group_bin, weights=deviation**2, minlength=bins)
    clusters = np.bincount(group_bin, minlength=bins).astype(np.float64)
    low, high = cal.cluster_wilson(wins, rows, clusters, squares)
    return rows, mean_price, rate, low, high


def curve_table(obs: pd.DataFrame) -> pd.DataFrame:
    """Calibration curve by venue, horizon and price sample.

    ``gap`` is the win rate minus the mean price in the bin. Its interval is
    the Wilson interval of the win rate, shifted by the mean price.
    """
    rows = []
    for sample in SAMPLES:
        edges = _edges(sample)
        for venue, days, whole in _groups(obs, "before_close"):
            frame = take(whole, sample)
            if frame.empty:
                continue
            p, y, codes = _xy(frame)
            count, mean_price, rate, low, high = bin_win_rates(p, y, codes, edges)
            index = cal.bin_index(p, edges)
            for k in range(edges.size - 1):
                if count[k] == 0:
                    continue
                rows.append(
                    {
                        "sample": sample,
                        "venue": venue,
                        "days_before_close": days,
                        "price_bin": _bin_label(edges, k),
                        "markets": int(count[k]),
                        "clusters": int(np.unique(codes[index == k]).size),
                        "mean_price": mean_price[k],
                        "win_rate": rate[k],
                        "gap": rate[k] - mean_price[k],
                        "gap_low": low[k] - mean_price[k],
                        "gap_high": high[k] - mean_price[k],
                    }
                )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ the bias

_BIAS_NAMES = (
    "mean_gap",
    "mz_alpha",
    "mz_psi",
    "logit_intercept",
    "logit_slope",
    "longshot_gap",
    "favourite_gap",
)
_SHORT = ("mean_gap", "mz_psi", "logit_slope")


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


def _bias_row(
    frame: pd.DataFrame, n_boot: int, seed: int, by: str = "unit"
) -> dict[str, float | int]:
    p, y, codes = _xy(frame, by)
    point = _bias_vector(p, y, None)
    low, high = _interval(lambda w: _bias_vector(p, y, w), codes, n_boot, seed)
    row: dict[str, float | int] = {
        **_counts(frame),
        "longshots": int(np.sum(p < LONGSHOT_BELOW)),
        "favourites": int(np.sum(p >= FAVOURITE_FROM)),
        "in_logit_fit": int(np.sum((p >= LOGIT_PRICE_FLOOR) & (p <= 1.0 - LOGIT_PRICE_FLOOR))),
    }
    for i, name in enumerate(_BIAS_NAMES):
        row[name] = float(point[i])
        row[f"{name}_low"] = float(low[i])
        row[f"{name}_high"] = float(high[i])
    return row


def _short(row: dict[str, float | int]) -> dict[str, float | int]:
    return {
        key: value
        for key, value in row.items()
        if key in ("markets", "events", "clusters") or key.startswith(_SHORT)
    }


def bias_table(
    obs: pd.DataFrame, n_boot: int, seed: int, kind: str = "before_close"
) -> pd.DataFrame:
    """The favourite-longshot bias by venue, horizon and price sample, measured four ways.

    ``mean_gap`` is the mean of outcome minus price. ``mz_alpha`` and ``mz_psi``
    are the Mincer-Zarnowitz coefficients. ``logit_slope`` is the logistic
    recalibration slope. ``longshot_gap`` and ``favourite_gap`` are the mean of
    outcome minus price for prices under 0.2 and from 0.8 up.
    """
    label = "days_before_close" if kind == "before_close" else "days_after_open"
    rows = []
    for sample in SAMPLES:
        for venue, days, whole in _groups(obs, kind):
            frame = take(whole, sample)
            if frame.empty:
                continue
            row = _bias_row(frame, n_boot, _seed(seed, "bias", kind, sample, venue, days))
            rows.append({"sample": sample, "venue": venue, label: days, **row})
    return pd.DataFrame(rows)


def clustering_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """The same estimates with intervals from two choices of cluster.

    Only for venues whose sample was drawn by series. The point estimates are
    identical by construction. The intervals differ.
    """
    rows = []
    for sample in SAMPLES:
        for venue, days, whole in _groups(obs, "before_close"):
            frame = take(whole, sample)
            if frame.empty or (frame["unit"] == frame["cluster"]).all():
                continue
            for name, by in (("event", "cluster"), ("series", "unit")):
                row = _bias_row(frame, n_boot, _seed(seed, "clustering", sample, venue, days), by)
                rows.append(
                    {
                        "sample": sample,
                        "venue": venue,
                        "days_before_close": days,
                        "resampled": name,
                        **_short(row),
                    }
                )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- Brier

ALL_MARKETS = "every market with a price"
SAME_MARKETS = "markets with a price at every horizon"
LIVE_MARKETS = "markets priced from 5c to 95c"


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
    markets priced at every horizon, which makes the horizons comparable. The
    third keeps live prices only, where the score is not helped by markets
    that were already decided.
    """
    live = obs[is_live(obs["price"].to_numpy(dtype=np.float64))]
    samples = [
        (LIVE_MARKETS, live),
        (ALL_MARKETS, obs),
        (SAME_MARKETS, _seen_at_every_horizon(obs)),
    ]
    rows: list[dict[str, float | int | str]] = []
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
                **_counts(frame),
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
    for sample in SAMPLES:
        for venue in sorted(subset["venue"].unique()):
            for category in CATEGORIES:
                frame = subset[(subset["venue"] == venue) & (subset["category"] == category)]
                frame = take(frame, sample)
                if len(frame) < MIN_CATEGORY_ROWS:
                    continue
                p, y, _ = _xy(frame)
                row = _bias_row(frame, n_boot, _seed(seed, "category", sample, venue, category))
                naive = cal.climatology(y)
                score = cal.brier(p, y)
                rows.append(
                    {
                        "sample": sample,
                        "venue": venue,
                        "category": category,
                        "base_rate": float(y.mean()),
                        "brier": score,
                        "skill_vs_base_rate": 1.0 - score / naive if naive > 0 else float("nan"),
                        **_short(row),
                    }
                )
    return pd.DataFrame(rows)


# Lower edges of the volume tiers, in dollars, for the sample with a floor.
VOLUME_TIERS_USD = (100_000.0, 200_000.0, 500_000.0, 2_000_000.0)
MIN_SPLIT_ROWS = 50


def _tier_label(low: float, high: float) -> str:
    if low <= 0:
        return f"under ${high:,.0f}"
    return f"from ${low:,.0f}" + ("" if high == float("inf") else f" to ${high:,.0f}")


def split_table(obs: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """Bias by market type on both venues, and by volume tier on Polymarket.

    These two splits were chosen after the first main tables had been read, to
    see where the Polymarket deviation sits. They are exploratory.
    """
    rows = []
    for sample in SAMPLES:
        for venue, days, whole in _groups(obs, "before_close"):
            frame = take(whole, sample)
            parts: list[tuple[str, str, pd.DataFrame]] = [
                ("market type", "yes or no", frame[frame["yes_no"]]),
                ("market type", "two named sides", frame[~frame["yes_no"]]),
            ]
            if venue == "polymarket":
                for low, high in pairwise([*VOLUME_TIERS_USD, float("inf")]):
                    tier = frame[(frame["volume"] >= low) & (frame["volume"] < high)]
                    parts.append(("volume", _tier_label(low, high), tier))
            for split, group, part in parts:
                if len(part) < MIN_SPLIT_ROWS:
                    continue
                row = _bias_row(
                    part.reset_index(drop=True),
                    n_boot,
                    _seed(seed, "split", sample, venue, days, group),
                )
                rows.append(
                    {
                        "sample": sample,
                        "venue": venue,
                        "days_before_close": days,
                        "split": split,
                        "group": group,
                        **_short(row),
                    }
                )
    return pd.DataFrame(rows)


# ------------------------------------------------------------ the volume floor

NOFLOOR_TIERS_USD = (0.0, 1_000.0, 10_000.0, 100_000.0)
FLOOR_USD = 100_000.0


def floor_table(nofloor: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """Bias in the sample drawn with no volume floor, under floors applied afterwards.

    The first rows keep markets whose final volume is at least a floor, from no
    floor up to the one the main sample was drawn with. The remaining rows are
    the tiers between those floors.
    """
    rows = []
    for sample in SAMPLES:
        for venue, days, whole in _groups(nofloor, "before_close"):
            frame = take(whole, sample)
            parts = [("every market", frame)]
            for low in NOFLOOR_TIERS_USD[1:]:
                parts.append((f"at least ${low:,.0f}", frame[frame["volume"] >= low]))
            for low, high in pairwise(NOFLOOR_TIERS_USD):
                tier = frame[(frame["volume"] >= low) & (frame["volume"] < high)]
                parts.append((_tier_label(low, high), tier))
            for group, part in parts:
                if len(part) < MIN_SPLIT_ROWS:
                    continue
                row = _bias_row(
                    part.reset_index(drop=True),
                    n_boot,
                    _seed(seed, "floor", sample, venue, days, group),
                )
                price = part["price"].to_numpy(dtype=np.float64)
                rows.append(
                    {
                        "sample": sample,
                        "venue": venue,
                        "days_before_close": days,
                        "final_volume": group,
                        "share_priced_at_exactly_50c": float(np.mean(np.abs(price - 0.5) < 1e-9)),
                        **_short(row),
                    }
                )
    return pd.DataFrame(rows)


def _slope_psi(p: Array, y: Array, weights: Array | None) -> Array:
    vector = _bias_vector(p, y, weights)
    return np.array([vector[4], vector[2]])


def _slope_psi_draws(p: Array, y: Array, codes: Codes, n_boot: int, seed: int) -> Array:
    def statistic(weights: Array) -> Array:
        return _slope_psi(p, y, weights)

    return cal.cluster_bootstrap(statistic, codes, n_boot, seed)


def _difference_rows(
    label: str,
    point_a: Array,
    draws_a: Array,
    point_b: Array,
    draws_b: Array,
    draws_diff: Array,
) -> dict[str, float | str]:
    row: dict[str, float | str] = {"comparison": label}
    low_a, high_a = cal.percentile_interval(draws_a)
    low_b, high_b = cal.percentile_interval(draws_b)
    low_d, high_d = cal.percentile_interval(draws_diff)
    for i, name in enumerate(("logit_slope", "mz_psi")):
        row[f"{name}_a"] = float(point_a[i])
        row[f"{name}_a_low"] = float(low_a[i])
        row[f"{name}_a_high"] = float(high_a[i])
        row[f"{name}_b"] = float(point_b[i])
        row[f"{name}_b_low"] = float(low_b[i])
        row[f"{name}_b_high"] = float(high_b[i])
        row[f"{name}_diff"] = float(point_a[i] - point_b[i])
        row[f"{name}_diff_low"] = float(low_d[i])
        row[f"{name}_diff_high"] = float(high_d[i])
    return row


def floor_test_table(
    obs: pd.DataFrame, nofloor: pd.DataFrame, floor_venue: str, n_boot: int, seed: int
) -> pd.DataFrame:
    """Does the slope move when the volume floor is removed?

    Two comparisons, each as a difference a - b with a bootstrap interval:

    1. the sample drawn above the floor against the sample drawn with no floor.
       The two were drawn separately, so their bootstraps are independent.
    2. inside the no-floor sample, markets that ended at or above the floor
       against those that ended below it. One bootstrap resamples events and
       recomputes both.
    """
    rows = []
    main = {
        days: frame for venue, days, frame in _groups(obs, "before_close") if venue == floor_venue
    }
    for sample in SAMPLES:
        for _, days, whole in _groups(nofloor, "before_close"):
            free = take(whole, sample)
            if days not in main or len(free) < MIN_SPLIT_ROWS:
                continue
            floored = take(main[days], sample)
            base = {"sample": sample, "days_before_close": days}

            pa, ya, ca = _xy(floored)
            pb, yb, cb = _xy(free)
            draws_a = _slope_psi_draws(pa, ya, ca, n_boot, _seed(seed, "floor-a", sample, days))
            draws_b = _slope_psi_draws(pb, yb, cb, n_boot, _seed(seed, "floor-b", sample, days))
            both = len(set(floored["market_id"]) & set(free["market_id"]))
            rows.append(
                {
                    **base,
                    "markets_a": len(floored),
                    "markets_b": len(free),
                    "markets_in_both": both,
                    **_difference_rows(
                        "a: drawn above the floor, b: drawn with no floor",
                        _slope_psi(pa, ya, None),
                        draws_a,
                        _slope_psi(pb, yb, None),
                        draws_b,
                        draws_a - draws_b,
                    ),
                }
            )

            above = (free["volume"] >= FLOOR_USD).to_numpy(dtype=np.float64)
            below = 1.0 - above
            if min(above.sum(), below.sum()) < MIN_SPLIT_ROWS:
                continue

            def parts(
                w: Array | None, pb: Array = pb, yb: Array = yb, above: Array = above
            ) -> Array:
                weight = np.ones(pb.size) if w is None else w
                return np.concatenate(
                    [
                        _slope_psi(pb, yb, weight * above),
                        _slope_psi(pb, yb, weight * (1.0 - above)),
                    ]
                )

            point = parts(None)
            draws = cal.cluster_bootstrap(parts, cb, n_boot, _seed(seed, "floor-in", sample, days))
            rows.append(
                {
                    **base,
                    "markets_a": int(above.sum()),
                    "markets_b": int(below.sum()),
                    "markets_in_both": 0,
                    **_difference_rows(
                        "no-floor sample only. a: ended at or above the floor, b: ended below it",
                        point[:2],
                        draws[:, :2],
                        point[2:],
                        draws[:, 2:],
                        draws[:, :2] - draws[:, 2:],
                    ),
                }
            )
    columns = ["sample", "days_before_close", "comparison"]
    frame = pd.DataFrame(rows)
    return frame[columns + [c for c in frame.columns if c not in columns]] if rows else frame


# ------------------------------------------------- profit after costs, and its null

NULL_BY_CLUSTER = "one draw per cluster"
NULL_BY_MARKET = "one draw per market"
NULL_SCHEMES = (NULL_BY_CLUSTER, NULL_BY_MARKET)
_CHUNK = 250


def _cost_models(frame: pd.DataFrame) -> list[tuple[str, bool, Array, Array, Array | float]]:
    """(name, has costs, cost of the priced side, sale price of the priced side, fee rate)."""
    price = frame["price"].to_numpy(dtype=np.float64)
    bid = frame["bid"].to_numpy(dtype=np.float64)
    ask = frame["ask"].to_numpy(dtype=np.float64)
    if np.all(np.isfinite(bid)) and np.all(np.isfinite(ask)):
        rate = frame["fee_rate"].to_numpy(dtype=np.float64)
        return [
            ("midpoint, no fee", False, price, price, 0.0),
            ("quoted side, with fee", True, ask, bid, rate),
        ]
    return [
        ("reported price, no fee", False, price, price, 0.0),
        ("reported price, top fee rate", True, price, price, fees.POLYMARKET_MAX_RATE),
    ]


class _Layout:
    """Rows of one venue across all horizons, sorted so that tests are contiguous.

    A test is one (horizon, price bin). Rows are ordered by test and then by
    cluster, so that sums over clusters and over tests are both sums over
    contiguous runs.
    """

    def __init__(self, frame: pd.DataFrame, edges: Array, horizons: list[int]) -> None:
        bins = edges.size - 1
        p = frame["price"].to_numpy(dtype=np.float64)
        days = frame["days"].to_numpy()
        horizon = np.searchsorted(np.asarray(horizons), days)
        test = horizon * bins + cal.bin_index(p, edges)
        cluster = cal.cluster_codes(frame["unit"].to_numpy(dtype=str))
        market = cal.cluster_codes(frame["market_id"].to_numpy(dtype=str))
        span = int(cluster.max()) + 1
        self.order = np.lexsort((cluster, test))
        key = (test * span + cluster)[self.order]
        self.group_start = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        group_test = test[self.order][self.group_start]
        self.test_start = np.flatnonzero(np.r_[True, group_test[1:] != group_test[:-1]])
        self.tests = group_test[self.test_start]
        self.group_test_index = np.searchsorted(self.tests, group_test)
        self.group_rows = np.diff(np.r_[self.group_start, key.size]).astype(np.float64)
        self.rows = np.add.reduceat(self.group_rows, self.test_start)
        self.clusters = np.diff(np.r_[self.test_start, self.group_start.size]).astype(np.float64)
        self.p = p[self.order]
        self.cluster = cluster[self.order]
        self.market = market[self.order]
        self.row_test_index = np.searchsorted(self.tests, test[self.order])
        self.horizon = self.tests // bins
        self.bin = self.tests % bins

    def per_test(self, values: Array) -> Array:
        """Mean of a per-row quantity (in the original row order) within each test."""
        ordered = values[self.order]
        return np.asarray(np.bincount(self.row_test_index, weights=ordered) / self.rows)

    def win_rates(self, y: Array) -> tuple[Array, Array, Array]:
        """Win rate and its Wilson interval per test, for outcomes of shape (draws, rows).

        ``y`` must already be in the sorted row order.
        """
        by_group = np.add.reduceat(y, self.group_start, axis=1)
        wins = np.add.reduceat(by_group, self.test_start, axis=1)
        rate = wins / self.rows
        deviation = by_group - rate[:, self.group_test_index] * self.group_rows
        squares = np.add.reduceat(deviation**2, self.test_start, axis=1)
        low, high = cal.cluster_wilson(wins, self.rows, self.clusters, squares)
        return rate, low, high

    def simulate(self, scheme: str, n_sims: int, seed: int) -> Iterator[Array]:
        """Outcomes of a calibrated market in the sorted row order, a few hundred draws at a time.

        Each row wins when a uniform draw falls below its price, so every row
        is calibrated at its own price. The draw is shared by all rows of one
        cluster, or of one market, across horizons. Sharing it makes outcomes
        as positively dependent as calibrated prices allow.
        """
        share = self.cluster if scheme == NULL_BY_CLUSTER else self.market
        rng = np.random.default_rng(seed)
        for start in range(0, n_sims, _CHUNK):
            draws = rng.random((min(_CHUNK, n_sims - start), int(share.max()) + 1))
            yield (draws[:, share] < self.p).astype(np.float64)


def holm(p: Array) -> Array:
    """Holm's step-down adjustment. Valid whatever the dependence between tests."""
    order = np.argsort(p, kind="stable")
    scaled = (p.size - np.arange(p.size)) * p[order]
    adjusted = np.minimum(np.maximum.accumulate(scaled), 1.0)
    out = np.empty_like(adjusted)
    out[order] = adjusted
    return np.asarray(out, dtype=np.float64)


def edge_tables(obs: pd.DataFrame, n_sims: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """What a taker would have made per contract, and how that compares with chance.

    The first table has one row per way to trade a price bin: buy the priced
    side or the other side, at the stated cost, and hold to settlement.
    ``edge`` is the mean profit per contract in dollars: the win rate of the
    side bought minus its mean cost. The interval is the Wilson interval of the
    win rate, shifted by the mean cost.

    For the rows with costs, the same statistics are computed on simulated
    outcomes from a market that is calibrated at every quoted price, with the
    same prices, costs and clusters. ``p_null`` is the share of simulations
    with an edge at least as large as the one observed, and ``p_holm`` adjusts
    it for the number of tests in the price sample. The second table counts how
    many intervals sit above zero, against how many the simulations give.
    """
    before = obs[obs["kind"] == "before_close"]
    horizons = sorted(int(d) for d in before["days"].unique())
    rows: list[dict[str, float | int | str]] = []
    summary: list[dict[str, float | int | str]] = []
    for sample in SAMPLES:
        edges = _edges(sample)
        null_hits = {scheme: np.zeros(n_sims) for scheme in NULL_SCHEMES}
        first = len(rows)
        for venue in sorted(before["venue"].unique()):
            frame = take(before[before["venue"] == venue], sample)
            if frame.empty:
                continue
            layout = _Layout(frame, edges, horizons)
            y = frame["outcome"].to_numpy(dtype=np.float64)[layout.order][None, :]
            rate, low, high = (a[0] for a in layout.win_rates(y))
            for model, costed, cost, sale, fee in _cost_models(frame):
                other = 1.0 - sale
                outlay = {
                    "buy priced side": layout.per_test(cost),
                    "buy other side": layout.per_test(other),
                }
                total = {
                    "buy priced side": layout.per_test(cost + fees.fee_per_contract(cost, fee)),
                    "buy other side": layout.per_test(other + fees.fee_per_contract(other, fee)),
                }
                observed = {
                    "buy priced side": (rate - total["buy priced side"], low, high),
                    "buy other side": (1 - rate - total["buy other side"], 1 - high, 1 - low),
                }
                p_null: dict[str, Array] = {}
                if costed:
                    for scheme in NULL_SCHEMES:
                        at_least = {side: np.zeros(layout.tests.size) for side in observed}
                        done = 0
                        null_seed = _seed(seed, "null", sample, venue, scheme)
                        for sims in layout.simulate(scheme, n_sims, null_seed):
                            s_rate, s_low, s_high = layout.win_rates(sims)
                            drawn = {
                                "buy priced side": (s_rate, s_low),
                                "buy other side": (1 - s_rate, 1 - s_high),
                            }
                            stop = done + sims.shape[0]
                            for side, (s_win, s_bound) in drawn.items():
                                null_hits[scheme][done:stop] += np.sum(
                                    s_bound - total[side] > 0, axis=1
                                )
                                at_least[side] += np.sum(
                                    s_win - total[side] >= observed[side][0] - 1e-12, axis=0
                                )
                            done = stop
                        if scheme == NULL_BY_CLUSTER:
                            for side in observed:
                                p_null[side] = (1.0 + at_least[side]) / (n_sims + 1.0)
                for side, (edge, side_low, side_high) in observed.items():
                    for t in range(layout.tests.size):
                        k = int(layout.bin[t])
                        mean_cost = float(outlay[side][t])
                        rows.append(
                            {
                                "sample": sample,
                                "venue": venue,
                                "days_before_close": horizons[int(layout.horizon[t])],
                                "cost_model": model,
                                "side": side,
                                "price_bin": _bin_label(edges, k),
                                "markets": int(layout.rows[t]),
                                "clusters": int(layout.clusters[t]),
                                "mean_cost": mean_cost,
                                "edge": float(edge[t]),
                                "edge_low": float(side_low[t] - total[side][t]),
                                "edge_high": float(side_high[t] - total[side][t]),
                                "return_on_cost": float(edge[t]) / mean_cost
                                if mean_cost > 0
                                else float("nan"),
                                "p_null": float(p_null[side][t]) if costed else float("nan"),
                                "p_holm": float("nan"),
                            }
                        )
        costed_rows = [i for i in range(first, len(rows)) if rows[i]["p_null"] == rows[i]["p_null"]]
        if not costed_rows:
            continue
        adjusted = holm(np.array([float(rows[i]["p_null"]) for i in costed_rows]))
        for i, value in zip(costed_rows, adjusted, strict=True):
            rows[i]["p_holm"] = float(value)
        hits = sum(1 for i in costed_rows if float(rows[i]["edge_low"]) > 0)
        for scheme in NULL_SCHEMES:
            null = null_hits[scheme]
            summary.append(
                {
                    "sample": sample,
                    "null": scheme,
                    "tests": len(costed_rows),
                    "intervals_above_zero": hits,
                    "expected_under_null": float(null.mean()),
                    "null_95th_percentile": float(np.quantile(null, 0.95)),
                    "share_of_simulations_with_at_least_as_many": float(
                        (1.0 + np.sum(null >= hits)) / (n_sims + 1.0)
                    ),
                    "tests_with_p_null_below_0.025": sum(
                        1 for i in costed_rows if float(rows[i]["p_null"]) < 0.025
                    ),
                    "smallest_p_holm": float(adjusted.min()),
                    "tests_with_p_holm_below_0.05": int(np.sum(adjusted < 0.05)),
                    "simulations": n_sims,
                }
            )
    table = pd.DataFrame(rows).sort_values(
        ["sample", "venue", "days_before_close", "cost_model", "side", "price_bin"],
        ascending=[False, True, True, True, False, True],
        ignore_index=True,
    )
    return table, pd.DataFrame(summary)


# ------------------------------------------------------------- bookkeeping


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
                "share_outside_5c_to_95c": float(np.mean(~is_live(p))),
                "markets_from_5c_to_95c": int(np.sum(is_live(p))),
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


def run_all(obs: pd.DataFrame, n_boot: int, seed: int, n_sims: int) -> dict[str, pd.DataFrame]:
    """Every table that depends only on the main observations."""
    edge, null = edge_tables(obs, n_sims, seed)
    return {
        "calibration_curve": curve_table(obs),
        "longshot_bias": bias_table(obs, n_boot, seed),
        "longshot_bias_after_open": bias_table(obs, n_boot, seed, kind="after_open"),
        "clustering": clustering_table(obs, n_boot, seed),
        "brier": brier_table(obs, n_boot, seed),
        "by_category": category_table(obs, n_boot, seed),
        "edge_after_costs": edge,
        "edge_null": null,
        "splits": split_table(obs, n_boot, seed),
        "extremes": extremes_table(obs),
    }
