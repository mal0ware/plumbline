"""Rebuild every table and figure.

    uv run python scripts/reproduce.py          # from data/, into results/
    uv run python scripts/reproduce.py --fast   # synthetic markets, into results_fast/

The full run needs the downloads made by scripts/fetch_data.py. The fast run
needs no data and no network: it simulates one fair venue and one with a
planted favourite-longshot bias, and runs the same code on them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from plumbline import collect, config, dataset, experiments, observe, plots, simulate

ROOT = Path(__file__).resolve().parents[1]

FULL_BOOTSTRAPS = 2000
FAST_BOOTSTRAPS = 200
FULL_SIMULATIONS = 10000
FAST_SIMULATIONS = 500

Loaded = tuple[
    dataset.Pairs, dataset.Pairs, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]
]


def to_markdown(frame: pd.DataFrame) -> str:
    """A plain markdown table. Floats are shown to four decimals."""

    def cell(value: object) -> str:
        if isinstance(value, float):
            return "" if value != value else f"{value:.4f}"
        return str(value)

    header = "| " + " | ".join(str(column) for column in frame.columns) + " |"
    rule = "| " + " | ".join("---" for _ in frame.columns) + " |"
    body = [
        "| " + " | ".join(cell(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, rule, *body]) + "\n"


def write_table(out: Path, name: str, frame: pd.DataFrame) -> None:
    frame.to_csv(out / f"{name}.csv", index=False, float_format="%.6f", lineterminator="\n")
    (out / f"{name}.md").write_text(to_markdown(frame), encoding="utf-8", newline="\n")


def synthetic() -> Loaded:
    fair = simulate.simulate_markets(2000, seed=config.SEED, venue="synthetic-fair")
    biased = simulate.simulate_markets(
        2000,
        seed=config.SEED + 1,
        slope=1.3,
        venue="synthetic-biased",
        spread=0.02,
        fee_rate=0.07,
        events_per_series=2,
    )
    # A second fair draw stands in for the sample with no volume floor.
    free = simulate.simulate_markets(1000, seed=config.SEED + 2, venue=dataset.NOFLOOR_VENUE)
    funnel = pd.DataFrame(
        [
            {"venue": "synthetic-fair", "step": "simulated", "markets": len(fair)},
            {"venue": "synthetic-biased", "step": "simulated", "markets": len(biased)},
            {"venue": dataset.NOFLOOR_VENUE, "step": "simulated", "markets": len(free)},
        ]
    )
    reach = pd.DataFrame(
        columns=[
            "venue",
            "close_year",
            "markets_fetched",
            "with_price_history",
            "share_with_history",
        ]
    )
    return (
        fair + biased,
        free,
        funnel,
        reach,
        dataset.kalshi_fee_terms(Path("nowhere")),
        {"data": "synthetic", "floor_venue": "synthetic-fair"},
    )


def real(data: Path) -> Loaded:
    for folder in ("polymarket", collect.NOFLOOR):
        if not (data / folder / "history.jsonl").exists():
            raise SystemExit(
                f"no {folder} data in {data}: run scripts/fetch_data.py, or use --fast"
            )
    pm_pairs, pm_funnel, pm_reach = dataset.load_polymarket(data)
    free_pairs, free_funnel, free_reach = dataset.load_polymarket_nofloor(data)
    k_pairs, k_funnel, k_reach = dataset.load_kalshi(data)
    stamp = data / "manifest.json"
    manifest = json.loads(stamp.read_text(encoding="utf-8")) if stamp.exists() else {}
    info = {"data": "fetched", "floor_venue": "polymarket", "fetch": manifest}
    return (
        pm_pairs + k_pairs,
        free_pairs,
        pd.DataFrame(pm_funnel + free_funnel + k_funnel),
        pd.concat([pm_reach, free_reach, k_reach], ignore_index=True),
        dataset.kalshi_fee_terms(data),
        info,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="synthetic data, fewer resamples")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out: Path = args.out or (ROOT / ("results_fast" if args.fast else "results"))
    out.mkdir(parents=True, exist_ok=True)
    n_boot = FAST_BOOTSTRAPS if args.fast else FULL_BOOTSTRAPS
    n_sims = FAST_SIMULATIONS if args.fast else FULL_SIMULATIONS
    pairs, free_pairs, funnel, reach, fee_terms, info = (
        synthetic() if args.fast else real(args.data)
    )

    obs = observe.build_table(pairs)
    free = observe.build_table(free_pairs)
    both = pd.concat([obs, free], ignore_index=True)
    fetched: dict[str, int] = {}
    for market, _ in pairs + free_pairs:
        fetched[market.venue] = fetched.get(market.venue, 0) + 1

    tables = experiments.run_all(obs, n_boot, config.SEED, n_sims)
    floor_venue = str(info.pop("floor_venue"))
    tables["volume_floor"] = experiments.floor_table(free, n_boot, config.SEED)
    tables["volume_floor_test"] = experiments.floor_test_table(
        obs, free, floor_venue, n_boot, config.SEED
    )
    tables["extremes"] = experiments.extremes_table(both)
    tables["sample_funnel"] = funnel
    tables["history_reach"] = reach
    tables["sample_dates"] = dataset.sample_dates(pairs + free_pairs)
    tables["kalshi_fee_terms"] = fee_terms
    tables["coverage"] = experiments.coverage_table(both, fetched)
    for name, frame in tables.items():
        write_table(out, name, frame)

    plots.calibration_figure(tables["calibration_curve"], out / "calibration.png")
    plots.edge_figure(tables["edge_after_costs"], out / "edge_after_costs.png")
    plots.brier_figure(tables["brier"], out / "brier_by_horizon.png")
    plots.floor_figure(tables["volume_floor"], tables["longshot_bias"], out / "volume_floor.png")

    run = {
        **info,
        "bootstrap_resamples": n_boot,
        "null_simulations": n_sims,
        "seed": config.SEED,
        "observations": len(obs),
        "markets": len(pairs),
        "observations_no_floor": len(free),
        "markets_no_floor": len(free_pairs),
    }
    (out / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(tables)} tables and 4 figures to {out}")


if __name__ == "__main__":
    main()
