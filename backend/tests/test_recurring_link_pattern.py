from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module

DESCRIPTOR = "UTILITYCO BILL PAY 123456789 WEB ID: ABC123"


def _client(db_session, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, with_category=True):
    user = models.User(username="l", hashed_password="x", display_name="L")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    cat = models.Category(user_id=user.id, name="Utilities", type=models.CategoryType.expense)
    db.add_all([acct, cat]); db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Electric",
        category_id=cat.id if with_category else None,
        amount=Decimal("180.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=8,
        start_date=date(2026, 1, 1), is_active=True,
    )
    db.add(item); db.flush()
    db.add_all([
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 7, 8),
                           amount=Decimal("-171.20"), description=DESCRIPTOR, is_actual=True),
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 8, 8),
                           amount=Decimal("-180.44"), description=DESCRIPTOR, is_actual=True),
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 8, 9),
                           amount=Decimal("-42.00"), description="COFFEE SHOP", is_actual=True),
    ])
    db.commit()
    return user, item, cat


def test_linking_files_past_transactions_under_the_existing_item(db_session):
    """Accepting a suggestion created a duplicate item because raw descriptors
    never match the friendly name a person typed."""
    user, item, cat = _seed(db_session)
    c = _client(db_session, user)

    r = c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR}).json()
    assert r["linked_checking"] == 2
    assert r["rule_created"] is True
    assert r["category_name"] == "Utilities"

    linked = db_session.query(models.Transaction).filter(
        models.Transaction.recurring_item_id == item.id).all()
    assert len(linked) == 2
    assert all(t.category_id == cat.id for t in linked)


def test_unrelated_transactions_are_untouched(db_session):
    user, item, cat = _seed(db_session)
    c = _client(db_session, user)
    c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR})

    other = db_session.query(models.Transaction).filter(
        models.Transaction.description == "COFFEE SHOP").first()
    assert other.recurring_item_id is None
    assert other.category_id is None


def test_a_rule_is_left_behind_so_future_ones_classify_on_arrival(db_session):
    user, item, cat = _seed(db_session)
    c = _client(db_session, user)
    c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR})

    rule = db_session.query(models.TransactionRule).filter_by(user_id=user.id).first()
    assert rule.pattern == DESCRIPTOR
    assert rule.category_id == cat.id
    assert rule.action == models.RuleAction.set_category


def test_linking_twice_does_not_stack_duplicate_rules(db_session):
    user, item, cat = _seed(db_session)
    c = _client(db_session, user)
    first = c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR}).json()
    second = c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR}).json()

    assert second["rule_created"] is False
    assert second["rule_id"] == first["rule_id"]
    assert db_session.query(models.TransactionRule).filter_by(user_id=user.id).count() == 1


def test_no_rule_when_the_item_has_no_category(db_session):
    """set_category with no category is a no-op that would look like it worked."""
    user, item, _ = _seed(db_session, with_category=False)
    c = _client(db_session, user)

    r = c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR}).json()
    assert r["rule_created"] is False and r["rule_id"] is None
    # Transactions still get attached to the item, which is the other half.
    assert r["linked_checking"] == 2


def test_transactions_already_claimed_by_another_item_are_left_alone(db_session):
    """Re-pointing them would corrupt that bill's history rather than fix this one."""
    user, item, cat = _seed(db_session)
    other_item = models.RecurringItem(
        user_id=user.id, account_id=item.account_id, name="Something else",
        amount=Decimal("10.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_active=True)
    db_session.add(other_item); db_session.flush()
    claimed = db_session.query(models.Transaction).filter(
        models.Transaction.description == DESCRIPTOR).first()
    claimed.recurring_item_id = other_item.id
    db_session.commit()

    r = _client(db_session, user).post(
        f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR}).json()
    assert r["linked_checking"] == 1
    db_session.refresh(claimed)
    assert claimed.recurring_item_id == other_item.id


def test_blank_pattern_is_rejected(db_session):
    """It would match everything and recategorize the whole ledger."""
    user, item, cat = _seed(db_session)
    assert _client(db_session, user).post(
        f"/recurring/{item.id}/link-pattern", json={"pattern": "   "}).status_code == 422


def test_a_linked_descriptor_stops_being_suggested(db_session):
    """The suggestion list filters by normalized ITEM NAME, which a raw bank
    descriptor never matches, so a linked pattern kept reappearing forever."""
    from backend.services.recurring_detector import detect_patterns

    user, item, cat = _seed(db_session)
    before = [s.description for s in detect_patterns(db_session, user.id, min_occurrences=2)]
    assert any(DESCRIPTOR in d for d in before)

    _client(db_session, user).post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR})

    after = [s.description for s in detect_patterns(db_session, user.id, min_occurrences=2)]
    assert not any(DESCRIPTOR in d for d in after)


def test_card_linked_item_can_link_unlinked_card_transactions(db_session):
    """A card-linked item (card_id set) gets the same manual-teach fallback
    the checking side already has -- claims unlinked CreditCardTransaction
    rows by recurring_item_id, not just category. Regression: this endpoint
    used to only categorize card rows, never link them, because of a stale
    comment claiming CreditCardTransaction had no recurring_item_id column
    at all (it does -- added in an earlier task of this plan)."""
    user = models.User(username="cardlink", hashed_password="x", display_name="CL")
    db_session.add(user)
    db_session.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("1000"), statement_day=1, due_day=20)
    cat = models.Category(user_id=user.id, name="Personal Care", type=models.CategoryType.expense)
    db_session.add_all([acct, card, cat])
    db_session.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, card_id=card.id, category_id=cat.id,
        name="Test Haircut", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=True, is_active=True,
    )
    db_session.add(item)
    db_session.flush()
    db_session.add_all([
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 10, 12),
                                      amount=Decimal("45.00"), merchant="TEST BARBERS #42"),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 9, 14),
                                      amount=Decimal("47.00"), merchant="TEST BARBERS #42"),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 1),
                                      amount=Decimal("12.00"), merchant="COFFEE SHOP"),
    ])
    db_session.commit()

    c = _client(db_session, user)
    r = c.post(f"/recurring/{item.id}/link-pattern", json={"pattern": "TEST BARBERS #42"}).json()

    assert r["linked_card"] == 2
    linked = db_session.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.recurring_item_id == item.id).all()
    assert len(linked) == 2
    assert all(t.category_id == cat.id for t in linked)

    other = db_session.query(models.CreditCardTransaction).filter_by(merchant="COFFEE SHOP").first()
    assert other.recurring_item_id is None


def test_unlinked_descriptors_are_still_suggested(db_session):
    """The filter must be scoped to linked rows, not suppress detection."""
    from backend.services.recurring_detector import detect_patterns

    user, item, cat = _seed(db_session)
    acct = db_session.query(models.Account).filter_by(user_id=user.id).first()
    for d in (date(2026, 6, 3), date(2026, 7, 3), date(2026, 8, 3)):
        db_session.add(models.Transaction(user_id=user.id, account_id=acct.id, date=d,
                                          amount=Decimal("-58.00"), description="GYM MEMBERSHIP 55512",
                                          is_actual=True))
    db_session.commit()
    _client(db_session, user).post(f"/recurring/{item.id}/link-pattern", json={"pattern": DESCRIPTOR})

    after = [s.description for s in detect_patterns(db_session, user.id, min_occurrences=2)]
    assert any("GYM MEMBERSHIP" in d for d in after)
