"""The maths, tested against closed forms and identities before any data is trusted."""

from __future__ import annotations

import numpy as np
import pytest

from plumbline import calibration as cal


def _bernoulli(q: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.uniform(size=q.size) < q).astype(np.float64)


def test_brier_closed_forms() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert cal.brier(y, y) == 0.0
    assert cal.brier(1.0 - y, y) == 1.0
    assert cal.brier(np.full(4, 0.5), y) == pytest.approx(0.25)
    assert cal.brier(np.array([0.7, 0.2, 0.9, 0.4]), y) == pytest.approx(
        (0.09 + 0.04 + 0.01 + 0.16) / 4
    )


def test_base_rate_forecast_scores_ybar_times_one_minus_ybar() -> None:
    y = np.array([1.0, 1.0, 1.0, 0.0])
    assert cal.climatology(y) == pytest.approx(0.75 * 0.25)
    assert cal.brier(np.full(4, 0.75), y) == pytest.approx(cal.climatology(y))


def test_murphy_identity_is_exact_for_discrete_forecasts() -> None:
    rng = np.random.default_rng(1)
    p = rng.choice(np.array([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]), 5000)
    y = _bernoulli(np.clip(p + 0.05, 0, 1), 2)
    parts = cal.brier_decomposition(p, y)
    assert parts.within_bin == pytest.approx(0.0, abs=1e-12)
    assert parts.reliability - parts.resolution + parts.uncertainty == pytest.approx(
        cal.brier(p, y), abs=1e-12
    )


def test_decomposition_sums_to_brier_for_continuous_prices() -> None:
    rng = np.random.default_rng(3)
    p = rng.uniform(size=4000)
    y = _bernoulli(p**1.5, 4)
    assert cal.brier_decomposition(p, y).total == pytest.approx(cal.brier(p, y), abs=1e-12)


def test_perfectly_calibrated_bins_have_zero_reliability() -> None:
    p = np.array([0.25] * 4 + [0.75] * 4)
    y = np.array([1.0, 0, 0, 0, 1, 1, 1, 0])
    parts = cal.brier_decomposition(p, y)
    assert parts.reliability == pytest.approx(0.0)
    assert parts.resolution == pytest.approx(0.0625)
    assert parts.uncertainty == pytest.approx(0.25)


def test_reliability_bins_and_edges() -> None:
    p = np.array([0.0, 0.05, 0.1, 0.95, 1.0])
    y = np.array([0.0, 1.0, 0.0, 1.0, 1.0])
    curve = cal.reliability(p, y)
    assert curve.weight[0] == 2 and curve.weight[1] == 1 and curve.weight[9] == 2
    assert curve.win_rate[0] == pytest.approx(0.5)
    assert curve.mean_price[9] == pytest.approx(0.975)
    assert np.isnan(curve.win_rate[5])


def test_mincer_zarnowitz_recovers_an_exact_linear_bias() -> None:
    p = np.linspace(0.05, 0.95, 19)
    # Outcomes cannot be fractional, so repeat each price and set the win share exactly.
    alpha, psi = -0.02, 0.04
    target = p + alpha + psi * p
    prices, outcomes = [], []
    for price, rate in zip(p, target, strict=True):
        wins = round(rate * 10_000)
        prices.extend([price] * 10_000)
        outcomes.extend([1.0] * wins + [0.0] * (10_000 - wins))
    a, b = cal.mincer_zarnowitz(np.array(prices), np.array(outcomes))
    assert a == pytest.approx(alpha, abs=2e-4)
    assert b == pytest.approx(psi, abs=4e-4)


def test_calibrated_forecasts_come_out_calibrated() -> None:
    rng = np.random.default_rng(7)
    q = rng.uniform(0.02, 0.98, 200_000)
    y = _bernoulli(q, 8)
    alpha, psi = cal.mincer_zarnowitz(q, y)
    a, b = cal.logistic_recalibration(q, y)
    assert abs(alpha) < 0.005 and abs(psi) < 0.01
    assert abs(a) < 0.02 and b == pytest.approx(1.0, abs=0.02)
    curve = cal.reliability(q, y)
    assert np.max(np.abs(curve.win_rate - curve.mean_price)) < 0.01


@pytest.mark.parametrize("slope", [0.7, 1.3, 1.8])
def test_planted_longshot_bias_is_recovered_with_sign_and_size(slope: float) -> None:
    rng = np.random.default_rng(11)
    q = rng.uniform(0.02, 0.98, 200_000)
    y = _bernoulli(q, 12)
    quoted = 1.0 / (1.0 + np.exp(-cal.logit(q) / slope))
    a, b = cal.logistic_recalibration(quoted, y)
    assert b == pytest.approx(slope, rel=0.03)
    assert abs(a) < 0.03
    _, psi = cal.mincer_zarnowitz(quoted, y)
    assert np.sign(psi) == np.sign(slope - 1.0)
    longshots = cal.mean_gap(quoted, y, quoted < 0.2)
    favourites = cal.mean_gap(quoted, y, quoted >= 0.8)
    assert np.sign(longshots) == -np.sign(slope - 1.0)
    assert np.sign(favourites) == np.sign(slope - 1.0)


def test_integer_weights_equal_repeated_rows() -> None:
    rng = np.random.default_rng(13)
    p = rng.uniform(size=300)
    y = _bernoulli(p, 14)
    w = rng.integers(0, 4, size=300).astype(np.float64)
    rp, ry = np.repeat(p, w.astype(int)), np.repeat(y, w.astype(int))
    assert cal.brier(p, y, w) == pytest.approx(cal.brier(rp, ry))
    assert cal.climatology(y, w) == pytest.approx(cal.climatology(ry))
    assert cal.mincer_zarnowitz(p, y, w) == pytest.approx(cal.mincer_zarnowitz(rp, ry))
    assert cal.logistic_recalibration(p, y, w) == pytest.approx(
        cal.logistic_recalibration(rp, ry), abs=1e-8
    )
    weighted, repeated = cal.reliability(p, y, weights=w), cal.reliability(rp, ry)
    np.testing.assert_allclose(weighted.win_rate, repeated.win_rate)
    np.testing.assert_allclose(weighted.mean_price, repeated.mean_price)


def test_bootstrap_is_deterministic_and_respects_clusters() -> None:
    rng = np.random.default_rng(17)
    # 200 events of 10 identical markets each: 2000 rows but only 200 independent draws.
    outcome = (rng.uniform(size=200) < 0.5).astype(np.float64)
    y = np.repeat(outcome, 10)
    p = np.full(y.size, 0.5)
    by_event = cal.cluster_codes(np.repeat(np.arange(200), 10).astype(str))
    by_row = cal.cluster_codes(np.arange(y.size).astype(str))

    def mean_outcome(weights: np.ndarray) -> np.ndarray:
        return np.array([np.sum(weights * y) / np.sum(weights)])

    first = cal.cluster_bootstrap(mean_outcome, by_event, 400, seed=5)
    again = cal.cluster_bootstrap(mean_outcome, by_event, 400, seed=5)
    np.testing.assert_array_equal(first, again)
    naive = cal.cluster_bootstrap(mean_outcome, by_row, 400, seed=5)
    # The honest standard error is sqrt(10) times the one that ignores clustering.
    assert first.std() / naive.std() == pytest.approx(np.sqrt(10), rel=0.2)
    assert first.std() == pytest.approx(0.5 / np.sqrt(200), rel=0.15)
    assert p.size == y.size


def test_percentile_interval_covers_the_truth_about_as_often_as_it_says() -> None:
    hits = 0
    trials = 200
    for trial in range(trials):
        rng = np.random.default_rng(1000 + trial)
        y = (rng.uniform(size=300) < 0.3).astype(np.float64)
        codes = cal.cluster_codes(np.arange(300).astype(str))
        draws = cal.cluster_bootstrap(
            lambda w, y=y: np.array([np.sum(w * y) / np.sum(w)]), codes, 300, seed=trial
        )
        low, high = cal.percentile_interval(draws)
        hits += int(low[0] <= 0.3 <= high[0])
    assert 0.90 <= hits / trials <= 0.99


def test_bad_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        cal.brier(np.array([1.2]), np.array([1.0]))
    with pytest.raises(ValueError):
        cal.brier(np.array([0.2]), np.array([0.5]))
    with pytest.raises(ValueError):
        cal.brier(np.array([0.2, 0.3]), np.array([1.0]))
