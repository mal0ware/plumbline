"""Intervals for one price bin, the calibrated null, and the correction for many tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from plumbline import calibration as cal
from plumbline import experiments

Z2 = 1.959964**2


def _wilson(wins: float, rows: float, clusters: float, squares: float) -> tuple[float, float]:
    low, high = cal.cluster_wilson(
        np.array(wins), np.array(rows), np.array(clusters), np.array(squares)
    )
    return float(low), float(high)


def test_wilson_matches_the_textbook_interval_without_clustering() -> None:
    # 30 wins of 100 independent rows: sum of squared deviations is 30*0.49 + 70*0.09 = 21.
    low, high = _wilson(30, 100, 100, 21.0)
    # The cluster-robust variance carries a factor 100/99, hence 99 effective rows.
    n = 99.0
    centre = (0.3 + Z2 / (2 * n)) / (1 + Z2 / n)
    half = 1.959964 * np.sqrt(0.3 * 0.7 / n + Z2 / (4 * n * n)) / (1 + Z2 / n)
    assert low == pytest.approx(centre - half)
    assert high == pytest.approx(centre + half)
    assert low == pytest.approx(0.2189, abs=2e-3) and high == pytest.approx(0.3958, abs=2e-3)


def test_wilson_is_never_degenerate_when_every_market_won() -> None:
    # 31 wins of 31 in 25 events: the case a bootstrap gets wrong.
    low, high = _wilson(31, 31, 25, 0.0)
    assert high == pytest.approx(1.0)
    assert low == pytest.approx(25 / (25 + Z2))
    assert low < 0.87
    lost_low, lost_high = _wilson(0, 31, 25, 0.0)
    assert lost_low == pytest.approx(0.0) and lost_high == pytest.approx(1 - low)
    one_low, one_high = _wilson(5, 5, 1, 0.0)
    assert one_high - one_low > 0.7


def test_wilson_widens_with_clustering() -> None:
    # 20 clusters of 10 identical rows, half of the clusters won.
    squares = 20 * (5.0**2)
    low, high = _wilson(100, 200, 20, squares)
    plain_low, plain_high = _wilson(100, 200, 200, 50.0)
    assert high - low > 2.5 * (plain_high - plain_low)
    # About 19 effective rows.
    half = 1.959964 * np.sqrt(0.25 / 19 + Z2 / (4 * 19 * 19)) / (1 + Z2 / 19)
    assert high - low == pytest.approx(2 * half)


def test_wilson_covers_the_truth_about_as_often_as_it_says() -> None:
    rng = np.random.default_rng(11)
    truth, clusters, size = 0.85, 40, 3
    covered = 0
    trials = 2000
    for _ in range(trials):
        # Every market in a cluster shares one outcome.
        won = (rng.random(clusters) < truth).astype(np.float64)
        wins, rows = won.sum() * size, clusters * size
        squares = float(np.sum((won * size - wins / rows * size) ** 2))
        low, high = _wilson(wins, rows, clusters, squares)
        covered += low <= truth <= high
    assert 0.93 <= covered / trials <= 0.99


def _frame(price: list[float], outcome: list[int], unit: list[str]) -> pd.DataFrame:
    n = len(price)
    return pd.DataFrame(
        {
            "venue": "v",
            "market_id": [f"m{i}" for i in range(n)],
            "cluster": unit,
            "unit": unit,
            "kind": "before_close",
            "days": 7,
            "price": price,
            "bid": [p - 0.02 for p in price],
            "ask": [p + 0.02 for p in price],
            "fee_rate": 0.07,
            "outcome": outcome,
        }
    )


def test_a_bin_where_every_market_won_does_not_clear_its_costs() -> None:
    # 31 markets at 85 cents in 25 events, all of which won, plus ordinary rows elsewhere.
    units = [f"e{i % 25}" for i in range(31)] + [f"x{i}" for i in range(40)]
    obs = _frame([0.85] * 31 + [0.5] * 40, [1] * 31 + [1, 0] * 20, units)
    edge, null = experiments.edge_tables(obs, n_sims=300, seed=1)
    row = edge[
        (edge["sample"] == experiments.LIVE)
        & (edge["price_bin"] == "0.80-0.90")
        & (edge["side"] == "buy priced side")
        & (edge["cost_model"] == "quoted side, with fee")
    ].iloc[0]
    assert row["markets"] == 31 and row["clusters"] == 25
    cost = 0.87 + 0.07 * 0.87 * 0.13
    assert row["edge"] == pytest.approx(1.0 - cost)
    assert row["edge_high"] == pytest.approx(1.0 - cost)
    assert row["edge_low"] == pytest.approx(25 / (25 + Z2) - cost)
    assert row["edge_low"] < 0 < row["edge"]
    assert 0 < row["p_null"] <= row["p_holm"] <= 1
    assert (null["intervals_above_zero"] == 0).all()


def test_the_curve_uses_the_same_interval() -> None:
    units = [f"e{i % 25}" for i in range(31)]
    curve = experiments.curve_table(_frame([0.85] * 31, [1] * 31, units))
    row = curve[curve["sample"] == experiments.LIVE].iloc[0]
    assert row["gap"] == pytest.approx(0.15)
    assert row["gap_low"] == pytest.approx(25 / (25 + Z2) - 0.85)
    assert row["gap_high"] == pytest.approx(0.15)


def test_live_sample_and_its_bins() -> None:
    obs = _frame([0.02, 0.05, 0.5, 0.95, 0.97], [0, 0, 1, 1, 1], list("abcde"))
    assert experiments.take(obs, experiments.LIVE)["price"].tolist() == [0.05, 0.5, 0.95]
    assert len(experiments.take(obs, experiments.ALL)) == 5
    curve = experiments.curve_table(obs)
    live = curve[curve["sample"] == experiments.LIVE]
    assert live["price_bin"].tolist() == ["0.05-0.10", "0.50-0.60", "0.90-0.95"]
    extremes = experiments.extremes_table(obs).iloc[0]
    assert extremes["share_outside_5c_to_95c"] == pytest.approx(0.4)
    assert extremes["share_within_2c_of_0_or_1"] == pytest.approx(0.2)
    assert extremes["markets_from_5c_to_95c"] == 3


def test_holm_against_a_worked_example() -> None:
    p = np.array([0.01, 0.04, 0.03, 0.005])
    np.testing.assert_allclose(experiments.holm(p), [0.03, 0.06, 0.06, 0.02])
    assert experiments.holm(np.array([0.5, 0.9])).max() <= 1.0


def test_null_outcomes_are_calibrated_and_shared_within_a_cluster() -> None:
    price = [0.2, 0.2, 0.7, 0.7] * 50
    units = [f"e{i // 2}" for i in range(200)]
    obs = _frame(price, [0] * 200, units)
    layout = experiments._Layout(obs, experiments.LIVE_EDGES, [7])
    for scheme in experiments.NULL_SCHEMES:
        sims = np.vstack(list(layout.simulate(scheme, 600, seed=2)))
        assert sims.shape == (600, 200)
        np.testing.assert_allclose(sims.mean(axis=0), layout.p, atol=0.07)
    by_cluster = np.vstack(list(layout.simulate(experiments.NULL_BY_CLUSTER, 600, seed=2)))
    by_market = np.vstack(list(layout.simulate(experiments.NULL_BY_MARKET, 600, seed=2)))
    # Two rows of one cluster at the same price always share an outcome.
    same = (layout.cluster[:-1] == layout.cluster[1:]) & (layout.p[:-1] == layout.p[1:])
    assert same.sum() == 100
    assert (by_cluster[:, :-1][:, same] == by_cluster[:, 1:][:, same]).all()
    assert not (by_market[:, :-1][:, same] == by_market[:, 1:][:, same]).all()
    # So the win rate of a bin varies more from draw to draw.
    assert layout.win_rates(by_cluster)[0].std(axis=0).mean() > 1.2 * (
        layout.win_rates(by_market)[0].std(axis=0).mean()
    )
