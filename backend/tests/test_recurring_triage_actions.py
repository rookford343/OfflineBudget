from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module

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
    assert rule.pattern == "CITY TRASH 8812" and rule.category_id == cats["home"].id


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
