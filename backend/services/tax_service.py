"""Federal + state tax estimation. Results are estimates, not tax advice.

BRACKET_YEAR is the tax year the tables below actually encode. It is exported
and returned by the API so the UI can warn when the year being estimated is
not the year the brackets are for, instead of quietly applying the wrong
table behind a line of fine print. Update the tables and this constant
together.
"""
from __future__ import annotations
from decimal import Decimal

BRACKET_YEAR = 2025

# 2025 federal brackets: (rate, bracket_floor)
_BRACKETS = {
    "single": [
        (Decimal("0.10"), Decimal("0")),
        (Decimal("0.12"), Decimal("11925")),
        (Decimal("0.22"), Decimal("48475")),
        (Decimal("0.24"), Decimal("103350")),
        (Decimal("0.32"), Decimal("197300")),
        (Decimal("0.35"), Decimal("250525")),
        (Decimal("0.37"), Decimal("626350")),
    ],
    "married_jointly": [
        (Decimal("0.10"), Decimal("0")),
        (Decimal("0.12"), Decimal("23850")),
        (Decimal("0.22"), Decimal("96950")),
        (Decimal("0.24"), Decimal("206700")),
        (Decimal("0.32"), Decimal("394600")),
        (Decimal("0.35"), Decimal("501050")),
        (Decimal("0.37"), Decimal("751600")),
    ],
    "married_separately": [
        (Decimal("0.10"), Decimal("0")),
        (Decimal("0.12"), Decimal("11925")),
        (Decimal("0.22"), Decimal("48475")),
        (Decimal("0.24"), Decimal("103350")),
        (Decimal("0.32"), Decimal("197300")),
        (Decimal("0.35"), Decimal("250525")),
        (Decimal("0.37"), Decimal("375800")),
    ],
    "head_of_household": [
        (Decimal("0.10"), Decimal("0")),
        (Decimal("0.12"), Decimal("17000")),
        (Decimal("0.22"), Decimal("64850")),
        (Decimal("0.24"), Decimal("103350")),
        (Decimal("0.32"), Decimal("197300")),
        (Decimal("0.35"), Decimal("250500")),
        (Decimal("0.37"), Decimal("626350")),
    ],
}

_STANDARD_DEDUCTION = {
    "single": Decimal("15000"),
    "married_jointly": Decimal("30000"),
    "married_separately": Decimal("15000"),
    "head_of_household": Decimal("22500"),
}

# Approximate effective state income tax rates (for middle-income earner).
# No-tax states use 0.0. Flat-tax states use exact rate.
# Progressive states use simplified effective rate near $75k income.
STATE_RATES: dict[str, float] = {
    "AK": 0.0,  "FL": 0.0,  "NV": 0.0,  "NH": 0.0,  "SD": 0.0,
    "TN": 0.0,  "TX": 0.0,  "WA": 0.0,  "WY": 0.0,
    "AL": 0.050, "AZ": 0.025, "AR": 0.048, "CA": 0.093,
    "CO": 0.044, "CT": 0.060, "DE": 0.066, "GA": 0.054,
    "HI": 0.082, "ID": 0.058, "IL": 0.0495, "IN": 0.0315,
    "IA": 0.060, "KS": 0.057, "KY": 0.045, "LA": 0.042,
    "ME": 0.071, "MD": 0.055, "MA": 0.050, "MI": 0.0425,
    "MN": 0.079, "MS": 0.047, "MO": 0.054, "MT": 0.066,
    "NE": 0.068, "NJ": 0.075, "NM": 0.059, "NY": 0.085,
    "NC": 0.045, "ND": 0.025, "OH": 0.038, "OK": 0.050,
    "OR": 0.099, "PA": 0.0307, "RI": 0.060, "SC": 0.065,
    "UT": 0.0485, "VT": 0.065, "VA": 0.055, "WV": 0.055,
    "WI": 0.065, "DC": 0.085,
}

SS_WAGE_BASE_2025 = Decimal("176100")
SS_RATE = Decimal("0.062")
MEDICARE_RATE = Decimal("0.0145")
ADDITIONAL_MEDICARE_THRESHOLD = {
    "single": Decimal("200000"),
    "married_jointly": Decimal("250000"),
    "married_separately": Decimal("125000"),
    "head_of_household": Decimal("200000"),
}


def _apply_brackets(taxable: Decimal, filing_status: str) -> tuple[Decimal, list[dict]]:
    brackets = _BRACKETS.get(filing_status, _BRACKETS["single"])
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


def estimate_taxes(
    filing_status: str,
    state: str,
    gross_income: Decimal,
    other_income: Decimal,
    deductible_expenses: Decimal,
    federal_withheld: Decimal,
    state_withheld: Decimal,
) -> dict:
    filing_status = filing_status or "single"
    total_income = gross_income + other_income

    std_ded = _STANDARD_DEDUCTION.get(filing_status, Decimal("15000"))
    itemized = deductible_expenses
    deduction = max(std_ded, itemized)
    taxable_income = max(Decimal("0"), total_income - deduction)

    federal_tax, brackets = _apply_brackets(taxable_income, filing_status)

    # State tax (simple flat-rate approximation)
    state_rate = Decimal(str(STATE_RATES.get(state.upper(), 0.05)))
    state_taxable = max(Decimal("0"), total_income - std_ded)
    state_tax = state_taxable * state_rate

    # FICA
    ss_taxable = min(gross_income, SS_WAGE_BASE_2025)
    fica_ss = ss_taxable * SS_RATE
    fica_medicare = gross_income * MEDICARE_RATE
    add_medicare_threshold = ADDITIONAL_MEDICARE_THRESHOLD.get(filing_status, Decimal("200000"))
    if total_income > add_medicare_threshold:
        fica_medicare += (total_income - add_medicare_threshold) * Decimal("0.009")

    total_tax = federal_tax + state_tax + fica_ss + fica_medicare
    effective_rate = total_tax / total_income if total_income > 0 else Decimal("0")

    federal_refund = federal_withheld - federal_tax
    state_refund = state_withheld - state_tax
    total_refund = federal_refund + state_refund

    return {
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
    }
