"""The real-spending rule: one place decides what a transaction is.

Every spending and income total in the app (Spending page charts, Budget
overview, weekly digest, monthly email, Month in Review, Sankey, Left to
Spend, pacer) reads its rows through this module. Before it existed each
caller filtered `amount < 0` itself with its own exclusions, and six
different totals recipes disagreed on the same month.

Verdicts (see docs/architecture.md, "Real-spending rule"):

  - card_payment: a checking debit paying off a card, or the card-side
    payment row. The charges it settles are counted one by one already.
  - transfer: money moved between the user's own accounts (checking
    description heuristic), or any checking or card row filed under a
    savings-type category.
  - income: a checking credit; a debit filed under an income category is
    income with a negative amount (a paycheck reversal reduces income).
  - spend: everything else. Card refunds are negative spend, and so is a
    checking credit whose description matches a spend debit in the same
    window (a same-merchant refund). Refunds may push a category negative;
    totals are never clamped.

Only actual (`is_actual`) checking rows count. Card rows have no planned
state, and a card with no transaction feed simply contributes no rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session, joinedload

from backend import models
from backend.services.card_matching import card_matches_description, looks_like_card_autopay
from backend.services.spending_helpers import is_card_payment, looks_like_internal_transfer

SpendKind = Literal["spend", "income", "transfer", "card_payment"]
Source = Literal["checking", "card"]

_ZERO = Decimal("0")


@dataclass(frozen=True)
class Verdict:
    kind: SpendKind
    amount: Decimal  # positive = spend/income magnitude; refunds are negative spend


@dataclass(frozen=True)
class SpendTotals:
    by_category: dict[int | None, Decimal]  # net of refunds; may be negative
    spend: Decimal
    income: Decimal


@dataclass(frozen=True)
class ClassifiedRow:
    """A fetched row with its verdict. `row` is a Transaction when source is
    "checking" and a CreditCardTransaction when source is "card"."""
    row: models.Transaction | models.CreditCardTransaction
    source: Source
    verdict: Verdict

    @property
    def category_id(self) -> int | None:
        return self.row.category_id


def _category_type(row) -> models.CategoryType | None:
    cat = row.category
    return cat.type if cat is not None else None


def is_checking_card_payment(description: str | None, active_cards: list[models.CreditCard]) -> bool:
    # card_matches_description accepts everything match_payment_card does
    # (last four, unique first word, compacted name) and also an ambiguous
    # first word shared by two cards, which is still a payoff to *some* card.
    # looks_like_card_autopay catches a payoff to a card no longer active.
    desc = description or ""
    if any(card_matches_description(card, desc) for card in active_cards):
        return True
    return looks_like_card_autopay(desc)


def classify_checking(
    txn: models.Transaction,
    active_cards: list[models.CreditCard],
    *,
    refund_descriptions: frozenset[str] = frozenset(),
) -> Verdict:
    """The verdict for one actual checking row.

    `refund_descriptions` holds the descriptions of spend debits in the same
    window; a credit matching one is a refund (negative spend) rather than
    income. spend_totals / classified_rows compute it for you.
    """
    if not txn.is_actual:
        raise ValueError("classify_checking: only actual (is_actual) rows have a verdict")
    amount = txn.amount
    magnitude = abs(amount)
    if is_checking_card_payment(txn.description, active_cards):
        return Verdict("card_payment", magnitude)
    cat_type = _category_type(txn)
    if looks_like_internal_transfer(txn.description) or cat_type == models.CategoryType.savings:
        return Verdict("transfer", magnitude)
    if cat_type == models.CategoryType.income:
        return Verdict("income", amount)
    if amount < 0:
        return Verdict("spend", magnitude)
    if txn.description and txn.description in refund_descriptions:
        return Verdict("spend", -amount)
    return Verdict("income", amount)


def classify_card(txn: models.CreditCardTransaction) -> Verdict:
    """The verdict for one card row: a payment against the card, spend
    (charges positive, refunds negative), or -- for a row filed under a
    savings-type category -- a transfer, the same as on the checking side.
    Card rows are never income and have no description-based transfers."""
    if is_card_payment(txn.merchant):
        return Verdict("card_payment", abs(txn.amount))
    if _category_type(txn) == models.CategoryType.savings:
        return Verdict("transfer", abs(txn.amount))
    return Verdict("spend", txn.amount)


def active_cards(db: Session, user_id: int) -> list[models.CreditCard]:
    return db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()


def classify_checking_rows(
    rows: list[models.Transaction], cards: list[models.CreditCard],
) -> list[ClassifiedRow]:
    """Classify a window of actual checking rows together, so a credit that
    matches a spend debit in the same window nets as a refund."""
    first_pass = [(t, classify_checking(t, cards)) for t in rows]
    refund_descriptions = frozenset(
        t.description for t, v in first_pass
        if v.kind == "spend" and t.amount < 0 and t.description
    )
    out = []
    for t, v in first_pass:
        if v.kind == "income" and t.amount > 0 and t.description in refund_descriptions:
            v = classify_checking(t, cards, refund_descriptions=refund_descriptions)
        out.append(ClassifiedRow(t, "checking", v))
    return out


def classified_rows(
    db: Session,
    user_id: int,
    start: date,
    end: date,
    *,
    account_id: int | None = None,
    card_id: int | None = None,
    include_checking: bool = True,
    include_cards: bool = True,
) -> list[ClassifiedRow]:
    """Every actual checking row and card row in [start, end] with its
    verdict. `account_id` narrows the checking side only and `card_id` the
    card side only, matching the Spending page filters."""
    out: list[ClassifiedRow] = []
    if include_checking:
        q = db.query(models.Transaction).options(joinedload(models.Transaction.category)).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
        )
        if account_id:
            q = q.filter(models.Transaction.account_id == account_id)
        out += classify_checking_rows(q.all(), active_cards(db, user_id))
    if include_cards:
        q = db.query(models.CreditCardTransaction).options(
            joinedload(models.CreditCardTransaction.category),
        ).filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
        )
        if card_id:
            q = q.filter(models.CreditCardTransaction.card_id == card_id)
        out += [ClassifiedRow(t, "card", classify_card(t)) for t in q.all()]
    return out


def totals_of(rows: list[ClassifiedRow]) -> SpendTotals:
    by_category: dict[int | None, Decimal] = {}
    spend = income = _ZERO
    for r in rows:
        if r.verdict.kind == "spend":
            spend += r.verdict.amount
            by_category[r.category_id] = by_category.get(r.category_id, _ZERO) + r.verdict.amount
        elif r.verdict.kind == "income":
            income += r.verdict.amount
    return SpendTotals(by_category=by_category, spend=spend, income=income)


def savings_moved_rows(rows: list[ClassifiedRow]) -> list[ClassifiedRow]:
    """The rows that moved money into a savings-type category: transfer
    verdicts on checking debits and card charges filed under one. A credit
    filed there (money pulled back out) is not counted, as before the rule
    existed."""
    out = []
    for r in rows:
        if r.verdict.kind != "transfer" or r.row.category is None:
            continue
        if r.row.category.type != models.CategoryType.savings:
            continue
        is_outflow = r.row.amount < 0 if r.source == "checking" else r.row.amount > 0
        if is_outflow:
            out.append(r)
    return out


def savings_moved(db: Session, user_id: int, start: date, end: date) -> dict[int, Decimal]:
    """Money moved into each savings-type category in [start, end].

    Not spending -- every spend total excludes it -- but a savings-type
    budget line tracks it as that line's actual ("moved to savings") and
    rolls over against it.
    """
    moved: dict[int, Decimal] = {}
    for r in savings_moved_rows(classified_rows(db, user_id, start, end)):
        moved[r.category_id] = moved.get(r.category_id, _ZERO) + r.verdict.amount
    return moved


def spend_totals(db: Session, user_id: int, start: date, end: date) -> SpendTotals:
    """Real spending (net of refunds) and income in [start, end]."""
    return totals_of(classified_rows(db, user_id, start, end))
