import math
from datetime import date


DEFAULT_CURRENCY = "INR"


def _monthly_rate(annual_rate: float) -> float:
    """Convert an annual interest rate (percentage) into a monthly decimal rate.

    The input is expected as an annual percentage rate (APR), e.g. 9.0 for 9% p.a.
    The returned value is the monthly decimal rate, e.g. 0.0075 for 9% p.a.

    Note:
        This legacy module rounds the monthly rate to 4 decimals, which affects
        downstream computations. Tests should lock down this behaviour.
    """
    r = round(annual_rate / 1200, 4)
    return r


def emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Calculate the Equated Monthly Instalment (EMI).

    Args:
        principal: Loan amount.
        annual_rate: Annual interest rate (percentage), e.g. 9.0 for 9% p.a.
        tenure_months: Tenure in months.

    Returns:
        Monthly EMI amount rounded to 2 decimals.

    Raises:
        ValueError: If principal <= 0 or tenure_months <= 0.
    """
    if tenure_months <= 0:
        raise ValueError("tenure must be positive")
    if principal <= 0:
        raise ValueError("principal must be positive")
    r = _monthly_rate(annual_rate)
    if r == 0:
        return round(principal / tenure_months, 2)
    f = (1 + r) ** tenure_months
    return round(principal * r * f / (f - 1), 2)


def total_payment(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Total amount paid over the full tenure (principal + interest)."""
    return round(emi(principal, annual_rate, tenure_months) * tenure_months, 2)


def total_interest(principal: float, annual_rate: float, tenure_months: int) -> float:
    """Total interest paid over the full tenure."""
    return round(total_payment(principal, annual_rate, tenure_months) - principal, 2)


def amortisation_schedule(
    principal: float, annual_rate: float, tenure_months: int
) -> list[dict[str, float]]:
    """Generate a month-by-month amortisation schedule.

    Each row contains:
      - month: Month number starting at 1
      - emi: EMI paid that month
      - interest: Interest component
      - principal: Principal component
      - balance: Outstanding balance after payment
    """
    r = _monthly_rate(annual_rate)
    instalment = emi(principal, annual_rate, tenure_months)
    balance = principal
    rows: list[dict[str, float]] = []
    for month in range(1, tenure_months + 1):
        interest = round(balance * r, 2)
        principal_part = round(instalment - interest, 2)
        if month == tenure_months:
            principal_part = round(balance, 2)
            instalment_amt = round(principal_part + interest, 2)
        else:
            instalment_amt = instalment
        balance = round(balance - principal_part, 2)
        rows.append(
            {
                "month": month,
                "emi": instalment_amt,
                "interest": interest,
                "principal": principal_part,
                "balance": max(balance, 0.0),
            }
        )
    return rows


def outstanding_after(
    principal: float,
    annual_rate: float,
    tenure_months: int,
    months_paid: int,
) -> float:
    """Outstanding balance after `months_paid` instalments have been paid."""
    if months_paid <= 0:
        return round(principal, 2)
    sched = amortisation_schedule(principal, annual_rate, tenure_months)
    if months_paid > len(sched):
        return 0.0
    return float(sched[months_paid - 1]["balance"])


def remaining_tenure(balance: float, annual_rate: float, instalment: float) -> int:
    """Compute remaining months needed to repay `balance` at given rate and EMI.

    This is the inverse of the EMI formula (solves for n).
    """
    if instalment <= 0:
        raise ValueError("instalment must be positive")
    r = _monthly_rate(annual_rate)
    if balance <= 0:
        return 0
    if r == 0:
        return math.ceil(balance / instalment)
    if instalment <= balance * r:
        raise ValueError("instalment too small to repay the loan")
    n = -math.log(1 - balance * r / instalment) / math.log(1 + r)
    return math.ceil(n)


def prepayment_savings(
    principal: float,
    annual_rate: float,
    tenure_months: int,
    prepay_month: int,
    prepay_amount: float,
) -> dict[str, float]:
    """Estimate savings from a lump-sum prepayment while keeping EMI unchanged.

    The model assumes:
      1) You pay EMIs normally until `prepay_month`.
      2) You make a lump-sum prepayment.
      3) You keep the original EMI and shorten the remaining tenure.

    Returns a dictionary including interest saved and the revised tenure.
    """
    instalment = emi(principal, annual_rate, tenure_months)
    sched = amortisation_schedule(principal, annual_rate, tenure_months)
    if prepay_month < 1 or prepay_month > tenure_months:
        raise ValueError("prepay_month must be between 1 and tenure_months")
    balance = sched[prepay_month - 1]["balance"]
    new_balance = balance - prepay_amount
    if new_balance <= 0:
        months_left = 0
    else:
        months_left = remaining_tenure(new_balance, annual_rate, instalment)
    original_left = tenure_months - prepay_month
    interest_paid_so_far = sum(row["interest"] for row in sched[:prepay_month])
    original_interest = total_interest(principal, annual_rate, tenure_months)
    new_total = instalment * prepay_month + prepay_amount + instalment * months_left
    new_interest = new_total - principal
    return {
        "emi": instalment,
        "months_saved": float(original_left - months_left),
        "new_tenure": float(prepay_month + months_left),
        "interest_saved": round(original_interest - new_interest, 2),
        "interest_paid_before_prepayment": round(interest_paid_so_far, 2),
    }


def compare_offers(principal: float, offers: list[dict]) -> list[dict[str, float]]:
    """Compare multiple loan offers (rate/tenure/fee) and sort by total cost."""
    out: list[dict[str, float]] = []
    for o in offers:
        e = emi(principal, o["rate"], o["tenure"])
        ti = total_interest(principal, o["rate"], o["tenure"])
        fee = o.get("processing_fee_pct", 0) * principal / 100
        out.append(
            {
                "bank": o["bank"],
                "emi": e,
                "total_interest": ti,
                "processing_fee": round(fee, 2),
                "total_cost": round(ti + fee, 2),
            }
        )
    out.sort(key=lambda x: x["total_cost"])
    return out


def eligible_amount(
    monthly_income: float,
    existing_emis: float,
    annual_rate: float,
    tenure_months: int,
    foir: float = 0.5,
) -> float:
    """Estimate maximum eligible principal based on income/FOIR and EMI capacity."""
    available = monthly_income * foir - existing_emis
    if available <= 0:
        return 0.0
    r = _monthly_rate(annual_rate)
    if r == 0:
        return round(available * tenure_months, 2)
    f = (1 + r) ** tenure_months
    return round(available * (f - 1) / (r * f), 2)


def format_inr(amount: float) -> str:
    """Format a number in Indian currency style with ₹ and lakh/crore grouping."""
    neg = amount < 0
    amount = abs(round(amount, 2))
    whole, frac = f"{amount:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + whole + "." + frac


def schedule_to_csv(rows: list[dict[str, float]], path: str) -> None:
    """Write an amortisation schedule to a CSV file.

    Args:
        rows: Rows as returned by :func:`amortisation_schedule`.
        path: Destination file path.

    Returns:
        None
    """
    with open(path, "w") as fh:
        fh.write("month,emi,interest,principal,balance\n")
        for r in rows:
            fh.write(
                f'{r["month"]},{r["emi"]},{r["interest"]},{r["principal"]},{r["balance"]}\n'
            )


def summary(
    principal: float, annual_rate: float, tenure_months: int, start: date | None = None
) -> dict[str, str]:
    """Human-readable summary including EMI, total interest/payment, and last EMI month."""
    start = start or date.today()
    e = emi(principal, annual_rate, tenure_months)
    end_year = start.year + (start.month - 1 + tenure_months) // 12
    end_month = (start.month - 1 + tenure_months) % 12 + 1
    return {
        "principal": format_inr(principal),
        "rate": f"{annual_rate}% p.a.",
        "tenure": f"{tenure_months} months",
        "emi": format_inr(e),
        "total_interest": format_inr(total_interest(principal, annual_rate, tenure_months)),
        "total_payment": format_inr(total_payment(principal, annual_rate, tenure_months)),
        "last_emi": f"{end_year}-{end_month:02d}",
        "currency": DEFAULT_CURRENCY,
    }
