# Architecture / Function Guide (loan-calc)

This document explains what each function in `loan_calc/calculator.py` does, what it returns, and key assumptions/pitfalls that can lead to “wrong numbers” being reported by users.

Source: `loan-calc/loan_calc/calculator.py`


## Overview

The module provides:

- Core loan math:
  - Monthly interest rate conversion
  - EMI (equated monthly instalment)
  - Total payment / total interest
- Amortisation schedule generation and derived helpers
- Prepayment “savings” estimation
- Offer comparison
- Eligible loan amount calculation (reverse EMI)
- Formatting / exporting helpers
- A high-level `summary()` helper suitable for CLI/UI display

All computations are performed in **months** and the interest inputs are assumed to be **annual percentage rates** (APR-ish) unless stated otherwise.


## Functions

### `DEFAULT_CURRENCY = "INR"`
A constant used by `summary()` to report the currency string.


### `_monthly_rate(annual_rate)`
**Purpose:** Convert an annual percentage rate (e.g. `9.5` for 9.5% p.a.) into a monthly decimal rate.

**Implementation:**
- Computes `annual_rate / 1200` (i.e. `/100` to convert percent to decimal, then `/12` for monthly).
- Rounds to **4 decimals**.

**Returns:** `float` monthly rate `r` such that monthly interest is `balance * r`.

**Pitfalls / likely source of wrong numbers:**
- **Rounding to 4 decimals is very aggressive.**  
  Example: 8.65% p.a. → monthly is 0.00720833..., rounded to 0.0072. Over long tenures this can shift totals.
- If you want bank-like results, you typically:
  - do *not* round `r` this early, and/or
  - compute using higher precision and only round displayed currency amounts.

This early rounding affects **EMI**, **schedule**, **total_payment**, **total_interest**, **eligible_amount**, and **prepayment_savings** because they all depend on `_monthly_rate()` either directly or indirectly.


### `emi(principal, annual_rate, tenure_months)`
**Purpose:** Compute the EMI for a fixed-rate loan.

**Inputs:**
- `principal` (P): loan amount, must be > 0
- `annual_rate` (percent p.a.)
- `tenure_months` (N): number of monthly instalments, must be > 0

**Algorithm:**
- Compute monthly rate `r = _monthly_rate(annual_rate)`
- If `r == 0`:
  - EMI = `principal / tenure_months`
- Else:
  - Let `f = (1 + r) ** tenure_months`
  - EMI = `principal * r * f / (f - 1)`
- Rounds the EMI to **2 decimals**.

**Returns:** `float` EMI rounded to 2 decimal places.

**Pitfalls:**
- Because `r` is rounded to 4 decimals, `emi()` can deviate from expected values for certain rates/tenures.
- Rounding EMI to 2 decimals is typical, but if later computations assume an unrounded EMI, totals can drift.


### `total_payment(principal, annual_rate, tenure_months)`
**Purpose:** Compute total paid over full tenure assuming constant EMI.

**Algorithm:**
- `emi(...) * tenure_months`
- Rounded to 2 decimals.

**Returns:** `float`

**Pitfalls:**
- Uses the **rounded EMI** from `emi()`. Multiplying a rounded EMI by many months can differ from schedules where the last EMI is adjusted.
- Does not model real-world rounding adjustments in the final payment.


### `total_interest(principal, annual_rate, tenure_months)`
**Purpose:** Compute total interest over full tenure.

**Algorithm:**
- `total_payment(...) - principal`
- Rounded to 2 decimals.

**Returns:** `float`

**Pitfalls:**
- Inherits rounding drift from both `total_payment()` and `emi()`.


### `amortisation_schedule(principal, annual_rate, tenure_months)`
**Purpose:** Produce month-by-month breakup of EMI into interest and principal, with running balance.

**Algorithm (as coded):**
- `r = _monthly_rate(annual_rate)`
- `instalment = emi(principal, annual_rate, tenure_months)` (already rounded to 2 decimals)
- Initialize `balance = principal`
- For `month in range(1, tenure_months)`:
  - `interest = round(balance * r, 2)`
  - `principal_part = round(instalment - interest, 2)`
  - Attempts to special-case the last month:
    - `if month == tenure_months: ...`
  - Update balance: `balance = round(balance - principal_part, 2)`
  - Append a row dict

**Returns:** `list[dict]` rows with:
- `month`: month number (1-based)
- `emi`: EMI amount for that month
- `interest`: interest component
- `principal`: principal component
- `balance`: remaining balance after payment

**Major pitfalls / very likely cause of “wrong numbers”:**
1. **Off-by-one bug: last month is never included**
   - Loop is `range(1, tenure_months)`, which runs months `1..tenure_months-1`.
   - The `if month == tenure_months:` block is unreachable.
   - Result: schedule length is `tenure_months - 1`, missing the final payment.
2. **End-of-loan adjustment never happens**
   - Many amortisation schedules adjust the last payment to clear the exact remaining balance (due to rounding).
   - The code intends to do that, but due to (1) it never does.

This impacts:
- `outstanding_after()` (uses schedule balance)
- `prepayment_savings()` (uses schedule and interest sums)


### `outstanding_after(principal, annual_rate, tenure_months, months_paid)`
**Purpose:** Return the outstanding principal after `months_paid` instalments have been paid.

**Algorithm:**
- If `months_paid <= 0`, return principal (rounded)
- Build full schedule via `amortisation_schedule()`
- If `months_paid > len(sched)`, return 0.0
- Else return `sched[months_paid - 1]["balance"]`

**Returns:** `float`

**Pitfalls:**
- Because `amortisation_schedule()` currently returns only `tenure_months-1` rows, this function can report:
  - balance becoming 0 earlier than expected, or
  - inconsistencies for `months_paid == tenure_months`
- Also O(N) schedule construction each call (fine for small N, but avoidable).


### `remaining_tenure(balance, annual_rate, instalment)`
**Purpose:** Compute number of months required to repay a given `balance` with a fixed `instalment`.

**Expected math:** Uses the closed-form for amortising loans:
- If monthly rate is `r` (decimal per month), months:
  - `n = -log(1 - balance*r/instalment) / log(1+r)`

**Implementation (as coded):**
- `r = annual_rate / 100`
- Special cases:
  - if `balance <= 0`: return 0
  - if `r == 0`: `ceil(balance / instalment)`
  - if `instalment <= balance * r`: raise
- Else compute `n` with formula above and return `ceil(n)`

**Returns:** `int` months, rounded up.

**Pitfalls / very likely cause of “wrong numbers”:**
- **Rate unit bug:** This function treats `annual_rate/100` as if it were a **monthly** rate.  
  It should likely use `_monthly_rate(annual_rate)` (i.e. `annual_rate/1200`) to be consistent with the rest of the module.
- Because `prepayment_savings()` uses `remaining_tenure()`, prepayment tenure reduction can be dramatically wrong (often too short) for non-zero interest rates.


### `prepayment_savings(principal, annual_rate, tenure_months, prepay_month, prepay_amount)`
**Purpose:** Estimate savings when making a lump-sum prepayment in a given month, while keeping the EMI constant and shortening tenure.

**Docstring:** “Keep the same EMI after a lump-sum prepayment and shorten the tenure.”

**Algorithm (as coded):**
1. Compute `instalment = emi(...)`
2. Build `sched = amortisation_schedule(...)`
3. Take outstanding after `prepay_month` from schedule:
   - `balance = sched[prepay_month - 1]["balance"]`
4. New balance:
   - `new_balance = balance - prepay_amount`
5. Compute months left:
   - if `new_balance <= 0` → `months_left = 0`
   - else `months_left = remaining_tenure(new_balance, annual_rate, instalment)`
6. Compute:
   - `original_left = tenure_months - prepay_month`
   - `interest_paid_so_far = sum(interest for first prepay_month rows)`
   - `original_interest = total_interest(principal, annual_rate, tenure_months)`
7. Approximate a new total paid:
   - `new_total = instalment * prepay_month + prepay_amount + instalment * months_left`
   - `new_interest = new_total - principal`
8. Return a dict including months saved and interest saved.

**Returns:** `dict`:
- `emi`
- `months_saved`
- `new_tenure`
- `interest_saved`
- `interest_paid_before_prepayment`

**Pitfalls:**
- Inherits the amortisation schedule issues:
  - missing last month
  - potentially wrong balances
- Inherits the `remaining_tenure()` rate bug (major).
- `new_total` is a simplification:
  - It assumes all EMIs are exactly equal to `instalment` and ignores last-payment adjustment.
  - It assumes prepayment happens in addition to the EMI at `prepay_month` (may or may not match user expectations).
- No validation that `prepay_month` is within schedule bounds; can throw IndexError for invalid input.


### `compare_offers(principal, offers)`
**Purpose:** Compare multiple loan offers (rate + tenure + optional processing fee) and sort by total cost.

**Inputs:**
- `principal` loan amount
- `offers` list of dicts; each dict expects:
  - `bank`
  - `rate`
  - `tenure`
  - optional `processing_fee_pct`

**Algorithm:**
- For each offer:
  - compute `emi`
  - compute `total_interest`
  - fee = `processing_fee_pct * principal / 100`
  - total_cost = `total_interest + fee`
- Sort ascending by `total_cost`

**Returns:** `list[dict]` sorted offers.

**Pitfalls:**
- Uses `total_interest()` which is based on rounded EMI; can differ slightly from more exact schedule totals.
- Fee is added to interest only; it excludes principal by design (it’s comparing “cost over principal”).


### `eligible_amount(monthly_income, existing_emis, annual_rate, tenure_months, foir=0.5)`
**Purpose:** Compute maximum eligible principal given an affordable EMI, essentially the inverse of `emi()`.

**Inputs:**
- `monthly_income`
- `existing_emis` (monthly obligations)
- `foir` (fixed obligation to income ratio, default 0.5)

**Algorithm:**
- `available = monthly_income * foir - existing_emis`
- If `available <= 0`, return 0
- Let `r = _monthly_rate(annual_rate)`
- If `r == 0`: eligible = `available * tenure_months`
- Else:
  - `f = (1 + r) ** tenure_months`
  - eligible = `available * (f - 1) / (r * f)`
- Round to 2 decimals.

**Returns:** `float`

**Pitfalls:**
- Same early rounding of monthly rate to 4 decimals affects results.


### `format_inr(amount)`
**Purpose:** Format a numeric amount in Indian numbering format with a rupee symbol.

**Behavior:**
- Preserves sign
- Rounds to 2 decimals
- Applies lakh/crore comma grouping (e.g. `12,34,567.89`)
- Prefixes with `₹`

**Returns:** `str`

**Pitfalls:**
- Purely presentational; no effect on core math.


### `schedule_to_csv(rows, path)`
**Purpose:** Save a schedule (list of row dicts) to a CSV file.

**Behavior:**
- Writes header line and one line per row.

**Returns:** `None`

**Pitfalls:**
- Opens file with default encoding and newline handling; on Windows you may prefer `newline=""` to avoid blank lines in some CSV readers.


### `summary(principal, annual_rate, tenure_months, start=None)`
**Purpose:** Produce a UI/CLI friendly summary of a loan.

**Inputs:**
- `start`: a `datetime.date`; defaults to `date.today()`

**Algorithm:**
- `e = emi(...)`
- Compute end year/month after `tenure_months`
- Return dict with formatted values:
  - principal, rate, tenure, emi
  - total_interest, total_payment
  - last_emi as `YYYY-MM`
  - currency from `DEFAULT_CURRENCY`

**Returns:** `dict[str, str]`

**Pitfalls:**
- Totals inherit rounding assumptions described earlier.
- The computed `last_emi` is a month bucket (no day); good enough for display, but not a precise due date.


## Known issues causing incorrect results (summary)

1. **Amortisation schedule off-by-one**
   - Missing the last month entirely (`range(1, tenure_months)` should likely include `tenure_months`).
2. **`remaining_tenure()` uses wrong interest rate unit**
   - Treats `annual_rate/100` as a monthly rate.
   - Should likely use `_monthly_rate(annual_rate)`.
3. **Early rounding of monthly rate**
   - `_monthly_rate()` rounds to 4 decimals; can noticeably impact long tenure loans.
4. **Total/interest computations depend on rounded EMI**
   - `total_payment()` / `total_interest()` multiply the rounded EMI rather than summing an adjusted schedule.

These issues are consistent with user reports of “wrong numbers for some loans”, especially around:
- long tenures (20–30 years),
- interest rates with 3+ decimals,
- prepayment scenarios.


## Data flow / dependencies

- `_monthly_rate()` is a shared primitive used by: `emi()`, `amortisation_schedule()`, `eligible_amount()`.
- `emi()` is used by: `total_payment()`, `amortisation_schedule()`, `prepayment_savings()`, `compare_offers()`, `summary()`.
- `amortisation_schedule()` is used by: `outstanding_after()`, `prepayment_savings()`.
- `total_payment()` is used by: `total_interest()`, `summary()`.
- `total_interest()` is used by: `prepayment_savings()`, `compare_offers()`, `summary()`.


## Notes on “bank matching” behavior

If the goal is to match bank statements closely, typical changes include:
- Use higher precision for `r` and intermediate computations.
- Round interest/principal per period to currency precision, but ensure the **final period** clears the remaining principal exactly by adjusting the last principal/EMI.
- For prepayments, model the exact moment of prepayment (before or after EMI) and recompute schedules accordingly.
