from datetime import date
from decimal import Decimal
from backend.services.spendable_pacer import week_bounds, weeks_remaining_in_month


def test_week_bounds_for_a_midweek_date():
    # Aug 7 2026 is a Friday; the Sun-Sat week containing it is Aug 2-8.
    assert week_bounds(date(2026, 8, 7)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_sunday_itself():
    assert week_bounds(date(2026, 8, 2)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_saturday_itself():
    assert week_bounds(date(2026, 8, 8)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_weeks_remaining_in_month_on_the_first_of_a_28_day_month():
    # Feb 2026 has 28 days (not a leap year) -- exactly 4 weeks remain on day 1.
    assert weeks_remaining_in_month(date(2026, 2, 1)) == Decimal("4")


def test_weeks_remaining_in_month_on_the_last_day():
    # 1 day remaining -> 1/7 of a week, never zero (avoids downstream division by zero).
    assert weeks_remaining_in_month(date(2026, 2, 28)) == Decimal("1") / Decimal("7")


def test_weeks_remaining_in_month_mid_month():
    # Feb 8 2026: days_remaining = 28 - 8 + 1 = 21 -> 21/7 = 3 exactly.
    assert weeks_remaining_in_month(date(2026, 2, 8)) == Decimal("3")


from backend import models
from backend.services.spendable_pacer import discretionary_spend_in_range


def _make_user_and_checking(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db.add(checking)
    db.flush()
    return user, checking


def test_counts_a_plain_discretionary_checking_transaction(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-45.00"), description="Coffee shop", is_actual=True,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("45.00")


def test_excludes_a_recurring_linked_checking_transaction(db_session):
    """A bill payment (e.g. mortgage debit) is already counted in `leftover`
    up front -- counting it again here would double-dip."""
    user, checking = _make_user_and_checking(db_session)
    recurring = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Mortgage", amount=Decimal("2000.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1),
    )
    db_session.add(recurring)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-2000.00"), description="Mortgage Co", is_actual=True,
        recurring_item_id=recurring.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_savings_category_checking_transaction(db_session):
    user, checking = _make_user_and_checking(db_session)
    savings_cat = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    db_session.add(savings_cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-500.00"), description="To savings", is_actual=True,
        category_id=savings_cat.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_verified_planned_transfer_transaction(db_session):
    """A PlannedTransfer's verified_transaction_id points at the real
    transaction that fulfilled it -- a savings movement, not spending, even
    if it landed in an uncategorized or non-savings-tagged row."""
    user, checking = _make_user_and_checking(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add(savings)
    db_session.flush()
    txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-1000.00"), description="Transfer to savings", is_actual=True,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=checking.id, to_account_id=savings.id,
        amount=Decimal("1000.00"), target_date=date(2026, 8, 3),
        status=models.PlannedTransferStatus.verified, verified_transaction_id=txn.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_checking_refund_nets_against_the_matching_debit(db_session):
    """Regression: a checking refund (positive amount) used to be dropped
    entirely by the amount < 0 filter instead of netting against the debit
    it reverses."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 8, 3), amount=Decimal("-50.00"), description="Home Depot", is_actual=True),
        models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 8, 5), amount=Decimal("50.00"), description="Home Depot", is_actual=True),
    ])
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_checking_refund_never_nets_against_unrelated_income(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 8, 3), amount=Decimal("-50.00"), description="Home Depot", is_actual=True),
        models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 8, 4), amount=Decimal("1000.00"), description="Zelle from Elaine Ford", is_actual=True),
    ])
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("50.00")


def test_card_refund_nets_against_the_matching_charge(db_session):
    """Regression (real-world pattern: Ozwell $25 charge + $25 refund used
    to show as $25 of spend with the refund silently dropped, or worse, as
    $50 if the refund happened to be miscategorized as another charge)."""
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"), statement_day=28, due_day=15)
    db_session.add(card)
    db_session.flush()
    db_session.add_all([
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 3), amount=Decimal("25.00"), merchant="OZWELL, LLC"),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 4), amount=Decimal("-25.00"), merchant="OZWELL, LLC"),
    ])
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_card_net_refund_period_reduces_discretionary_spend_below_zero(db_session):
    """A week where refunds exceed charges should show as NEGATIVE
    discretionary spend (real extra spendable money), not floor at zero."""
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"), statement_day=28, due_day=15)
    db_session.add(card)
    db_session.flush()
    db_session.add_all([
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 3), amount=Decimal("30.00"), merchant="Store"),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 4), amount=Decimal("-100.00"), merchant="Store"),
    ])
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("-70.00")


def test_excludes_a_credit_card_autopay_debit(db_session):
    """Regression (real data, July 2026): a $11,312.54 checking debit reading
    'CHASE CREDIT CRD AUTOPAY' is a credit-card PAYMENT, not spending -- the
    charges it settles were already counted on the card side. It carries no
    category and no recurring_item_id, so neither pre-existing exclusion
    caught it, and it alone drove Spendable this week to -$40,004.84."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Chase Sapphire", last_four="1312",
        credit_limit=Decimal("20000.00"), statement_day=28, due_day=15,
    ))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-11312.54"), is_actual=True,
        description="CHASE CREDIT CRD AUTOPAY                    PPD ID: 4760039224",
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_card_autopay_matched_by_the_cards_name_token(db_session):
    """The second real pattern: 'APPLECARD GSBANK PAYMENT' matches the
    'Apple Card' row on its first name token, with no last_four to fall back
    on (that card's last_four is blank in real data)."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Apple Card", last_four="",
        credit_limit=Decimal("5000.00"), statement_day=28, due_day=15,
    ))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-210.15"), is_actual=True,
        description="APPLECARD GSBANK PAYMENT    16069006        WEB ID: 9999999999",
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_an_inactive_cards_autopay_is_still_only_matched_against_active_cards(db_session):
    """Guard on the exclusion's scope: only ACTIVE cards are consulted, so a
    retired card's name can't quietly suppress real spending forever."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Zephyr Rewards", credit_limit=Decimal("1000.00"),
        statement_day=28, due_day=15, is_active=False,
    ))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-60.00"), description="ZEPHYR COFFEE ROASTERS", is_actual=True,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("60.00")


def test_excludes_an_internal_online_transfer(db_session):
    """Regression (real data, July 2026): 'Online Transfer to CHK ...0054'
    moves $1,000 between the household's own accounts. Nothing was spent, but
    with no category and no recurring link it counted as discretionary spend."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-1000.00"), is_actual=True,
        description="Online Transfer to CHK ...0054 transaction#: 30221323328 07/31",
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_transfer_heuristic_matches_the_documented_wordings(db_session):
    user, checking = _make_user_and_checking(db_session)
    for i, desc in enumerate([
        "Online Transfer to SAV ...8452 transaction#: 24419258103",
        "TRANSFER TO SAVINGS ACCOUNT",
        "Transfer from Checking ...0054",
    ]):
        db_session.add(models.Transaction(
            user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
            amount=Decimal("-100.00"), description=desc, is_actual=True,
        ))
    db_session.add(models.Transaction(  # control: a real purchase still counts
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-25.00"), description="Bookstore", is_actual=True,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("25.00")


def test_counts_a_groceries_category_checking_transaction(db_session):
    """Groceries spend is ordinary discretionary spend and must count.

    It used to be excluded because budget_snapshot removed the Groceries
    BUDGET from the pool up front, so counting the spend as well deducted the
    same money twice. That pre-removal was wrong -- groceries is a budget
    line, not a committed bill -- and was dropped on 2026-08-16 to match Dan's
    spreadsheet. With the budget no longer pre-removed, the spend has to land
    here instead."""
    user, checking = _make_user_and_checking(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-150.00"), description="Kroger", is_actual=True,
        category_id=groceries.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("150.00")


def test_excludes_an_expense_typed_savings_category_transaction(db_session):
    """The real 'Savings' category is typed `expense`, not `savings` -- zero
    CategoryType.savings categories exist in the production data -- so it must
    be excluded by NAME, matching what budget_snapshot.py hardcodes."""
    user, checking = _make_user_and_checking(db_session)
    savings = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.expense)
    db_session.add(savings)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-500.00"), description="Move to savings", is_actual=True,
        category_id=savings.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_a_similarly_named_category_is_not_excluded(db_session):
    """Exclusion is exact and case-sensitive, matching budget_snapshot.py's
    hardcoded "Savings"/"Groceries" -- 'Grocery Delivery' is ordinary spend."""
    user, checking = _make_user_and_checking(db_session)
    cat = models.Category(user_id=user.id, name="Grocery Delivery", type=models.CategoryType.expense)
    db_session.add(cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-40.00"), description="Instacart", is_actual=True,
        category_id=cat.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("40.00")


def test_counts_a_groceries_category_card_transaction(db_session):
    """Card grocery spend counts too, and it is the big half: real card
    grocery spend was $1,626.13 in July 2026 alone.

    Excluded until 2026-08-16 because the Groceries budget was removed from
    the pool up front; that pre-removal is gone (see budget_snapshot's
    leftover), so this spend must land in the total like any other."""
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add_all([card, groceries])
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("1626.13"), merchant="Kroger", category_id=groceries.id,
    ))
    db_session.add(models.CreditCardTransaction(  # control: uncategorized charge still counts
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("42.00"), merchant="Hardware Store",
    ))
    db_session.commit()

    # 1626.13 groceries + 42.00 control -- groceries no longer sits outside the total.
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("1668.13")


def test_counts_a_plain_card_charge(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("80.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("80.00")


def test_excludes_a_card_linked_recurring_subscription_from_card_spend(db_session):
    """A subscription billed to a card (RecurringItem.card_id set) is
    already counted in `leftover` via _cc_budget_total -- deduct it from
    the card total for the range it fires in, the same day-of-month
    'firing' logic budget_snapshot.py's _charged_so_far already uses
    (not per-transaction fuzzy matching)."""
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Streaming", amount=Decimal("15.99"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1), card_id=card.id,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("80.00"), merchant="Grocery Store",
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("15.99"), merchant="Streaming Co",
    ))
    db_session.commit()

    # Total card charges in range = 95.99; the subscription's 15.99 is
    # deducted (it fires day_of_month=3, inside [Aug 1, Aug 7]) -> 80.00.
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("80.00")


def test_recurring_card_charge_firing_across_a_month_boundary(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    # Fires on the 2nd of every month -- Sep 2 falls inside a week that
    # starts Aug 30 (Sunday) and ends Sep 5 (Saturday).
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Streaming", amount=Decimal("15.99"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=2, start_date=date(2026, 1, 1), card_id=card.id,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 9, 2),
        amount=Decimal("100.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    # 100.00 total in range, 15.99 subscription deducted (fires Sep 2, inside range).
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 30), date(2026, 9, 5)) == Decimal("84.01")


from backend.services.spendable_pacer import compute_weekly_spendable


def test_this_week_target_splits_the_pool_evenly_with_no_spend_yet(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.commit()

    # Feb 1 2026 is a Sunday, Feb has 28 days -> exactly 4 whole weeks.
    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 1))

    assert result.spendable_this_week == Decimal("625.00")  # 2500 / 4
    assert result.days_left_in_week == 7
    assert result.spendable_today == Decimal("89.29")  # 625 / 7, quantized
    assert result.on_pace is True


def test_overspending_shrinks_a_later_weeks_target(db_session):
    """Rollover: $700 spent in week 1 (target was $625, so $75 over) eats
    into every remaining week, not just week 1."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 3),
        amount=Decimal("-700.00"), description="Big week", is_actual=True,
    ))
    db_session.commit()

    # Feb 8 2026 is the Sunday starting week 2. 3 whole weeks remain (21/7).
    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 8))

    # remaining_pool = 2500 - 700 = 1800; 1800 / 3 weeks = 600 (vs the
    # original 625/week even pace -- the $75 overspend split across 3
    # remaining weeks is exactly the $25/week shortfall: 625 - 25 = 600).
    assert result.spendable_this_week == Decimal("600.00")
    assert result.on_pace is True


def test_prior_week_and_this_weeks_spend_are_not_double_counted(db_session):
    """Regression: the pool must be depleted by spend from BEFORE this
    week only. Depleting it by full month-to-date (which always includes
    this week's own spend) and then ALSO subtracting this week's spend
    from the per-week target double-counts every dollar spent so far this
    week."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(  # week 1 spend
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 3),
        amount=Decimal("-700.00"), description="Week 1", is_actual=True,
    ))
    db_session.add(models.Transaction(  # week 2 spend, on the day being evaluated
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 8),
        amount=Decimal("-50.00"), description="Week 2 so far", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 8))

    # this_week_target = (2500 - 700) / 3 weeks = 600 (week 1's spend only,
    # matching test_overspending_shrinks_a_later_weeks_target above);
    # spendable_this_week = 600 - 50 (week 2's own spend, subtracted once) = 550.
    # A double-counting bug would instead deplete the pool by 750 (700+50)
    # before dividing AND subtract the 50 again, landing on 533.33.
    assert result.spendable_this_week == Decimal("550.00")


def test_this_weeks_spend_reduces_spendable_this_week(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 1),
        amount=Decimal("-900.00"), description="Overspend", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 1))

    # this_week_target = 2500/4 = 625; spend_this_week (Feb1-Feb1) = 900.
    assert result.spendable_this_week == Decimal("-275.00")
    assert result.on_pace is False


def test_this_weeks_spend_is_clipped_to_the_current_month(db_session):
    """A calendar week can start in the previous month -- Aug 1 2026 is a
    Saturday, so its Sun-Sat week runs Jul 26 - Aug 1. Spend from before
    the month started must not count against THIS week's target, even
    though it falls inside the raw Sun-Sat window."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 7, 31),
        amount=Decimal("-5000.00"), description="July spending", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 8, 1))

    # spend_this_week must be 0 -- July's $5000 sits outside the clipped
    # [Aug 1, Aug 1] window -- so spendable_this_week is the full target,
    # completely unaffected by July's spend. That is what this test asserts.
    #
    # The target itself is prorated by this stub week's one-day length:
    #   this_week_share = 1/7, weeks_left = 31/7
    #   target = 2500 * ((1/7) / (31/7)) = 2500 / 31 = 80.65
    # This expected literal was previously 564.52 (= 2500 / (31/7)), which
    # handed this single-day stub week a FULL week's dollars -- the exact
    # day-one spike Important 4 fixes. The change here is a mechanical
    # consequence of the prorated formula, not a change to what this test
    # is checking (July spend staying out of August's window).
    expected_target = (Decimal("2500.00") / Decimal("31")).quantize(Decimal("0.01"))
    assert expected_target == Decimal("80.65")
    assert result.spendable_this_week == expected_target


def test_trailing_partial_week_never_exceeds_the_remaining_pool(db_session):
    """Regression (Critical 3): in the month's trailing partial week
    weeks_left < 1, so `remaining_pool / weeks_left` INFLATES the target
    above the entire remaining pool. Nov 30 2026 is a Monday, so the final
    stretch is Nov 29-30: weeks_left = 2/7, and the unclamped formula would
    hand out 200 / (2/7) = $700 -- 3.5x the $200 actually left for the month.

    This replaces the clamp assertion carried by the deleted
    test_weekly_allowance_uses_full_amount_in_final_week_of_month.
    """
    user, checking = _make_user_and_checking(db_session)
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("200.00"), date(2026, 11, 29))

    remaining_pool = Decimal("200.00")  # no prior-week spend, so pool == leftover
    assert result.spendable_this_week == Decimal("200.00")  # exactly the pool, NOT 700.00
    assert result.spendable_this_week <= remaining_pool

    # The week runs Nov 29 (Sun) - Dec 5 (Sat), but only Nov 29-30 fall in
    # November, and spendable_this_week only covers those 2 days. The daily
    # pace must divide by the same 2, not by the raw 7 -- dividing $200 across
    # 7 days reported $28.57/day when the real answer is $100/day.
    assert result.days_left_in_week == 2
    assert result.spendable_today == Decimal("100.00")  # 200 / 2, NOT 200 / 7 = 28.57


def test_trailing_partial_week_with_a_negative_pool_is_not_inflated(db_session):
    """Regression: the old `min(target, remaining_pool)` clamp was sign-naive.
    For a NEGATIVE pool min() picks the MORE negative branch, so instead of
    bounding the deficit it inflated it -- on real July 31 2026 data it showed
    -$24,645.69 against a true -$21,245.04.

    Nov 29 2026 (Sunday) opens the month's final 2-day stretch (Nov 30 is a
    Monday), so weeks_left = 2/7 and this week's clipped days = 2 -> ratio 1.
    Pool = 300 - 1000 = -700, so the target is exactly the pool: -700.00.
    The old clamp gave -700 / (2/7) = -2450.00, a 3.5x overstated deficit.
    """
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(  # prior-week spend that overdraws the pool
        user_id=user.id, account_id=checking.id, date=date(2026, 11, 10),
        amount=Decimal("-1000.00"), description="Big earlier week", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("300.00"), date(2026, 11, 29))

    remaining_pool = Decimal("-700.00")  # 300 leftover - 1000 spent before this week
    assert result.spendable_this_week == Decimal("-700.00")  # exactly the pool, NOT -2450.00
    assert result.spendable_this_week >= remaining_pool  # deficit bounded, not amplified
    assert result.on_pace is False


def test_mid_month_negative_pool_is_amortized_across_remaining_weeks(db_session):
    """Regression: a mid-month deficit must be spread proportionally over the
    weeks left, not charged in full to every one of them. The old clamp had
    exactly that effect for negative pools, with zero test coverage.

    Aug 9 2026 is a Sunday. weeks_left = 23/7 (Aug 9..Aug 31), this week is a
    full 7 days, so the ratio is 7/23 and the target is -500 * 7/23 = -152.17.
    Under the old clamp this was min(-152.17, -500) = -500.00 -- the entire
    month's deficit charged to this single week.
    """
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 5),
        amount=Decimal("-1000.00"), description="Prior week overspend", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("500.00"), date(2026, 8, 9))

    # remaining_pool = 500 - 1000 = -500
    assert result.spendable_this_week == Decimal("-152.17")
    assert result.spendable_this_week > Decimal("-500.00")  # amortized, not full-charged
    assert result.on_pace is False


def test_leading_stub_week_is_not_given_a_full_weeks_allocation(db_session):
    """Regression (Important 4): Aug 2026 starts on a Saturday, so its first
    "week" is the single day Aug 1. Treating that stub as a full week spiked
    spendable_today to $564.52 on day one and cliffed to ~$83/day the next
    morning -- a 6.8x day-one spike. Prorated, the stub's per-DAY rate lines
    up with the following full week's instead.
    """
    user, checking = _make_user_and_checking(db_session)
    db_session.commit()

    stub = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 8, 1))
    next_week = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 8, 2))

    # Stub week: 1 day, share = 1/7, weeks_left = 31/7 -> 2500/31 = 80.65,
    # spread over its 1 remaining day.
    assert stub.days_left_in_week == 1
    assert stub.spendable_this_week == Decimal("80.65")
    assert stub.spendable_today == Decimal("80.65")

    # Following full week: 7 days, share = 1, weeks_left = 30/7 -> 583.33
    # over 7 days = 83.33/day.
    assert next_week.days_left_in_week == 7
    assert next_week.spendable_this_week == Decimal("583.33")
    assert next_week.spendable_today == Decimal("83.33")

    # The point of the fix: day one is NOT inflated relative to the next
    # week's daily rate. (Pre-fix it was 564.52 vs 83.33 -- 6.8x.)
    assert stub.spendable_today <= next_week.spendable_today


def test_spendable_this_week_is_stable_across_the_same_week(db_session):
    """Regression: this_week_target must not drift day-to-day within the
    same calendar week just because as_of advances -- only actual spend
    (or a new week starting) should change it."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 3),
        amount=Decimal("-700.00"), description="Week 1", is_actual=True,
    ))
    db_session.commit()

    sunday_result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 8))
    wednesday_result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 11))
    saturday_result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 14))

    assert sunday_result.spendable_this_week == Decimal("600.00")
    assert wednesday_result.spendable_this_week == Decimal("600.00")
    assert saturday_result.spendable_this_week == Decimal("600.00")


def test_week_never_exceeds_the_month_it_belongs_to(db_session):
    """The weekly figure is a share of the month's remaining pool, so it can
    never be larger than that pool.

    Regression: the dashboard paired the pacer's weekly value with the legacy
    balance-derived `left_to_spend`, which is a different calculation on a
    different basis. On Dan's real data that read "$696.65 spendable this
    week" above "$448.25 this month" -- a week bigger than its own month.
    """
    from backend.services.spendable_pacer import compute_weekly_spendable

    user, _checking = _make_user_and_checking(db_session)
    db_session.commit()
    leftover = Decimal("3316.84")
    # Walk a whole month so leading stubs, full weeks, and the trailing
    # partial week are all covered, not just today's position.
    for day in range(1, 32):
        as_of = date(2026, 8, day)
        result = compute_weekly_spendable(db_session, user.id, leftover, as_of)
        assert result.spendable_this_week <= result.remaining_this_month, (
            f"{as_of}: week {result.spendable_this_week} > month {result.remaining_this_month}"
        )
        assert result.remaining_this_month <= leftover
