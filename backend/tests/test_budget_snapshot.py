from datetime import date
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.schemas import ForecastEntry
from backend.services.budget_snapshot import compute_budget_snapshot


def _seed_spreadsheet_scenario(db):
    """Reproduces Budget.xlsx exactly as of 2026-08-07: income, checking
    bills, credit-card-linked recurring subscriptions, budget allocations,
    and the real Chase Sapphire balance."""
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()

    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("10000.00"))
    # Dan's real spreadsheet cell for this scenario (2026-08-07): "2026
    # Overview"!B12 = -9273.76+10524.22+605.99 = 1856.45, i.e. the card term
    # both formulas consume is new-spending-since-statement, NOT the card's
    # full running balance. Modeled here with the three real columns rather
    # than by pre-baking 1856.45 into current_balance: the old fixture did
    # the latter with balance_due=0, which made the two candidate formulas
    # indistinguishable and hid a $9,236 live error in left_to_spend.
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25,
        current_balance=Decimal("10524.22"), balance_due=Decimal("9273.76"),
        pending_charges=Decimal("605.99"), next_payment_date=date(2026, 8, 25),
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
    """A one-day forecast bottoming out at `amount`, standing in for
    build_forecast() -- isolates this test from forecast_engine's own
    correctness, which has its own test coverage.

    Was a QuarterSummary list until 2026-08-14, when the lookahead minimum
    moved off build_quarters onto a rolling 3-month build_forecast window."""
    return [ForecastEntry(date=date(2026, 8, 20), projected_balance=Decimal(amount), transactions=[])]


def test_left_to_spend_and_safety_margin_match_spreadsheet_exactly(db_session):
    user, checking, card = _seed_spreadsheet_scenario(db_session)

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    # 1 cent above the spreadsheet's displayed $1,567.72 cell: expected. Excel
    # keeps full float precision through its intermediate math and only rounds
    # for display; our Decimal(14,2) columns round each input (Income ->
    # $13,732.30, HOA -> $58.33) to cents up front, and reconstructing from
    # already-rounded inputs lands one cent higher. Verified by hand -- do not
    # "fix" this back to 1567.72.
    assert snapshot.left_to_spend == Decimal("1567.73")
    # left_to_spend_weekly is no longer derived from left_to_spend -- it's
    # the transaction-driven weekly pacer now (see test_spendable_pacer.py).
    # Not asserted here; this test only covers the spreadsheet-verified
    # left_to_spend/safety_margin formulas.
    #
    # safety_margin's golden value changed 2026-08-13: Dan found this metric
    # (then called "Not Saving") double-counting new_spending_total (the
    # same shape of bug as the left_to_spend fix above, just on the other
    # formula) and rewrote '2026 Overview'!B18 to drop that term entirely --
    # see compute_budget_snapshot's safety_margin comment. This fixture's card
    # carries $1,856.45 of new_spending_total (see its docstring), so the
    # old golden value plus that same amount is the new one:
    # 2085.64 + 1856.45 = 3942.09. Structural check on the formula shape,
    # not yet re-verified against a live spreadsheet cell -- see
    # budget_snapshot.py's note that quarter_min itself still needs a fresh
    # reconciliation pass before this can be trusted to the cent.
    assert snapshot.safety_margin == Decimal("3942.09")
    assert snapshot.safety_margin_weekly == Decimal("1103.79")


def test_no_active_cards_gives_zero_card_balance(db_session):
    user = models.User(username="nocard", hashed_password="x", display_name="NoCard")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    db_session.add(checking)
    db_session.commit()

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("500.00")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    assert snapshot.cards == []
    # With zero income/bills/budgets seeded, leftover is 0, so left_to_spend
    # reduces to just +ChargedSoFar(0) -CardBalances(0) = 0.
    assert snapshot.left_to_spend == Decimal("0.00")


def test_pending_charges_move_left_to_spend_only(db_session):
    """A pending charge is money already spent, so it must reduce Left to
    Spend by exactly its amount -- that formula's new_spending_total term
    (current_balance - balance_due + pending_charges) sees it directly.

    Not Saving must NOT move: it stopped using new_spending_total entirely
    on 2026-08-13 (see compute_budget_snapshot's safety_margin comment), so a
    pending charge doesn't reach it at all until it actually posts and
    shows up inside quarter_min's own forecast walk. This inverts the test's
    original name and assertion (both moving together) -- that was itself
    the era of the safety_margin double-count Dan later caught.

    Left to Spend's reactivity was corrected 2026-08-12 against "2026
    Overview"!B17, whose card term is B12 = -balance_due + current_balance +
    pending_charges.

    current_balance is seeded equal to balance_due so the baseline delta is
    zero and the pending charge is the only thing moving -- an earlier
    version left current_balance at its 0 default while balance_due was
    1000, a state a real card cannot be in."""
    user = models.User(username="pendtest", hashed_password="x", display_name="PendTest")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("2000.00"))
    card = models.CreditCard(
        user_id=user.id, name="Test Card", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25, current_balance=Decimal("1000.00"),
        balance_due=Decimal("1000.00"), next_payment_date=date(2026, 8, 25),
    )
    db_session.add_all([checking, card])
    db_session.flush()
    # A modest recurring expense so there's a real (non-mocked) forecast to
    # walk -- this test deliberately does NOT mock build_forecast, unlike
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

    assert with_pending.left_to_spend == baseline.left_to_spend - Decimal("500.00"), "Left to Spend must drop by exactly the pending amount"
    assert with_pending.safety_margin == baseline.safety_margin, "Not Saving must NOT react to pending_charges -- it no longer uses new_spending_total at all"


def test_left_to_spend_ignores_already_statemented_balance(db_session):
    """Reproduces the live 2026-08-12 error directly: Left to Spend must not
    be reduced by a card's balance_due.

    That amount is the last statement's total. It is already a budgeted
    payment -- it sits in the Credit Card Bills list and the forecast injects
    it on the card's due date -- so subtracting it from this month's spending
    room charges Dan for it twice. Live symptom: the app reported
    -$8,290.67 while Budget.xlsx reported +$945.85, a gap of $9,236 against
    $9,560.91 of combined balance_due.

    Two cards with identical NEW spending but wildly different statemented
    balances must therefore produce the same Left to Spend."""
    def _seed(username: str, balance_due: str, current_balance: str):
        user = models.User(username=username, hashed_password="x", display_name=username)
        db_session.add(user)
        db_session.flush()
        checking = models.Account(
            user_id=user.id, name="Checking", type=models.AccountType.checking,
            current_balance=Decimal("10000.00"),
        )
        card = models.CreditCard(
            user_id=user.id, name="Card", credit_limit=Decimal("29000.00"),
            statement_day=28, due_day=25,
            current_balance=Decimal(current_balance), balance_due=Decimal(balance_due),
            next_payment_date=date(2026, 8, 25),
        )
        db_session.add_all([checking, card])
        db_session.commit()
        return user, checking

    # Both carry exactly $500 of new, un-statemented spending.
    fresh_user, fresh_checking = _seed("freshstmt", "0.00", "500.00")
    heavy_user, heavy_checking = _seed("heavystmt", "9273.76", "9773.76")

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5000.00")):
        fresh = compute_budget_snapshot(db_session, fresh_user, fresh_checking.id, as_of=date(2026, 8, 12))
        heavy = compute_budget_snapshot(db_session, heavy_user, heavy_checking.id, as_of=date(2026, 8, 12))

    assert heavy.left_to_spend == fresh.left_to_spend, (
        "a large statemented balance_due must not reduce Left to Spend -- "
        "it is an already-budgeted payment, not new spending"
    )
    assert heavy.left_to_spend == Decimal("-500.00"), (
        "with no income or bills seeded, leftover is 0, so Left to Spend is "
        "just -new_spending_total"
    )


def test_safety_margin_does_not_double_count_the_cc_payoff(db_session):
    """Reproduces a live bug (2026-08-08, corrected 2026-08-09 after reading
    Dan's real spreadsheet): quarter_min's forecast already models paying
    off each card's last-statement balance (balance_due) on its due date --
    confirmed against Dan's own "2026 Forecast" sheet, which hand-models the
    identical payoff event inline. safety_margin must NOT subtract that same
    balance_due amount again; it subtracts only new spending accumulated
    since the statement closed (current_balance - balance_due +
    pending_charges). When current_balance == balance_due (no new spending
    since the statement), that delta is zero, so the payoff already inside
    quarter_min is the only place it gets counted -- safety_margin should land
    near the un-paid-off balance, not deeply negative.

    (An earlier version of this fix instead excluded the payoff from
    quarter_min entirely, on the theory that keeping it there was the double-
    count. That was wrong -- the double-count came from subtracting the full
    current_balance downstream, not from quarter_min including the payoff.
    Confirmed by reading Budget.xlsx directly.)"""
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
        balance_due=Decimal("3000.00"),  # no new spending since the statement -- delta is 0
        next_payment_date=date(2026, 8, 25),
    )
    db_session.add_all([checking, card])
    db_session.commit()

    snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 8))

    # quarter_min already reflects the ~$3,000 payoff (checking dips to
    # ~$2,000 on the due date). new_spending_total is 0 (current_balance ==
    # balance_due), so safety_margin should land near that ~$2,000 floor, not
    # near -$1,000 (which is what a second full-balance subtraction would
    # produce).
    assert snapshot.safety_margin > Decimal("0")


def test_weekly_figures_are_the_monthly_ones_prorated(db_session):
    """Both weekly numbers must be their own monthly value scaled by the share
    of the month remaining -- the method Dan's spreadsheet uses.

    Verified against the sheet 2026-08-16 with 2.2857 weeks left (share
    0.4375): Left to Spend -385.84 -> -168.80 and Safety Margin 2698.00 ->
    1180.38, both to the cent. Note the invariant is on MAGNITUDE, not order:
    with a negative pool the weekly figure is numerically larger than the
    monthly one, which is correct and is why an earlier `week <= month`
    assertion was wrong.
    """
    user, checking, card = _seed_spreadsheet_scenario(db_session)

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    # Aug 7: 25 days remain -> 25/7 weeks, so one week is 7/25 of the month.
    share = Decimal("7") / Decimal("25")
    assert snapshot.left_to_spend_weekly == (snapshot.left_to_spend * share).quantize(Decimal("0.01"))
    assert snapshot.safety_margin_weekly == (snapshot.safety_margin * share).quantize(Decimal("0.01"))
    assert abs(snapshot.left_to_spend_weekly) <= abs(snapshot.left_to_spend)


def test_weekly_proration_matches_dans_spreadsheet_to_the_cent():
    """The two ratios the sheet showed on 2026-08-16, checked directly."""
    from backend.services.budget_snapshot import _weekly_allowance

    as_of = date(2026, 8, 16)  # 16 days remain -> 2.2857 weeks -> share 0.4375
    assert _weekly_allowance(Decimal("-385.84"), as_of)[0] == Decimal("-168.80")
    assert _weekly_allowance(Decimal("2698.00"), as_of)[0] == Decimal("1180.38")
