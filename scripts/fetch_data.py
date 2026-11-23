"""Download settled markets and their price histories into data/.

Only public, keyless endpoints are called. Requests are spaced out, failures
are retried with backoff, and every stage can be resumed. Nothing in data/ is
ever committed.

    uv run python scripts/fetch_data.py                 # everything
    uv run python scripts/fetch_data.py --only polymarket
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from plumbline import collect
from plumbline.http import PoliteClient

ROOT = Path(__file__).resolve().parents[1]

# Seconds between requests. Well under what either venue publishes as its limit.
POLYMARKET_INTERVAL = 0.2
KALSHI_INTERVAL = 0.5


def log(message: str) -> None:
    print(f"{datetime.now(tz=UTC):%H:%M:%S} {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("polymarket", "kalshi"), default=None)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    data: Path = args.data
    data.mkdir(parents=True, exist_ok=True)

    if args.only in (None, "polymarket"):
        client = PoliteClient(POLYMARKET_INTERVAL)
        collect.fetch_polymarket_markets(data, client, log)
        collect.fetch_polymarket_histories(data, client, log)
    if args.only in (None, "kalshi"):
        client = PoliteClient(KALSHI_INTERVAL)
        collect.fetch_kalshi_series(data, client, log)
        collect.fetch_kalshi_markets(data, client, log)
        collect.fetch_kalshi_candles(data, client, log)

    manifest = data / "manifest.json"
    stamp = {"fetched_utc": f"{datetime.now(tz=UTC):%Y-%m-%dT%H:%M:%SZ}"}
    if manifest.exists():
        stamp = {
            **stamp,
            "first_fetched_utc": json.loads(manifest.read_text()).get(
                "first_fetched_utc", stamp["fetched_utc"]
            ),
        }
    else:
        stamp["first_fetched_utc"] = stamp["fetched_utc"]
    manifest.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
