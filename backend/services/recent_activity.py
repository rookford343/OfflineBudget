"""Dashboard 'Recent transactions' card: the newest checking + card rows
merged into one feed.

Reuses the same exclusion predicates the Spending page is built on
(filter_real_spend, is_card_payment) so this list can't disagree with that
page about what counts as a transfer, a card payoff, or real spend -- same
class of drift spending_helpers' own docstrings warn about (see
filter_real_spend / is_real_checking_spend).
"""
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload, contains_eager
from backend import models
from backend import schemas
from backend.services.spending_helpers import filter_real_spend, is_card_payment
from backend.services.merchant_normalizer import build_alias_map, display_name


def get_recent_activity(db: Session, user_id: int, limit: int = 10) -> list[schemas.RecentActivityItem]:
    """Newest-`limit` rows across checking + card activity, newest first,
    tie-broken by id descending.

    Fetches `limit * 3` candidates per source before merging so that
    dropping transfers/payoffs/card-payments doesn't starve the final list
    below `limit` when enough real rows exist further back.
    """
    candidate_n = limit * 3
    alias_map = build_alias_map(db, user_id)

    checking_rows = (
        db.query(models.Transaction)
        .join(models.Account, models.Transaction.account_id == models.Account.id)
        .options(contains_eager(models.Transaction.account), joinedload(models.Transaction.category))
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            # Bank sync writes rows for every linked account, not just
            # checking -- a savings/money-market row (e.g. "Interest paid")
            # is real activity on that account but not what this card means
            # by "recent transactions", which is scoped to checking + card.
            models.Account.type == models.AccountType.checking,
        )
        .order_by(models.Transaction.date.desc(), models.Transaction.id.desc())
        .limit(candidate_n)
        .all()
    )
    # Description-based, sign-agnostic: catches a transfer/payoff whether the
    # row is a debit or a credit (e.g. an incoming "Transfer from savings").
    checking_rows = filter_real_spend(db, user_id, checking_rows)

    card_rows = (
        db.query(models.CreditCardTransaction)
        .options(joinedload(models.CreditCardTransaction.card), joinedload(models.CreditCardTransaction.category))
        .filter(models.CreditCardTransaction.user_id == user_id)
        .order_by(models.CreditCardTransaction.date.desc(), models.CreditCardTransaction.id.desc())
        .limit(candidate_n)
        .all()
    )
    card_rows = [t for t in card_rows if not is_card_payment(t.merchant)]

    items: list[schemas.RecentActivityItem] = []
    for t in checking_rows:
        items.append(schemas.RecentActivityItem(
            id=t.id,
            uid=f"checking-{t.id}",
            date=t.date,
            description=display_name(t.description, alias_map),
            amount=t.amount,  # already signed: spending negative, income positive
            category_name=t.category.name if t.category else None,
            source="checking",
            source_name=t.account.name if t.account else "",
        ))
    for t in card_rows:
        items.append(schemas.RecentActivityItem(
            id=t.id,
            uid=f"card-{t.id}",
            date=t.date,
            description=display_name(t.merchant, alias_map),
            # card stores charges positive; flip to match checking's
            # convention. `or Decimal("0")` normalizes the -0.00 a zero-amount
            # row would otherwise negate to -- Decimal treats any zero as
            # falsy regardless of sign, so this swaps it for a clean 0.
            amount=-t.amount or Decimal("0"),
            category_name=t.category.name if t.category else None,
            source="card",
            source_name=t.card.name if t.card else "",
        ))

    items.sort(key=lambda i: (i.date, i.id), reverse=True)
    return items[:limit]
