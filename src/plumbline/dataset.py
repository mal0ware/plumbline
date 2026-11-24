"""Turning the cached downloads into markets with quotes, and counting what drops out."""

from __future__ import annotations

from dataclasses import replace
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


NOFLOOR_VENUE = "polymarket-nofloor"


def load_polymarket_nofloor(data: Path) -> tuple[Pairs, list[dict[str, Any]], pd.DataFrame]:
    """The Polymarket sample drawn with no volume floor, under its own venue name."""
    return load_polymarket(
        data,
        folder=collect.NOFLOOR,
        venue=NOFLOOR_VENUE,
        per_month=config.PM_NOFLOOR_HISTORIES_PER_MONTH,
        listed="closed markets listed on the drawn days, any volume, started two days before",
    )


def load_polymarket(
    data: Path,
    folder: str = "polymarket",
    venue: str = "polymarket",
    per_month: int = config.PM_HISTORIES_PER_MONTH,
    listed: str = "closed markets listed above the volume floor",
) -> tuple[Pairs, list[dict[str, Any]], pd.DataFrame]:
    """Sampled Polymarket markets with their quotes, the selection funnel, and reach by year."""
    records = collect.load_polymarket_records(data, folder)
    parsed = [(record, polymarket.parse_market(record)) for record in records]
    binary = [(record, market) for record, market in parsed if market is not None]
    settled = [(record, market) for record, market in binary if market.outcome is not None]
    lived = [(record, market) for record, market in settled if collect.long_enough(market)]
    sampled = set(collect.polymarket_sample(records, per_month))
    histories = {
        str(row["id"]): [Quote(ts=int(t), price=float(p)) for t, p in row["history"]]
        for row in collect.read_jsonl(data / folder / "history.jsonl")
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
        pairs.append((replace(market, venue=venue), quotes))
    funnel = [
        _funnel_row("polymarket", listed, len(records)),
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
    for row in funnel:
        row["venue"] = venue
    return pairs, funnel, _reach_frame(venue, reach)


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


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")


def sample_dates(pairs: Pairs) -> pd.DataFrame:
    """Per venue: the first and last close among fetched markets, and the earliest price."""
    spans: dict[str, list[int]] = {}
    for market, quotes in pairs:
        span = spans.setdefault(market.venue, [market.close_ts, market.close_ts, 2**62])
        span[0] = min(span[0], market.close_ts)
        span[1] = max(span[1], market.close_ts)
        if quotes:
            span[2] = min(span[2], quotes[0].ts)
    rows = [
        {
            "venue": venue,
            "first_close": _day(span[0]),
            "last_close": _day(span[1]),
            "earliest_price": _day(span[2]) if span[2] < 2**62 else "",
        }
        for venue, span in sorted(spans.items())
    ]
    return pd.DataFrame(rows, columns=["venue", "first_close", "last_close", "earliest_price"])


def kalshi_fee_terms(data: Path) -> pd.DataFrame:
    """How many listed Kalshi series carry each fee type and fee multiplier."""
    counts: dict[tuple[str, str], int] = {}
    for row in collect.read_jsonl(data / "kalshi" / "series.jsonl"):
        key = (str(row.get("fee_type")), str(row.get("fee_multiplier")))
        counts[key] = counts.get(key, 0) + 1
    rows = [
        {"fee_type": fee_type, "fee_multiplier": multiplier, "series": count}
        for (fee_type, multiplier), count in sorted(counts.items())
    ]
    return pd.DataFrame(rows, columns=["fee_type", "fee_multiplier", "series"])
