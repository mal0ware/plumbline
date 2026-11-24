"""Kalshi: settled markets and daily candlesticks from the public trade API.

Endpoints, all public and keyless:

- ``GET /series`` lists every series with its category and fee terms.
- ``GET /markets`` and ``GET /historical/markets`` list settled markets. The
  second serves markets settled before a cutoff the exchange moves forward.
- ``GET /series/{series}/markets/{ticker}/candlesticks`` and
  ``GET /historical/markets/{ticker}/candlesticks`` return daily quotes.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote as urlquote
from urllib.parse import urlencode

from plumbline import config
from plumbline.http import PoliteClient
from plumbline.markets import Market, Quote, parse_time

BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Coefficient of the general taker fee, per contract: 0.07 * P * (1 - P).
TAKER_COEFFICIENT = 0.07

DAILY_MINUTES = 1440
MAX_HISTORICAL_PAGES = 3

_CATEGORY = {
    "sports": "sports",
    "crypto": "crypto",
    "elections": "politics",
    "politics": "politics",
    "world": "politics",
    "economics": "economics",
    "financials": "economics",
    "companies": "economics",
    "commodities": "economics",
    "entertainment": "culture",
    "mentions": "culture",
    "culture": "culture",
    "social": "culture",
}

_SERIES_FIELDS = ("ticker", "title", "category", "fee_type", "fee_multiplier")
_MARKET_FIELDS = (
    "ticker",
    "event_ticker",
    "title",
    "market_type",
    "open_time",
    "close_time",
    "result",
    "volume_fp",
    "can_close_early",
)


def category(name: str | None) -> str:
    """Map a Kalshi series category to one coarse category."""
    return _CATEGORY.get((name or "").strip().lower(), "other")


def list_series(client: PoliteClient) -> list[dict[str, Any]]:
    """Every series, reduced to the fields this project uses."""
    payload = client.get_json(f"{BASE}/series")
    return [{key: row.get(key) for key in _SERIES_FIELDS} for row in payload.get("series") or []]


def _slim_market(raw: dict[str, Any], tier: str) -> dict[str, Any]:
    kept: dict[str, Any] = {key: raw.get(key) for key in _MARKET_FIELDS}
    kept["tier"] = tier
    return kept


def settled_markets(client: PoliteClient, series: str, max_close_ts: int) -> list[dict[str, Any]]:
    """Settled markets of one series from both tiers, closed before ``max_close_ts``."""
    rows: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(MAX_HISTORICAL_PAGES):
        params = {"series_ticker": series, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        page = client.get_json(f"{BASE}/historical/markets?{urlencode(params)}")
        rows.extend(_slim_market(raw, "historical") for raw in page.get("markets") or [])
        cursor = str(page.get("cursor") or "")
        if not cursor:
            break
    params = {
        "series_ticker": series,
        "status": "settled",
        "limit": "1000",
        "max_close_ts": str(max_close_ts),
    }
    page = client.get_json(f"{BASE}/markets?{urlencode(params)}")
    rows.extend(_slim_market(raw, "live") for raw in page.get("markets") or [])
    kept = []
    for row in rows:
        closed = parse_time(row.get("close_time"))
        if closed is not None and closed < max_close_ts:
            kept.append(row)
    return kept


def parse_market(record: dict[str, Any], series: dict[str, Any]) -> Market | None:
    """Turn a slim market record into a ``Market``. ``None`` if not binary or undated.

    Only a result of ``yes`` or ``no`` counts as an outcome. Scalar and void
    results leave the outcome empty, so the market is never scored.
    """
    if record.get("market_type") != "binary":
        return None
    opened = parse_time(record.get("open_time"))
    closed = parse_time(record.get("close_time"))
    if opened is None or closed is None:
        return None
    result = str(record.get("result") or "").lower()
    outcome = 1 if result == "yes" else 0 if result == "no" else None
    multiplier = series.get("fee_multiplier")
    return Market(
        venue="kalshi",
        market_id=str(record["ticker"]),
        cluster=f"k-{record.get('event_ticker') or record['ticker']}",
        title=str(record.get("title") or ""),
        category=category(series.get("category")),
        open_ts=opened,
        close_ts=closed,
        outcome=outcome,
        volume=float(record.get("volume_fp") or 0.0),
        yes_no=True,
        fee_rate=TAKER_COEFFICIENT * float(1.0 if multiplier is None else multiplier),
        series=f"k-{record['series_ticker']}" if record.get("series_ticker") else "",
    )


def fetch_candles(client: PoliteClient, record: dict[str, Any]) -> Any:
    """Fetch the daily candlesticks of one market over its whole life."""
    opened = parse_time(record.get("open_time"))
    closed = parse_time(record.get("close_time"))
    assert opened is not None and closed is not None
    params = urlencode(
        {
            "start_ts": str(opened),
            "end_ts": str(closed + config.DAY),
            "period_interval": str(DAILY_MINUTES),
        }
    )
    ticker = urlquote(str(record["ticker"]), safe="")
    if record.get("tier") == "historical":
        return client.get_json(f"{BASE}/historical/markets/{ticker}/candlesticks?{params}")
    series = urlquote(str(record["series_ticker"]), safe="")
    return client.get_json(f"{BASE}/series/{series}/markets/{ticker}/candlesticks?{params}")


def _number(block: Any, key: str) -> float | None:
    if not isinstance(block, dict):
        return None
    value = block.get(key, block.get(f"{key}_dollars"))
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def slim_candles(payload: Any) -> list[list[float | None]]:
    """Reduce a candlestick response to rows of [end time, bid, ask, last trade]."""
    rows: list[list[float | None]] = []
    candles = payload.get("candlesticks", []) if isinstance(payload, dict) else []
    for candle in candles:
        if not isinstance(candle, dict) or "end_period_ts" not in candle:
            continue
        rows.append(
            [
                float(candle["end_period_ts"]),
                _number(candle.get("yes_bid"), "close"),
                _number(candle.get("yes_ask"), "close"),
                _number(candle.get("price"), "close"),
            ]
        )
    return rows


def parse_candles(rows: list[list[float | None]]) -> list[Quote]:
    """Turn cached candle rows into quotes, keeping only usable two-sided quotes.

    The price is the midpoint of the closing bid and ask. A day is dropped if
    either side is missing, if the bid is below one cent or the ask above 99
    cents (a one-sided book), or if the spread is wider than the limit.
    """
    quotes: list[Quote] = []
    for row in rows:
        ts, bid, ask = row[0], row[1], row[2]
        if ts is None or bid is None or ask is None:
            continue
        if bid < 0.01 or ask > 0.99 or ask <= bid:
            continue
        if ask - bid > config.KALSHI_MAX_SPREAD + 1e-9:
            continue
        quotes.append(Quote(ts=int(ts), price=(bid + ask) / 2.0, bid=bid, ask=ask))
    return sorted(quotes, key=lambda quote: quote.ts)
