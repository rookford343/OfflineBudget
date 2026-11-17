"""GET /recurring/breakdown's by_account rollup -- groups active expense
items under the account that pays them, or the card instead when the item
carries a card_id (a card charge groups under the card, not the checking
account that eventually pays it off). Mirrors test_recurring_breakdown_owner.py's
style for by_owner.

This repo wires auth via a get_current_user dependency override rather than a
bearer-token scheme (see test_recurring_router_skip.py) -- auth_headers below
is an empty placeholder kept only so the call shape matches other breakdown
test files; no real header is required.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module


@pytest.fixture()
def client(db_session, test_user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: test_user
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    return {}


@pytest.fixture()
def test_recurring_item(db_session, test_user, test_account):
    """A bare active expense RecurringItem on test_account, with no category
    or owner tagged -- for tests that just need a valid item tied to the
    account."""
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Streaming",
        amount=Decimal("15.00"), type=models.RecurringType.expense,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    return item


def test_checking_item_groups_under_its_account(client, auth_headers, test_recurring_item, test_account):
    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    group = next(g for g in by_account if g["group_id"] == test_account.id and g["group_name"] == test_account.name)
    assert any(i["id"] == test_recurring_item.id for i in group["items"] or any(
        i["id"] == test_recurring_item.id for c in group["categories"] for i in c["items"]
    ))


def test_card_item_groups_under_the_card_not_its_account(client, auth_headers, db_session, test_user, test_account, test_card):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Haircut", amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    card_group = next(g for g in by_account if g["group_id"] == test_card.id and g["group_name"] == test_card.name)
    found = any(i["id"] == item.id for i in card_group["items"]) or any(
        i["id"] == item.id for c in card_group["categories"] for i in c["items"]
    )
    assert found
    # Matched on id AND name, same as card_group above -- Account and
    # CreditCard are separate tables with independent id sequences, so in a
    # fresh test DB test_account.id and test_card.id both legitimately start
    # at 1; an id-only lookup here would find the card bucket by coincidence
    # and misreport it as the account bucket.
    account_group = next(
        (g for g in by_account if g["group_id"] == test_account.id and g["group_name"] == test_account.name),
        None,
    )
    if account_group:
        assert not any(i["id"] == item.id for i in account_group["items"])


def test_credit_card_payment_type_excluded_from_by_account(client, auth_headers, db_session, test_user, test_account, test_card):
    payment_item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test CC Payment", amount=Decimal("500.00"), type=models.RecurringType.credit_card_payment,
        day_of_month=20, start_date=date(2026, 1, 1),
    )
    db_session.add(payment_item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    for g in by_account:
        all_items = list(g["items"]) + [i for c in g["categories"] for i in c["items"]]
        assert not any(i["id"] == payment_item.id for i in all_items)


def test_inactive_item_excluded_from_by_account(client, auth_headers, db_session, test_user, test_account):
    """is_active defaults True on the model -- an item explicitly paused
    (is_active=False) must not surface in by_account at all, same traversal
    pattern as the credit_card_payment exclusion test above."""
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id,
        name="Test Paused Subscription", amount=Decimal("9.99"),
        type=models.RecurringType.expense,
        day_of_month=5, start_date=date(2026, 1, 1), is_active=False,
    )
    db_session.add(item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    for g in by_account:
        all_items = list(g["items"]) + [i for c in g["categories"] for i in c["items"]]
        assert not any(i["id"] == item.id for i in all_items)


def test_account_with_no_items_produces_no_bucket(client, auth_headers, db_session, test_user, test_account, test_card):
    """An account or card with zero recurring items must never surface as an
    empty placeholder bucket in by_account -- neither directly (checked by
    id/name below) nor structurally (no bucket anywhere in the response may
    have both an empty items list and every nested categories[*].items list
    empty). test_card gets zero items on purpose, to prove a resolvable but
    unused holder stays out of the response entirely; one real item on
    test_account keeps the response from being trivially empty."""
    empty_account = models.Account(
        user_id=test_user.id, name="Test Unused Account",
        type=models.AccountType.checking, current_balance=Decimal("0.00"),
    )
    db_session.add(empty_account)
    db_session.commit()

    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id,
        name="Test Subscription", amount=Decimal("12.00"),
        type=models.RecurringType.expense,
        day_of_month=10, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]

    # Matched on id AND name -- Account and CreditCard have independent id
    # sequences, so a numeric-only match could coincidentally hit the other
    # table's bucket (see the same note in test_card_item_groups_under_the_
    # card_not_its_account above).
    assert not any(
        g["group_id"] == empty_account.id and g["group_name"] == empty_account.name for g in by_account
    )
    assert not any(
        g["group_id"] == test_card.id and g["group_name"] == test_card.name for g in by_account
    )
    for g in by_account:
        all_items = list(g["items"]) + [i for c in g["categories"] for i in c["items"]]
        assert all_items, f"bucket {g['group_id']} ({g['group_name']}) has no items anywhere"
