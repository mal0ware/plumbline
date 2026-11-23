"""Taker fees on the two venues, and what is left of a calibration gap after them.

Both venues charge takers a fee of the same shape, proportional to p * (1 - p):

- Kalshi: 0.07 * C * P * (1 - P), the order total rounded up to the next cent.
  Source: Bürgi, Deng and Whelan (2026), section 2. A series can scale the
  coefficient through the ``fee_multiplier`` field of the public series record.
- Polymarket: C * feeRate * p * (1 - p), feeRate between 0 and 0.05 by market
  category. Source: the fee page of the Polymarket documentation.

``C`` is the number of contracts and ``p`` the price in dollars.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

KALSHI_COEFFICIENT = 0.07
POLYMARKET_MAX_RATE = 0.05


def _check_price(price: float) -> None:
    if not 0.0 <= price <= 1.0:
        raise ValueError("price must lie in [0, 1]")


def kalshi_taker_fee(
    price: float, contracts: int = 1, coefficient: float = KALSHI_COEFFICIENT
) -> float:
    """Fee in dollars on an order of ``contracts`` at ``price``, rounded up to a cent."""
    _check_price(price)
    if contracts < 0:
        raise ValueError("contracts must not be negative")
    raw_cents = coefficient * contracts * price * (1.0 - price) * 100.0
    return math.ceil(round(raw_cents, 9)) / 100.0


def polymarket_taker_fee(price: float, shares: float, rate: float) -> float:
    """Fee in dollars on ``shares`` bought at ``price`` under fee rate ``rate``."""
    _check_price(price)
    return shares * rate * price * (1.0 - price)


def fee_per_contract(price: Array, rate: Array | float) -> Array:
    """Per-contract fee for a large order, where rounding no longer matters."""
    return np.asarray(rate * price * (1.0 - price), dtype=np.float64)


def taker_edge_yes(y: Array, cost: Array, rate: Array | float) -> Array:
    """Profit per contract, in dollars, of buying the priced side at ``cost`` and holding.

    The contract pays 1 if the outcome is 1. The fee is charged on the cost.
    """
    return np.asarray(y - cost - fee_per_contract(cost, rate), dtype=np.float64)


def taker_edge_no(y: Array, sell_price: Array, rate: Array | float) -> Array:
    """Profit per contract of buying the other side, which costs 1 - ``sell_price``.

    ``sell_price`` is what the priced side can be sold for: the bid where a
    quote is known, the single reported price otherwise.
    """
    cost = 1.0 - sell_price
    return np.asarray((1.0 - y) - cost - fee_per_contract(cost, rate), dtype=np.float64)
