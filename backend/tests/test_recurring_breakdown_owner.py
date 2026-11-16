from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module


@pytest.fixture()
def client(db_session):
    user = models.User(username="rec-owner", hashed_password="x", display_name="Rec Owner")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.commit()

    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, account


def _item(db, user, account, **kw):
    defaults = dict(
        user_id=user.id, account_id=account.id, name="Thing",
        amount=Decimal("100.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    defaults.update(kw)
    item = models.RecurringItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_unassigned_items_fall_in_family_bucket(client, db_session):
    test_client, user, account = client
    item = _item(db_session, user, account, name="Groceries")
    db_session.commit()

    by_owner = test_client.get("/recurring/breakdown").json()["by_owner"]

    family = next(g for g in by_owner if g["owner_id"] is None)
    assert family["owner_name"] == "Family"
    assert any(i["id"] == item.id for i in family["items"])


def test_owned_item_falls_in_its_owner_bucket(client, db_session):
    test_client, user, account = client
    member = models.HouseholdMember(user_id=user.id, name="Test Member")
    db_session.add(member)
    db_session.commit()
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Test Haircut",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1), owner_id=member.id,
    )
    db_session.add(item)
    db_session.commit()

    by_owner = test_client.get("/recurring/breakdown").json()["by_owner"]

    group = next(g for g in by_owner if g["owner_id"] == member.id)
    assert group["owner_name"] == "Test Member"
    assert any(i["id"] == item.id for i in group["items"])


def test_by_category_shape_is_unchanged_when_owners_are_present(client, db_session):
    """by_category must stay purely additive -- tagging an item with an owner
    doesn't change what by_category reports for it."""
    test_client, user, account = client
    member = models.HouseholdMember(user_id=user.id, name="Test Member")
    db_session.add(member)
    db_session.commit()
    _item(db_session, user, account, name="Tagged", owner_id=member.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert body["by_category"] == [
        {
            "group_id": None, "group_name": "Unclassified", "monthly": "100.00",
            "categories": [],
            "items": [
                {
                    "id": body["by_category"][0]["items"][0]["id"], "name": "Tagged",
                    "amount": "100.00", "type": "expense", "frequency": "monthly",
                    "monthly_equivalent": "100.00", "end_date": None, "months_remaining": None,
                },
            ],
        },
    ]


def test_income_items_are_excluded_from_by_owner(client, db_session):
    """Only expense-type items count toward by_owner, same as by_category --
    income is not spending that belongs to anyone's bucket."""
    test_client, user, account = client
    _item(db_session, user, account, name="Paycheck", type=models.RecurringType.income)
    db_session.commit()

    by_owner = test_client.get("/recurring/breakdown").json()["by_owner"]

    assert by_owner == []


def test_credit_card_payment_items_are_excluded_from_by_owner(client, db_session):
    """credit_card_payment is excluded from by_owner the same way it's
    excluded from by_category -- it pays off card charges already counted
    elsewhere, so folding it in here would double-count that spending."""
    test_client, user, account = client
    card = models.CreditCard(
        user_id=user.id, name="Test Card", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("0.00"),
    )
    db_session.add(card)
    db_session.flush()
    _item(
        db_session, user, account, name="Card Payment",
        type=models.RecurringType.credit_card_payment, card_id=card.id,
    )
    db_session.commit()

    by_owner = test_client.get("/recurring/breakdown").json()["by_owner"]

    assert by_owner == []


def test_owner_group_monthly_sums_only_its_own_items(client, db_session):
    test_client, user, account = client
    member = models.HouseholdMember(user_id=user.id, name="Test Member")
    db_session.add(member)
    db_session.commit()
    _item(db_session, user, account, name="Owned A", amount=Decimal("30.00"), owner_id=member.id)
    _item(db_session, user, account, name="Owned B", amount=Decimal("20.00"), owner_id=member.id)
    _item(db_session, user, account, name="Family Thing", amount=Decimal("15.00"))
    db_session.commit()

    by_owner = test_client.get("/recurring/breakdown").json()["by_owner"]

    group = next(g for g in by_owner if g["owner_id"] == member.id)
    family = next(g for g in by_owner if g["owner_id"] is None)
    assert Decimal(group["monthly"]) == Decimal("50.00")
    assert Decimal(family["monthly"]) == Decimal("15.00")


def test_family_bucket_sorts_last(client, db_session):
    """No stated preference in the plan for Family's position among sorted
    owner groups -- this test documents the implementation's call: Family
    (the default/fallback bucket) always trails the named owners, mirroring
    by_category's Unclassified placement, even when Family's own monthly
    total is largest."""
    test_client, user, account = client
    member = models.HouseholdMember(user_id=user.id, name="Test Member")
    db_session.add(member)
    db_session.commit()
    _item(db_session, user, account, name="Owned", amount=Decimal("5.00"), owner_id=member.id)
    _item(db_session, user, account, name="Family Thing", amount=Decimal("500.00"))
    db_session.commit()

    by_owner = test_client.get("/recurring/breakdown").json()["by_owner"]

    assert by_owner[-1]["owner_id"] is None
    assert by_owner[-1]["owner_name"] == "Family"
