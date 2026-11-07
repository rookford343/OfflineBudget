"""The one real-spending rule (services/real_spend.py).

Every spending and income total in the app asks this module whether a row is
spend, income, a transfer or a card payment, and for its signed amount. These
tests pin each verdict on synthetic rows, then pin that every surface showing
"spending for the month" returns the same figure from one fixture.
"""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import spending as spending_router_module
from backend.services.real_spend import (
    Verdict,
    classify_card,
    classify_checking,
    savings_moved,
    spend_totals,
)

START = date(2026, 3, 1)
END = date(2026, 3, 31)


def _user(db):
    user = models.User(username="realspend", hashed_password="x", display_name="RS")
    db.add(user)
    db.flush()
    return user


def _account(db, user):
    acct = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(acct)
    db.flush()
    return acct


def _card(db, user, name="Chase Sapphire", last_four=None, balance=Decimal("0")):
    card = models.CreditCard(
        user_id=user.id, name=name, last_four=last_four, credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, current_balance=balance,
    )
    db.add(card)
    db.flush()
    return card


def _cat(db, user, name, type_=models.CategoryType.expense, parent=None, sort_order=0):
    cat = models.Category(
        user_id=user.id, name=name, type=type_, color="#888888", sort_order=sort_order,
        parent_id=parent.id if parent else None,
    )
    db.add(cat)
    db.flush()
    return cat


def _chk(db, user, acct, amount, description, cat=None, day=10, is_actual=True):
    t = models.Transaction(
        user_id=user.id, account_id=acct.id, date=date(2026, 3, day),
        amount=Decimal(amount), description=description, is_actual=is_actual,
        category_id=cat.id if cat else None,
    )
    db.add(t)
    db.flush()
    return t


def _cc(db, user, card, amount, merchant, cat=None, day=10):
    t = models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 3, day),
        amount=Decimal(amount), merchant=merchant, category_id=cat.id if cat else None,
    )
    db.add(t)
    db.flush()
    return t


def test_card_autopay_is_card_payment(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    card = _card(db_session, user)
    checking_debit = _chk(db_session, user, acct, "-1000.00", "CHASE CREDIT CRD AUTOPAY")
    # A payoff for a card that is no longer active still reads as a payoff.
    closed_card_debit = _chk(db_session, user, acct, "-75.00", "CITI AUTOPAY PAYMENT")
    card_row = _cc(db_session, user, card, "1000.00", "AUTOMATIC PAYMENT - THANK")

    assert classify_checking(checking_debit, [card]) == Verdict("card_payment", Decimal("1000.00"))
    assert classify_checking(closed_card_debit, [card]).kind == "card_payment"
    assert classify_card(card_row) == Verdict("card_payment", Decimal("1000.00"))


def test_own_account_transfer_is_transfer_both_directions(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    out = _chk(db_session, user, acct, "-500.00", "Online Transfer to SAV ...0000")
    back = _chk(db_session, user, acct, "200.00", "Online Transfer from SAV ...0000")

    assert classify_checking(out, []) == Verdict("transfer", Decimal("500.00"))
    assert classify_checking(back, []) == Verdict("transfer", Decimal("200.00"))
    totals = spend_totals(db_session, user.id, START, END)
    assert totals.spend == Decimal("0")
    assert totals.income == Decimal("0")


def test_zelle_to_person_is_spend(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    zelle = _chk(db_session, user, acct, "-60.00", "Zelle payment to Example Person")

    assert classify_checking(zelle, []) == Verdict("spend", Decimal("60.00"))
    assert spend_totals(db_session, user.id, START, END).spend == Decimal("60.00")


def test_card_refund_nets_spend(db_session):
    user = _user(db_session)
    card = _card(db_session, user)
    shopping = _cat(db_session, user, "Shopping")
    _cc(db_session, user, card, "100.00", "EXAMPLE SHOP", shopping)
    refund = _cc(db_session, user, card, "-25.00", "EXAMPLE SHOP", shopping, day=12)

    assert classify_card(refund) == Verdict("spend", Decimal("-25.00"))
    totals = spend_totals(db_session, user.id, START, END)
    assert totals.spend == Decimal("75.00")
    assert totals.by_category[shopping.id] == Decimal("75.00")


def test_checking_refund_matching_a_debit_nets_spend(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _chk(db_session, user, acct, "-40.00", "EXAMPLE HARDWARE")
    refund = _chk(db_session, user, acct, "15.00", "EXAMPLE HARDWARE", day=14)

    assert classify_checking(refund, [], refund_descriptions=frozenset({"EXAMPLE HARDWARE"})) == (
        Verdict("spend", Decimal("-15.00"))
    )
    totals = spend_totals(db_session, user.id, START, END)
    assert totals.spend == Decimal("25.00")
    assert totals.income == Decimal("0")


def test_refunds_exceeding_charges_go_negative(db_session):
    user = _user(db_session)
    card = _card(db_session, user)
    shopping = _cat(db_session, user, "Shopping")
    _cc(db_session, user, card, "10.00", "EXAMPLE SHOP", shopping)
    _cc(db_session, user, card, "-30.00", "EXAMPLE SHOP", shopping, day=12)

    totals = spend_totals(db_session, user.id, START, END)
    assert totals.by_category[shopping.id] == Decimal("-20.00")
    assert totals.spend == Decimal("-20.00")


def test_income_category_debit_reduces_income(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    salary = _cat(db_session, user, "Salary", models.CategoryType.income)
    _chk(db_session, user, acct, "3000.00", "EXAMPLE EMPLOYER PAYROLL", salary)
    reversal = _chk(db_session, user, acct, "-200.00", "EXAMPLE EMPLOYER REVERSAL", salary)

    assert classify_checking(reversal, []) == Verdict("income", Decimal("-200.00"))
    totals = spend_totals(db_session, user.id, START, END)
    assert totals.income == Decimal("2800.00")
    assert totals.spend == Decimal("0")


def test_savings_category_debit_is_transfer(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    savings = _cat(db_session, user, "Emergency Fund", models.CategoryType.savings)
    debit = _chk(db_session, user, acct, "-250.00", "EXAMPLE BROKERAGE DEPOSIT", savings)

    assert classify_checking(debit, []) == Verdict("transfer", Decimal("250.00"))
    assert spend_totals(db_session, user.id, START, END).spend == Decimal("0")


def test_savings_category_card_row_is_transfer(db_session):
    user = _user(db_session)
    card = _card(db_session, user)
    savings = _cat(db_session, user, "Emergency Fund", models.CategoryType.savings)
    row = _cc(db_session, user, card, "150.00", "EXAMPLE TRANSFER", savings)

    assert classify_card(row) == Verdict("transfer", Decimal("150.00"))
    assert spend_totals(db_session, user.id, START, END).spend == Decimal("0")


def test_savings_line_tracks_money_moved_not_spend(db_session):
    from backend.services.budget_calculator import apply_rollover, compute_overview

    user = _user(db_session)
    acct = _account(db_session, user)
    card = _card(db_session, user)
    savings = _cat(db_session, user, "Emergency Fund", models.CategoryType.savings)
    savings.rollover_enabled = True
    _chk(db_session, user, acct, "-500.00", "EXAMPLE BROKERAGE DEPOSIT", savings)
    # Money pulled back out of savings is not subtracted from "moved".
    _chk(db_session, user, acct, "100.00", "EXAMPLE BROKERAGE WITHDRAWAL", savings, day=12)
    _cc(db_session, user, card, "40.00", "EXAMPLE SHOP")
    db_session.add(models.BudgetAllocation(
        user_id=user.id, category_id=savings.id, year=2026, month=3,
        budgeted_amount=Decimal("800.00"),
    ))
    db_session.commit()

    assert savings_moved(db_session, user.id, START, END) == {savings.id: Decimal("500.00")}
    totals = spend_totals(db_session, user.id, START, END)
    assert totals.spend == Decimal("40.00")
    assert savings.id not in totals.by_category

    row = next(r for r in compute_overview(db_session, user.id, 2026, 3) if r.category_id == savings.id)
    assert row.actual_total == Decimal("500.00")
    assert row.actual_checking == Decimal("500.00")

    assert apply_rollover(db_session, user.id, 2026, 3) == 1
    db_session.refresh(savings)
    assert savings.rollover_balance == Decimal("300.00")


def test_planned_checking_rows_do_not_count(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _chk(db_session, user, acct, "-90.00", "EXAMPLE PLANNED", is_actual=False)

    assert spend_totals(db_session, user.id, START, END).spend == Decimal("0")


def test_balance_only_card_has_no_rows_and_no_crash(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _card(db_session, user, name="Apple Card", balance=Decimal("800.00"))
    _chk(db_session, user, acct, "-30.00", "EXAMPLE CAFE")

    totals = spend_totals(db_session, user.id, START, END)
    assert totals.spend == Decimal("30.00")
    assert totals.income == Decimal("0")


def _month_fixture(db, *, edge_cases=False):
    """One month with every verdict represented. `edge_cases` adds the rows
    the surfaces used to disagree on: a card refund, a paycheck reversal
    under an income category, and a savings-category debit."""
    user = _user(db)
    acct = _account(db, user)
    card = _card(db, user)
    salary = _cat(db, user, "Salary", models.CategoryType.income)
    wants = _cat(db, user, "Wants", sort_order=1)
    dining = _cat(db, user, "Dining", parent=wants, sort_order=1)
    shopping = _cat(db, user, "Shopping", parent=wants, sort_order=2)
    _cc(db, user, card, "300.00", "EXAMPLE SHOP", shopping)
    _cc(db, user, card, "100.00", "EXAMPLE DINER", dining, day=11)
    _chk(db, user, acct, "-50.00", "EXAMPLE CAFE", dining, day=12)
    _chk(db, user, acct, "-1000.00", "CHASE CREDIT CRD AUTOPAY", day=20)
    _chk(db, user, acct, "-500.00", "Online Transfer to SAV ...0000", day=21)
    _chk(db, user, acct, "3000.00", "EXAMPLE EMPLOYER PAYROLL", salary, day=15)
    if edge_cases:
        savings = _cat(db, user, "Emergency Fund", models.CategoryType.savings, sort_order=2)
        _cc(db, user, card, "-20.00", "EXAMPLE SHOP", shopping, day=16)
        _chk(db, user, acct, "-200.00", "EXAMPLE EMPLOYER REVERSAL", salary, day=17)
        _chk(db, user, acct, "-250.00", "EXAMPLE BROKERAGE DEPOSIT", savings, day=18)
    db.commit()
    return user


def test_spend_totals_one_month(db_session):
    user = _month_fixture(db_session)

    totals = spend_totals(db_session, user.id, START, END)

    assert totals.spend == Decimal("450.00")
    assert totals.income == Decimal("3000.00")


def test_all_spend_surfaces_agree(db_session):
    from backend.services.budget_calculator import compute_overview
    from backend.services.spending_helpers import category_totals_for_range
    from backend.services.summary_generator import _month_spending_by_category

    user = _month_fixture(db_session, edge_cases=True)
    totals = spend_totals(db_session, user.id, START, END)
    expected = totals.spend
    assert expected == Decimal("430.00")
    assert totals.income == Decimal("2800.00")

    assert sum(category_totals_for_range(db_session, user.id, START, END).values()) == expected

    overview = compute_overview(db_session, user.id, 2026, 3)
    # Savings-type lines track money moved to savings, not spending.
    spend_rows = [r for r in overview if r.parent_id is None and r.category_type != "savings"]
    assert sum((r.actual_total for r in spend_rows), Decimal("0")) == expected
    savings_row = next(r for r in overview if r.category_type == "savings")
    assert savings_row.actual_total == Decimal("250.00")

    _, debits, credits = _month_spending_by_category(db_session, user.id, 2026, 3)
    assert debits == expected
    assert credits == Decimal("2800.00")

    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    by_cat = client.get("/spending/by-category", params={"start": START, "end": END})
    assert by_cat.status_code == 200
    assert Decimal(str(by_cat.json()["total_actual"])) == expected

    sankey = client.get("/spending/sankey/2026/3")
    assert sankey.status_code == 200
    expense_links = [
        link for link in sankey.json()["links"] if link["target"].startswith("expense:")
    ]
    assert sum((Decimal(str(link["value"])) for link in expense_links), Decimal("0")) == expected

    monthly = client.get("/spending/monthly", params={"start": START, "end": END})
    assert Decimal(str(monthly.json()[0]["total"])) == expected


def test_checking_refund_looks_back_ninety_days_and_only_backwards(db_session):
    """The refund verdict is the credit's own: a same-merchant debit up to 90
    days before it nets it (even outside the query window); one 91 days
    before, or one dated after it, does not."""
    user = _user(db_session)
    acct = _account(db_session, user)
    for desc, amount, when in (
        ("EXAMPLE NEAR DEBIT", "-40.00", date(2026, 3, 1)),
        ("EXAMPLE NEAR DEBIT", "15.00", date(2026, 5, 30)),    # 90 days later: a refund
        ("EXAMPLE FAR DEBIT", "-40.00", date(2026, 3, 1)),
        ("EXAMPLE FAR DEBIT", "15.00", date(2026, 5, 31)),     # 91 days later: income
        ("EXAMPLE LATER DEBIT", "15.00", date(2026, 5, 5)),    # credit first: income
        ("EXAMPLE LATER DEBIT", "-40.00", date(2026, 5, 20)),
    ):
        db_session.add(models.Transaction(
            user_id=user.id, account_id=acct.id, date=when, amount=Decimal(amount),
            description=desc, is_actual=True,
        ))
    db_session.commit()
    # May alone: the March debits are outside the window.
    totals = spend_totals(db_session, user.id, date(2026, 5, 1), date(2026, 5, 31))
    assert totals.income == Decimal("30.00")                  # far + later credits
    assert totals.spend == Decimal("40.00") - Decimal("15.00")  # later debit, less the near refund
