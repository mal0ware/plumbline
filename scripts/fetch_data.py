"""Download settled markets and their price histories into data/.

Only public, keyless endpoints are called. Requests are spaced out, failures
are retried with backoff, and every stage can be resumed. Nothing in data/ is
ever committed.

    uv run python scripts/fetch_data.py                 # everything
    uv run python scripts/fetch_data.py --only polymarket
    uv run python scripts/fetch_data.py --only nofloor
    uv run python scripts/fetch_data.py --only kalshi

Each run adds one entry to data/manifest.json with its start, its end and the
number of requests it made, so the manifest is a log of every session.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plumbline import collect, config
from plumbline.http import PoliteClient

ROOT = Path(__file__).resolve().parents[1]

# Seconds between requests. Well under what either venue publishes as its limit.
POLYMARKET_INTERVAL = 0.2
KALSHI_INTERVAL = 0.25

STAGES = ("polymarket", "nofloor", "kalshi")


def log(message: str) -> None:
    print(f"{datetime.now(tz=UTC):%H:%M:%S} {message}", flush=True)


def now() -> str:
    return f"{datetime.now(tz=UTC):%Y-%m-%dT%H:%M:%SZ}"


def record_session(path: Path, session: dict[str, Any]) -> None:
    """Append one session to the manifest, keeping whatever was there."""
    manifest: dict[str, Any] = {}
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    sessions = list(manifest.get("sessions", []))
    sessions.append(session)
    manifest["sessions"] = sessions
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=STAGES, default=None)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    data: Path = args.data
    data.mkdir(parents=True, exist_ok=True)
    stages = STAGES if args.only is None else (args.only,)
    started = now()
    requests = 0

    if "polymarket" in stages:
        client = PoliteClient(POLYMARKET_INTERVAL)
        collect.fetch_polymarket_markets(data, client, log)
        collect.fetch_polymarket_histories(data, client, log)
        requests += client.requests_made
    if "nofloor" in stages:
        client = PoliteClient(POLYMARKET_INTERVAL)
        collect.fetch_polymarket_nofloor_markets(data, client, log)
        collect.fetch_polymarket_histories(
            data, client, log, collect.NOFLOOR, config.PM_NOFLOOR_HISTORIES_PER_MONTH
        )
        requests += client.requests_made
    if "kalshi" in stages:
        client = PoliteClient(KALSHI_INTERVAL)
        collect.fetch_kalshi_series(data, client, log)
        collect.fetch_kalshi_markets(data, client, log)
        collect.fetch_kalshi_candles(data, client, log)
        requests += client.requests_made

    record_session(
        data / "manifest.json",
        {
            "stages": list(stages),
            "started_utc": started,
            "finished_utc": now(),
            "requests": requests,
        },
    )
    log(f"done, {requests} requests")


if __name__ == "__main__":
    main()
