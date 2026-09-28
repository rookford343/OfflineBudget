from datetime import date, timedelta
import pytest
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module
from backend.services.rules_engine import apply_rules

E = models.CategoryType.expense
DESC = "ACME CLOUD STORAGE"


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db):
    user = models.User(username="ta", hashed_password="x", display_name="TA")
    other = models.User(username="tb", hashed_password="x", display_name="TB")
    db.add_all([user, other]); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    card = models.CreditCard(user_id=user.id, name="Card", credit_limit=Decimal("1000"), statement_day=1, due_day=20)
    home = models.Category(user_id=user.id, name="Home", type=E)
    subs = models.Category(user_id=user.id, name="Subscriptions", type=E)
    manual = models.Category(user_id=user.id, name="Manual pick", type=E)
    income = models.Category(user_id=user.id, name="Income", type=models.CategoryType.income)
    foreign = models.Category(user_id=other.id, name="Theirs", type=E)
    db.add_all([acct, card, home, subs, manual, income, foreign]); db.flush()

    trash = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Trash service", amount=Decimal("25.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=5, start_date=date(2026, 1, 1),
    )
    hulu = models.RecurringItem(
        user_id=user.id, account_id=acct.id, card_id=card.id, name="Hulu", amount=Decimal("18.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=9, start_date=date(2026, 1, 1),
    )
    db.add_all([trash, hulu]); db.flush()
    db.add_all([
        models.Transaction(user_id=user.id, account_id=acct.id, recurring_item_id=trash.id, date=date(2026, 8, 5),
                           amount=Decimal("-25.00"), description="CITY TRASH 8812", is_actual=True),
        models.Transaction(user_id=user.id, account_id=acct.id, recurring_item_id=trash.id, date=date(2026, 9, 5),
                           amount=Decimal("-25.00"), description="CITY TRASH 8812", is_actual=True, category_id=manual.id),
        models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 9, 9),
                                     amount=Decimal("18.00"), merchant="HULU 877-8244858"),
    ])
    today = date.today()
    for n in range(3):
        db.add(models.Transaction(
            user_id=user.id, account_id=acct.id, date=today - timedelta(days=30 * n + 1),
            amount=Decimal("-9.99"), description=DESC, is_actual=True,
        ))
    db.commit()
    return user, acct, {"home": home, "subs": subs, "manual": manual, "income": income, "foreign": foreign}, {"trash": trash, "hulu": hulu}


def test_classify_item_sets_category_creates_rule_and_backfills_only_null(db_session):
    user, _, cats, items = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/recurring/triage/classify", json={"recurring_item_id": items["trash"].id, "category_id": cats["home"].id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rule_created"] is True
    assert body["backfilled"] == 1
    db_session.expire_all()
    assert db_session.get(models.RecurringItem, items["trash"].id).category_id == cats["home"].id
    txns = db_session.query(models.Transaction).filter(models.Transaction.recurring_item_id == items["trash"].id).all()
    assert sorted(t.category_id for t in txns) == sorted([cats["home"].id, cats["manual"].id])  # manual kept
    rule = db_session.get(models.TransactionRule, body["rule_id"])
    # Store/reference numbers stripped, so next month's descriptor still matches.
    assert rule.pattern == "CITY TRASH" and rule.category_id == cats["home"].id


def test_classify_twice_does_not_duplicate_rule(db_session):
    user, _, cats, items = _seed(db_session)
    c = _client(db_session, user)
    payload = {"recurring_item_id": items["trash"].id, "category_id": cats["home"].id}
    c.post("/recurring/triage/classify", json=payload)
    second = c.post("/recurring/triage/classify", json=payload).json()
    assert second["rule_created"] is False
    assert db_session.query(models.TransactionRule).count() == 1


def test_classify_card_item_backfills_matching_uncategorized_card_rows(db_session):
    user, _, cats, items = _seed(db_session)
    r = _client(db_session, user).post("/recurring/triage/classify", json={"recurring_item_id": items["hulu"].id, "category_id": cats["subs"].id}).json()
    assert r["backfilled"] == 1
    row = db_session.query(models.CreditCardTransaction).one()
    db_session.refresh(row)
    assert row.category_id == cats["subs"].id


def test_classify_untracked_pattern_creates_linked_item(db_session):
    user, acct, cats, _ = _seed(db_session)
    r = _client(db_session, user).post("/recurring/triage/classify", json={"pattern_key": "acme cloud storage", "category_id": cats["subs"].id})
    assert r.status_code == 200, r.text
    item = db_session.get(models.RecurringItem, r.json()["recurring_item_id"])
    assert item.category_id == cats["subs"].id
    assert item.amount == Decimal("9.99")
    assert item.account_id == acct.id
    linked = db_session.query(models.Transaction).filter(models.Transaction.recurring_item_id == item.id).count()
    assert linked == 3


def test_classify_rejects_bad_category_and_bad_body(db_session):
    user, _, cats, items = _seed(db_session)
    c = _client(db_session, user)
    for cat in ("income", "foreign"):
        r = c.post("/recurring/triage/classify", json={"recurring_item_id": items["trash"].id, "category_id": cats[cat].id})
        assert r.status_code == 400, cat
    assert c.post("/recurring/triage/classify", json={"category_id": cats["home"].id}).status_code == 422
    assert c.post("/recurring/triage/classify", json={"recurring_item_id": 999999, "category_id": cats["home"].id}).status_code == 404
    assert c.post("/recurring/triage/classify", json={"pattern_key": "nope", "category_id": cats["home"].id}).status_code == 404


def test_dismiss_is_idempotent(db_session):
    user, *_ = _seed(db_session)
    c = _client(db_session, user)
    assert c.post("/recurring/triage/dismiss", json={"pattern_key": "acme cloud storage"}).status_code == 200
    assert c.post("/recurring/triage/dismiss", json={"pattern_key": "acme cloud storage"}).status_code == 200
    assert db_session.query(models.RecurringDismissal).count() == 1


def test_duplicate_deactivates_and_relinks_never_deletes(db_session):
    user, _, _, items = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/recurring/triage/duplicate", json={"keep_id": items["hulu"].id, "deactivate_id": items["trash"].id})
    assert r.status_code == 200
    assert r.json()["relinked"] == 2
    db_session.expire_all()
    gone = db_session.get(models.RecurringItem, items["trash"].id)
    assert gone is not None and gone.is_active is False
    assert db_session.query(models.Transaction).filter(models.Transaction.recurring_item_id == items["hulu"].id).count() == 2


def test_duplicate_rejects_same_or_inactive(db_session):
    user, _, _, items = _seed(db_session)
    c = _client(db_session, user)
    assert c.post("/recurring/triage/duplicate", json={"keep_id": items["hulu"].id, "deactivate_id": items["hulu"].id}).status_code == 400
    items["trash"].is_active = False
    db_session.commit()
    assert c.post("/recurring/triage/duplicate", json={"keep_id": items["hulu"].id, "deactivate_id": items["trash"].id}).status_code == 400


def _card_item(db, user, card, name):
    item = models.RecurringItem(
        user_id=user.id, account_id=db.query(models.Account).one().id, card_id=card.id, name=name, amount=Decimal("40.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=12, start_date=date(2026, 1, 1),
    )
    db.add(item); db.flush()
    return item


def test_rule_from_noisy_descriptor_matches_next_months_variant(db_session):
    user, acct, cats, _ = _seed(db_session)
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Gym", amount=Decimal("30.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1),
    )
    db_session.add(item); db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=item.id, date=date(2026, 9, 3),
        amount=Decimal("-30.00"), description="ACME FITNESS DUES PPD ID: 4411223344", is_actual=True,
    ))
    db_session.commit()
    body = _client(db_session, user).post("/recurring/triage/classify", json={"recurring_item_id": item.id, "category_id": cats["home"].id}).json()
    rule = db_session.get(models.TransactionRule, body["rule_id"])
    assert rule.pattern == "ACME FITNESS DUES"
    hit = apply_rules("ACME FITNESS DUES PPD ID: 9988776655", [rule])
    assert hit is not None and hit.category_id == cats["home"].id


def _classify_card_item_with_descriptor(db, user, acct, cats, descriptor, card_merchants):
    """A card-paid item whose linked checking row carries `descriptor`, with
    uncategorized card rows that a broad rule would wrongly claim."""
    card = db.query(models.CreditCard).one()
    item = _card_item(db, user, card, "Utility")
    db.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=item.id, date=date(2026, 9, 3),
        amount=Decimal("-60.00"), description=descriptor, is_actual=True,
    ))
    for n, m in enumerate(card_merchants):
        db.add(models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 9, 4 + n),
                                            amount=Decimal("10.00"), merchant=m))
    db.commit()
    return _client(db, user).post("/recurring/triage/classify", json={"recurring_item_id": item.id, "category_id": cats["home"].id}).json()


@pytest.mark.parametrize("descriptor, merchant", [
    ("ACH DEBIT 20260903 CITY OF SPRINGFIELD", "ACH DEBIT ELSEWHERE"),
    ("HOME #5001 DEPOT", "HOMEGOODS 12"),
    ("ACMEFLIX.COM #5001 LOS GATOS CA", "ACMEFLIX.COM OTHER"),
])
def test_interior_noise_makes_the_pattern_weak_not_a_broad_leading_run(db_session, descriptor, merchant):
    # Stripping interior noise leaves text that isn't contiguous in the raw
    # descriptor. Its leading run ("ACH DEBIT", "HOME") would be a rule that
    # files every future ACH debit / anything "home" -- so no rule at all.
    user, acct, cats, _ = _seed(db_session)
    body = _classify_card_item_with_descriptor(db_session, user, acct, cats, descriptor, [merchant])
    assert body["rule_id"] is None and body["rule_created"] is False
    assert body["backfilled"] == 1   # its own linked row only
    assert db_session.query(models.TransactionRule).count() == 0
    db_session.expire_all()
    assert db_session.query(models.CreditCardTransaction).filter_by(merchant=merchant).one().category_id is None


def test_whitespace_only_difference_keeps_the_full_pattern_as_written(db_session):
    # Repeated spaces are not noise: the rule is the full descriptor exactly
    # as the bank spaced it (so a contains-match on raw text still fires),
    # never a leading fragment like "CITY".
    user, acct, cats, _ = _seed(db_session)
    body = _classify_card_item_with_descriptor(db_session, user, acct, cats, "CITY  OF SPRINGFIELD UTIL", ["CITY PIZZA"])
    rule = db_session.get(models.TransactionRule, body["rule_id"])
    assert rule.pattern == "CITY  OF SPRINGFIELD UTIL"
    assert apply_rules("CITY  OF SPRINGFIELD UTIL", [rule]) is not None
    db_session.expire_all()
    assert db_session.query(models.CreditCardTransaction).filter_by(merchant="CITY PIZZA").one().category_id is None


def test_generic_card_item_name_creates_no_rule_and_no_card_backfill(db_session):
    user, _, cats, _ = _seed(db_session)
    card = db_session.query(models.CreditCard).one()
    gas = _card_item(db_session, user, card, "Gas")
    db_session.add(models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 9, 12),
                                                amount=Decimal("41.00"), merchant="VEGAS STEAKHOUSE"))
    db_session.commit()
    body = _client(db_session, user).post("/recurring/triage/classify", json={"recurring_item_id": gas.id, "category_id": cats["home"].id}).json()
    assert body["rule_id"] is None and body["rule_created"] is False
    assert body["backfilled"] == 0
    assert db_session.query(models.TransactionRule).count() == 0
    db_session.expire_all()
    assert db_session.get(models.RecurringItem, gas.id).category_id == cats["home"].id
    assert all(r.category_id is None for r in db_session.query(models.CreditCardTransaction).all())


def test_weak_pattern_still_backfills_the_items_own_linked_rows(db_session):
    user, acct, cats, _ = _seed(db_session)
    card = db_session.query(models.CreditCard).one()
    water = _card_item(db_session, user, card, "Water")
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=water.id, date=date(2026, 9, 12),
        amount=Decimal("-40.00"), description="WATER 991122", is_actual=True,
    ))
    db_session.commit()
    body = _client(db_session, user).post("/recurring/triage/classify", json={"recurring_item_id": water.id, "category_id": cats["home"].id}).json()
    assert body["rule_id"] is None and body["rule_created"] is False
    assert body["backfilled"] == 1


def test_percent_in_name_does_not_wildcard_the_card_backfill(db_session):
    user, _, cats, _ = _seed(db_session)
    card = db_session.query(models.CreditCard).one()
    club = _card_item(db_session, user, card, "Fun%Club")
    db_session.add_all([
        models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 9, 12),
                                     amount=Decimal("40.00"), merchant="FUN%CLUB 0042"),
        models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 9, 13),
                                     amount=Decimal("40.00"), merchant="FUNNY BIG CLUB"),
    ])
    db_session.commit()
    body = _client(db_session, user).post("/recurring/triage/classify", json={"recurring_item_id": club.id, "category_id": cats["subs"].id}).json()
    assert body["backfilled"] == 1
    db_session.expire_all()
    by_merchant = {r.merchant: r.category_id for r in db_session.query(models.CreditCardTransaction).all()}
    assert by_merchant["FUN%CLUB 0042"] == cats["subs"].id
    assert by_merchant["FUNNY BIG CLUB"] is None


def test_long_pattern_truncated_before_lookup_so_reclassify_reuses_rule(db_session):
    user, acct, cats, _ = _seed(db_session)
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Long", amount=Decimal("5.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1),
    )
    db_session.add(item); db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=item.id, date=date(2026, 9, 3),
        amount=Decimal("-5.00"), description="LONGMERCHANT " * 25, is_actual=True,
    ))
    db_session.commit()
    c = _client(db_session, user)
    payload = {"recurring_item_id": item.id, "category_id": cats["home"].id}
    assert c.post("/recurring/triage/classify", json=payload).json()["rule_created"] is True
    assert c.post("/recurring/triage/classify", json=payload).json()["rule_created"] is False
    assert db_session.query(models.TransactionRule).count() == 1


def test_long_dismiss_key_truncated_before_lookup(db_session):
    user, *_ = _seed(db_session)
    c = _client(db_session, user)
    key = "x" * 300
    assert c.post("/recurring/triage/dismiss", json={"pattern_key": key}).status_code == 200
    assert c.post("/recurring/triage/dismiss", json={"pattern_key": key}).status_code == 200
    assert db_session.query(models.RecurringDismissal).count() == 1
