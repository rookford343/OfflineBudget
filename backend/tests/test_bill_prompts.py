"""Statement-date prompts ("Bills to confirm"): the window during which a
monthly checking bill's real statement is expected to have arrived, prompting
for its actual amount before the due date passes. Built on the existing
bill-override feature (BillAmountOverride / POST /bill-overrides).

Worked example throughout (see brief): Power Co, statement day S=17, due day
8. On Oct 16 it prompts (D = Oct 17, due = Nov 8). On Oct 15 it doesn't (D =
Sep 17, due = Oct 8, already passed). On Nov 5 it still prompts (same window).
On Nov 9 there's no prompt (window closed the day after the due date).
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module
from backend.services.bill_prompts import bills_to_confirm

TODAY = "backend.routers.recurring._today"


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _user(db, username="u"):
    user = models.User(username=username, hashed_password="x", display_name="U")
    db.add(user); db.flush()
    return user


def _account(db, user):
    acct = models.Account(
        user_id=user.id, name="Chk", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(acct); db.flush()
    return acct


def _card(db, user):
    card = models.CreditCard(
        user_id=user.id, name="Card", credit_limit=Decimal("1000.00"),
        statement_day=1, due_day=15,
    )
    db.add(card); db.commit()
    return card


def _item(
    db, user, acct, *, name="Power Co", amount="100.00", statement_day=17,
    day_of_month=8, frequency=models.RecurringFrequency.monthly,
    type=models.RecurringType.expense, card_id=None, is_active=True,
):
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name=name, amount=Decimal(amount),
        type=type, frequency=frequency, day_of_month=day_of_month,
        statement_day=statement_day, card_id=card_id, is_active=is_active,
        start_date=date(2020, 1, 1),
    )
    db.add(item); db.commit()
    return item


# ── Window edges from the worked example ─────────────────────────────────────

def test_prompts_the_day_before_the_statement_is_due(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=8)
    results = bills_to_confirm(db_session, user.id, date(2026, 10, 16))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].name == "Power Co"
    assert results[0].estimated_amount == Decimal("100.00")
    assert results[0].statement_date == date(2026, 10, 17)
    assert results[0].due_date == date(2026, 11, 8)


def test_no_prompt_the_day_before_that(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, statement_day=17, day_of_month=8)
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 15)) == []


def test_still_prompts_close_to_the_due_date(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=8)
    results = bills_to_confirm(db_session, user.id, date(2026, 11, 5))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].statement_date == date(2026, 10, 17)
    assert results[0].due_date == date(2026, 11, 8)


def test_no_prompt_once_the_due_date_has_passed(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, statement_day=17, day_of_month=8)
    assert bills_to_confirm(db_session, user.id, date(2026, 11, 9)) == []


# ── Crossing month and year ends ─────────────────────────────────────────────

def test_crosses_a_month_end(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, name="Water Co", statement_day=28, day_of_month=5)
    results = bills_to_confirm(db_session, user.id, date(2026, 12, 30))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].statement_date == date(2026, 12, 28)
    assert results[0].due_date == date(2027, 1, 5)


def test_crosses_a_year_end(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, name="Water Co", statement_day=28, day_of_month=5)
    results = bills_to_confirm(db_session, user.id, date(2027, 1, 3))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].statement_date == date(2026, 12, 28)
    assert results[0].due_date == date(2027, 1, 5)


def test_window_closes_the_day_after_a_crossed_due_date(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, name="Water Co", statement_day=28, day_of_month=5)
    assert bills_to_confirm(db_session, user.id, date(2027, 1, 6)) == []


# ── Clamping ──────────────────────────────────────────────────────────────────

def test_clamps_a_31_statement_day_in_a_30_day_month(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=31, day_of_month=8)
    # April has 30 days -- day 31 clamps to April 30.
    results = bills_to_confirm(db_session, user.id, date(2026, 4, 29))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].statement_date == date(2026, 4, 30)
    assert results[0].due_date == date(2026, 5, 8)


def test_clamps_a_31_statement_day_in_february(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=31, day_of_month=8)
    # 2026 is not a leap year -- February clamps to the 28th.
    results = bills_to_confirm(db_session, user.id, date(2026, 2, 27))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].statement_date == date(2026, 2, 28)
    assert results[0].due_date == date(2026, 3, 8)


# ── Due day 0 (last day of month) ────────────────────────────────────────────

def test_due_day_zero_is_the_last_day_of_month(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=0)
    results = bills_to_confirm(db_session, user.id, date(2026, 10, 20))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].statement_date == date(2026, 10, 17)
    assert results[0].due_date == date(2026, 10, 31)


# ── Existing overrides ────────────────────────────────────────────────────────

def test_existing_override_for_the_due_date_removes_the_prompt(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=8)
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=date(2026, 11, 8), actual_amount=Decimal("224.31"),
    ))
    db_session.commit()
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 16)) == []


def test_override_for_a_different_date_does_not_remove_the_prompt(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=8)
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=date(2026, 10, 8), actual_amount=Decimal("199.00"),
    ))
    db_session.commit()
    results = bills_to_confirm(db_session, user.id, date(2026, 10, 16))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id
    assert results[0].due_date == date(2026, 11, 8)


# ── Exclusions ────────────────────────────────────────────────────────────────

def test_card_paid_items_are_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    card = _card(db_session, user)
    _item(db_session, user, acct, statement_day=17, day_of_month=8, card_id=card.id)
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 16)) == []


def test_non_monthly_items_are_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, statement_day=17, day_of_month=8,
          frequency=models.RecurringFrequency.yearly)
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 16)) == []


def test_income_items_are_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, statement_day=17, day_of_month=8,
          type=models.RecurringType.income)
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 16)) == []


def test_inactive_items_are_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, statement_day=17, day_of_month=8, is_active=False)
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 16)) == []


def test_items_with_no_statement_day_are_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, statement_day=None, day_of_month=8)
    assert bills_to_confirm(db_session, user.id, date(2026, 10, 16)) == []


def test_another_users_items_never_appear(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=8)
    other = _user(db_session, username="other")
    other_acct = _account(db_session, other)
    _item(db_session, other, other_acct, statement_day=17, day_of_month=8)

    results = bills_to_confirm(db_session, user.id, date(2026, 10, 16))
    assert len(results) == 1
    assert results[0].recurring_item_id == item.id


def test_sorted_by_due_date(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    # On Oct 16 (D = Oct 17), day-of-month 25 is due Oct 25; day-of-month 8
    # has already passed this month and rolls to Nov 8 -- so the due-day-25
    # item, added second, must still sort FIRST.
    due_nov8 = _item(db_session, user, acct, name="Power Co", statement_day=17, day_of_month=8)
    due_oct25 = _item(db_session, user, acct, name="Gas Co", statement_day=17, day_of_month=25)
    results = bills_to_confirm(db_session, user.id, date(2026, 10, 16))
    assert [r.recurring_item_id for r in results] == [due_oct25.id, due_nov8.id]


# ── Endpoint ──────────────────────────────────────────────────────────────────

def test_endpoint_returns_200_with_the_list(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, statement_day=17, day_of_month=8)
    with patch(TODAY, return_value=date(2026, 10, 16)):
        r = _client(db_session, user).get("/recurring/bills-to-confirm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["recurring_item_id"] == item.id
    assert body[0]["due_date"] == "2026-11-08"
    assert body[0]["statement_date"] == "2026-10-17"
    assert Decimal(body[0]["estimated_amount"]) == Decimal("100.00")
