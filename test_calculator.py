import sys
from pathlib import Path

import pytest

# Make `loan_calc` importable when running pytest from the repo root without installing.
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../loan-calc
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loan_calc.calculator import (
    amortisation_schedule,
    emi,
    outstanding_after,
    prepayment_savings,
    remaining_tenure,
    total_interest,
    total_payment,
)


def test_emi_zero_interest():
    # Edge case: 0% interest should degrade to simple division.
    assert emi(120_000, 0.0, 12) == 10_000.00


def test_emi_one_month_tenure():
    # Edge case: 1-month tenure.
    # With annual_rate=12% => monthly=1% (given the module’s rounding to 4 decimals).
    # EMI for n=1 should be P*(1+r).
    assert emi(10_000, 12.0, 1) == pytest.approx(10_100.00, abs=0.01)


def test_emi_very_large_principal_is_finite():
    # Edge case: very large principal should still return a finite positive number.
    e = emi(1_000_000_000, 9.0, 240)
    assert e > 0
    assert e != float("inf")


def test_prepayment_larger_than_balance_closes_loan():
    # Edge case: prepayment larger than outstanding should close the loan immediately
    # and should not produce negative "months_saved".
    res = prepayment_savings(
        principal=100_000,
        annual_rate=12.0,
        tenure_months=12,
        prepay_month=2,
        prepay_amount=1_000_000,
    )
    assert res["new_tenure"] <= 2
    assert res["months_saved"] >= 0


def test_total_payment_interest_consistency():
    p, r, n = 500_000, 10.0, 60
    e = emi(p, r, n)
    assert total_payment(p, r, n) == pytest.approx(e * n, abs=0.01)
    assert total_interest(p, r, n) == pytest.approx(total_payment(p, r, n) - p, abs=0.01)


def test_amortisation_schedule_length_and_final_balance():
    # Schedule should have exactly `tenure_months` rows and end near zero balance.
    rows = amortisation_schedule(100_000, 12.0, 12)
    assert len(rows) == 12
    assert rows[0]["month"] == 1
    assert rows[-1]["month"] == 12
    assert rows[-1]["balance"] == pytest.approx(0.0, abs=0.05)


def test_outstanding_after_all_months_is_zero():
    assert outstanding_after(100_000, 10.0, 12, 12) == 0.0


def test_remaining_tenure_zero_interest():
    # Edge case: 0% interest -> ceil(balance/instalment)
    assert remaining_tenure(100_000, 0.0, 10_000) == 10
