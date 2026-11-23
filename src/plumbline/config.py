"""Every choice that defines the sample, fixed before any result was looked at."""

from __future__ import annotations

SEED = 20261123

# Polymarket: closed markets whose scheduled end falls in these months (inclusive).
PM_FIRST_MONTH = (2022, 10)
PM_LAST_MONTH = (2026, 10)
PM_MIN_VOLUME_USD = 100_000.0
PM_HISTORIES_PER_MONTH = 300

# Kalshi: settled markets that closed before this instant (2026-11-01T00:00:00Z).
KALSHI_MAX_CLOSE_TS = 1793491200
KALSHI_SERIES_SAMPLED = 600
KALSHI_MARKETS_PER_SERIES = 25
KALSHI_MIN_VOLUME_CONTRACTS = 100.0

# A market must have been open at least this long to be sampled.
MIN_LIFETIME_DAYS = 2.0

# Horizons before the close, in days. The 7-day horizon is the primary one.
HORIZONS_DAYS = (1, 7, 30)
PRIMARY_HORIZON_DAYS = 7

# A price may be at most this old at the moment it is read.
MAX_STALENESS_HOURS = 36.0

# Kalshi quotes wider than this are not used as a price.
KALSHI_MAX_SPREAD = 0.20

DAY = 86_400
