from datetime import date
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.schemas import QuarterSummary, ForecastEntry
from backend.services.budget_snapshot import compute_budget_snapshot


def _seed_spreadsheet_scenario(db):
    """Reproduces Budget.xlsx exactly as of 2026-08-07: income, checking
    bills, credit-card-linked recurring subscriptions, budget allocations,
    and the real Chase Sapphire balance."""
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()

    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("10000.00"))
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, current_balance=Decimal("1856.45"),
        # Before bank sync existed, Dan kept balance_due in step with
        # current_balance by hand -- this golden scenario predates the split
        # documented in compute_budget_snapshot, so the two match here.
        balance_due=Decimal("1856.45"),
    )
    db.add_all([checking, card])
    db.flush()

    income_cat = models.Category(user_id=user.id, name="Income", type=models.CategoryType.income)
    savings_cat = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    groceries_cat = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db.add_all([income_cat, savings_cat, groceries_cat])
    db.flush()

    db.add_all([
        models.BudgetAllocation(user_id=user.id, category_id=savings_cat.id, year=2026, month=0, budgeted_amount=Decimal("1000.00")),
        models.BudgetAllocation(user_id=user.id, category_id=groceries_cat.id, year=2026, month=0, budgeted_amount=Decimal("700.00")),
    ])

    # Income: Budget!B7 = 13732.295 (two paychecks + bonus/12; simplified to
    # one recurring item of the same total for this test -- the formula only
    # needs the monthly total, not the paycheck split).
    db.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Income", amount=Decimal("13732.295"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))

    # Checking Bills (Budget!B10:B18, total F1 = 6129.553333) + Tithing
    # (Budget!F4 = 1300, modeled as a checking recurring item like the real app).
    checking_bills = [
        ("Chevy Insurance", "194.00", 2), ("Duke (Electric)", "180.00", 8),
        ("Rivian R1T", "500.89", 17), ("Phone", "136.74", 18),
        ("Mortgage", "4404.65", 23), ("Stormwater", "4.94", 1),
        ("HOA Fees", "58.33333333", 1), ("Rivian R2", "500.00", 1),
        ("House Cleaning", "150.00", 1), ("Tithing", "1300.00", 15),
    ]
    for name, amount, day in checking_bills:
        db.add(models.RecurringItem(
            user_id=user.id, account_id=checking.id, name=name, amount=Decimal(amount),
            type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
            day_of_month=day, start_date=date(2026, 1, 1),
        ))

    # Credit Card Bills (Budget!B22:C41, total F2 = 1454.24) -- recurring
    # subscriptions charged to the card, not checking (card_id set).
    card_bills = [
        ("Peloton", "25.68", 2), ("Vitamins", "200.00", 5), ("Home Internet", "49.99", 6),
        ("Ozwell", "149.99", 8), ("Stormwater CC", "20.00", 11), ("Areli Apple Music", "10.99", 12),
        ("Greenix", "84.00", 12), ("Canopy", "13.00", 15), ("HBO", "18.49", 15),
        ("Citizens Energy", "200.00", 17), ("Spotify", "10.99", 18), ("Vet", "99.90", 18),
        ("Skin Twins", "160.00", 20), ("Trash (WM)", "15.00", 21), ("Quip", "12.84", 23),
        ("Oura Ring", "5.99", 25), ("Hulu", "5.00", 28), ("Netflix", "19.99", 29),
        ("Apple", "57.39", 30), ("Grass Cutting", "295.00", 30),
    ]
    for name, amount, day in card_bills:
        db.add(models.RecurringItem(
            user_id=user.id, account_id=checking.id, card_id=card.id, name=name, amount=Decimal(amount),
            type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
            day_of_month=day, start_date=date(2026, 1, 1),
        ))

    db.commit()
    return user, checking, card


def _fake_quarter_min(amount: str):
    """Returns a QuarterSummary list with one quarter whose days bottom out
    at `amount`, standing in for build_quarters() -- isolates this test from
    forecast_engine's own correctness, which has its own test coverage."""
    return [QuarterSummary(
        quarter=3, year=2026,
        open_balance=Decimal(amount), close_balance=Decimal(amount),
        total_income=Decimal("0"), total_expenses=Decimal("0"), net=Decimal("0"),
        days=[ForecastEntry(date=date(2026, 8, 20), projected_balance=Decimal(amount), transactions=[])],
    )]


def test_left_to_spend_and_not_saving_match_spreadsheet_exactly(db_session):
    user, checking, card = _seed_spreadsheet_scenario(db_session)

    with patch("backend.services.budget_snapshot.build_quarters", return_value=_fake_quarter_min("5120.66")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    # 1 cent above the spreadsheet's displayed $1,567.72 cell: expected. Excel
    # keeps full float precision through its intermediate math and only rounds
    # for display; our Decimal(14,2) columns round each input (Income ->
    # $13,732.30, HOA -> $58.33) to cents up front, and reconstructing from
    # already-rounded inputs lands one cent higher. Verified by hand -- do not
    # "fix" this back to 1567.72.
    assert snapshot.left_to_spend == Decimal("1567.73")
    assert snapshot.left_to_spend_weekly == Decimal("438.96")
    assert snapshot.not_saving == Decimal("2085.64")
    assert snapshot.not_saving_weekly == Decimal("583.98")


def test_weekly_allowance_uses_full_amount_in_final_week_of_month(db_session):
    user, checking, card = _seed_spreadsheet_scenario(db_session)

    with patch("backend.services.budget_snapshot.build_quarters", return_value=_fake_quarter_min("5120.66")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 28))

    # 4 days remain (28,29,30,31) <= 7, so the weekly figure equals the full
    # left-to-spend amount rather than being divided further.
    assert snapshot.left_to_spend_weekly == snapshot.left_to_spend


def test_no_active_cards_gives_zero_card_balance(db_session):
    user = models.User(username="nocard", hashed_password="x", display_name="NoCard")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    db_session.add(checking)
    db_session.commit()

    with patch("backend.services.budget_snapshot.build_quarters", return_value=_fake_quarter_min("500.00")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    assert snapshot.cards == []
    # With zero income/bills/budgets seeded, leftover is 0, so left_to_spend
    # reduces to just +ChargedSoFar(0) -CardBalances(0) = 0.
    assert snapshot.left_to_spend == Decimal("0.00")


def test_not_saving_reacts_to_pending_charges_but_left_to_spend_does_not(db_session):
    """Not Saving includes pending_charges via its explicit balance_due_total
    term (balance_due + pending_charges per card) -- so entering a pending
    charge should move Not Saving but never Left to Spend (which uses
    current_balance, not balance_due/pending_charges, and never touches the
    forecast). This is intentional: it matches the user's stated reason for
    wanting pending_charges in the first place. Do not "fix" this to isolate
    Not Saving from it.

    Previously this flowed transitively through quarter_min (the forecast's
    own CC-payment injection folded pending_charges in) -- that path also
    double-counted the payoff itself (see
    test_not_saving_does_not_double_count_the_cc_payoff) and was replaced
    2026-08-08 with this explicit term. The user-visible reactivity is the
    same; the mechanism is no longer entangled with the forecast."""
    user = models.User(username="pendtest", hashed_password="x", display_name="PendTest")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("2000.00"))
    card = models.CreditCard(
        user_id=user.id, name="Test Card", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("1000.00"),
        next_payment_date=date(2026, 8, 25),
    )
    db_session.add_all([checking, card])
    db_session.flush()
    # A modest recurring expense so there's a real (non-mocked) forecast to
    # walk -- this test deliberately does NOT mock build_quarters, unlike
    # the golden-value test, because the whole point is to exercise the
    # real forecast path where pending_charges actually lives.
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Rent", amount=Decimal("500.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    baseline = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    card.pending_charges = Decimal("500.00")
    db_session.commit()

    with_pending = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    assert with_pending.left_to_spend == baseline.left_to_spend, "Left to Spend must never react to pending_charges"
    assert with_pending.not_saving == baseline.not_saving - Decimal("500.00"), "Not Saving must react by exactly the pending amount (it dropped, since it's a payment)"


def test_not_saving_does_not_double_count_the_cc_payoff(db_session):
    """Reproduces a live bug (2026-08-08): the quarter's minimum projected
    day landed exactly on the credit card's due date, which the forecast
    engine already models as a full payoff withdrawal from checking. Since
    not_saving separately subtracts the card balance as its own term,
    quarter_min must be computed WITHOUT that payoff already baked in, or
    the same payoff gets subtracted twice.

    Unlike test_left_to_spend_and_not_saving_match_spreadsheet_exactly (which
    mocks build_quarters entirely, bypassing this interaction), this test
    exercises the real forecast engine so the double-count is actually
    reachable."""
    user = models.User(username="dan2", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.flush()

    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("10000.00"),
        statement_day=25, due_day=25, current_balance=Decimal("3000.00"),
        balance_due=Decimal("3000.00"),
        next_payment_date=date(2026, 8, 25),
    )
    db_session.add_all([checking, card])
    db_session.commit()

    snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 8))

    # The forecast's own minimum day (the payoff date) drops to ~$2,000
    # (5000 - 3000 payoff). If not_saving's quarter_min already reflects
    # that payoff, subtracting card_balances (3000) again would land
    # around 2000 - 3000 = -1000. Without the double-count, quarter_min
    # should stay near the un-paid-off balance (~5000), so not_saving
    # lands near 5000 - 3000 = 2000, not deeply negative.
    assert snapshot.not_saving > Decimal("0")
