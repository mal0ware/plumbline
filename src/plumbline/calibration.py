"""Calibration statistics for binary forecasts.

Every statistic takes optional non-negative weights. With integer weights the
result equals the unweighted statistic on a sample in which each row is
repeated that many times, which is what the cluster bootstrap relies on.

Notation: ``p`` is the price read as a probability, ``y`` the outcome (0 or 1).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

DECILE_EDGES: Array = np.linspace(0.0, 1.0, 11)


def _weights(weights: Array | None, size: int) -> Array:
    if weights is None:
        return np.ones(size, dtype=np.float64)
    if weights.shape != (size,):
        raise ValueError("weights must match the data")
    return weights.astype(np.float64)


def _check(p: Array, y: Array) -> None:
    if p.shape != y.shape or p.ndim != 1:
        raise ValueError("p and y must be one-dimensional and the same length")
    if p.size and (p.min() < 0.0 or p.max() > 1.0):
        raise ValueError("prices must lie in [0, 1]")
    if p.size and not np.all((y == 0.0) | (y == 1.0)):
        raise ValueError("outcomes must be 0 or 1")


def bin_index(p: Array, edges: Array = DECILE_EDGES) -> NDArray[np.intp]:
    """Index of the bin each price falls in. Bins are [lo, hi), the last is [lo, hi]."""
    index = np.searchsorted(edges, p, side="right") - 1
    return np.clip(index, 0, edges.size - 2)


@dataclass(frozen=True)
class Reliability:
    """Per-bin weight, mean price and win rate. Empty bins hold NaN means."""

    weight: Array
    mean_price: Array
    win_rate: Array


def reliability(
    p: Array, y: Array, edges: Array = DECILE_EDGES, weights: Array | None = None
) -> Reliability:
    """The calibration curve: within each price bin, mean price against win rate."""
    _check(p, y)
    w = _weights(weights, p.size)
    bins = edges.size - 1
    index = bin_index(p, edges)
    total = np.bincount(index, weights=w, minlength=bins)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_price = np.bincount(index, weights=w * p, minlength=bins) / total
        win_rate = np.bincount(index, weights=w * y, minlength=bins) / total
    return Reliability(weight=total, mean_price=mean_price, win_rate=win_rate)


def brier(p: Array, y: Array, weights: Array | None = None) -> float:
    """Brier (1950) score: the mean of (p - y)^2. Lower is better."""
    _check(p, y)
    w = _weights(weights, p.size)
    return float(np.sum(w * (p - y) ** 2) / np.sum(w))


def climatology(y: Array, weights: Array | None = None) -> float:
    """Brier score of always forecasting the sample base rate: ybar * (1 - ybar)."""
    w = _weights(weights, y.size)
    base = float(np.sum(w * y) / np.sum(w))
    return base * (1.0 - base)


@dataclass(frozen=True)
class BrierParts:
    """Murphy (1973) partition of the Brier score, plus what binning leaves over."""

    reliability: float
    resolution: float
    uncertainty: float
    within_bin: float

    @property
    def total(self) -> float:
        return self.reliability - self.resolution + self.uncertainty + self.within_bin


def brier_decomposition(
    p: Array, y: Array, edges: Array = DECILE_EDGES, weights: Array | None = None
) -> BrierParts:
    """Split the Brier score into reliability - resolution + uncertainty.

    With bins k of weight share w_k, mean price pbar_k and win rate ybar_k:

        reliability = sum_k w_k (pbar_k - ybar_k)^2
        resolution  = sum_k w_k (ybar_k - ybar)^2
        uncertainty = ybar (1 - ybar)

    Murphy's identity is exact when every forecast in a bin is the same number.
    Prices vary within a bin, which adds the term

        within_bin = sum_k w_k [ var_k(p) - 2 cov_k(p, y) ]

    so that the four parts always sum to the Brier score.
    """
    _check(p, y)
    w = _weights(weights, p.size)
    curve = reliability(p, y, edges, w)
    share = curve.weight / np.sum(curve.weight)
    filled = curve.weight > 0
    base = float(np.sum(w * y) / np.sum(w))
    rel = float(np.sum(share[filled] * (curve.mean_price[filled] - curve.win_rate[filled]) ** 2))
    res = float(np.sum(share[filled] * (curve.win_rate[filled] - base) ** 2))
    unc = base * (1.0 - base)
    index = bin_index(p, edges)
    dp = p - curve.mean_price[index]
    dy = y - curve.win_rate[index]
    within = float(np.sum(w * (dp * dp - 2.0 * dp * dy)) / np.sum(w))
    return BrierParts(reliability=rel, resolution=res, uncertainty=unc, within_bin=within)


def mincer_zarnowitz(p: Array, y: Array, weights: Array | None = None) -> tuple[float, float]:
    """Least squares fit of y - p = alpha + psi * p. Returns (alpha, psi).

    Unbiased prices give alpha = psi = 0. A negative alpha with a positive psi
    is the favourite-longshot pattern: cheap contracts win less often than
    their price, dear ones more often.
    """
    _check(p, y)
    w = _weights(weights, p.size)
    total = np.sum(w)
    mean_p = np.sum(w * p) / total
    error = y - p
    mean_e = np.sum(w * error) / total
    variance = np.sum(w * (p - mean_p) ** 2)
    if variance <= 0.0:
        return float(mean_e), float("nan")
    psi = float(np.sum(w * (p - mean_p) * (error - mean_e)) / variance)
    return float(mean_e - psi * mean_p), psi


def logit(p: Array, clip: float = 1e-4) -> Array:
    """Log odds, with prices clipped away from 0 and 1."""
    clipped = np.clip(p, clip, 1.0 - clip)
    return np.log(clipped / (1.0 - clipped))


def logistic_recalibration(
    p: Array, y: Array, weights: Array | None = None, iterations: int = 50
) -> tuple[float, float]:
    """Maximum-likelihood fit of P(y = 1) = sigmoid(a + b * logit(p)). Returns (a, b).

    Calibrated prices give a = 0 and b = 1. A slope above 1 means outcomes are
    more extreme than prices say, which is the favourite-longshot bias. The fit
    is Newton's method on the two-parameter logistic likelihood.
    """
    _check(p, y)
    w = _weights(weights, p.size)
    x = logit(p)
    a, b = 0.0, 1.0
    for _ in range(iterations):
        mu = 1.0 / (1.0 + np.exp(-np.clip(a + b * x, -35.0, 35.0)))
        g0 = float(np.sum(w * (y - mu)))
        g1 = float(np.sum(w * (y - mu) * x))
        v = w * mu * (1.0 - mu)
        h00, h01, h11 = float(np.sum(v)), float(np.sum(v * x)), float(np.sum(v * x * x))
        det = h00 * h11 - h01 * h01
        if det <= 1e-12:
            return float("nan"), float("nan")
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a, b = a + da, b + db
        if abs(da) + abs(db) < 1e-10:
            break
    return a, b


def mean_gap(p: Array, y: Array, mask: NDArray[np.bool_], weights: Array | None = None) -> float:
    """Mean of y - p over the rows picked by ``mask``. NaN if none are picked."""
    w = _weights(weights, p.size) * mask
    total = float(np.sum(w))
    return float(np.sum(w * (y - p)) / total) if total > 0 else float("nan")


def cluster_codes(clusters: list[str] | NDArray[np.str_]) -> NDArray[np.intp]:
    """Integer code for each row's cluster."""
    _, codes = np.unique(np.asarray(clusters), return_inverse=True)
    return codes.astype(np.intp)


def cluster_bootstrap(
    statistic: Callable[[Array], Array],
    codes: NDArray[np.intp],
    n_boot: int,
    seed: int,
) -> Array:
    """Bootstrap a weighted statistic by resampling whole clusters.

    Markets in one event share an outcome, so rows are not independent. Each
    replicate draws clusters with replacement and passes ``statistic`` the
    number of times each row's cluster was drawn, as that row's weight. Returns
    an array with one row per replicate.
    """
    if codes.size == 0:
        raise ValueError("no rows to resample")
    n_clusters = int(codes.max()) + 1
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        counts = np.bincount(rng.integers(0, n_clusters, size=n_clusters), minlength=n_clusters)
        draws.append(np.atleast_1d(statistic(counts[codes].astype(np.float64))))
    return np.vstack(draws)


def percentile_interval(draws: Array, level: float = 0.95) -> tuple[Array, Array]:
    """Percentile interval of each column of bootstrap draws, ignoring NaN."""
    tail = (1.0 - level) / 2.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        low = np.nanquantile(draws, tail, axis=0)
        high = np.nanquantile(draws, 1.0 - tail, axis=0)
    return np.asarray(low, dtype=np.float64), np.asarray(high, dtype=np.float64)
