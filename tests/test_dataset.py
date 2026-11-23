"""Loading a small cache laid out like data/, and the counts of what drops out."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plumbline import collect, config, dataset, observe
from plumbline.markets import parse_time

DAY = config.DAY


def _pm(market_id: int, **changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": str(market_id),
        "question": "q",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["1", "0"]',
        "clobTokenIds": f'["{market_id}1", "{market_id}2"]',
        "volumeNum": 150000.0,
        "startDate": "2024-04-01T00:00:00Z",
        "endDate": "2024-04-20T00:00:00Z",
        "closedTime": "2024-04-20 01:00:00+00",
        "tags": ["Politics"],
        "eventId": "7",
    }
    record.update(changes)
    return record


def _kalshi(ticker: str, **changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "ticker": ticker,
        "event_ticker": "EV-1",
        "title": "t",
        "market_type": "binary",
        "open_time": "2024-04-01T00:00:00Z",
        "close_time": "2024-04-20T00:00:00Z",
        "result": "yes",
        "volume_fp": "5000.00",
        "tier": "historical",
    }
    record.update(changes)
    return record


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    close = parse_time("2024-04-20T00:00:00Z")
    assert close is not None
    collect.write_jsonl(
        tmp_path / "polymarket" / "markets" / "2024-04.jsonl",
        [
            _pm(1),
            _pm(2, outcomePrices='["0.5", "0.5"]'),
            _pm(3, endDate="2024-04-01T06:00:00Z"),
            _pm(4, outcomePrices='["0", "1"]'),
        ],
    )
    collect.write_jsonl(
        tmp_path / "polymarket" / "history.jsonl",
        [
            {"id": "1", "history": [[close - 8 * DAY, 0.6], [close - 2 * DAY, 0.8]]},
            {"id": "4", "history": []},
        ],
    )
    collect.write_jsonl(
        tmp_path / "kalshi" / "series.jsonl",
        [{"ticker": "S", "category": "Economics", "fee_multiplier": 1}, {"ticker": "EMPTY"}],
    )
    collect.write_jsonl(
        tmp_path / "kalshi" / "markets" / "S.jsonl",
        [
            _kalshi("S-A"),
            _kalshi("S-B", result="scalar"),
            _kalshi("S-C", volume_fp="3.00"),
            _kalshi("S-D", close_time="2024-04-01T12:00:00Z"),
            _kalshi("S-E", result="no"),
        ],
    )
    collect.write_jsonl(tmp_path / "kalshi" / "markets" / "EMPTY.jsonl", [])
    collect.write_jsonl(
        tmp_path / "kalshi" / "candles.jsonl",
        [
            {"ticker": "S-A", "candles": [[close - 7.5 * DAY, 0.70, 0.74, 0.72]]},
            {"ticker": "S-E", "candles": [[close - 7.5 * DAY, 0.00, 0.02, None]]},
        ],
    )
    return tmp_path


def _steps(funnel: list[dict[str, Any]]) -> dict[str, int]:
    return {str(row["step"]): int(row["markets"]) for row in funnel}


def test_polymarket_funnel_counts_every_exclusion(cache: Path) -> None:
    pairs, funnel, reach = dataset.load_polymarket(cache)
    steps = _steps(funnel)
    assert steps["closed markets listed above the volume floor"] == 4
    assert steps["not settled cleanly to one side (excluded)"] == 1
    assert steps["open less than the minimum lifetime (excluded)"] == 1
    assert steps["eligible"] == 2
    assert steps["sampled and fetched"] == 2
    assert steps["fetched, history empty"] == 1
    assert [market.market_id for market, _ in pairs] == ["1", "4"]
    assert reach["markets_fetched"].tolist() == [2]
    assert reach["with_price_history"].tolist() == [1]


def test_kalshi_funnel_counts_every_exclusion(cache: Path) -> None:
    pairs, funnel, _ = dataset.load_kalshi(cache)
    steps = _steps(funnel)
    assert steps["series listed"] == 2
    assert steps["series drawn at random"] == 2
    assert steps["drawn series with any settled market"] == 1
    assert steps["result not yes or no (excluded)"] == 1
    assert steps["below the volume floor (excluded)"] == 1
    assert steps["open less than the minimum lifetime (excluded)"] == 1
    assert steps["eligible"] == 2
    assert steps["fetched, no usable two-sided quote on any day"] == 1
    assert sorted(market.market_id for market, _ in pairs) == ["S-A", "S-E"]


def test_observations_from_the_cache(cache: Path) -> None:
    pm_pairs, _, _ = dataset.load_polymarket(cache)
    k_pairs, _, _ = dataset.load_kalshi(cache)
    table = observe.build_table(pm_pairs + k_pairs)
    week = table[(table["kind"] == "before_close") & (table["days"] == 7)]
    by_venue = {row.venue: row for row in week.itertuples()}
    assert set(by_venue) == {"polymarket", "kalshi"}
    assert by_venue["polymarket"].price == pytest.approx(0.6)
    assert by_venue["kalshi"].price == pytest.approx(0.72)
    assert by_venue["kalshi"].ask == pytest.approx(0.74)
    assert by_venue["kalshi"].fee_rate == pytest.approx(0.07)
    # The split market and the one with a one-sided book never appear.
    assert set(table["market_id"]) == {"1", "S-A"}
