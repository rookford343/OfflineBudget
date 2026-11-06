"""Federal + state tax estimation. Results are estimates, not tax advice.

Federal tables are keyed by tax year in _TABLES. estimate_taxes(year=...)
uses that year's table, or the nearest bundled one when the year isn't
bundled (the latest for future years, the earliest for older ones), and
returns the table year it actually used as bracket_year so the UI can warn
on a mismatch instead of quietly applying the wrong table.

Adding a year: copy the latest _TABLES entry under the new year and fill in
the bracket floors and standard deduction from that year's IRS Rev. Proc.,
and the Social Security wage base from the SSA's announcement. If Indiana's
flat rate changes, add the year to _STATE_RATE_OVERRIDES too.
"""
from __future__ import annotations
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

# IRS flat rate for withholding on supplemental wages (bonuses) up to $1M.
SUPPLEMENTAL_FEDERAL_RATE = Decimal("0.22")

# Paychecks per year assumed when no paycheck item can be identified.
ASSUMED_PAYCHECKS_PER_YEAR = 26


def _ladder(*floors: str) -> list[tuple[Decimal, Decimal]]:
    """(rate, bracket_floor) pairs for the 10/12/22/24/32/35/37% brackets,
    given the six floors above the 10% bracket."""
    rates = ("0.10", "0.12", "0.22", "0.24", "0.32", "0.35", "0.37")
    return [(Decimal(r), Decimal(f)) for r, f in zip(rates, ("0",) + floors)]


# Per-year federal tables. Brackets: (rate, bracket_floor).
_TABLES: dict[int, dict] = {
    # Rev. Proc. 2024-40 brackets; standard deduction as raised by the OBBBA.
    2025: {
        "brackets": {
            "single": _ladder("11925", "48475", "103350", "197300", "250525", "626350"),
            "married_jointly": _ladder("23850", "96950", "206700", "394600", "501050", "751600"),
            "married_separately": _ladder("11925", "48475", "103350", "197300", "250525", "375800"),
            "head_of_household": _ladder("17000", "64850", "103350", "197300", "250500", "626350"),
        },
        "standard_deduction": {
            "single": Decimal("15750"),
            "married_jointly": Decimal("31500"),
            "married_separately": Decimal("15750"),
            "head_of_household": Decimal("23625"),
        },
        "ss_wage_base": Decimal("176100"),
    },
    # Rev. Proc. 2025-32.
    2026: {
        "brackets": {
            "single": _ladder("12400", "50400", "105700", "201775", "256225", "640600"),
            "married_jointly": _ladder("24800", "100800", "211400", "403550", "512450", "768700"),
            "married_separately": _ladder("12400", "50400", "105700", "201775", "256225", "384350"),
            "head_of_household": _ladder("17700", "67450", "105700", "201750", "256200", "640600"),
        },
        "standard_deduction": {
            "single": Decimal("16100"),
            "married_jointly": Decimal("32200"),
            "married_separately": Decimal("16100"),
            "head_of_household": Decimal("24150"),
        },
        "ss_wage_base": Decimal("184500"),
    },
    # Rev. Proc. 2026-35.
    2027: {
        "brackets": {
            "single": _ladder("12800", "52025", "109125", "208325", "264550", "661375"),
            "married_jointly": _ladder("25600", "104050", "218250", "416650", "529100", "793650"),
            "married_separately": _ladder("12800", "52025", "109125", "208325", "264550", "396825"),
            "head_of_household": _ladder("18250", "69650", "109100", "208300", "264550", "661350"),
        },
        "standard_deduction": {
            "single": Decimal("16600"),
            "married_jointly": Decimal("33200"),
            "married_separately": Decimal("16600"),
            "head_of_household": Decimal("24925"),
        },
        "ss_wage_base": Decimal("192300"),
    },
}

# The latest bundled table year (the default when no year is given).
BRACKET_YEAR = max(_TABLES)


def _table_year(year: int | None) -> int:
    """The bundled table year to use for `year`: itself if bundled, else the
    nearest bundled year (latest for future years, earliest for older)."""
    if year is None:
        return BRACKET_YEAR
    if year in _TABLES:
        return year
    return BRACKET_YEAR if year > BRACKET_YEAR else min(_TABLES)


def ss_wage_base_for(year: int) -> Decimal | None:
    """The published Social Security wage base for `year`, or None when that
    year isn't bundled (callers fall back to the user's own setting)."""
    table = _TABLES.get(year)
    return table["ss_wage_base"] if table else None


# Approximate effective state income tax rates (for middle-income earner).
# No-tax states use 0.0. Flat-tax states use exact rate.
# Progressive states use simplified effective rate near $75k income.
STATE_RATES: dict[str, float] = {
    "AK": 0.0,  "FL": 0.0,  "NV": 0.0,  "NH": 0.0,  "SD": 0.0,
    "TN": 0.0,  "TX": 0.0,  "WA": 0.0,  "WY": 0.0,
    "AL": 0.050, "AZ": 0.025, "AR": 0.048, "CA": 0.093,
    "CO": 0.044, "CT": 0.060, "DE": 0.066, "GA": 0.054,
    "HI": 0.082, "ID": 0.058, "IL": 0.0495, "IN": 0.029,
    "IA": 0.060, "KS": 0.057, "KY": 0.045, "LA": 0.042,
    "ME": 0.071, "MD": 0.055, "MA": 0.050, "MI": 0.0425,
    "MN": 0.079, "MS": 0.047, "MO": 0.054, "MT": 0.066,
    "NE": 0.068, "NJ": 0.075, "NM": 0.059, "NY": 0.085,
    "NC": 0.045, "ND": 0.025, "OH": 0.038, "OK": 0.050,
    "OR": 0.099, "PA": 0.0307, "RI": 0.060, "SC": 0.065,
    "UT": 0.0485, "VT": 0.065, "VA": 0.055, "WV": 0.055,
    "WI": 0.065, "DC": 0.085,
}

# Per-year exact rates where a flat-tax state's rate is scheduled to change.
# STATE_RATES above stays the fallback for every other state and year.
_STATE_RATE_OVERRIDES: dict[int, dict[str, float]] = {
    2025: {"IN": 0.030},
    2026: {"IN": 0.0295},
    2027: {"IN": 0.029},
}


def _state_rate(state: str, year: int | None) -> float:
    override = _STATE_RATE_OVERRIDES.get(year, {}) if year is not None else {}
    return override.get(state, STATE_RATES.get(state, 0.05))

SS_RATE = Decimal("0.062")
MEDICARE_RATE = Decimal("0.0145")
ADDITIONAL_MEDICARE_THRESHOLD = {
    "single": Decimal("200000"),
    "married_jointly": Decimal("250000"),
    "married_separately": Decimal("125000"),
    "head_of_household": Decimal("200000"),
}


def _apply_brackets(
    taxable: Decimal, filing_status: str, table_year: int = BRACKET_YEAR,
) -> tuple[Decimal, list[dict]]:
    table = _TABLES[table_year]["brackets"]
    brackets = table.get(filing_status, table["single"])
    tax = Decimal("0")
    breakdown = []
    for i, (rate, floor) in enumerate(brackets):
        next_floor = brackets[i + 1][1] if i + 1 < len(brackets) else None
        if taxable <= floor:
            break
        top = min(taxable, next_floor) if next_floor else taxable
        income_in_bracket = top - floor
        tax_in_bracket = income_in_bracket * rate
        tax += tax_in_bracket
        breakdown.append({
            "rate": float(rate),
            "floor": float(floor),
            "ceiling": float(next_floor) if next_floor else None,
            "income": float(income_in_bracket),
            "tax": float(tax_in_bracket),
        })
    return tax, breakdown


def assumed_biweekly_counts(year: int, as_of: date | None) -> tuple[int, int]:
    """(paychecks in `year`, paychecks left after `as_of`) assuming 26 a year
    when no paycheck schedule is known: prorated by days left in the year
    when `as_of` falls in it, all of them when it's earlier or unset, none
    when it's later."""
    n = ASSUMED_PAYCHECKS_PER_YEAR
    if as_of is None or as_of.year < year:
        return n, n
    if as_of.year > year:
        return n, 0
    year_days = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    left = (date(year, 12, 31) - as_of).days
    return n, int((Decimal(n * left) / year_days).quantize(Decimal(1), ROUND_HALF_UP))


def _withholding(
    *, year: int | None, as_of: date | None, ytd: Decimal, per_paycheck: Decimal | None,
    projecting: bool, past_year: bool, paychecks_remaining: int,
    bonuses: Sequence[tuple[date, Decimal]], bonus_rate: Decimal,
) -> dict:
    """One tax's (federal or state) projected withholding breakdown, with the
    basis (see estimate_taxes) it was found on."""
    zero = Decimal("0")
    if past_year:
        return {"basis": "past_year", "ytd": zero, "per_paycheck": per_paycheck or zero,
                "remaining_paychecks": zero, "bonus": zero, "total": zero}
    if not projecting:
        return {"basis": "ytd_only", "ytd": ytd, "per_paycheck": zero,
                "remaining_paychecks": zero, "bonus": zero, "total": ytd}
    in_year = as_of is not None and as_of.year == year
    base = ytd if in_year else zero
    pp = per_paycheck or zero
    remaining = (pp * paychecks_remaining).quantize(CENT)
    # A bonus paid on or before the stub date is already inside its YTD.
    bonus = sum(
        ((gross * bonus_rate).quantize(CENT) for d, gross in bonuses
         if not in_year or d > as_of),
        zero,
    )
    return {"basis": "projected" if in_year else "projected_full_year",
            "ytd": base, "per_paycheck": pp, "remaining_paychecks": remaining,
            "bonus": bonus, "total": base + remaining + bonus}


def estimate_taxes(
    filing_status: str,
    state: str,
    gross_income: Decimal,
    other_income: Decimal,
    deductible_expenses: Decimal,
    federal_withheld: Decimal,
    state_withheld: Decimal,
    year: int | None = None,
    *,
    bonuses: Sequence[tuple[date, Decimal]] = (),
    pretax_per_paycheck: Decimal | None = None,
    federal_per_paycheck: Decimal | None = None,
    state_per_paycheck: Decimal | None = None,
    withholding_as_of: date | None = None,
    paychecks_in_year: int | None = None,
    paychecks_remaining: int | None = None,
    paycheck_basis: str = "schedule",
) -> dict:
    """Full-year tax estimate. Pure: the caller gathers every input.

    gross_income is the year's salary; `bonuses` are (pay date, gross) for
    the year's bonuses, which count as wages for every tax. federal_withheld
    / state_withheld are the pay stub's YTD figures as of withholding_as_of.
    pretax_per_paycheck x paychecks_in_year comes off federal and state
    taxable wages, not Social Security/Medicare wages (conservative: a 401k
    deferral is still FICA wages; only some premiums/HSA aren't).

    withholding.federal.basis / withholding.state.basis say how each tax's
    withholding compared against the tax was found:
      projected           -- stub in `year`: YTD + per-paycheck x paychecks
                             left after it + bonus withholding after it
      projected_full_year -- stub earlier or unset: per-paycheck x all of
                             the year's paychecks + all bonus withholding
      past_year           -- stub from a later year: no withholding known
                             for `year`; refund/owed are None (see the W-2)
      ytd_only            -- that tax's per-paycheck amount is blank: its
                             YTD compared as-is (a blank is never $0)
    Each tax projects only from its own per-paycheck amount. A no-income-tax
    state follows the federal basis (its blank isn't worth a warning).
    Top-level withholding_basis is the shared basis when both agree, else
    "mixed" (one tax projected, the other still YTD-only).
    """
    filing_status = filing_status or "single"
    zero = Decimal("0")
    bonus_gross = sum((g for _, g in bonuses), zero)
    wages = gross_income + bonus_gross
    total_income = wages + other_income
    table_year = _table_year(year)
    table = _TABLES[table_year]

    if paychecks_in_year is None or paychecks_remaining is None:
        est_year = year if year is not None else (withholding_as_of or date(table_year, 1, 1)).year
        paychecks_in_year, paychecks_remaining = assumed_biweekly_counts(est_year, withholding_as_of)
        paycheck_basis = "assumed_biweekly"
    pretax = ((pretax_per_paycheck or zero) * paychecks_in_year).quantize(CENT)
    income_tax_income = max(zero, total_income - pretax)

    std_ded = table["standard_deduction"].get(filing_status, table["standard_deduction"]["single"])
    itemized = deductible_expenses
    deduction = max(std_ded, itemized)
    taxable_income = max(zero, income_tax_income - deduction)

    federal_tax, brackets = _apply_brackets(taxable_income, filing_status, table_year)

    # State tax (simple flat-rate approximation)
    state_rate = Decimal(str(_state_rate(state.upper(), year)))
    state_taxable = max(zero, income_tax_income - std_ded)
    state_tax = state_taxable * state_rate

    # FICA (bonus included; pre-tax deductions deliberately not subtracted)
    ss_taxable = min(wages, table["ss_wage_base"])
    fica_ss = ss_taxable * SS_RATE
    fica_medicare = wages * MEDICARE_RATE
    add_medicare_threshold = ADDITIONAL_MEDICARE_THRESHOLD.get(filing_status, Decimal("200000"))
    if total_income > add_medicare_threshold:
        fica_medicare += (total_income - add_medicare_threshold) * Decimal("0.009")

    total_tax = federal_tax + state_tax + fica_ss + fica_medicare
    effective_rate = total_tax / total_income if total_income > 0 else zero

    # Withholding
    fed_projecting = federal_per_paycheck is not None
    state_projecting = (
        fed_projecting if state_rate == 0 and state_per_paycheck is None
        else state_per_paycheck is not None
    )
    basis_year = year if year is not None else (withholding_as_of.year if withholding_as_of else None)
    past_year = (
        withholding_as_of is not None and basis_year is not None
        and withholding_as_of.year > basis_year
    )
    common = dict(year=basis_year, as_of=withholding_as_of, past_year=past_year,
                  paychecks_remaining=paychecks_remaining, bonuses=bonuses)
    fed_w = _withholding(ytd=federal_withheld, per_paycheck=federal_per_paycheck,
                         projecting=fed_projecting, bonus_rate=SUPPLEMENTAL_FEDERAL_RATE, **common)
    state_w = _withholding(ytd=state_withheld, per_paycheck=state_per_paycheck,
                           projecting=state_projecting, bonus_rate=state_rate, **common)
    withholding_basis = fed_w["basis"] if fed_w["basis"] == state_w["basis"] else "mixed"
    federal_withheld = fed_w["total"]
    state_withheld = state_w["total"]

    if past_year:
        federal_refund = state_refund = total_refund = None
    else:
        federal_refund = federal_withheld - federal_tax
        state_refund = state_withheld - state_tax
        total_refund = federal_refund + state_refund

    return {
        "salary": gross_income,
        "bonus_gross": bonus_gross,
        "other_income": other_income,
        "pretax_deductions": pretax,
        "paychecks_in_year": paychecks_in_year,
        "paychecks_remaining": paychecks_remaining,
        "paycheck_basis": paycheck_basis,
        "withholding_basis": withholding_basis,
        "withholding_as_of": withholding_as_of,
        "withholding": {"federal": fed_w, "state": state_w},
        "federal_tax": federal_tax,
        "state_tax": state_tax,
        "fica_ss": fica_ss,
        "fica_medicare": fica_medicare,
        "total_tax": total_tax,
        "effective_rate": effective_rate,
        "federal_withheld": federal_withheld,
        "state_withheld": state_withheld,
        "federal_refund_or_owed": federal_refund,
        "state_refund_or_owed": state_refund,
        "total_refund_or_owed": total_refund,
        "taxable_income": taxable_income,
        "deduction_used": deduction,
        "deductible_expenses": deductible_expenses,
        "used_itemized": itemized > std_ded,
        "standard_deduction": std_ded,
        "state_rate": float(state_rate),
        "state_no_income_tax": state_rate == 0,
        "filing_status": filing_status,
        "state": state.upper(),
        "brackets": brackets,
        "bracket_year": table_year,
    }
