"""Cross-surface parity: one headline figure, one value, whichever screen shows it.

Each test builds one invented fixture and reads the same concept off every
surface that displays it. A failure here means two surfaces disagree, which is
the bug the shared calculation layer exists to prevent (docs/architecture.md).

Pinned dates: "today" is 2026-11-02 for the forward-looking figures. The
spending test pins 2026-10-31 so the weekly digest's trailing seven days are
exactly the last week of October, where all of that fixture's spending sits.

All figures are invented.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import forecast as forecast_router_module
from backend.routers import recurring as recurring_router_module
from backend.routers import budget as budget_router_module
from backend.routers import spending as spending_router_module
from backend.services import budget_snapshot
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.budget_calculator import compute_overview
from backend.services.card_payment_model import card_payments
from backend.services.month_base import build_month_base
from backend.services.real_spend import spend_totals
from backend.services.summary_generator import (
    _month_spending_by_category,
    generate_summary,
    generate_weekly_digest,
)
from backend.tests.test_month_leftover_parity import BOOST, NET, _budget, _expense, _seed

D = Decimal
TODAY = date(2026, 11, 2)


def _pin_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    for module in (
        "backend.services.forecast_engine",
        "backend.services.card_payment_model",
        "backend.services.budget_snapshot",
        "backend.services.summary_generator",
    ):
        monkeypatch.setattr(f"{module}.date", _FixedDate)


def _client(db, user, *routers) -> TestClient:
    app = FastAPI()
    for router_module in routers:
        app.include_router(router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _card(db, user, name, *, statement_day, due_day, due, balance_due, **kw):
    card = models.CreditCard(
        user_id=user.id, name=name, credit_limit=D("10000.00"), statement_day=statement_day,
        due_day=due_day, is_active=True, current_balance=balance_due,
        balance_due=balance_due, next_payment_date=due, **kw,
    )
    db.add(card)
    db.flush()
    return card


def _headline_fixture(db):
    """November 2026: two paychecks past the Social Security base, a weekly
    card bill, a quarterly bill, a savings-funded one-off, a refund (a planned
    inflow), an unfunded one-off that makes the late-month low, and a fresh pending charge. Two cards with locked statements that
    fall due before the first paycheck, so the lowest point sits after both."""
    user, checking = _seed(db, "headline", remaining=D("0"))
    checking.current_balance = D("3000.00")
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=D("30000.00"),
    )
    db.add(savings)
    visa = _card(db, user, "Test Visa", statement_day=28, due_day=5, due=date(2026, 11, 5),
                 balance_due=D("400.00"), pending_charges=D("75.00"),
                 pending_charges_updated_at=datetime(2026, 11, 1, 9, 0))
    _card(db, user, "Test Mastercard", statement_day=20, due_day=9, due=date(2026, 11, 9),
          balance_due=D("250.00"), pending_charges=D("0"))
    _expense(db, user, checking, "Electric", "200.00", day_of_month=8)
    _expense(db, user, checking, "Lawn", "25.00", card_id=visa.id,  # weekly: Mondays
             frequency=models.RecurringFrequency.weekly, day_of_month=0)
    _expense(db, user, checking, "Stormwater", "150.00",  # quarterly, due whole in November
             frequency=models.RecurringFrequency.quarterly, month_of_year=2, day_of_month=0)
    db.add_all([
        models.PlannedExpense(
            user_id=user.id, account_id=checking.id, name="New roof", amount=D("900.00"),
            expected_date=date(2026, 11, 20), funding_account_id=savings.id, funding_lead_days=1,
        ),
        models.PlannedExpense(
            user_id=user.id, account_id=checking.id, name="Furnace", amount=D("7000.00"),
            expected_date=date(2026, 11, 24),
        ),
        models.PlannedExpense(
            user_id=user.id, name="Refund", amount=D("100.00"), expected_date=date(2026, 11, 21),
            direction=models.PlannedDirection.inflow,
        ),
    ])
    _budget(db, user, "Groceries", "700.00")
    db.commit()
    return user, checking


def test_leftover_is_one_number_on_every_surface(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)

    base = build_month_base(db_session, user, 2026, 11)
    client = _client(db_session, user, recurring_router_module)
    resp = client.get("/recurring/month-summary", params={"year": 2026, "month": 11})
    assert resp.status_code == 200
    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=TODAY)

    # The fixture really exercises the Social Security boost and the settled rules:
    # two boosted paychecks, a funded one-off netting to zero, a quarterly bill whole.
    income = 2 * (NET + BOOST)
    bills = D("200.00") + 5 * D("25.00") + D("150.00")
    assert base.left_over == income - bills - D("7000.00") + D("100.00") - D("700.00")
    assert D(str(resp.json()["left_over"])) == base.left_over
    assert snap.leftover == base.left_over


def test_lowest_point_matches_the_forecast_endpoint(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)
    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=TODAY)

    client = _client(db_session, user, forecast_router_module)
    end = budget_snapshot._months_ahead_end(TODAY, 3)
    resp = client.get("/forecast", params={
        "account_id": checking.id, "start": (TODAY - timedelta(days=45)).isoformat(),
        "end": end.isoformat(),
    })
    assert resp.status_code == 200
    days = [schemas.ForecastEntry.model_validate(row) for row in resp.json()]
    cards = db_session.query(models.CreditCard).all()
    mask = budget_snapshot.floor_mask(days, cards)
    low, low_date = budget_snapshot._floor_minimum(days, mask, TODAY)

    assert low_date is not None and low_date > date(2026, 11, 9), "the low must follow both locked payoffs"
    assert (snap.lookahead_minimum, snap.lookahead_minimum_date) == (low, low_date)
    assert snap.explain["lookahead_minimum"].result == low


def test_each_cards_next_payment_agrees_across_forecast_explain_and_model(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)
    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=TODAY)
    end = budget_snapshot._months_ahead_end(TODAY, 3)

    client = _client(db_session, user, forecast_router_module)
    resp = client.get("/forecast", params={
        "account_id": checking.id, "start": TODAY.isoformat(), "end": end.isoformat(),
    })
    assert resp.status_code == 200
    forecast_line: dict[str, tuple[date, Decimal]] = {}
    for row in resp.json():
        for t in row["transactions"]:
            if t["name"].startswith(("CC Payment: ", "CC Estimate: ")):
                name = t["name"].split(": ", 1)[1]
                forecast_line.setdefault(name, (date.fromisoformat(row["date"]), abs(D(str(t["amount"])))))

    explain_line: dict[str, tuple[str, Decimal]] = {}
    low_row = snap.explain["lookahead_minimum"].rows[0]
    for child in low_row.informational_children:
        label_date, _, name = child.label.partition(" — ")
        if not name.startswith(("CC Payment: ", "CC Estimate: ")):
            continue  # the statement-closed heads-up shares this list
        card_name = name.split(": ", 1)[1]
        explain_line.setdefault(card_name, (label_date, abs(child.amount)))

    model_line: dict[str, tuple[date, Decimal]] = {}
    cards = {c.id: c.name for c in db_session.query(models.CreditCard).all()}
    for p in sorted(
        card_payments(db_session, user, checking, TODAY, end,
                      include_unbilled_card_bills=True, today=TODAY),
        key=lambda p: p.due,
    ):
        model_line.setdefault(cards[p.card_id], (p.due, abs(p.amount)))

    assert set(model_line) == {"Test Visa", "Test Mastercard"}
    assert model_line["Test Visa"] == (date(2026, 11, 5), D("400.00"))
    assert model_line["Test Mastercard"] == (date(2026, 11, 9), D("250.00"))
    assert forecast_line == model_line
    # The explain panel names the same payments (its label carries the date as "Nov 5").
    assert set(explain_line) == set(model_line)
    for name, (due, amount) in model_line.items():
        label_date, explain_amount = explain_line[name]
        assert label_date == f"{due:%b} {due.day}"
        assert explain_amount == amount


def _spending_fixture(db):
    """October 2026 spending, all in its last week. Not spending: a card
    autopay, a transfer to savings and a paycheck. Netted: a checking refund
    and a card refund. Spend: 120 + 60 + (40 - 15) + (80 - 15) = 270."""
    user = models.User(username="parityspend", hashed_password="x", display_name="PS")
    db.add(user)
    db.flush()
    acct = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("5000.00"),
    )
    db.add(acct)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=D("5000.00"),
        statement_day=28, due_day=25, current_balance=D("0"),
    )
    db.add(card)
    db.flush()

    def cat(name, kind):
        c = models.Category(user_id=user.id, name=name, type=kind, color="#888888")
        db.add(c)
        db.flush()
        return c

    groceries = cat("Groceries", models.CategoryType.expense)
    dining = cat("Dining", models.CategoryType.expense)
    pay = cat("Pay", models.CategoryType.income)
    savings = cat("Savings", models.CategoryType.savings)
    for amount, desc, category, day in (
        ("-120.00", "EXAMPLE GROCER", groceries, 26),
        ("-60.00", "Zelle payment to Example Person", dining, 27),
        ("-40.00", "EXAMPLE HARDWARE", dining, 27),
        ("15.00", "EXAMPLE HARDWARE", dining, 29),
        ("-400.00", "CHASE CREDIT CRD AUTOPAY", None, 28),
        ("-250.00", "Online Transfer to SAV ...0000", savings, 28),
        ("3000.00", "EXAMPLE EMPLOYER PAYROLL", pay, 30),
    ):
        db.add(models.Transaction(
            user_id=user.id, account_id=acct.id, date=date(2026, 10, day), amount=D(amount),
            description=desc, is_actual=True, category_id=category.id if category else None,
        ))
    for amount, day in (("80.00", 26), ("-15.00", 29)):
        db.add(models.CreditCardTransaction(
            card_id=card.id, user_id=user.id, date=date(2026, 10, day), amount=D(amount),
            merchant="EXAMPLE CAFE", category_id=dining.id,
        ))
    for category, amount in ((groceries, "500.00"), (dining, "200.00")):
        db.add(models.BudgetAllocation(
            user_id=user.id, category_id=category.id, year=2026, month=10, budgeted_amount=D(amount),
        ))
    db.commit()
    return user, acct


def test_last_months_spend_is_one_number_on_every_surface(db_session, monkeypatch):
    _pin_today(monkeypatch, date(2026, 10, 31))
    user, acct = _spending_fixture(db_session)
    expected = D("270.00")
    assert spend_totals(db_session, user.id, date(2026, 10, 1), date(2026, 10, 31)).spend == expected

    # Month in Review: its debits, and the net cashflow it narrates (income less spend).
    _, debits, credits = _month_spending_by_category(db_session, user.id, 2026, 10)
    assert debits == expected
    assert generate_summary(db_session, user.id, 2026, 10).net_cashflow == credits - expected

    client = _client(db_session, user, spending_router_module, budget_router_module)
    sankey = client.get("/spending/sankey/2026/10")
    assert sankey.status_code == 200
    expense_links = [lk for lk in sankey.json()["links"] if lk["target"].startswith("expense:")]
    assert sum((D(str(lk["value"])) for lk in expense_links), D("0")) == expected

    overview = client.get("/budget/overview", params={"year": 2026, "month": 10})
    assert overview.status_code == 200
    rows = [r for r in overview.json() if r["parent_id"] is None and r["category_type"] != "savings"]
    assert sum((D(str(r["actual_total"])) for r in rows), D("0")) == expected
    assert sum(
        (r.actual_total for r in compute_overview(db_session, user.id, 2026, 10)
         if r.parent_id is None and r.category_type != "savings"), D("0"),
    ) == expected

    digest = generate_weekly_digest(db_session, user, acct.id)
    assert digest.total_spent == expected
    assert sum((c.total for c in digest.categories), D("0")) == expected
