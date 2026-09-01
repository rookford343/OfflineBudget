from datetime import date, datetime
from decimal import Decimal
from backend import models, schemas
from backend.services.import_service import run_import


def _make_user_and_card(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("100.00"),
    )
    db.add(card)
    db.flush()
    return user, card


def test_card_sale_increases_balance(db_session):
    user, card = _make_user_and_card(db_session)
    rows = [schemas.ImportConfirmRow(date=date(2026, 8, 4), description="Meijer", amount=Decimal("-52.90"))]

    run_import(db_session, user, rows, account_id=None, card_id=card.id)

    assert card.current_balance == Decimal("152.90")
    txn = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).one()
    assert txn.amount == Decimal("52.90")  # positive = charge


def test_card_return_decreases_balance(db_session):
    user, card = _make_user_and_card(db_session)
    rows = [schemas.ImportConfirmRow(date=date(2026, 8, 3), description="Ozwell Return", amount=Decimal("25.00"))]

    run_import(db_session, user, rows, account_id=None, card_id=card.id)

    assert card.current_balance == Decimal("75.00")
    txn = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).one()
    # Regression: this used to be stored as +25.00 (abs() discarded the
    # refund's sign, making it indistinguishable from a $25 charge --
    # confirmed against real Chase data for this exact Ozwell scenario).
    assert txn.amount == Decimal("-25.00")  # negative = refund/credit


def test_checking_autopay_reduces_matching_card_balance(db_session):
    """A checking-side CC autopay debit should reduce the matching card's
    balance, even though the real bank description ("CHASE CREDIT CRD
    AUTOPAY") never contains the card's full display name ("Chase Sapphire")
    verbatim -- only the issuer name in common."""
    user, card = _make_user_and_card(db_session)
    card.name = "Chase Sapphire"
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("5000.00"))
    db_session.add(checking)
    db_session.flush()

    rows = [schemas.ImportConfirmRow(
        date=date(2026, 7, 27), description="CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224",
        amount=Decimal("-11312.54"), is_transfer=True,
    )]

    run_import(db_session, user, rows, account_id=checking.id, card_id=None)

    assert card.current_balance == Decimal("0.00")  # 100.00 - 11312.54, floored at 0


def test_bank_sync_autopay_reduces_matching_card_balance_without_manual_tag(db_session):
    """Real-world regression (2026-09-01): a bank's autopay description is
    deterministic, machine-generated text -- it should never require Dan to
    hand-configure a transaction_rule tagging it is_transfer before the
    matching card's balance gets corrected. Any bank_sync-sourced row must
    trigger the same correction is_transfer=True already does, with no rule
    involved."""
    user, card = _make_user_and_card(db_session)
    card.name = "Chase Sapphire"
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("5000.00"))
    db_session.add(checking)
    db_session.flush()

    rows = [schemas.ImportConfirmRow(
        date=date(2026, 8, 26), description="CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224",
        amount=Decimal("-11312.54"),  # is_transfer left at its False default -- no rule tagged it
    )]

    run_import(
        db_session, user, rows, account_id=checking.id, card_id=None,
        source=models.TransactionSource.bank_sync,
    )

    assert card.current_balance == Decimal("0.00")  # 100.00 - 11312.54, floored at 0
    assert card.balance_as_of == datetime(2026, 8, 26, 0, 0)


def test_dedupes_across_whitespace_formatting_difference(db_session):
    """Reproduces a live bug (2026-08-08): a bank's CSV export pads ACH
    descriptions with internal whitespace ('PAYROLL     PPD ID: 123'), while
    SimpleFIN returns the same transaction already whitespace-normalized
    ('PAYROLL PPD ID: 123'). Both describe the identical real-world
    transaction and must dedupe against each other even without a shared
    external_id -- an exact string-equality heuristic misses this and
    double-imports every overlapping transaction on first sync."""
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.flush()

    csv_row = schemas.ImportConfirmRow(
        date=date(2026, 7, 15), amount=Decimal("6121.01"),
        description="MIDCONTINENT IND PAYROLL                    PPD ID: 6506940773",
    )
    run_import(db_session, user, [csv_row], account_id=account.id, card_id=None)

    sync_row = schemas.ImportConfirmRow(
        date=date(2026, 7, 15), amount=Decimal("6121.01"),
        description="MIDCONTINENT IND PAYROLL PPD ID: 6506940773",
        external_id="simplefin-txn-1",
    )
    result = run_import(db_session, user, [sync_row], account_id=account.id, card_id=None)

    assert result.imported == 0
    assert result.skipped_duplicates == 1
    txns = db_session.query(models.Transaction).filter_by(account_id=account.id).all()
    assert len(txns) == 1


def test_card_dedupes_across_whitespace_formatting_difference(db_session):
    """Card-side twin of the checking-account whitespace dedup bug."""
    user, card = _make_user_and_card(db_session)

    csv_row = schemas.ImportConfirmRow(
        date=date(2026, 8, 3), amount=Decimal("-25.00"),
        description="TARGET   T-1063",
    )
    run_import(db_session, user, [csv_row], account_id=None, card_id=card.id)

    sync_row = schemas.ImportConfirmRow(
        date=date(2026, 8, 3), amount=Decimal("-25.00"),
        description="TARGET T-1063",
        external_id="simplefin-txn-2",
    )
    result = run_import(db_session, user, [sync_row], account_id=None, card_id=card.id)

    assert result.imported == 0
    assert result.skipped_duplicates == 1
    txns = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).all()
    assert len(txns) == 1


def test_card_dedupes_sync_posted_a_few_days_after_the_csv_date(db_session):
    """Reproduces the live bug found 2026-08-12: a card CSV export carries the
    transaction date, SimpleFIN reports the post date 1-2 days later, and
    exact-date dedupe matched neither -- 130 card rows ($7,702.40) were
    double-counted across 2026-07-10..2026-08-04, inflating the Household
    Snapshot's category totals and the weekly email. The real Airbnb charge
    below appeared on 7/21 in the CSV and 7/22 from sync."""
    user, card = _make_user_and_card(db_session)

    csv_row = schemas.ImportConfirmRow(
        date=date(2026, 7, 21), amount=Decimal("-2123.69"),
        description="AIRBNB * HMXKC4BDXD",
    )
    run_import(db_session, user, [csv_row], account_id=None, card_id=card.id)

    sync_row = schemas.ImportConfirmRow(
        date=date(2026, 7, 22), amount=Decimal("-2123.69"),
        description="AIRBNB * HMXKC4BDXD",
        external_id="simplefin-airbnb-1",
    )
    result = run_import(db_session, user, [sync_row], account_id=None, card_id=card.id)

    assert result.imported == 0
    assert result.skipped_duplicates == 1
    txns = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).all()
    assert len(txns) == 1
    # The CSV row survives -- it carries the true transaction date, not the
    # bank's post date, which is what the dedupe script keeps too.
    assert txns[0].date == date(2026, 7, 21)


def test_card_keeps_a_genuine_repeat_charge_outside_the_window(db_session):
    """A real second charge at the same merchant for the same amount, far
    enough out to be unambiguous, must still import. Guards the widened
    window against over-collapsing."""
    user, card = _make_user_and_card(db_session)

    first = schemas.ImportConfirmRow(
        date=date(2026, 7, 2), amount=Decimal("-8.75"), description="MTA*NYCT PAYGO",
    )
    run_import(db_session, user, [first], account_id=None, card_id=card.id)

    later = schemas.ImportConfirmRow(
        date=date(2026, 7, 9), amount=Decimal("-8.75"), description="MTA*NYCT PAYGO",
    )
    result = run_import(db_session, user, [later], account_id=None, card_id=card.id)

    assert result.imported == 1
    assert db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).count() == 2


def test_card_two_synced_charges_do_not_collapse_onto_one_csv_row(db_session):
    """The 1:1 guard. Dan really does hit MTA*NYCT PAYGO for $3.00 several
    times a day. If one CSV row is already stored and sync then delivers two
    genuine charges inside the window, exactly one may be treated as its
    duplicate -- the other is new money and must import. Before `consumed`,
    both matched the same stored row and one real charge vanished."""
    user, card = _make_user_and_card(db_session)

    csv_row = schemas.ImportConfirmRow(
        date=date(2026, 6, 2), amount=Decimal("-3.00"), description="MTA*NYCT PAYGO",
    )
    run_import(db_session, user, [csv_row], account_id=None, card_id=card.id)

    sync_rows = [
        schemas.ImportConfirmRow(
            date=date(2026, 6, 3), amount=Decimal("-3.00"),
            description="MTA*NYCT PAYGO", external_id="sf-mta-1",
        ),
        schemas.ImportConfirmRow(
            date=date(2026, 6, 3), amount=Decimal("-3.00"),
            description="MTA*NYCT PAYGO", external_id="sf-mta-2",
        ),
    ]
    result = run_import(db_session, user, sync_rows, account_id=None, card_id=card.id)

    assert result.skipped_duplicates == 1
    assert result.imported == 1
    assert db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).count() == 2


def test_checking_dedupes_sync_posted_a_day_after_the_csv_date(db_session):
    """Checking-side twin of the post-date window fix. Live data happened to be
    clean on this side, but the same matcher runs there."""
    user = models.User(username="chk", hashed_password="x", display_name="Chk")
    db_session.add(user)
    db_session.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.flush()

    csv_row = schemas.ImportConfirmRow(
        date=date(2026, 8, 3), amount=Decimal("-200.00"), description="VICKY HOUSE CLEAN",
    )
    run_import(db_session, user, [csv_row], account_id=account.id, card_id=None)

    sync_row = schemas.ImportConfirmRow(
        date=date(2026, 8, 5), amount=Decimal("-200.00"),
        description="VICKY HOUSE CLEAN", external_id="sf-vicky-1",
    )
    result = run_import(db_session, user, [sync_row], account_id=account.id, card_id=None)

    assert result.imported == 0
    assert result.skipped_duplicates == 1
    assert db_session.query(models.Transaction).filter_by(account_id=account.id).count() == 1


def test_a_synced_charge_and_its_refund_net_to_zero_discretionary_spend(db_session):
    """End-to-end regression, reproducing the real Ozwell scenario from a
    SimpleFIN-style sync: a $25 charge (negative row.amount) and its $25
    refund (positive row.amount), same day, same merchant. Before the sign
    fix, both landed as +$25 CreditCardTransaction rows -- indistinguishable
    charges -- so the pacer's refund-netting logic (which only nets a
    negative amount) never triggered and the week showed $50 of Ozwell
    spend instead of $0."""
    from backend.services.spendable_pacer import discretionary_spend_in_range

    user, card = _make_user_and_card(db_session)
    rows = [
        schemas.ImportConfirmRow(date=date(2026, 8, 3), description="OZWELL, LLC", amount=Decimal("-25.00")),
        schemas.ImportConfirmRow(date=date(2026, 8, 3), description="OZWELL, LLC", amount=Decimal("25.00")),
    ]
    run_import(db_session, user, rows, account_id=None, card_id=card.id)

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")
