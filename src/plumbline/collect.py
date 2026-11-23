"""Downloading and caching. Everything here writes under ``data/``, which is never committed.

Each stage is resumable: finished month files, series files and already-fetched
histories are skipped, so an interrupted run can be started again.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from plumbline import config, kalshi, polymarket
from plumbline.http import HttpError, PoliteClient
from plumbline.markets import Market

Log = Callable[[str], None]


def months(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    """Calendar months from ``first`` to ``last``, both included."""
    out: list[tuple[int, int]] = []
    year, month = first
    while (year, month) <= last:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{year}-{month:02d}-01T00:00:00Z", f"{next_year}-{next_month:02d}-01T00:00:00Z"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Write rows to ``path`` atomically, one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield the rows of a JSON-lines file. A truncated last line is skipped."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def choose(ids: list[str], count: int, seed: int) -> list[str]:
    """A seeded random subset of ``ids`` that does not depend on their input order."""
    ordered = sorted(set(ids))
    if len(ordered) <= count:
        return ordered
    rng = np.random.default_rng(seed)
    picked = rng.choice(len(ordered), size=count, replace=False)
    return sorted(ordered[int(i)] for i in picked)


def long_enough(market: Market) -> bool:
    """True if the market was open for at least the minimum lifetime."""
    return market.close_ts - market.open_ts >= config.MIN_LIFETIME_DAYS * config.DAY


# ---------------------------------------------------------------- Polymarket


def fetch_polymarket_markets(data: Path, client: PoliteClient, log: Log) -> None:
    """List closed markets above the volume floor, one file per month of end date."""
    for year, month in months(config.PM_FIRST_MONTH, config.PM_LAST_MONTH):
        path = data / "polymarket" / "markets" / f"{year}-{month:02d}.jsonl"
        if path.exists():
            continue
        end_min, end_max = _month_bounds(year, month)
        rows = list(
            polymarket.iter_closed_markets(
                client, end_min=end_min, end_max=end_max, min_volume=config.PM_MIN_VOLUME_USD
            )
        )
        write_jsonl(path, rows)
        log(f"polymarket markets {path.stem}: {len(rows)}")


def load_polymarket_records(data: Path) -> list[dict[str, Any]]:
    """Every cached Gamma record, one per market id."""
    seen: dict[str, dict[str, Any]] = {}
    for path in sorted((data / "polymarket" / "markets").glob("*.jsonl")):
        for row in read_jsonl(path):
            seen[str(row["id"])] = row
    return [seen[key] for key in sorted(seen)]


def polymarket_sample(records: list[dict[str, Any]]) -> list[str]:
    """The market ids whose price history is fetched.

    Eligible markets are binary, cleanly settled, have a CLOB token and were open
    for the minimum lifetime. Up to a fixed number are drawn per month of close.
    None of these conditions looks at a price before the close.
    """
    by_month: dict[str, list[str]] = {}
    for record in records:
        market = polymarket.parse_market(record)
        if market is None or market.outcome is None or not long_enough(market):
            continue
        if polymarket.first_token(record) is None:
            continue
        month = datetime.fromtimestamp(market.close_ts, tz=UTC).strftime("%Y-%m")
        by_month.setdefault(month, []).append(market.market_id)
    chosen: list[str] = []
    for index, month in enumerate(sorted(by_month)):
        chosen.extend(choose(by_month[month], config.PM_HISTORIES_PER_MONTH, config.SEED + index))
    return sorted(chosen)


def fetch_polymarket_histories(data: Path, client: PoliteClient, log: Log) -> None:
    """Fetch the price history of every sampled market that is not cached yet."""
    records = {str(r["id"]): r for r in load_polymarket_records(data)}
    path = data / "polymarket" / "history.jsonl"
    done = {str(row["id"]) for row in read_jsonl(path)}
    todo = [
        market_id
        for market_id in polymarket_sample(list(records.values()))
        if market_id not in done
    ]
    log(f"polymarket histories: {len(done)} cached, {len(todo)} to fetch")
    for count, market_id in enumerate(todo, start=1):
        token = polymarket.first_token(records[market_id])
        assert token is not None
        try:
            payload = polymarket.fetch_history(client, token)
        except HttpError as exc:
            log(f"polymarket history {market_id}: {exc}")
            continue
        quotes = polymarket.parse_history(payload)
        _append_jsonl(path, {"id": market_id, "history": [[q.ts, q.price] for q in quotes]})
        if count % 500 == 0:
            log(f"polymarket histories: {count}/{len(todo)}")


# -------------------------------------------------------------------- Kalshi


def fetch_kalshi_series(data: Path, client: PoliteClient, log: Log) -> None:
    """Cache the list of every series, with its category and fee terms."""
    path = data / "kalshi" / "series.jsonl"
    if path.exists():
        return
    rows = kalshi.list_series(client)
    write_jsonl(path, rows)
    log(f"kalshi series: {len(rows)}")


def kalshi_series_sample(series: list[dict[str, Any]]) -> list[str]:
    """A seeded random draw of series tickers."""
    tickers = [str(row["ticker"]) for row in series if row.get("ticker")]
    return choose(tickers, config.KALSHI_SERIES_SAMPLED, config.SEED)


def fetch_kalshi_markets(data: Path, client: PoliteClient, log: Log) -> None:
    """For each sampled series, cache its settled markets (one page from each tier)."""
    series = list(read_jsonl(data / "kalshi" / "series.jsonl"))
    for count, ticker in enumerate(kalshi_series_sample(series), start=1):
        path = data / "kalshi" / "markets" / f"{ticker}.jsonl"
        if path.exists():
            continue
        try:
            rows = kalshi.settled_markets(client, ticker, config.KALSHI_MAX_CLOSE_TS)
        except HttpError as exc:
            log(f"kalshi markets {ticker}: {exc}")
            continue
        write_jsonl(path, rows)
        if count % 50 == 0:
            log(f"kalshi markets: {count} series done")


def load_kalshi_records(data: Path) -> list[dict[str, Any]]:
    """Every cached Kalshi market record, one per ticker, with its series attached."""
    seen: dict[str, dict[str, Any]] = {}
    for path in sorted((data / "kalshi" / "markets").glob("*.jsonl")):
        for row in read_jsonl(path):
            row["series_ticker"] = path.stem
            seen[str(row["ticker"])] = row
    return [seen[key] for key in sorted(seen)]


def kalshi_sample(records: list[dict[str, Any]], series: dict[str, dict[str, Any]]) -> list[str]:
    """The tickers whose candlesticks are fetched: a capped draw within each series."""
    by_series: dict[str, list[str]] = {}
    for record in records:
        info = series.get(str(record.get("series_ticker")), {})
        market = kalshi.parse_market(record, info)
        if market is None or market.outcome is None or not long_enough(market):
            continue
        if market.volume < config.KALSHI_MIN_VOLUME_CONTRACTS:
            continue
        by_series.setdefault(str(record["series_ticker"]), []).append(market.market_id)
    chosen: list[str] = []
    for index, ticker in enumerate(sorted(by_series)):
        chosen.extend(
            choose(by_series[ticker], config.KALSHI_MARKETS_PER_SERIES, config.SEED + index)
        )
    return sorted(chosen)


def fetch_kalshi_candles(data: Path, client: PoliteClient, log: Log) -> None:
    """Fetch daily candlesticks for every sampled market that is not cached yet."""
    series = {str(row["ticker"]): row for row in read_jsonl(data / "kalshi" / "series.jsonl")}
    records = {str(r["ticker"]): r for r in load_kalshi_records(data)}
    path = data / "kalshi" / "candles.jsonl"
    done = {str(row["ticker"]) for row in read_jsonl(path)}
    todo = [t for t in kalshi_sample(list(records.values()), series) if t not in done]
    log(f"kalshi candles: {len(done)} cached, {len(todo)} to fetch")
    for count, ticker in enumerate(todo, start=1):
        record = records[ticker]
        try:
            payload = kalshi.fetch_candles(client, record)
        except HttpError as exc:
            log(f"kalshi candles {ticker}: {exc}")
            continue
        _append_jsonl(path, {"ticker": ticker, "candles": kalshi.slim_candles(payload)})
        if count % 500 == 0:
            log(f"kalshi candles: {count}/{len(todo)}")
