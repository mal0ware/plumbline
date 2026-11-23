"""Polymarket: settled markets from the Gamma API, price history from the CLOB API.

Endpoints, both public and keyless:

- ``GET https://gamma-api.polymarket.com/markets/keyset`` lists markets.
- ``GET https://clob.polymarket.com/prices-history`` returns a token's price series.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

from plumbline.http import PoliteClient
from plumbline.markets import Market, Quote, parse_time

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# The finest spacing, in minutes, at which the history endpoint returned any
# points for closed markets when this was built (see PAPER.md, "Data reach").
HISTORY_FIDELITY_MINUTES = 720

# Highest taker rate in the published fee table; used as the upper-bound scenario.
MAX_TAKER_RATE = 0.05

KEPT_FIELDS = (
    "id",
    "question",
    "outcomes",
    "outcomePrices",
    "clobTokenIds",
    "volumeNum",
    "startDate",
    "createdAt",
    "endDate",
    "closedTime",
    "umaResolutionStatus",
    "negRisk",
    "feeType",
    "feeSchedule",
    "category",
)

_TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sports", ("sports", "esports", "soccer", "nba", "nfl", "tennis", "mlb", "nhl", "games")),
    ("crypto", ("crypto", "bitcoin", "ethereum", "nfts", "defi", "crypto prices")),
    (
        "politics",
        ("politics", "elections", "geopolitics", "world", "us-current-affairs", "global politics"),
    ),
    ("economics", ("economy", "economics", "finance", "business", "fed", "stocks", "earnings")),
    (
        "culture",
        ("culture", "pop culture", "pop-culture", "entertainment", "mentions", "movies", "music"),
    ),
)


def category_from_labels(labels: list[str]) -> str:
    """Map a market's tag labels to one coarse category. First matching rule wins."""
    lowered = {label.strip().lower() for label in labels}
    for category, keys in _TAG_RULES:
        if lowered.intersection(keys):
            return category
    return "other"


def slim(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields this project uses from one Gamma market record."""
    kept: dict[str, Any] = {key: raw.get(key) for key in KEPT_FIELDS}
    kept["tags"] = [str(tag.get("label", "")) for tag in raw.get("tags") or []]
    events = raw.get("events") or []
    kept["eventId"] = str(events[0].get("id")) if events else None
    return kept


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def settled_outcome(outcome_prices: Any) -> int | None:
    """1 if the first outcome paid out, 0 if the second did, ``None`` otherwise.

    A settled binary market reports final prices of (1, 0) or (0, 1), sometimes a
    hair away from those. Anything else, such as (0.5, 0.5) for a split or (0, 0)
    for a void market, is not a clean settlement and returns ``None``.
    """
    prices = _json_list(outcome_prices)
    if len(prices) != 2:
        return None
    try:
        first, second = float(prices[0]), float(prices[1])
    except (TypeError, ValueError):
        return None
    if first >= 0.99 and second <= 0.01:
        return 1
    if first <= 0.01 and second >= 0.99:
        return 0
    return None


def first_token(record: dict[str, Any]) -> str | None:
    """The CLOB token id of the first outcome, or ``None`` if the market has none."""
    tokens = _json_list(record.get("clobTokenIds"))
    return str(tokens[0]) if len(tokens) == 2 and tokens[0] else None


def parse_market(record: dict[str, Any]) -> Market | None:
    """Turn a slim Gamma record into a ``Market``. ``None`` if it is not binary or undated.

    The close time is the earlier of the scheduled end and the actual close, so
    that a market which settled early is not credited with prices from after
    its outcome was known. The priced side is the first listed outcome.
    """
    outcomes = _json_list(record.get("outcomes"))
    if len(outcomes) != 2:
        return None
    opened = parse_time(record.get("startDate")) or parse_time(record.get("createdAt"))
    candidates = (parse_time(record.get("endDate")), parse_time(record.get("closedTime")))
    ends = [moment for moment in candidates if moment is not None]
    if opened is None or not ends:
        return None
    labels = [str(label) for label in record.get("tags") or []]
    if record.get("category"):
        labels.append(str(record["category"]))
    schedule = record.get("feeSchedule") or {}
    market_id = str(record["id"])
    return Market(
        venue="polymarket",
        market_id=market_id,
        cluster=f"pm-{record.get('eventId') or 'm' + market_id}",
        title=str(record.get("question") or ""),
        category=category_from_labels(labels),
        open_ts=opened,
        close_ts=min(ends),
        outcome=settled_outcome(record.get("outcomePrices")),
        volume=float(record.get("volumeNum") or 0.0),
        yes_no=[str(o).lower() for o in outcomes] == ["yes", "no"],
        fee_rate=float(schedule.get("rate") or 0.0),
    )


def parse_history(payload: Any) -> list[Quote]:
    """Turn a ``prices-history`` response into quotes sorted by time."""
    points = payload.get("history", []) if isinstance(payload, dict) else []
    quotes = [
        Quote(ts=int(point["t"]), price=float(point["p"]))
        for point in points
        if isinstance(point, dict) and "t" in point and "p" in point
    ]
    return sorted(quotes, key=lambda quote: quote.ts)


def iter_closed_markets(
    client: PoliteClient, *, end_min: str, end_max: str, min_volume: float
) -> Iterator[dict[str, Any]]:
    """Yield slim records for closed markets whose scheduled end is in a window."""
    cursor: str | None = None
    while True:
        params = {
            "closed": "true",
            "limit": "100",
            "volume_num_min": str(int(min_volume)),
            "end_date_min": end_min,
            "end_date_max": end_max,
            "include_tag": "true",
        }
        if cursor:
            params["after_cursor"] = cursor
        page = client.get_json(f"{GAMMA}/markets/keyset?{urlencode(params)}")
        markets = page.get("markets") or []
        for raw in markets:
            yield slim(raw)
        cursor = page.get("next_cursor")
        if not cursor or not markets:
            return


def fetch_history(client: PoliteClient, token: str) -> Any:
    """Fetch the full price history of one token at the finest available spacing."""
    params = {"market": token, "interval": "max", "fidelity": str(HISTORY_FIDELITY_MINUTES)}
    return client.get_json(f"{CLOB}/prices-history?{urlencode(params)}")
