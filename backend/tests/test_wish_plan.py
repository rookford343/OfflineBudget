from datetime import date, timedelta
from decimal import Decimal
from backend.services.wish_plan import cum_from_flows, low_point, earliest_safe_date

D0 = date(2027, 1, 1)
DATES = [D0 + timedelta(days=i) for i in range(100)]


def _flat(v):
    return [Decimal(v)] * len(DATES)


def test_cum_from_flows_applies_from_flow_date_onward_and_ignores_outside():
    cum = cum_from_flows(DATES, [(DATES[10], Decimal("-50")), (DATES[20], Decimal("20")),
                                 (D0 + timedelta(days=500), Decimal("-999"))])
    assert cum[9] == 0 and cum[10] == Decimal("-50") and cum[20] == Decimal("-30") and cum[-1] == Decimal("-30")


def test_low_point_respects_mask_and_start():
    base = _flat("5000"); base[30] = Decimal("100"); base[60] = Decimal("900")
    mask = [True] * len(DATES); mask[30] = False
    assert low_point(base, mask, DATES, [], 0) == (Decimal("900"), 60)


def test_fits_today_later_and_never():
    base = _flat("3000")
    mask = [True] * len(DATES)
    zero = [Decimal(0)] * len(DATES)
    buy = lambda d: [(d, Decimal("-1500"))]
    r = earliest_safe_date(DATES, base, mask, zero, buy, Decimal("1000"), 0, 69)
    assert r["safe_date"] == DATES[0] and r["low"] == Decimal("1500")
    # A big bill on day 20 means buying before it breaches; after day 20 a paycheck restores.
    base2 = list(base)
    for i in range(20, 40): base2[i] = Decimal("2000")
    r2 = earliest_safe_date(DATES, base2, mask, zero, buy, Decimal("1000"), 0, 69)
    assert r2["safe_date"] == DATES[40]
    r3 = earliest_safe_date(DATES, base, mask, zero, lambda d: [(d, Decimal("-5000"))], Decimal("1000"), 0, 69)
    assert r3["safe_date"] is None and r3["shortfall"] == Decimal("3000") and r3["best_low"] == Decimal("-2000")


def test_prior_overlay_pushes_the_date_later():
    base = _flat("3000")
    mask = [True] * len(DATES)
    prior = cum_from_flows(DATES, [(DATES[0], Decimal("-1500")), (DATES[50], Decimal("1500"))])
    r = earliest_safe_date(DATES, base, mask, prior, lambda d: [(d, Decimal("-1000"))], Decimal("1000"), 0, 69)
    assert r["safe_date"] == DATES[50]


from backend import models
from backend.services.wish_plan import build_plan


def _seed(db, username="planner"):
    u = models.User(username=username, hashed_password="x", display_name="P")
    db.add(u); db.flush()
    acct = models.Account(user_id=u.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("5000.00"))
    db.add(acct); db.flush()
    return u, acct


def _wish(db, u, name, rank, price, method=models.WishMethod.full_checking):
    sc = models.ForecastScenario(user_id=u.id, name=name); db.add(sc); db.flush()
    it = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=rank, price=Decimal(price)); db.add(it); db.flush()
    op = models.WishOption(user_id=u.id, wish_item_id=it.id, label="full", method=method); db.add(op); db.flush()
    return it, op


def test_build_plan_stacks_in_rank_order(db_session):
    u, acct = _seed(db_session)
    today = date.today()
    # A paycheck every 14 days keeps the balance climbing so later dates fit.
    db_session.add(models.RecurringItem(user_id=u.id, account_id=acct.id, name="Pay", amount=Decimal("1000.00"),
                                        type=models.RecurringType.income, frequency=models.RecurringFrequency.biweekly,
                                        day_of_month=1, start_date=today + timedelta(days=1)))
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    first, _ = _wish(db_session, u, "Laptop", 0, "3500.00")
    second, _ = _wish(db_session, u, "Grill", 1, "1500.00")
    db_session.commit()
    plan = build_plan(db_session, u, acct.id, today)
    items = {i["name"]: i for i in plan["items"]}
    assert plan["cushion"] == Decimal("1000.00")
    assert items["Laptop"]["placement_date"] == today          # 5000 - 3500 = 1500 >= 1000
    assert items["Grill"]["placement_date"] > today            # must wait for paychecks after the laptop
    assert items["Laptop"]["options"][0]["total_cost"] == Decimal("3500.00")
    ex = items["Laptop"]["explain"]
    total = sum(Decimal(r["amount"]) for r in ex["rows"] if r["op"] in ("start", "add"))
    assert total == Decimal(ex["result"])


def test_build_plan_skips_a_bad_option_without_crashing(db_session):
    u, acct = _seed(db_session)
    today = date.today()
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    sc = models.ForecastScenario(user_id=u.id, name="Laptop"); db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("1000.00"))
    db_session.add(item); db_session.flush()
    bad = models.WishOption(user_id=u.id, wish_item_id=item.id, label="bad financed",
                            method=models.WishMethod.financed, months=None)
    good = models.WishOption(user_id=u.id, wish_item_id=item.id, label="full",
                             method=models.WishMethod.full_checking)
    db_session.add_all([bad, good]); db_session.flush()
    db_session.commit()

    plan = build_plan(db_session, u, acct.id, today)

    item_out = plan["items"][0]
    by_label = {o["label"]: o for o in item_out["options"]}
    assert by_label["bad financed"]["error"] is not None
    assert by_label["bad financed"]["monthly_payment"] is None
    assert by_label["bad financed"]["total_cost"] is None
    assert by_label["full"]["error"] is None
    assert item_out["plan_option_id"] == good.id
    assert item_out["fits"] is True


def test_plan_falls_back_to_a_valid_option_when_nothing_fits_and_target_is_used(db_session):
    # Option 0 errors (financed, months=None). Option 1 is valid but the price
    # is too big for the flat $5000 balance to ever clear the $1000 cushion,
    # so earliest_safe_date never finds a safe_date for it either. A future
    # target_date still has to pick the valid option over the errored one --
    # not opts_out[0], which here IS the errored option.
    u, acct = _seed(db_session)
    today = date.today()
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    sc = models.ForecastScenario(user_id=u.id, name="Boat")
    db_session.add(sc); db_session.flush()
    target = today + timedelta(days=10)
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("6000.00"),
                           target_date=target)
    db_session.add(item); db_session.flush()
    bad = models.WishOption(user_id=u.id, wish_item_id=item.id, label="bad financed",
                            method=models.WishMethod.financed, months=None)
    too_expensive = models.WishOption(user_id=u.id, wish_item_id=item.id, label="full",
                                      method=models.WishMethod.full_checking)
    db_session.add_all([bad, too_expensive]); db_session.flush()
    db_session.commit()

    plan = build_plan(db_session, u, acct.id, today)
    item_out = plan["items"][0]

    assert item_out["plan_option_id"] == too_expensive.id
    assert item_out["fits"] is True
    # The plan option itself never clears the cushion anywhere in the horizon.
    by_label = {o["label"]: o for o in item_out["options"]}
    assert by_label["full"]["safe_date"] is None
    # Ruling 2: a valid (future) target in use reports its own low/shortfall
    # against the cushion -- here the balance never recovers, so it's a flat
    # $1000 under cushion ($5000 - $6000 = -$1000; cushion $1000 - (-$1000)).
    assert item_out["target_ignored"] is False
    assert item_out["target_low"] == Decimal("-1000.00")
    assert item_out["target_shortfall"] == Decimal("2000.00")
    assert item_out["explain"]["title"] == "Your chosen date"


def test_every_option_errored_keeps_fits_false(db_session):
    # If every option errors, the fallback has nothing valid to choose --
    # opts_out[0] is used so there's still a plan_option_id, but fits must
    # stay False (no usable option), even with a future target_date.
    u, acct = _seed(db_session)
    today = date.today()
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    sc = models.ForecastScenario(user_id=u.id, name="Bad item")
    db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("1000.00"),
                           target_date=today + timedelta(days=5))
    db_session.add(item); db_session.flush()
    bad1 = models.WishOption(user_id=u.id, wish_item_id=item.id, label="bad1",
                             method=models.WishMethod.financed, months=None)
    bad2 = models.WishOption(user_id=u.id, wish_item_id=item.id, label="bad2",
                             method=models.WishMethod.financed, months=999)
    db_session.add_all([bad1, bad2]); db_session.flush()
    db_session.commit()

    plan = build_plan(db_session, u, acct.id, today)
    item_out = plan["items"][0]

    assert item_out["fits"] is False
    assert item_out["plan_option_id"] in (bad1.id, bad2.id)
    assert item_out["target_low"] is None
    assert item_out["target_shortfall"] is None


def test_past_target_date_is_ignored(db_session):
    u, acct = _seed(db_session)
    today = date.today()
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    sc = models.ForecastScenario(user_id=u.id, name="Grill")
    db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("500.00"),
                           target_date=today - timedelta(days=5))
    db_session.add(item); db_session.flush()
    db_session.add(models.WishOption(user_id=u.id, wish_item_id=item.id, label="full",
                                     method=models.WishMethod.full_checking))
    db_session.commit()

    plan = build_plan(db_session, u, acct.id, today)
    item_out = plan["items"][0]

    assert item_out["target_ignored"] is True
    assert item_out["placement_date"] == today  # falls back to the earliest safe date
    assert item_out["target_low"] is None
    assert item_out["target_shortfall"] is None


def test_scenario_proposed_expense_pushes_the_safe_date_later_or_breaks_the_fit(db_session):
    # Same _seed/paycheck setup as the stacking test, run twice: once with an
    # ordinary item, once with an otherwise-identical item whose scenario also
    # proposes a one-off $2000 expense 10 days out. The extra expense must
    # make the fit worse (later safe date, or no fit at all).
    today = date.today()

    def _plan_with(expense: bool):
        u, acct = _seed(db_session, username=f"planner_{expense}")
        db_session.add(models.RecurringItem(
            user_id=u.id, account_id=acct.id, name="Pay", amount=Decimal("1000.00"),
            type=models.RecurringType.income, frequency=models.RecurringFrequency.biweekly,
            day_of_month=1, start_date=today + timedelta(days=1)))
        db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
        it, _ = _wish(db_session, u, "Laptop", 0, "3000.00")
        if expense:
            # 3000 (buy) + 2500 (expense) leaves only 500 of the $6000 balance
            # during the days 10-13 dip (before the next paycheck), which
            # breaches the $1000 cushion -- buying day 0 no longer fits.
            db_session.add(models.ScenarioProposedExpense(
                scenario_id=it.scenario_id, name="Surprise bill", amount=Decimal("2500.00"),
                expected_date=today + timedelta(days=10), account_id=acct.id))
        db_session.commit()
        plan = build_plan(db_session, u, acct.id, today)
        return plan["items"][0]

    without_expense = _plan_with(False)
    with_expense = _plan_with(True)

    assert without_expense["placement_date"] == today  # 5000 - 3000 = 2000 >= 1000
    assert (
        with_expense["placement_date"] is None
        or with_expense["placement_date"] > without_expense["placement_date"]
    )


def test_explicit_plan_option_id_overrides_the_cheaper_auto_pick(db_session):
    u, acct = _seed(db_session)
    today = date.today()
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    sc = models.ForecastScenario(user_id=u.id, name="Laptop")
    db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("2000.00"))
    db_session.add(item); db_session.flush()
    cheap = models.WishOption(user_id=u.id, wish_item_id=item.id, label="cheap",
                              method=models.WishMethod.full_checking)
    costly = models.WishOption(user_id=u.id, wish_item_id=item.id, label="costly",
                               method=models.WishMethod.financed, months=12, apr=Decimal("12.0"))
    db_session.add_all([cheap, costly]); db_session.flush()
    item.plan_option_id = costly.id
    db_session.commit()

    plan = build_plan(db_session, u, acct.id, today)
    item_out = plan["items"][0]

    by_label = {o["label"]: o for o in item_out["options"]}
    assert by_label["costly"]["total_cost"] > by_label["cheap"]["total_cost"]
    assert item_out["plan_option_id"] == costly.id


def test_committed_scenario_has_no_placement_and_does_not_push_lower_ranked_items(db_session):
    u, acct = _seed(db_session)
    today = date.today()
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1000.00")))
    committed_item, _ = _wish(db_session, u, "Committed thing", 0, "3000.00")
    committed_item.scenario.status = "committed"
    draft_item, _ = _wish(db_session, u, "Grill", 1, "1500.00")
    db_session.commit()

    plan = build_plan(db_session, u, acct.id, today)
    items = {i["name"]: i for i in plan["items"]}

    assert items["Committed thing"]["placement_date"] is None
    assert items["Committed thing"]["fits"] is False
    # Not pushed later by the committed item's price -- the real forecast
    # already reflects committed costs; build_plan's rank-stacking must not
    # double-count it.
    assert items["Grill"]["placement_date"] == today  # 5000 - 1500 = 3500 >= 1000
