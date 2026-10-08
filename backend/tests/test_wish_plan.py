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


def _seed(db):
    u = models.User(username="planner", hashed_password="x", display_name="P")
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
