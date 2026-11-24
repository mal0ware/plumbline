"""Parsers, on records shaped like the ones the two APIs return. No network."""

from __future__ import annotations

from typing import Any

import pytest

from plumbline import kalshi, polymarket


def _gamma(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "500832",
        "question": "Will the thing happen by June 1?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0", "1"]',
        "clobTokenIds": '["111", "222"]',
        "volumeNum": 205624.0,
        "startDate": "2024-04-20T15:00:00Z",
        "createdAt": "2024-04-19T15:00:00Z",
        "endDate": "2024-06-01T12:00:00Z",
        "closedTime": "2024-06-05 02:55:41+00",
        "feeSchedule": None,
        "category": None,
        "tags": ["Politics", "India"],
        "eventId": "9001",
    }
    record.update(changes)
    return record


def test_polymarket_market_is_parsed() -> None:
    market = polymarket.parse_market(_gamma())
    assert market is not None
    assert market.venue == "polymarket" and market.market_id == "500832"
    assert market.cluster == "pm-9001"
    assert market.category == "politics"
    assert market.outcome == 0
    assert market.yes_no
    assert market.open_ts == 1713625200
    # The scheduled end comes before the actual close, so it is the close used.
    assert market.close_ts == 1717243200


def test_polymarket_early_settlement_uses_the_actual_close() -> None:
    market = polymarket.parse_market(_gamma(closedTime="2024-05-10 08:00:00+00"))
    assert market is not None and market.close_ts == 1715328000


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ('["1", "0"]', 1),
        ('["0", "1"]', 0),
        ('["0.9999989531672559", "0.0000010468327440"]', 1),
        ('["0.5", "0.5"]', None),
        ('["0", "0"]', None),
        ('["0.62", "0.38"]', None),
        ('["1", "0", "0"]', None),
        ("", None),
        (None, None),
        ("not json", None),
    ],
)
def test_only_a_clean_settlement_counts_as_an_outcome(prices: Any, expected: int | None) -> None:
    assert polymarket.settled_outcome(prices) == expected


def test_polymarket_rejects_markets_that_are_not_binary_or_dated() -> None:
    assert polymarket.parse_market(_gamma(outcomes='["A", "B", "C"]')) is None
    assert polymarket.parse_market(_gamma(endDate=None, closedTime=None)) is None
    assert polymarket.parse_market(_gamma(startDate=None, createdAt=None)) is None


def test_polymarket_named_sides_and_missing_event() -> None:
    market = polymarket.parse_market(
        _gamma(outcomes='["Hurricanes", "Panthers"]', eventId=None, tags=["Sports", "NHL"])
    )
    assert market is not None
    assert not market.yes_no
    assert market.cluster == "pm-m500832"
    assert market.category == "sports"


def test_polymarket_tokens_history_and_slimming() -> None:
    assert polymarket.first_token(_gamma()) == "111"
    assert polymarket.first_token(_gamma(clobTokenIds=None)) is None
    quotes = polymarket.parse_history({"history": [{"t": 20, "p": 0.4}, {"t": 10, "p": 0.3}]})
    assert [(q.ts, q.price) for q in quotes] == [(10, 0.3), (20, 0.4)]
    assert polymarket.parse_history({"error": "x"}) == []
    raw = {
        "id": "1",
        "description": "long text",
        "tags": [{"label": "Crypto"}],
        "events": [{"id": 77}],
    }
    slim = polymarket.slim(raw)
    assert "description" not in slim and slim["tags"] == ["Crypto"] and slim["eventId"] == "77"


def test_category_rules() -> None:
    assert polymarket.category_from_labels(["Esports", "Dota 2"]) == "sports"
    assert polymarket.category_from_labels(["Bitcoin"]) == "crypto"
    assert polymarket.category_from_labels(["Fed", "Economy"]) == "economics"
    assert polymarket.category_from_labels(["Weather"]) == "other"
    assert kalshi.category("Elections") == "politics"
    assert kalshi.category("Financials") == "economics"
    assert kalshi.category("Climate and Weather") == "other"
    assert kalshi.category(None) == "other"


def _kalshi(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "ticker": "KXFED-26SEP-T4.75",
        "event_ticker": "KXFED-26SEP",
        "title": "Fed funds above 4.75%?",
        "market_type": "binary",
        "open_time": "2025-08-06T14:30:00Z",
        "close_time": "2026-09-16T17:55:00Z",
        "result": "no",
        "volume_fp": "398151.88",
        "tier": "historical",
        "series_ticker": "KXFED",
    }
    record.update(changes)
    return record


def test_kalshi_market_is_parsed() -> None:
    series = {"category": "Economics", "fee_multiplier": 1}
    market = kalshi.parse_market(_kalshi(), series)
    assert market is not None
    assert market.outcome == 0 and market.category == "economics"
    assert market.cluster == "k-KXFED-26SEP"
    assert market.series == "k-KXFED"
    assert market.volume == pytest.approx(398151.88)
    assert market.fee_rate == pytest.approx(0.07)
    half = kalshi.parse_market(_kalshi(result="yes"), {"fee_multiplier": 0.5})
    assert half is not None and half.outcome == 1 and half.fee_rate == pytest.approx(0.035)
    free = kalshi.parse_market(_kalshi(), {"fee_multiplier": 0})
    assert free is not None and free.fee_rate == 0.0


@pytest.mark.parametrize("result", ["scalar", "", None, "void"])
def test_kalshi_result_other_than_yes_or_no_is_not_an_outcome(result: str | None) -> None:
    market = kalshi.parse_market(_kalshi(result=result), {})
    assert market is not None and market.outcome is None


def test_kalshi_rejects_non_binary_and_undated() -> None:
    assert kalshi.parse_market(_kalshi(market_type="scalar"), {}) is None
    assert kalshi.parse_market(_kalshi(close_time=None), {}) is None


def test_kalshi_candles_from_both_tiers() -> None:
    historical = {
        "candlesticks": [
            {
                "end_period_ts": 100,
                "yes_bid": {"close": "0.4000"},
                "yes_ask": {"close": "0.4400"},
                "price": {"close": None},
            },
        ]
    }
    live = {
        "candlesticks": [
            {
                "end_period_ts": 200,
                "yes_bid": {"close_dollars": "0.5000"},
                "yes_ask": {"close_dollars": "0.5200"},
                "price": {"close_dollars": "0.5100"},
            },
        ]
    }
    assert kalshi.slim_candles(historical) == [[100.0, 0.40, 0.44, None]]
    assert kalshi.slim_candles(live) == [[200.0, 0.50, 0.52, 0.51]]
    assert kalshi.slim_candles({"error": "x"}) == []


def test_kalshi_quotes_need_two_sides_and_a_tight_spread() -> None:
    rows: list[list[float | None]] = [
        [1.0, 0.40, 0.44, None],  # kept
        [2.0, 0.00, 0.03, None],  # no bid
        [3.0, 0.97, 1.00, None],  # no ask
        [4.0, 0.30, 0.60, None],  # too wide
        [5.0, None, 0.50, None],  # missing side
        [6.0, 0.50, 0.50, None],  # crossed or locked
        [7.0, 0.40, 0.60, None],  # exactly at the limit: kept
    ]
    quotes = kalshi.parse_candles(rows)
    assert [q.ts for q in quotes] == [1, 7]
    assert quotes[0].price == pytest.approx(0.42)
    assert quotes[0].bid == 0.40 and quotes[0].ask == 0.44
