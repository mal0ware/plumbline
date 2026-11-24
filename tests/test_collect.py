"""The HTTP client and the sampling rules, with a fake transport. No network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plumbline import collect, config, polymarket
from plumbline.http import HttpError, PoliteClient


class FakeNet:
    """Scripted responses, and a clock that only moves when the client sleeps."""

    def __init__(self, responses: list[tuple[int, Any]]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []
        self.now = 0.0
        self.sleeps: list[float] = []

    def transport(self, url: str) -> tuple[int, bytes]:
        self.urls.append(url)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def client(self, interval: float = 1.0, retries: int = 3) -> PoliteClient:
        return PoliteClient(
            interval,
            max_retries=retries,
            transport=self.transport,
            sleep=self.sleep,
            clock=self.clock,
        )


def test_requests_are_spaced() -> None:
    net = FakeNet([(200, {"a": 1}), (200, {"a": 2}), (200, {"a": 3})])
    client = net.client(interval=0.5)
    assert [client.get_json("u")["a"] for _ in range(3)] == [1, 2, 3]
    assert net.sleeps == [0.5, 0.5]


def test_rate_limit_and_server_errors_are_retried_with_backoff() -> None:
    net = FakeNet([(429, {}), (503, {}), (0, {}), (200, {"ok": True})])
    client = net.client(interval=0.0)
    assert client.get_json("u") == {"ok": True}
    assert net.sleeps == [2.0, 4.0, 8.0]
    assert client.requests_made == 4


def test_gives_up_after_the_last_retry() -> None:
    net = FakeNet([(429, {})] * 3)
    with pytest.raises(HttpError) as caught:
        net.client(interval=0.0, retries=2).get_json("u")
    assert caught.value.status == 429


def test_client_errors_are_not_retried() -> None:
    net = FakeNet([(404, {}), (200, {})])
    with pytest.raises(HttpError):
        net.client().get_json("u")
    assert len(net.urls) == 1


def test_the_client_sends_no_credentials() -> None:
    import inspect

    from plumbline import http

    source = inspect.getsource(http).lower()
    assert "authorization" not in source and "api_key" not in source and "token" not in source
    assert "@" not in http.USER_AGENT


def test_choose_is_seeded_and_ignores_input_order() -> None:
    ids = [str(i) for i in range(100)]
    first = collect.choose(ids, 10, seed=3)
    assert first == collect.choose(list(reversed(ids)), 10, seed=3)
    assert first != collect.choose(ids, 10, seed=4)
    assert len(first) == 10 and set(first) <= set(ids)
    assert collect.choose(ids[:5], 10, seed=3) == sorted(ids[:5])


def test_months() -> None:
    assert collect.months((2022, 11), (2023, 2)) == [(2022, 11), (2022, 12), (2023, 1), (2023, 2)]


def _record(market_id: int, **changes: Any) -> dict[str, Any]:
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
        "tags": [],
        "eventId": str(market_id // 2),
    }
    record.update(changes)
    return record


def test_polymarket_sample_keeps_only_settled_long_lived_markets_with_tokens() -> None:
    records = [
        _record(1),
        _record(2, outcomePrices='["0.5", "0.5"]'),  # split: never sampled
        _record(3, endDate="2024-04-01T12:00:00Z"),  # open for half a day
        _record(4, clobTokenIds=None),  # nothing to fetch
        _record(5, outcomes='["A", "B", "C"]'),  # not binary
        _record(6, outcomePrices='["0", "1"]'),
    ]
    assert collect.polymarket_sample(records) == ["1", "6"]


def test_polymarket_sample_is_capped_per_month_and_stable() -> None:
    records = [_record(i) for i in range(1, config.PM_HISTORIES_PER_MONTH + 51)]
    sample = collect.polymarket_sample(records)
    assert len(sample) == config.PM_HISTORIES_PER_MONTH
    assert sample == collect.polymarket_sample(list(reversed(records)))


def test_keyset_pagination_follows_the_cursor() -> None:
    page_one = {"markets": [{"id": "1"}, {"id": "2"}], "next_cursor": "abc"}
    page_two = {"markets": [{"id": "3"}], "next_cursor": None}
    net = FakeNet([(200, page_one), (200, page_two)])
    rows = list(
        polymarket.iter_closed_markets(
            net.client(interval=0.0), end_min="a", end_max="b", min_volume=100000
        )
    )
    assert [row["id"] for row in rows] == ["1", "2", "3"]
    assert "after_cursor" not in net.urls[0] and "after_cursor=abc" in net.urls[1]
    assert "closed=true" in net.urls[0] and "volume_num_min=100000" in net.urls[0]


def test_jsonl_round_trip_and_truncated_tail(tmp_path: Path) -> None:
    path = tmp_path / "x" / "rows.jsonl"
    collect.write_jsonl(path, [{"a": 1}, {"a": 2}])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"a": 3, "b"')  # a write that was cut off
    assert list(collect.read_jsonl(path)) == [{"a": 1}, {"a": 2}]
    assert list(collect.read_jsonl(tmp_path / "missing.jsonl")) == []


def test_histories_are_fetched_once_and_resumed(tmp_path: Path) -> None:
    collect.write_jsonl(
        tmp_path / "polymarket" / "markets" / "2024-04.jsonl", [_record(1), _record(6)]
    )
    net = FakeNet([(200, {"history": [{"t": 5, "p": 0.5}]}), (500, {}), (500, {})])
    client = net.client(interval=0.0, retries=1)
    logs: list[str] = []
    collect.fetch_polymarket_histories(tmp_path, client, logs.append)
    cached = list(collect.read_jsonl(tmp_path / "polymarket" / "history.jsonl"))
    assert cached == [{"id": "1", "history": [[5, 0.5]]}]
    assert any("HTTP 500" in line for line in logs)
    net.responses = [(200, {"history": []})]
    collect.fetch_polymarket_histories(tmp_path, client, logs.append)
    cached = list(collect.read_jsonl(tmp_path / "polymarket" / "history.jsonl"))
    assert [row["id"] for row in cached] == ["1", "6"]
    assert sum("market=11" in url for url in net.urls) == 1


def test_no_floor_listing_sends_no_volume_filter_and_a_start_cutoff() -> None:
    net = FakeNet([(200, {"markets": [{"id": "1"}], "next_cursor": None})])
    rows = list(
        polymarket.iter_closed_markets(
            net.client(interval=0.0), end_min="a", end_max="b", min_volume=0.0, start_max="c"
        )
    )
    assert [row["id"] for row in rows] == ["1"]
    assert "volume_num_min" not in net.urls[0] and "start_date_max=c" in net.urls[0]


def test_no_floor_days_are_a_fixed_draw_from_every_month() -> None:
    days = collect.nofloor_days()
    assert days == collect.nofloor_days() and len(set(days)) == len(days)
    listed = collect.months(config.PM_NOFLOOR_FIRST_MONTH, config.PM_LAST_MONTH)
    assert len(days) == config.PM_NOFLOOR_DAYS_PER_MONTH * len(listed)
    per_month: dict[str, int] = {}
    for day in days:
        per_month[day[:7]] = per_month.get(day[:7], 0) + 1
    assert set(per_month.values()) == {config.PM_NOFLOOR_DAYS_PER_MONTH}
    assert "2023-02-30" not in days and min(days) >= "2023-01-01"


def test_no_floor_listing_is_cached_by_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect, "nofloor_days", lambda: ["2025-06-10"])
    net = FakeNet([(200, {"markets": [{"id": "9"}], "next_cursor": None})])
    logs: list[str] = []
    collect.fetch_polymarket_nofloor_markets(tmp_path, net.client(interval=0.0), logs.append)
    collect.fetch_polymarket_nofloor_markets(tmp_path, net.client(interval=0.0), logs.append)
    assert len(net.urls) == 1
    url = net.urls[0]
    assert "end_date_min=2025-06-10T00%3A00%3A00Z" in url
    assert "end_date_max=2025-06-11T00%3A00%3A00Z" in url
    # Started at least two days before the end of the listed day.
    assert "start_date_max=2025-06-09T00%3A00%3A00Z" in url
    cached = collect.load_polymarket_records(tmp_path, collect.NOFLOOR)
    assert [row["id"] for row in cached] == ["9"]


def test_the_second_series_draw_keeps_the_first() -> None:
    series = [{"ticker": f"S{i:05d}"} for i in range(5000)]
    tickers = [row["ticker"] for row in series]
    first = collect.choose(tickers, config.KALSHI_SERIES_SAMPLED, config.SEED)
    both = collect.kalshi_series_sample(series)
    assert set(first) <= set(both)
    assert len(both) == len(set(both)) == config.KALSHI_SERIES_SAMPLED + config.KALSHI_SERIES_ADDED
    assert both == collect.kalshi_series_sample(list(reversed(series)))


def test_each_fetch_session_is_added_to_the_manifest(tmp_path: Path) -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("fetch_data", root / "scripts" / "fetch_data.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"note": "kept"}), encoding="utf-8")
    module.record_session(path, {"requests": 3})
    module.record_session(path, {"requests": 5})
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["note"] == "kept"
    assert [session["requests"] for session in manifest["sessions"]] == [3, 5]


def test_adding_series_does_not_change_the_markets_drawn_from_the_first_ones() -> None:
    series = {f"S{i:05d}": {"ticker": f"S{i:05d}"} for i in range(900)}
    first = collect.choose(list(series), config.KALSHI_SERIES_SAMPLED, config.SEED)
    later = sorted(set(series) - set(first))[:3]

    def markets(ticker: str) -> list[dict[str, Any]]:
        return [
            {
                "ticker": f"{ticker}-{n:03d}",
                "event_ticker": f"{ticker}-E{n // 4}",
                "market_type": "binary",
                "open_time": "2024-04-01T00:00:00Z",
                "close_time": "2024-04-20T00:00:00Z",
                "result": "yes",
                "volume_fp": "5000.00",
                "series_ticker": ticker,
            }
            for n in range(60)
        ]

    old = [row for ticker in first[:5] for row in markets(ticker)]
    new = [row for ticker in later for row in markets(ticker)]
    before = collect.kalshi_sample(old, series)
    after = collect.kalshi_sample(old + new, series)
    assert len(before) == 5 * config.KALSHI_MARKETS_PER_SERIES
    assert set(before) <= set(after)
    assert len(after) == 8 * config.KALSHI_MARKETS_PER_SERIES
    assert after == collect.kalshi_sample(list(reversed(old + new)), series)
