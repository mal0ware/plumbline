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
