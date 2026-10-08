from datetime import date, timedelta
from decimal import Decimal
import pytest
from backend import models
from backend.services import scenario_service
from backend.services.budget_snapshot import floor_mask
from backend.services.forecast_engine import build_forecast, _card_payoff_date_for_charge
from backend.services.wish_lifecycle import WishError, ensure_wish_items, commit_wish, uncommit_wish
from backend.services.wish_math import add_months
from backend.services.wish_plan import build_plan, _series, low_point


def _seed(db):
    u = models.User(username="life", hashed_password="x", display_name="L"); db.add(u); db.flush()
    acct = models.Account(user_id=u.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("10000.00")); db.add(acct); db.flush()
    card = models.CreditCard(user_id=u.id, name="Card", credit_limit=Decimal("9000"), statement_day=28,
                             due_day=25, current_balance=Decimal("0")); db.add(card); db.flush()
    return u, acct, card


def _wish(db, u, price, method, **kw):
    sc = models.ForecastScenario(user_id=u.id, name="Laptop"); db.add(sc); db.flush()
    it = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal(price)); db.add(it); db.flush()
    op = models.WishOption(user_id=u.id, wish_item_id=it.id, label="opt", method=method,
                           card_id=kw.get("card_id"), months=kw.get("months"),
                           apr=None if kw.get("apr") is None else Decimal(kw["apr"]),
                           down_payment=Decimal(kw.get("down", "0"))); db.add(op); db.flush()
    it.plan_option_id = op.id
    db.commit()
    return it


def test_ensure_creates_rows_for_existing_scenarios_once(db_session):
    u, _, _ = _seed(db_session)
    db_session.add_all([models.ForecastScenario(user_id=u.id, name="Old A"),
                        models.ForecastScenario(user_id=u.id, name="Old B")]); db_session.commit()
    ensure_wish_items(db_session, u.id); ensure_wish_items(db_session, u.id)
    rows = db_session.query(models.WishItem).filter_by(user_id=u.id).order_by(models.WishItem.rank).all()
    assert len(rows) == 2 and [r.rank for r in rows] == [0, 1] and all(r.price == 0 for r in rows)


def test_commit_full_card_creates_one_card_routed_one_off_and_uncommit_removes_it(db_session):
    u, acct, card = _seed(db_session)
    it = _wish(db_session, u, "2000.00", models.WishMethod.full_card, card_id=card.id)
    res = commit_wish(db_session, u, acct.id, it.id, date.today())
    pes = db_session.query(models.PlannedExpense).filter_by(user_id=u.id).all()
    assert len(pes) == 1 and pes[0].card_id == card.id and pes[0].amount == Decimal("2000.00")
    assert pes[0].expected_date == res["placement_date"]
    assert it.scenario.status == "committed"
    uncommit_wish(db_session, u, it.id)
    assert db_session.query(models.PlannedExpense).filter_by(user_id=u.id).count() == 0
    assert it.scenario.status == "draft"
    assert db_session.query(models.WishCommitRow).count() == 0


def test_commit_financed_creates_recurring_for_n_minus_1_and_final_one_off(db_session):
    u, acct, _ = _seed(db_session)
    it = _wish(db_session, u, "1000.00", models.WishMethod.financed, months=3, apr="0", down="100.00")
    res = commit_wish(db_session, u, acct.id, it.id, date.today())
    buy = res["placement_date"]
    rec = db_session.query(models.RecurringItem).filter_by(user_id=u.id).one()
    assert rec.amount == Decimal("300.00") and rec.type == models.RecurringType.expense
    pes = sorted(db_session.query(models.PlannedExpense).filter_by(user_id=u.id).all(), key=lambda p: p.expected_date)
    assert [p.amount for p in pes] == [Decimal("100.00"), Decimal("300.00")]   # down payment, final payment
    assert pes[0].expected_date == buy
    uncommit_wish(db_session, u, it.id)
    assert db_session.query(models.RecurringItem).filter_by(user_id=u.id).count() == 0
    assert db_session.query(models.PlannedExpense).filter_by(user_id=u.id).count() == 0


def test_commit_refused_when_nothing_fits_and_no_target(db_session):
    u, acct, _ = _seed(db_session)
    it = _wish(db_session, u, "999999.00", models.WishMethod.full_checking)
    with pytest.raises(WishError):
        commit_wish(db_session, u, acct.id, it.id, date.today())
    assert db_session.query(models.PlannedExpense).count() == 0


def test_commit_refused_when_chosen_option_has_error(db_session):
    """An option with `months` unset can't be priced -- monthly_payment raises
    inside build_plan, which caches that as this option's `error`. It is the
    item's only option, so build_plan's fallback still has to pick SOME
    option to report as `plan_option_id` (opts_out[0]), and a future
    target_date means `placement_date` is still set from the target rather
    than from this (unfit) option's safe_date. commit_wish must refuse
    rather than commit a scenario it can't actually place a purchase for."""
    u, acct, _ = _seed(db_session)
    it = _wish(db_session, u, "500.00", models.WishMethod.financed)  # months=None -> always errors
    it.target_date = date.today() + timedelta(days=5)
    db_session.commit()
    with pytest.raises(WishError):
        commit_wish(db_session, u, acct.id, it.id, date.today())
    assert db_session.query(models.PlannedExpense).count() == 0
    assert it.scenario.status == "draft"


def test_commit_persists_the_chosen_plan_option_for_highlighting(db_session):
    """Minor 1: build_plan computes a `plan_option_id` for the item (either
    the user's own pick, or its own cheapest-fitting auto-pick) but never
    wrote it back onto the WishItem row -- so once committed, item.plan_option_id
    stayed whatever it was before (often None), and the UI had nothing to
    highlight the option that was actually used for the purchase. Left
    unset here on purpose so build_plan's auto-pick is what resolves it."""
    u, acct, _ = _seed(db_session)
    sc = models.ForecastScenario(user_id=u.id, name="Grill"); db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("500.00"))
    db_session.add(item); db_session.flush()
    opt = models.WishOption(user_id=u.id, wish_item_id=item.id, label="Full",
                            method=models.WishMethod.full_checking)
    db_session.add(opt); db_session.flush()
    db_session.commit()
    assert item.plan_option_id is None

    commit_wish(db_session, u, acct.id, item.id, date.today())

    db_session.refresh(item)
    assert item.plan_option_id == opt.id


def test_commit_financed_with_card_creates_individual_one_offs_not_recurring(db_session):
    """I2 (RULING): a card-linked RecurringItem would be invisible whenever
    the card carries monthly_spend_estimate > 0 -- forecast_engine's flat
    estimate (~760-792) wins outright and never looks at card-linked
    RecurringItems in that branch, so the real financed payment would vanish
    from the forecast entirely instead of showing up. Card financing must
    create no RecurringItem at all: each scheduled payment is its own
    PlannedExpense with card_id set, landing on add_months(when, k), routed
    through the forecast the same way any other card one-off is -- via
    card_planned_by_date / _card_payoff_date_for_charge -- so it shows up on
    its real payoff date instead of being absorbed by the flat estimate."""
    u, acct, card = _seed(db_session)
    card.monthly_spend_estimate = Decimal("5500.00")
    db_session.commit()
    today = date(2026, 1, 5)
    it = _wish(db_session, u, "1000.00", models.WishMethod.financed, months=3, apr="0", down="100.00",
              card_id=card.id)
    it.target_date = today
    db_session.commit()

    res = commit_wish(db_session, u, acct.id, it.id, today)
    buy = res["placement_date"]
    assert buy == today

    assert db_session.query(models.RecurringItem).filter_by(user_id=u.id).count() == 0

    pes = db_session.query(models.PlannedExpense).filter_by(user_id=u.id).order_by(
        models.PlannedExpense.expected_date).all()
    assert all(p.card_id == card.id for p in pes)
    assert [p.amount for p in pes] == [Decimal("100.00"), Decimal("300.00"), Decimal("300.00"), Decimal("300.00")]
    payments = pes[1:]  # drop the down payment
    assert [p.expected_date for p in payments] == [add_months(buy, k) for k in (1, 2, 3)]

    days = build_forecast(db_session, u.id, acct.id, today, today + timedelta(days=150))
    by_date = {d.date: d.transactions for d in days}
    for pe in payments:
        payoff = _card_payoff_date_for_charge(card, pe.expected_date)
        matches = [
            t for t in by_date.get(payoff, [])
            if t.name == f"{pe.name} (via {card.name})" and t.amount == -pe.amount
        ]
        assert len(matches) == 1, f"expected exactly one match for {pe.name} on {payoff}, got {matches}"


def test_uncommit_refuses_once_payments_have_posted(db_session):
    """I1 (RULING): a posted bank-synced Transaction linking to a
    RecurringItem this wish created must block uncommit before anything is
    touched -- Transaction.recurring_item_id is a FK with no ondelete, so
    with foreign keys enforced, deleting that item mid-uncommit would
    otherwise crash partway through, stranding the wish half-uncommitted."""
    u, acct, _ = _seed(db_session)
    it = _wish(db_session, u, "1000.00", models.WishMethod.financed, months=3, apr="0", down="100.00")
    commit_wish(db_session, u, acct.id, it.id, date.today())

    rec = db_session.query(models.RecurringItem).filter_by(user_id=u.id).one()
    pe_count_before = db_session.query(models.PlannedExpense).filter_by(user_id=u.id).count()
    row_count_before = db_session.query(models.WishCommitRow).filter_by(wish_item_id=it.id).count()
    db_session.add(models.Transaction(
        user_id=u.id, account_id=acct.id, recurring_item_id=rec.id,
        date=date.today(), amount=Decimal("-300.00"), description="payment",
    ))
    db_session.commit()

    with pytest.raises(WishError):
        uncommit_wish(db_session, u, it.id)

    # Nothing changed: every created row still exists, exactly as it was.
    assert db_session.query(models.RecurringItem).filter_by(user_id=u.id).count() == 1
    assert db_session.query(models.PlannedExpense).filter_by(user_id=u.id).count() == pe_count_before
    assert db_session.query(models.WishCommitRow).filter_by(wish_item_id=it.id).count() == row_count_before
    assert it.scenario.status == "committed"


def test_commit_financed_from_checking_recurring_day_of_month_matches_buy_day(db_session):
    """Minor: day_of_month must mirror the buy date's own day -- the engine
    clamps it into short months itself, the same convention every other
    RecurringItem.day_of_month follows -- not add_months(when, 1).day, which
    silently loses a 29/30/31 buy day whenever the first payment month is
    shorter than the buy month (e.g. a Jan 31 buy's first payment falls in
    Feb, clamping the day to 28)."""
    u, acct, _ = _seed(db_session)
    today = date(2026, 1, 31)
    it = _wish(db_session, u, "900.00", models.WishMethod.financed, months=3, apr="0", down="0")
    it.target_date = today
    db_session.commit()

    commit_wish(db_session, u, acct.id, it.id, today)

    rec = db_session.query(models.RecurringItem).filter_by(user_id=u.id).one()
    assert rec.day_of_month == 31


def test_uncommit_wish_rolls_back_its_own_deletes_when_scenario_uncommit_refuses(db_session):
    """RULING: commit_wish's call to scenario_service.commit_scenario also
    materializes the scenario's own proposed_items (the general
    scenario-proposal mechanism), independent of the wish's chosen option.
    On uncommit, uncommit_wish deletes its own rows (the wish's commit rows)
    and flushes BEFORE calling scenario_service.uncommit_scenario -- which can
    then refuse over a committed proposed_item for a reason that has nothing
    to do with the wish's own rows (here: a bank-synced Transaction posted
    against it). Chose to roll back inside uncommit_wish itself (rather than
    pre-checking the scenario's blockers up front) so it stays atomic
    regardless of caller, not just when the HTTP route also rolls back."""
    u, acct, _ = _seed(db_session)
    it = _wish(db_session, u, "300.00", models.WishMethod.full_checking)
    proposed = models.ScenarioProposedItem(
        scenario_id=it.scenario_id, name="Side burner", amount=Decimal("25.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=5, start_date=date(2026, 11, 5), account_id=acct.id,
    )
    db_session.add(proposed)
    db_session.commit()

    commit_wish(db_session, u, acct.id, it.id, date.today())
    side_burner = db_session.query(models.RecurringItem).filter_by(name="Side burner").one()
    pe_count_before = db_session.query(models.PlannedExpense).filter_by(user_id=u.id).count()
    row_count_before = db_session.query(models.WishCommitRow).filter_by(wish_item_id=it.id).count()
    db_session.add(models.Transaction(
        user_id=u.id, account_id=acct.id, recurring_item_id=side_burner.id,
        date=date.today(), amount=Decimal("-25.00"), description="side burner payment",
    ))
    db_session.commit()

    with pytest.raises(scenario_service.ScenarioPaymentsPosted):
        uncommit_wish(db_session, u, it.id)

    # Nothing changed -- the wish's own rows, flushed-but-uncommitted deletes
    # included, were rolled back right along with the refused scenario-level
    # uncommit.
    assert db_session.query(models.RecurringItem).filter_by(name="Side burner").count() == 1
    assert db_session.query(models.PlannedExpense).filter_by(user_id=u.id).count() == pe_count_before
    assert db_session.query(models.WishCommitRow).filter_by(wish_item_id=it.id).count() == row_count_before
    assert it.scenario.status == "committed"


# ── Minor 3: plan-vs-commit agreement ────────────────────────────────────────

@pytest.mark.parametrize("label,method,price,kw", [
    ("full_checking", models.WishMethod.full_checking, "1500.00", {}),
    ("full_card_no_estimate", models.WishMethod.full_card, "1500.00", {"card": True}),
    ("financed_checking_12m_6pct", models.WishMethod.financed, "2400.00",
     {"months": 12, "apr": "6.0", "down": "200.00"}),
    ("financed_card_3m_0pct", models.WishMethod.financed, "1800.00",
     {"card": True, "months": 3, "apr": "0", "down": "100.00"}),
    ("full_checking_with_later_trade_in", models.WishMethod.full_checking, "1500.00",
     {"trade_value": "400.00", "trade_offset": 40}),
])
def test_plan_predicted_low_point_equals_the_committed_forecasts_low_point(db_session, label, method, price, kw):
    """Minor 3: build_plan's explain receipt predicts a low point for an
    option's placement date entirely from an in-memory overlay (the
    baseline forecast plus cumulative cash-flow deltas) -- it never actually
    runs the committed rows through forecast_engine. If the overlay math and
    the real engine ever disagreed (a routing rule the overlay doesn't
    mirror, a rounding edge, a month-end clamp), the UI's safe-date promise
    would silently diverge from what the real forecast shows once committed.
    Covers one method per combination called out in the fix-wave brief: plain
    checking, a card with no monthly_spend_estimate (so the real amount, not
    a flat estimate, must drive the forecast), financed from checking at a
    non-zero APR, financed on a card at 0%, and a later trade-in credit.
    "Today" is pinned (not date.today()) so the paycheck/rent schedule below
    and every date arithmetic step stay identical on every run."""
    db = db_session
    today = date(2026, 3, 2)
    u = models.User(username=f"equiv_{label}", hashed_password="x", display_name="Equiv")
    db.add(u)
    db.flush()
    acct = models.Account(user_id=u.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("6000.00"))
    db.add(acct)
    db.flush()
    card = models.CreditCard(user_id=u.id, name="Card", credit_limit=Decimal("9000.00"), statement_day=28,
                             due_day=25, current_balance=Decimal("0"))
    db.add(card)
    db.flush()
    db.add(models.RecurringItem(
        user_id=u.id, account_id=acct.id, name="Pay", amount=Decimal("2500.00"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=today - timedelta(days=400), is_active=True))
    db.add(models.RecurringItem(
        user_id=u.id, account_id=acct.id, name="Rent", amount=Decimal("2300.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=today - timedelta(days=400), is_active=True))
    db.add(models.WishSettings(user_id=u.id, cushion=Decimal("500.00")))
    sc = models.ForecastScenario(user_id=u.id, name="Equiv")
    db.add(sc)
    db.flush()
    trade_value = kw.get("trade_value")
    trade_offset = kw.get("trade_offset")
    item = models.WishItem(
        user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal(price),
        trade_in_value=Decimal(trade_value) if trade_value else Decimal("0"),
        trade_in_on=(today + timedelta(days=trade_offset)) if trade_offset is not None else None,
    )
    db.add(item)
    db.flush()
    opt = models.WishOption(
        user_id=u.id, wish_item_id=item.id, label="o", method=method,
        card_id=card.id if kw.get("card") else None, months=kw.get("months"),
        apr=None if kw.get("apr") is None else Decimal(kw["apr"]),
        down_payment=Decimal(kw.get("down", "0")),
    )
    db.add(opt)
    db.flush()
    item.plan_option_id = opt.id
    db.commit()

    plan = build_plan(db, u, acct.id, today)
    entry = plan["items"][0]
    assert entry["explain"] is not None, f"{label}: expected this option to fit and produce a receipt"
    predicted_low = Decimal(entry["explain"]["result"])
    placement = entry["placement_date"]
    assert placement is not None

    commit_wish(db, u, acct.id, item.id, today)

    end = today + timedelta(days=365)
    days = _series(db, u.id, acct.id, today, end)
    dates = [d.date for d in days]
    base = [Decimal(d.projected_balance) for d in days]
    mask = floor_mask(days, [card])
    idx = next(i for i, d in enumerate(dates) if d >= placement)
    actual = low_point(base, mask, dates, [], idx)
    assert actual is not None
    actual_low, _ = actual

    assert actual_low == predicted_low, (
        f"{label}: build_plan predicted a low point of {predicted_low}, "
        f"but the committed forecast's real low point is {actual_low}"
    )
