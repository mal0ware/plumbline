"""Turning the cached downloads into markets with quotes, and counting what drops out."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from plumbline import collect, config, kalshi, polymarket
from plumbline.markets import Market, Quote

Pairs = list[tuple[Market, list[Quote]]]


def _year(ts: int) -> int:
    return datetime.fromtimestamp(ts, tz=UTC).year


def _funnel_row(venue: str, step: str, count: int) -> dict[str, Any]:
    return {"venue": venue, "step": step, "markets": count}


def load_polymarket(data: Path) -> tuple[Pairs, list[dict[str, Any]], pd.DataFrame]:
    """Sampled Polymarket markets with their quotes, the selection funnel, and reach by year."""
    records = collect.load_polymarket_records(data)
    parsed = [(record, polymarket.parse_market(record)) for record in records]
    binary = [(record, market) for record, market in parsed if market is not None]
    settled = [(record, market) for record, market in binary if market.outcome is not None]
    lived = [(record, market) for record, market in settled if collect.long_enough(market)]
    sampled = set(collect.polymarket_sample(records))
    histories = {
        str(row["id"]): [Quote(ts=int(t), price=float(p)) for t, p in row["history"]]
        for row in collect.read_jsonl(data / "polymarket" / "history.jsonl")
    }
    pairs: Pairs = []
    reach: dict[int, list[int]] = {}
    for _, market in lived:
        if market.market_id not in sampled or market.market_id not in histories:
            continue
        quotes = histories[market.market_id]
        counts = reach.setdefault(_year(market.close_ts), [0, 0])
        counts[0] += 1
        counts[1] += int(len(quotes) > 0)
        pairs.append((market, quotes))
    funnel = [
        _funnel_row("polymarket", "closed markets listed above the volume floor", len(records)),
        _funnel_row("polymarket", "two outcomes, with open and close times", len(binary)),
        _funnel_row(
            "polymarket", "not settled cleanly to one side (excluded)", len(binary) - len(settled)
        ),
        _funnel_row("polymarket", "settled to one side", len(settled)),
        _funnel_row(
            "polymarket",
            "open less than the minimum lifetime (excluded)",
            len(settled) - len(lived),
        ),
        _funnel_row("polymarket", "eligible", len(lived)),
        _funnel_row("polymarket", "sampled and fetched", len(pairs)),
        _funnel_row(
            "polymarket", "fetched, history empty", sum(1 for _, quotes in pairs if not quotes)
        ),
    ]
    return pairs, funnel, _reach_frame("polymarket", reach)


def load_kalshi(data: Path) -> tuple[Pairs, list[dict[str, Any]], pd.DataFrame]:
    """Sampled Kalshi markets with their quotes, the selection funnel, and reach by year."""
    series = {
        str(row["ticker"]): row for row in collect.read_jsonl(data / "kalshi" / "series.jsonl")
    }
    records = collect.load_kalshi_records(data)
    series_seen = {str(record["series_ticker"]) for record in records}
    series_files = len(list((data / "kalshi" / "markets").glob("*.jsonl")))
    parsed = [
        kalshi.parse_market(record, series.get(str(record["series_ticker"]), {}))
        for record in records
    ]
    binary = [market for market in parsed if market is not None]
    settled = [market for market in binary if market.outcome is not None]
    traded = [m for m in settled if m.volume >= config.KALSHI_MIN_VOLUME_CONTRACTS]
    lived = [market for market in traded if collect.long_enough(market)]
    sampled = set(collect.kalshi_sample(records, series))
    candles = {
        str(row["ticker"]): row["candles"]
        for row in collect.read_jsonl(data / "kalshi" / "candles.jsonl")
    }
    pairs: Pairs = []
    reach: dict[int, list[int]] = {}
    any_candle = 0
    for market in lived:
        if market.market_id not in sampled or market.market_id not in candles:
            continue
        rows = candles[market.market_id]
        quotes = kalshi.parse_candles(rows)
        any_candle += int(len(rows) > 0)
        counts = reach.setdefault(_year(market.close_ts), [0, 0])
        counts[0] += 1
        counts[1] += int(len(quotes) > 0)
        pairs.append((market, quotes))
    funnel = [
        _funnel_row("kalshi", "series listed", len(series)),
        _funnel_row("kalshi", "series drawn at random", series_files),
        _funnel_row("kalshi", "drawn series with any settled market", len(series_seen)),
        _funnel_row("kalshi", "settled markets listed in drawn series", len(records)),
        _funnel_row("kalshi", "binary, with open and close times", len(binary)),
        _funnel_row("kalshi", "result not yes or no (excluded)", len(binary) - len(settled)),
        _funnel_row("kalshi", "below the volume floor (excluded)", len(settled) - len(traded)),
        _funnel_row(
            "kalshi", "open less than the minimum lifetime (excluded)", len(traded) - len(lived)
        ),
        _funnel_row("kalshi", "eligible", len(lived)),
        _funnel_row("kalshi", "sampled and fetched (capped per series)", len(pairs)),
        _funnel_row("kalshi", "fetched, no candlesticks at all", len(pairs) - any_candle),
        _funnel_row(
            "kalshi",
            "fetched, no usable two-sided quote on any day",
            sum(1 for _, quotes in pairs if not quotes),
        ),
    ]
    return pairs, funnel, _reach_frame("kalshi", reach)


def _reach_frame(venue: str, reach: dict[int, list[int]]) -> pd.DataFrame:
    rows = [
        {
            "venue": venue,
            "close_year": year,
            "markets_fetched": counts[0],
            "with_price_history": counts[1],
            "share_with_history": counts[1] / counts[0] if counts[0] else float("nan"),
        }
        for year, counts in sorted(reach.items())
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "venue",
            "close_year",
            "markets_fetched",
            "with_price_history",
            "share_with_history",
        ],
    )


def polymarket_listing_reach(data: Path) -> pd.DataFrame:
    """Listed Polymarket markets per close year, before any sampling."""
    counts: dict[int, int] = {}
    for record in collect.load_polymarket_records(data):
        market = polymarket.parse_market(record)
        if market is not None:
            counts[_year(market.close_ts)] = counts.get(_year(market.close_ts), 0) + 1
    return pd.DataFrame(
        [{"close_year": year, "markets_listed": n} for year, n in sorted(counts.items())]
    )
