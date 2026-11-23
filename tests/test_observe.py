"""No price is read from the future, and no unsettled market is scored."""

from __future__ import annotations

from dataclasses import replace

import pytest

from plumbline import config, observe
from plumbline.markets import Market, Quote, parse_time

DAY = config.DAY
OPEN = 1_700_000_000


def _market(life_days: int = 40, outcome: int | None = 1) -> Market:
    return Market(
        venue="test",
        market_id="m1",
        cluster="e1",
        title="",
        category="other",
        open_ts=OPEN,
        close_ts=OPEN + life_days * DAY,
        outcome=outcome,
        volume=1.0,
        yes_no=True,
        fee_rate=0.0,
    )


def _daily(life_days: int = 40) -> list[Quote]:
    return [Quote(ts=OPEN + day * DAY, price=day / 100) for day in range(life_days + 5)]


def test_price_at_takes_the_latest_quote_not_after_the_moment() -> None:
    quotes = [Quote(100, 0.1), Quote(200, 0.2), Quote(300, 0.3)]
    assert observe.price_at(quotes, 250, 1000) == quotes[1]
    assert observe.price_at(quotes, 200, 1000) == quotes[1]
    assert observe.price_at(quotes, 199, 1000) == quotes[0]
    assert observe.price_at(quotes, 99, 1000) is None
    assert observe.price_at([], 99, 1000) is None


def test_price_at_refuses_a_stale_quote() -> None:
    quotes = [Quote(100, 0.1)]
    assert observe.price_at(quotes, 150, 50) == quotes[0]
    assert observe.price_at(quotes, 151, 50) is None


def test_quotes_after_the_moment_never_change_the_observation() -> None:
    market = _market()
    quotes = _daily()
    base = observe.before_close(market, quotes, 7)
    assert base is not None
    moment = market.close_ts - 7 * DAY
    assert base.quote_ts <= moment
    assert base.price == pytest.approx(0.33)
    tampered = [q if q.ts <= moment else replace(q, price=0.99) for q in quotes]
    again = observe.before_close(market, tampered, 7)
    assert again is not None
    assert (again.quote_ts, again.price) == (base.quote_ts, base.price)


def test_no_market_is_counted_before_it_has_settled() -> None:
    quotes = _daily()
    market = _market(outcome=None)
    assert observe.before_close(market, quotes, 1) is None
    assert observe.after_open(market, quotes, 7) is None
    assert observe.build_table([(_market(outcome=None), quotes)]).empty


def test_a_market_not_yet_open_at_the_horizon_gives_nothing() -> None:
    market = _market(life_days=5)
    quotes = _daily(5)
    assert observe.before_close(market, quotes, 1) is not None
    assert observe.before_close(market, quotes, 7) is None
    assert observe.before_close(market, quotes, 30) is None


def test_stale_history_gives_nothing() -> None:
    market = _market()
    moment = market.close_ts - 7 * DAY
    stale = [Quote(ts=moment - 37 * 3600, price=0.4)]
    fresh = [Quote(ts=moment - 35 * 3600, price=0.4)]
    assert observe.before_close(market, stale, 7) is None
    assert observe.before_close(market, fresh, 7) is not None


def test_after_open_needs_a_day_left() -> None:
    quotes = _daily()
    assert observe.after_open(_market(life_days=8), quotes, 7) is not None
    assert observe.after_open(_market(life_days=7), quotes, 7) is None
    seen = observe.after_open(_market(life_days=40), quotes, 7)
    assert seen is not None and seen.price == pytest.approx(0.07)


def test_build_table_has_one_row_per_usable_moment() -> None:
    table = observe.build_table([(_market(life_days=40), _daily())])
    assert sorted(zip(table["kind"], table["days"], strict=True)) == [
        ("after_open", 7),
        ("before_close", 1),
        ("before_close", 7),
        ("before_close", 30),
    ]
    assert set(table["outcome"]) == {1}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-11-05T12:00:00Z", 1730808000),
        ("2024-11-06 15:17:41+00", 1730906261),
        ("2024-11-06 15:17:41.75469+00", 1730906261),
        ("2026-11-23T13:44:03.781224Z", 1795441443),
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_time(text: str | None, expected: int | None) -> None:
    assert parse_time(text) == expected
