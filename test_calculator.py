import pytest
from decimal import Decimal

from loan_calc.calculator import (
    amortisation_schedule,
    eligible_amount,
    emi,
    format_inr,
    outstanding_after,
    prepayment_savings,
    remaining_tenure,
    total_interest,
    total_payment,
)


def test_emi_known_value_long_tenure():
    # Acceptance criteria: ₹10,00,000 @ 9% p.a. for 240 months => ~ ₹8,997
    assert emi(1_000_000, 9.0, 240) == pytest.approx(8997, abs=1)


def test_emi_zero_interest_is_simple_division():
    assert emi(120_000, 0.0, 12) == 10_000.00


def test_emi_one_month_tenure():
    # 12% p.a => 1% per month (subject to rounding rules in _monthly_rate)
    # EMI = P * (1 + r) for n=1
    assert emi(10_000, 12.0, 1) == pytest.approx(10_100.00, abs=0.01)


def test_emi_very_large_principal_is_finite():
    # Should not overflow or become inf/NaN; just sanity check.
    e = emi(1_000_000_000, 9.0, 240)
    assert e > 0
    assert e != float("inf")


def test_total_payment_and_total_interest_consistent_with_emi():
    p, r, n = 500_000, 10.0, 60
    e = emi(p, r, n)
    assert total_payment(p, r, n) == pytest.approx(e * n, abs=0.01)
    assert total_interest(p, r, n) == pytest.approx(total_payment(p, r, n) - p, abs=0.01)


def test_amortisation_schedule_length_and_final_balance():
    # One row per month; last balance should be ~0.
    rows = amortisation_schedule(100_000, 12.0, 12)
    assert len(rows) == 12
    assert rows[0]["month"] == 1
    assert rows[-1]["month"] == 12
    assert rows[-1]["balance"] == pytest.approx(0.0, abs=0.05)


def test_outstanding_after_zero_months_is_principal():
    assert outstanding_after(100_000, 10.0, 12, 0) == 100_000.00


def test_outstanding_after_all_months_is_zero():
    assert outstanding_after(100_000, 10.0, 12, 12) == 0.0


def test_remaining_tenure_zero_interest():
    assert remaining_tenure(100_000, 0.0, 10_000) == 10


def test_remaining_tenure_positive_interest_sanity():
    # With positive interest, should take longer than the zero-interest case for same payment.
    assert remaining_tenure(100_000, 12.0, 10_000) > 10


def test_prepayment_larger_than_balance_closes_loan_and_never_negative_months_saved():
    res = prepayment_savings(
        principal=100_000,
        annual_rate=12.0,
        tenure_months=12,
        prepay_month=2,
        prepay_amount=1_000_000,  # intentionally larger than outstanding
    )
    assert res["new_tenure"] <= 2
    assert res["months_saved"] >= 0


def test_eligible_amount_zero_interest():
    # FOIR 50%: 100k income => 50k allowed; existing 10k => 40k available EMI
    assert eligible_amount(100_000, 10_000, 0.0, 12) == 480_000.00


def test_format_inr_grouping_and_sign():
    assert format_inr(0) == "₹0.00"
    assert format_inr(1000) == "₹1,000.00"
    assert format_inr(100000) == "₹1,00,000.00"
    assert format_inr(-1234.5) == "-₹1,234.50"
