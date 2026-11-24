"""The whole pipeline on simulated markets whose answer is known."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from plumbline import config, experiments, observe, simulate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def tables() -> dict[str, pd.DataFrame]:
    fair = simulate.simulate_markets(2500, seed=1, venue="fair")
    biased = simulate.simulate_markets(
        2500, seed=2, slope=1.3, venue="biased", spread=0.02, fee_rate=0.07
    )
    obs = observe.build_table(fair + biased)
    return experiments.run_all(obs, n_boot=200, seed=config.SEED, n_sims=400)


def _row(frame: pd.DataFrame, venue: str, days: int, sample: str = experiments.ALL) -> pd.Series:
    picked = frame[
        (frame["venue"] == venue)
        & (frame["days_before_close"] == days)
        & (frame["sample"] == sample)
    ]
    assert len(picked) == 1
    return picked.iloc[0]


def test_a_market_calibrated_by_construction_comes_out_calibrated(
    tables: dict[str, pd.DataFrame],
) -> None:
    for days in config.HORIZONS_DAYS:
        row = _row(tables["longshot_bias"], "fair", days)
        # 0.8 of the width of a 95% interval is about three standard errors.
        width = row["logit_slope_high"] - row["logit_slope_low"]
        assert abs(row["logit_slope"] - 1.0) <= 0.8 * width < 0.5
        assert abs(row["mz_psi"]) <= 0.8 * (row["mz_psi_high"] - row["mz_psi_low"])
        assert abs(row["mean_gap"]) < 0.03
        assert row["logit_slope_low"] < row["logit_slope"] < row["logit_slope_high"]
        live = _row(tables["longshot_bias"], "fair", days, experiments.LIVE)
        assert live["markets"] < row["markets"]
        live_width = live["logit_slope_high"] - live["logit_slope_low"]
        assert abs(live["logit_slope"] - 1.0) <= 0.8 * live_width < 0.6
    curve = tables["calibration_curve"]
    fair = curve[curve["venue"] == "fair"]
    inside = (fair["gap_low"] <= 0) & (fair["gap_high"] >= 0)
    assert inside.mean() >= 0.85
    assert (fair["gap_low"] < fair["gap"]).all() and (fair["gap"] < fair["gap_high"]).all()


def test_a_planted_longshot_bias_is_recovered(tables: dict[str, pd.DataFrame]) -> None:
    for days in config.HORIZONS_DAYS:
        row = _row(tables["longshot_bias"], "biased", days)
        assert row["logit_slope_low"] > 1.0
        width = row["logit_slope_high"] - row["logit_slope_low"]
        assert abs(row["logit_slope"] - 1.3) <= 0.8 * width < 0.5
        assert row["mz_psi_low"] > 0.0
        assert row["longshot_gap"] < 0.0 < row["favourite_gap"]
        live = _row(tables["longshot_bias"], "biased", days, experiments.LIVE)
        assert live["logit_slope_low"] > 1.0


def test_prices_beat_the_base_rate_and_more_so_near_the_close(
    tables: dict[str, pd.DataFrame],
) -> None:
    both = tables["brier"]
    assert set(both["sample"]) == {
        experiments.ALL_MARKETS,
        experiments.SAME_MARKETS,
        experiments.LIVE_MARKETS,
    }
    live = both[both["sample"] == experiments.LIVE_MARKETS]
    assert (live["skill_vs_base_rate"] > 0).all()
    same = both[both["sample"] == experiments.SAME_MARKETS]
    assert same.groupby("venue")["markets"].nunique().eq(1).all()
    brier = both[both["sample"] == experiments.ALL_MARKETS]
    for venue in ("fair", "biased"):
        scores = [_row(brier, venue, days, experiments.ALL_MARKETS)["brier"] for days in (1, 7, 30)]
        assert scores[0] < scores[1] < scores[2] < 0.25
        for days in (1, 7, 30):
            row = _row(brier, venue, days, experiments.ALL_MARKETS)
            assert row["skill_vs_base_rate"] > 0
            total = row["reliability"] - row["resolution"] + row["uncertainty"] + row["within_bin"]
            assert total == pytest.approx(row["brier"], abs=1e-9)


def test_fair_prices_lose_the_fee_and_the_spread(tables: dict[str, pd.DataFrame]) -> None:
    edge = tables["edge_after_costs"]
    costed = edge[(edge["venue"] == "biased") & (edge["cost_model"] == "quoted side, with fee")]
    free = edge[(edge["venue"] == "biased") & (edge["cost_model"] == "midpoint, no fee")]
    assert len(costed) == len(free) > 0
    merged = costed.merge(
        free, on=["sample", "days_before_close", "side", "price_bin"], suffixes=("_cost", "_free")
    )
    assert (merged["edge_cost"] < merged["edge_free"]).all()
    fair = edge[(edge["venue"] == "fair") & edge["cost_model"].str.contains("top fee rate")]
    assert len(fair) > 0
    assert (fair["edge"] * fair["markets"]).sum() / fair["markets"].sum() < 0


def test_no_fee_edges_of_the_two_sides_cancel(tables: dict[str, pd.DataFrame]) -> None:
    edge = tables["edge_after_costs"]
    free = edge[edge["cost_model"].str.contains("no fee")]
    wide = free.pivot_table(
        index=["sample", "venue", "days_before_close", "price_bin"], columns="side", values="edge"
    )
    np.testing.assert_allclose(wide["buy priced side"] + wide["buy other side"], 0, atol=1e-9)


def test_every_table_is_filled(tables: dict[str, pd.DataFrame]) -> None:
    for name, frame in tables.items():
        # No venue in this fixture is sampled by series, so that table is empty.
        assert frame.empty == (name == "clustering"), name
    assert set(tables["by_category"]["venue"]) == {"fair", "biased"}
    assert (tables["extremes"]["share_outside_5c_to_95c"] <= 1).all()
    for name in ("longshot_bias", "calibration_curve", "edge_after_costs", "by_category"):
        assert set(tables[name]["sample"]) == set(experiments.SAMPLES), name


def test_a_calibrated_market_rarely_beats_its_costs(tables: dict[str, pd.DataFrame]) -> None:
    null = tables["edge_null"]
    assert set(null["null"]) == set(experiments.NULL_SCHEMES)
    # With costs the chance of an interval above zero is far below 2.5% a test.
    assert (null["expected_under_null"] < 0.015 * null["tests"]).all()
    edge = tables["edge_after_costs"]
    fair = edge[(edge["venue"] == "fair") & edge["cost_model"].str.contains("top fee rate")]
    assert fair["p_null"].between(0, 1).all()
    assert (fair["p_holm"] >= fair["p_null"]).all()
    assert fair["p_holm"].min() > 0.05
    assert edge[edge["cost_model"].str.contains("no fee")]["p_null"].isna().all()
    # The planted bias makes dear contracts win too often, and the null sees it.
    biased = edge[(edge["venue"] == "biased") & edge["cost_model"].str.contains("with fee")]
    assert biased["p_null"].min() < 0.01


def test_series_and_event_clustering_agree_on_the_estimate() -> None:
    pairs = simulate.simulate_markets(600, seed=6, venue="by-series", events_per_series=3)
    plain = simulate.simulate_markets(100, seed=7, venue="by-event")
    obs = observe.build_table(pairs + plain)
    plain_rows = obs[obs["venue"] == "by-event"]
    assert (plain_rows["unit"] == plain_rows["cluster"]).all()
    both = experiments.clustering_table(obs, 100, config.SEED)
    assert set(both["venue"]) == {"by-series"}
    wide = both.pivot_table(
        index=["sample", "days_before_close"], columns="resampled", values="logit_slope"
    )
    np.testing.assert_allclose(wide["event"], wide["series"])
    assert (both["clusters"] < both["events"]).all()


def test_the_floor_test_separates_a_biased_sample_from_a_fair_one() -> None:
    fair = observe.build_table(simulate.simulate_markets(1500, seed=3, venue="fair"))
    again = observe.build_table(simulate.simulate_markets(1500, seed=4, venue="free"))
    bent = observe.build_table(simulate.simulate_markets(1500, seed=5, slope=1.4, venue="free"))
    same = experiments.floor_test_table(fair, again, "fair", 200, config.SEED)
    apart = experiments.floor_test_table(fair, bent, "fair", 200, config.SEED)
    first = same[same["comparison"].str.startswith("a: drawn")]
    assert len(first) == 6
    assert ((first["logit_slope_diff_low"] < 0) & (first["logit_slope_diff_high"] > 0)).mean() > 0.8
    second = apart[apart["comparison"].str.startswith("a: drawn")]
    assert (second["logit_slope_diff_high"] < 0).all()
    tiers = experiments.floor_table(again, 100, config.SEED)
    assert "every market" in set(tiers["final_volume"])


def test_reproduce_fast_is_deterministic(tmp_path: Path) -> None:
    outputs = []
    for name in ("first", "second"):
        out = tmp_path / name
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "reproduce.py"), "--fast", "--out", str(out)],
            check=True,
            capture_output=True,
        )
        outputs.append(out)
    files = sorted(path.name for path in outputs[0].glob("*.csv"))
    assert len(files) >= 9
    assert (outputs[0] / "calibration.png").stat().st_size > 0
    for name in [*files, "run.json"]:
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name
