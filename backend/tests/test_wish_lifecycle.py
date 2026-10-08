from datetime import date, timedelta
from decimal import Decimal
import pytest
from backend import models
from backend.services.wish_lifecycle import WishError, ensure_wish_items, commit_wish, uncommit_wish


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


def test_commit_financed_with_card_sets_account_id_on_recurring_item(db_session):
    """RecurringItem.account_id is NOT NULL even when card_id is also set --
    routers/recurring.py's RecurringCreate schema requires it unconditionally,
    and forecast_engine filters card-paid recurring items by account_id too.
    A card-routed financed payment must still carry the real account_id."""
    u, acct, card = _seed(db_session)
    it = _wish(db_session, u, "1000.00", models.WishMethod.financed, months=3, apr="0", down="100.00",
              card_id=card.id)
    commit_wish(db_session, u, acct.id, it.id, date.today())
    rec = db_session.query(models.RecurringItem).filter_by(user_id=u.id).one()
    assert rec.account_id == acct.id and rec.card_id == card.id
