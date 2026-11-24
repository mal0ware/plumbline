"""The common record both venues are reduced to."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

CATEGORIES = ("sports", "crypto", "politics", "economics", "culture", "other")


@dataclass(frozen=True)
class Market:
    """One binary contract.

    ``outcome`` is 1 if the priced side won, 0 if it lost, and ``None`` if the
    market has not settled cleanly to one side (still open, cancelled, split).
    Only markets with an outcome of 0 or 1 are ever scored. ``cluster`` is the
    event the market belongs to. ``series`` is a coarser group, set where the
    sample was drawn by series, and empty otherwise.
    """

    venue: str
    market_id: str
    cluster: str
    title: str
    category: str
    open_ts: int
    close_ts: int
    outcome: int | None
    volume: float
    yes_no: bool
    fee_rate: float
    series: str = ""


@dataclass(frozen=True)
class Quote:
    """A price for the priced side at one time. ``bid`` and ``ask`` may be missing."""

    ts: int
    price: float
    bid: float | None = None
    ask: float | None = None


def parse_time(text: str | None) -> int | None:
    """Parse the timestamp formats the two APIs use into Unix seconds (UTC)."""
    if not text:
        return None
    cleaned = text.strip().replace("Z", "+00:00")
    if " " in cleaned and "T" not in cleaned:
        cleaned = cleaned.replace(" ", "T", 1)
    if cleaned.endswith("+00"):
        cleaned += ":00"
    try:
        moment = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp())
