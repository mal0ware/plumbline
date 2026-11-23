"""Fee formulas against worked values."""

from __future__ import annotations

import numpy as np
import pytest

from plumbline import fees


def test_kalshi_fee_worked_values() -> None:
    # 0.07 * 100 * 0.5 * 0.5 = $1.75 exactly.
    assert fees.kalshi_taker_fee(0.50, 100) == pytest.approx(1.75)
    # One contract at 50c: 1.75c rounds up to 2c.
    assert fees.kalshi_taker_fee(0.50, 1) == pytest.approx(0.02)
    # 0.07 * 100 * 0.2 * 0.8 = $1.12 exactly, so no rounding.
    assert fees.kalshi_taker_fee(0.20, 100) == pytest.approx(1.12)
    # 0.07 * 3 * 0.33 * 0.67 = 4.643c, rounds up to 5c.
    assert fees.kalshi_taker_fee(0.33, 3) == pytest.approx(0.05)
    assert fees.kalshi_taker_fee(0.0, 10) == 0.0
    assert fees.kalshi_taker_fee(1.0, 10) == 0.0


def test_large_order_fee_per_contract_at_fifty_cents() -> None:
    # 0.07 * 0.5 * 0.5 = 1.75 cents a contract, the figure in Bürgi, Deng and Whelan.
    assert fees.kalshi_taker_fee(0.50, 100) / 100 == pytest.approx(0.0175)
    per_contract = fees.fee_per_contract(np.array([0.5]), fees.KALSHI_COEFFICIENT)[0]
    assert per_contract == pytest.approx(0.0175)


def test_kalshi_fee_is_symmetric_and_never_below_the_unrounded_fee() -> None:
    for cents in range(1, 100):
        price = cents / 100
        fee = fees.kalshi_taker_fee(price, 7)
        assert fee == pytest.approx(fees.kalshi_taker_fee(1 - price, 7))
        assert fee >= 0.07 * 7 * price * (1 - price) - 1e-12
        assert fee < 0.07 * 7 * price * (1 - price) + 0.01


def test_polymarket_fee_worked_values() -> None:
    assert fees.polymarket_taker_fee(0.5, 100, 0.05) == pytest.approx(1.25)
    assert fees.polymarket_taker_fee(0.9, 100, 0.01) == pytest.approx(0.09)
    assert fees.polymarket_taker_fee(0.3, 100, 0.0) == 0.0


def test_edges_without_fee_sum_to_minus_the_spread() -> None:
    y = np.array([1.0, 0.0, 1.0])
    bid = np.array([0.40, 0.40, 0.90])
    ask = np.array([0.44, 0.44, 0.92])
    total = fees.taker_edge_yes(y, ask, 0.0) + fees.taker_edge_no(y, bid, 0.0)
    np.testing.assert_allclose(total, -(ask - bid))


def test_edge_of_a_fair_price_is_minus_the_fee() -> None:
    price = np.full(100_000, 0.3)
    y = (np.random.default_rng(0).uniform(size=price.size) < 0.3).astype(np.float64)
    edge = fees.taker_edge_yes(y, price, 0.07).mean()
    assert edge == pytest.approx(-0.07 * 0.3 * 0.7, abs=0.005)


def test_prices_outside_the_unit_interval_are_rejected() -> None:
    with pytest.raises(ValueError):
        fees.kalshi_taker_fee(1.2)
    with pytest.raises(ValueError):
        fees.polymarket_taker_fee(-0.1, 1, 0.05)
