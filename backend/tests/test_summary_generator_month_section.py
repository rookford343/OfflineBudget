"""The daily email's "Spending this month" section: the weekly digest's
category and merchant breakdown over the month so far, from the same
spending_breakdown the Dashboard's digest card uses. It replaced the
"Budget this month" section on 2026-10-09."""
from datetime import date
from decimal import Decimal
from backend import models
import backend.services.summary_generator as summary_generator_module
from backend.services.summary_generator import generate_daily_summary

TODAY = date(2026, 10, 9)


def _with_today(monkeypatch, fixed_today: date):
    class _FakeDate(date):
        @classmethod
        def today(cls):
            return fixed_today
    monkeypatch.setattr(summary_generator_module, "date", _FakeDate)


def _seed(db):
    """Groceries $120 on checking, Shopping $300 + $45 on a card (two
    merchants), a $75 Groceries charge from LAST month that must not count,
    and a card payoff that is not spending."""
    user = models.User(username="monthuser", hashed_password="x", display_name="Month")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                              current_balance=Decimal("1000.00"))
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
                             statement_day=28, due_day=15)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    shopping = models.Category(user_id=user.id, name="Shopping", type=models.CategoryType.expense)
    db.add_all([checking, card, groceries, shopping])
    db.flush()
    db.add_all([
        models.Transaction(user_id=user.id, account_id=checking.id, category_id=groceries.id,
                           date=date(2026, 10, 3), amount=Decimal("-120.00"), description="Kroger", is_actual=True),
        models.Transaction(user_id=user.id, account_id=checking.id, category_id=groceries.id,
                           date=date(2026, 9, 28), amount=Decimal("-75.00"), description="Old Market", is_actual=True),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, category_id=shopping.id,
                                     date=date(2026, 10, 4), amount=Decimal("300.00"), merchant="Big Store"),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, category_id=shopping.id,
                                     date=date(2026, 10, 6), amount=Decimal("45.00"), merchant="Corner Shop"),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id,
                                     date=date(2026, 10, 7), amount=Decimal("900.00"), merchant="AUTOMATIC PAYMENT - THANK YOU"),
    ])
    db.commit()
    return user


def test_month_section_replaces_the_budget_section(db_session, monkeypatch):
    _with_today(monkeypatch, TODAY)
    html, text = generate_daily_summary(db_session, _seed(db_session))
    assert "Spending this month (Oct 1–9)" in html
    assert "SPENDING THIS MONTH (OCT 1–9)" in text
    assert "Budget this month" not in html
    # The old Month-to-Date section counted only checking debits and
    # contradicted this section's total, so it was removed.
    assert "Month-to-Date" not in html
    assert "MONTH-TO-DATE" not in text


def test_month_section_totals_checking_and_card_spend_for_this_month_only(db_session, monkeypatch):
    _with_today(monkeypatch, TODAY)
    html, text = generate_daily_summary(db_session, _seed(db_session))
    # 120 checking + 300 + 45 card; last month's $75 and the card payoff excluded
    assert "Total spent: <b style='color:#111827'>$465.00</b>" in html
    assert "Total spent: $465.00" in text
    assert "Old Market" not in html
    assert "AUTOMATIC PAYMENT" not in html


def test_month_section_lists_categories_highest_first_and_top_merchants(db_session, monkeypatch):
    _with_today(monkeypatch, TODAY)
    html, text = generate_daily_summary(db_session, _seed(db_session))
    assert text.index("  Shopping: $345.00") < text.index("  Groceries: $120.00")
    assert "  Big Store: $300.00" in text
    assert "  Corner Shop: $45.00" in text
    assert "  Kroger: $120.00" in text


def test_month_section_title_is_a_single_date_on_the_first(db_session, monkeypatch):
    _with_today(monkeypatch, date(2026, 10, 1))
    html, _ = generate_daily_summary(db_session, _seed(db_session))
    assert "Spending this month (Oct 1)" in html
    assert "Oct 1–1" not in html


def test_month_section_empty_state(db_session, monkeypatch):
    _with_today(monkeypatch, date(2026, 11, 2))
    html, _ = generate_daily_summary(db_session, _seed(db_session))
    assert "No categorized spending this month" in html
    assert "No merchant activity this month" in html
