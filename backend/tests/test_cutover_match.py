from datetime import date
from decimal import Decimal

from backend import models, schemas
from backend.services.cutover_match import find_match, cutover_zone
from backend.services.import_service import _find_duplicate_transaction
from backend.services.plaid_client import PlaidTransaction


def _make_user_and_account(db, username="plaiduser"):
    user = models.User(username=username, hashed_password="x", display_name="U")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("0.00"),
    )
    db.add(account)
    db.commit()
    return user, account


def _make_user_and_card(db, username="plaidcard"):
    user = models.User(username=username, hashed_password="x", display_name="U")
    db.add(user)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("0.00"),
    )
    db.add(card)
    db.commit()
    return user, card


def _plaid_txn(**overrides):
    defaults = dict(
        id="plaid-1", account_id="plaid-acc-1", date=date(2026, 3, 16),
        authorized_date=None, amount=Decimal("-4.50"), description="Coffee Shop",
        merchant_name=None, pending=False,
    )
    defaults.update(overrides)
    return PlaidTransaction(**defaults)


def test_zone_boundaries():
    cutover = date(2026, 3, 20)
    assert cutover_zone(date(2026, 3, 9), cutover) == "ignore"
    assert cutover_zone(date(2026, 3, 10), cutover) == "match"
    assert cutover_zone(date(2026, 3, 23), cutover) == "match"
    assert cutover_zone(date(2026, 3, 24), cutover) == "normal"


def test_matches_simplefin_row_with_token_overlap(db_session):
    """Stored descriptions keep a bank's trailing store-number noise
    ("COFFEE SHOP 1234"); Plaid's own text drops it. No digit-free token is
    shared verbatim with an exact string, but _evidence_tokens strips the
    digit-bearing token and the remaining words ("coffee", "shop") overlap."""
    user, account = _make_user_and_account(db_session)
    stored = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 15),
        amount=Decimal("-4.50"), description="COFFEE SHOP 1234", external_id="sf-1",
    )
    db_session.add(stored)
    db_session.commit()

    txn = _plaid_txn(date=date(2026, 3, 16), amount=Decimal("-4.50"), description="Coffee Shop")
    consumed: set[int] = set()
    match = find_match(db_session, user.id, account_id=account.id, card_id=None, txn=txn, consumed=consumed)

    assert match is not None
    assert match.id == stored.id
    assert stored.id in consumed


def test_amount_mismatch_no_match(db_session):
    user, account = _make_user_and_account(db_session)
    stored = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 15),
        amount=Decimal("-4.50"), description="Coffee Shop", external_id="sf-1",
    )
    db_session.add(stored)
    db_session.commit()

    txn = _plaid_txn(date=date(2026, 3, 16), amount=Decimal("-9.00"), description="Coffee Shop")
    match = find_match(db_session, user.id, account_id=account.id, card_id=None, txn=txn, consumed=set())

    assert match is None


def test_authorized_date_only_match(db_session):
    """Plaid's `date` (post date) can land outside the +/-3 day window while
    `authorized_date` (the real transaction date) is inside it -- the
    candidate must still be found via authorized_date alone."""
    user, account = _make_user_and_account(db_session)
    stored = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 15),
        amount=Decimal("-4.50"), description="Coffee Shop", external_id="sf-1",
    )
    db_session.add(stored)
    db_session.commit()

    txn = _plaid_txn(
        date=date(2026, 3, 25), authorized_date=date(2026, 3, 15),
        amount=Decimal("-4.50"), description="Coffee Shop",
    )
    match = find_match(db_session, user.id, account_id=account.id, card_id=None, txn=txn, consumed=set())

    assert match is not None
    assert match.id == stored.id


def test_two_identical_charges_match_one_to_one(db_session):
    """Two stored rows, two Plaid rows: each gets its own match, not the same
    one twice. A third Plaid row with nothing left to claim gets None."""
    user, account = _make_user_and_account(db_session)
    stored1 = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 15),
        amount=Decimal("-3.00"), description="MTA PAYGO", external_id="sf-1",
    )
    stored2 = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 15),
        amount=Decimal("-3.00"), description="MTA PAYGO", external_id="sf-2",
    )
    db_session.add_all([stored1, stored2])
    db_session.commit()

    consumed: set[int] = set()
    plaid_rows = [
        _plaid_txn(id="p1", date=date(2026, 3, 16), amount=Decimal("-3.00"), description="MTA PAYGO"),
        _plaid_txn(id="p2", date=date(2026, 3, 16), amount=Decimal("-3.00"), description="MTA PAYGO"),
        _plaid_txn(id="p3", date=date(2026, 3, 16), amount=Decimal("-3.00"), description="MTA PAYGO"),
    ]
    matches = [
        find_match(db_session, user.id, account_id=account.id, card_id=None, txn=t, consumed=consumed)
        for t in plaid_rows
    ]

    assert matches[0] is not None and matches[1] is not None
    assert matches[0].id != matches[1].id
    assert {matches[0].id, matches[1].id} == {stored1.id, stored2.id}
    assert matches[2] is None


def test_merchant_name_substring_match(db_session):
    """Neither normalized equality nor evidence-token overlap holds (the
    descriptions are unrelated text), but Plaid's merchant_name, lowercased,
    is found inside the stored description."""
    user, account = _make_user_and_account(db_session)
    stored = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 16),
        amount=Decimal("-6.25"), description="SQ *BLUEBOTTLECOFFEE1234", external_id="sf-1",
    )
    db_session.add(stored)
    db_session.commit()

    txn = _plaid_txn(
        date=date(2026, 3, 16), amount=Decimal("-6.25"),
        description="POS PURCHASE", merchant_name="BlueBottleCoffee",
    )
    match = find_match(db_session, user.id, account_id=account.id, card_id=None, txn=txn, consumed=set())

    assert match is not None
    assert match.id == stored.id


def test_card_side_sign(db_session):
    """A stored card charge is positive; the matching Plaid amount is the
    negative of it (Plaid's checking-convention sign, per plaid_client)."""
    user, card = _make_user_and_card(db_session)
    stored = models.CreditCardTransaction(
        user_id=user.id, card_id=card.id, date=date(2026, 3, 16),
        amount=Decimal("20.00"), merchant="Target", external_id="sf-1",
    )
    db_session.add(stored)
    db_session.commit()

    txn = _plaid_txn(date=date(2026, 3, 16), amount=Decimal("-20.00"), description="Target")
    match = find_match(db_session, user.id, account_id=None, card_id=card.id, txn=txn, consumed=set())

    assert match is not None
    assert match.id == stored.id


def test_find_match_requires_exactly_one_of_account_or_card():
    txn = _plaid_txn()
    for kwargs in [dict(account_id=None, card_id=None), dict(account_id=1, card_id=1)]:
        try:
            find_match(None, 1, txn=txn, consumed=set(), **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_alt_external_id_found_by_dedup(db_session):
    """Task 1's alt_external_id column records the Plaid id a cutover match
    was found under. A later sync re-sending that same Plaid id must dedupe
    against it through the normal external-id lookup, not just find_match.

    The stored row keeps its own (SimpleFIN) external_id, which excludes it
    from the heuristic fallback entirely (`external_id IS NULL`) -- so the
    only way this can resolve is the alt_external_id branch of the by-id
    lookup, not a coincidental heuristic match."""
    user, account = _make_user_and_account(db_session)
    stored = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 3, 16),
        amount=Decimal("-20.00"), description="Target",
        external_id="sf-999", alt_external_id="plaid:abc",
    )
    db_session.add(stored)
    db_session.commit()

    row = schemas.ImportConfirmRow(
        date=date(2026, 3, 16), amount=Decimal("-20.00"), description="Target",
        external_id="plaid:abc",
    )
    result = _find_duplicate_transaction(db_session, user.id, account.id, row)

    assert result is not None
    assert result.id == stored.id
