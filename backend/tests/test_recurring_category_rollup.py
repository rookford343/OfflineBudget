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
    user = models.User(username="rollup", hashed_password="x", display_name="Rollup")
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


def _cat(db, user, **kw):
    defaults = dict(user_id=user.id, name="Category", type=models.CategoryType.expense)
    defaults.update(kw)
    cat = models.Category(**defaults)
    db.add(cat)
    db.flush()
    return cat


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


def test_group_category_bill_grouping_with_totals(client, db_session):
    test_client, user, account = client
    group = _cat(db_session, user, name="Necessities")
    groceries = _cat(db_session, user, name="Groceries", parent_id=group.id)
    _item(db_session, user, account, name="Bulk store", amount=Decimal("60.00"), category_id=groceries.id)
    _item(db_session, user, account, name="Corner store", amount=Decimal("40.00"), category_id=groceries.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()
    groups = body["by_category"]

    assert len(groups) == 1
    g = groups[0]
    assert g["group_id"] == group.id
    assert g["group_name"] == "Necessities"
    assert Decimal(g["monthly"]) == Decimal("100.00")
    assert g["items"] == []
    assert len(g["categories"]) == 1
    node = g["categories"][0]
    assert node["category_id"] == groceries.id
    assert node["category_name"] == "Groceries"
    assert Decimal(node["monthly"]) == Decimal("100.00")
    assert [i["name"] for i in node["items"]] == ["Bulk store", "Corner store"], "largest first"


def test_yearly_bill_counted_as_one_twelfth_in_the_tree(client, db_session):
    test_client, user, account = client
    group = _cat(db_session, user, name="Wants")
    fun = _cat(db_session, user, name="Fun", parent_id=group.id)
    _item(db_session, user, account, name="Annual pass", amount=Decimal("120.00"),
          frequency=models.RecurringFrequency.yearly, month_of_year=6, category_id=fun.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()
    node = body["by_category"][0]["categories"][0]

    assert Decimal(node["items"][0]["monthly_equivalent"]) == Decimal("10.00")
    assert Decimal(node["monthly"]) == Decimal("10.00")


def test_quarterly_bill_counted_as_one_third_in_the_tree(client, db_session):
    test_client, user, account = client
    group = _cat(db_session, user, name="Wants")
    fun = _cat(db_session, user, name="Fun", parent_id=group.id)
    _item(db_session, user, account, name="Box subscription", amount=Decimal("30.00"),
          frequency=models.RecurringFrequency.quarterly, month_of_year=1, category_id=fun.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()
    node = body["by_category"][0]["categories"][0]

    assert Decimal(node["items"][0]["monthly_equivalent"]) == Decimal("10.00")
    assert Decimal(node["monthly"]) == Decimal("10.00")


def test_item_filed_directly_on_a_top_level_category_goes_into_group_items(client, db_session):
    test_client, user, account = client
    group = _cat(db_session, user, name="Charity")
    _item(db_session, user, account, name="Giving", amount=Decimal("200.00"), category_id=group.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()
    g = body["by_category"][0]

    assert g["group_id"] == group.id
    assert g["categories"] == []
    assert [i["name"] for i in g["items"]] == ["Giving"]
    assert Decimal(g["monthly"]) == Decimal("200.00")


def test_unclassified_group_present_only_when_needed_and_sorted_last(client, db_session):
    test_client, user, account = client

    # No uncategorized expenses yet -- Unclassified must not appear at all.
    group = _cat(db_session, user, name="Necessities")
    _item(db_session, user, account, name="Rent", amount=Decimal("500.00"), category_id=group.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()
    assert all(g["group_name"] != "Unclassified" for g in body["by_category"])

    # Now add a bigger uncategorized expense -- it would sort first by amount
    # alone, but Unclassified always goes last.
    _item(db_session, user, account, name="Mystery charge", amount=Decimal("900.00"), category_id=None)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()
    names = [g["group_name"] for g in body["by_category"]]
    assert names[-1] == "Unclassified"
    unclassified = body["by_category"][-1]
    assert unclassified["group_id"] is None
    assert unclassified["categories"] == []
    assert [i["name"] for i in unclassified["items"]] == ["Mystery charge"]
    assert Decimal(unclassified["monthly"]) == Decimal("900.00")


def test_credit_card_payment_excluded_from_expense_monthly_and_tree(client, db_session):
    test_client, user, account = client
    group = _cat(db_session, user, name="Necessities")
    _item(db_session, user, account, name="Rent", amount=Decimal("500.00"), category_id=group.id)
    _item(db_session, user, account, name="Card payoff", amount=Decimal("300.00"),
          type=models.RecurringType.credit_card_payment, category_id=group.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert Decimal(body["expense_monthly"]) == Decimal("500.00")
    all_tree_names = [i["name"] for g in body["by_category"] for i in g["items"]] + \
        [i["name"] for g in body["by_category"] for c in g["categories"] for i in c["items"]]
    assert "Card payoff" not in all_tree_names


def test_income_totals_sum_active_income_only(client, db_session):
    test_client, user, account = client
    _item(db_session, user, account, name="Paycheck", amount=Decimal("2000.00"),
          type=models.RecurringType.income)
    _item(db_session, user, account, name="Side gig", amount=Decimal("500.00"),
          type=models.RecurringType.income)
    _item(db_session, user, account, name="Rent", amount=Decimal("500.00"),
          type=models.RecurringType.expense)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert Decimal(body["income_monthly"]) == Decimal("2500.00")


def test_another_users_category_never_leaks_into_the_tree(client, db_session):
    test_client, user, account = client
    other = models.User(username="other", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.flush()
    other_cat = _cat(db_session, other, name="Other Person's Category")
    # Simulates a stale/foreign category_id -- the item belongs to `user` but
    # its category was never validated as belonging to that same user.
    _item(db_session, user, account, name="Odd one", amount=Decimal("50.00"), category_id=other_cat.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    names = [g["group_name"] for g in body["by_category"]]
    assert "Other Person's Category" not in names
    unclassified = body["by_category"][-1]
    assert unclassified["group_name"] == "Unclassified"
    assert [i["name"] for i in unclassified["items"]] == ["Odd one"]


def test_groups_sorted_by_monthly_descending(client, db_session):
    test_client, user, account = client
    small = _cat(db_session, user, name="Small")
    big = _cat(db_session, user, name="Big")
    _item(db_session, user, account, name="Small bill", amount=Decimal("10.00"), category_id=small.id)
    _item(db_session, user, account, name="Big bill", amount=Decimal("900.00"), category_id=big.id)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert [g["group_name"] for g in body["by_category"]] == ["Big", "Small"]


def test_existing_breakdown_fields_keep_working_alongside_the_new_ones(client, db_session):
    test_client, user, account = client
    _item(db_session, user, account, name="Mortgage", amount=Decimal("4404.65"))
    _item(db_session, user, account, name="iPhone Duo", amount=Decimal("57.87"),
          end_date=date(2028, 10, 23))
    _item(db_session, user, account, name="Paycheck", amount=Decimal("6066.63"),
          type=models.RecurringType.income)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert Decimal(body["ongoing_monthly"]) == Decimal("4404.65")
    assert Decimal(body["ending_monthly"]) == Decimal("57.87")
    assert "Mortgage" in [i["name"] for i in body["ongoing"]]
    assert [i["name"] for i in body["ending"]] == ["iPhone Duo"]
