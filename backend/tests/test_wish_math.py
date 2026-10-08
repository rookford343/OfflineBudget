from datetime import date
from decimal import Decimal
from backend import models


def _user(db, name="wisher"):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.flush(); return u


def test_wish_tables_round_trip(db_session):
    u = _user(db_session)
    sc = models.ForecastScenario(user_id=u.id, name="New laptop")
    db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("2000.00"),
                           trade_in_value=Decimal("300.00"))
    db_session.add(item); db_session.flush()
    opt = models.WishOption(user_id=u.id, wish_item_id=item.id, label="0% / 12",
                            method=models.WishMethod.financed, months=12, apr=Decimal("0"))
    db_session.add(opt); db_session.flush()
    item.plan_option_id = opt.id
    db_session.add(models.WishSettings(user_id=u.id, cushion=Decimal("1500.00")))
    db_session.commit()
    db_session.refresh(item)
    assert [o.label for o in item.options] == ["0% / 12"]
    assert opt.down_payment == Decimal("0")


def test_deleting_item_with_a_plan_option_succeeds(db_session):
    u = _user(db_session)
    sc = models.ForecastScenario(user_id=u.id, name="New laptop")
    db_session.add(sc); db_session.flush()
    item = models.WishItem(user_id=u.id, scenario_id=sc.id, rank=0, price=Decimal("2000.00"),
                           trade_in_value=Decimal("300.00"))
    db_session.add(item); db_session.flush()
    opt = models.WishOption(user_id=u.id, wish_item_id=item.id, label="0% / 12",
                            method=models.WishMethod.financed, months=12, apr=Decimal("0"))
    db_session.add(opt); db_session.flush()
    item.plan_option_id = opt.id
    db_session.commit()
    db_session.delete(item)
    db_session.commit()
    assert db_session.query(models.WishItem).filter_by(id=item.id).first() is None
    assert db_session.query(models.WishOption).filter_by(id=opt.id).first() is None


from backend.services.wish_math import (
    net_price, financed_principal, payment_schedule, total_cost, monthly_payment,
    add_months, option_flows,
)
M = models.WishMethod


def _item(price="2000.00", trade="0", trade_on=None):
    return models.WishItem(price=Decimal(price), trade_in_value=Decimal(trade), trade_in_on=trade_on, rank=0)


def _opt(method, **kw):
    return models.WishOption(label="x", method=method, card_id=kw.get("card_id"), months=kw.get("months"),
                             apr=None if kw.get("apr") is None else Decimal(kw["apr"]),
                             down_payment=Decimal(kw.get("down", "0")), sort_order=0)


def _card(cid=1, statement_day=28, due_day=25):
    return models.CreditCard(id=cid, name="Card", credit_limit=Decimal("1"), statement_day=statement_day,
                             due_day=due_day, current_balance=Decimal("0"))


def test_net_price_trade_in_now_vs_later():
    assert net_price(_item(trade="300.00")) == Decimal("1700.00")
    assert net_price(_item(trade="300.00", trade_on=date(2027, 1, 5))) == Decimal("2000.00")
    assert net_price(_item(price="100", trade="300")) == Decimal("0")


def test_zero_percent_schedule_sums_exactly_with_last_payment_absorbing_rounding():
    sched = payment_schedule(Decimal("1000.00"), Decimal("0"), 3)
    assert sched == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert sum(sched) == Decimal("1000.00")


def test_amortized_schedule_at_apr():
    sched = payment_schedule(Decimal("1200.00"), Decimal("12"), 12)
    assert sched[0] == Decimal("106.62")          # standard amortization at 1%/month
    assert len(sched) == 12
    assert sum(sched) == Decimal("1279.42")       # amortized total, last payment adjusted (verified independently)


def test_total_cost_and_monthly_payment():
    item = _item(trade="200.00")
    fin = _opt(M.financed, months=10, apr="0", down="300.00")
    assert financed_principal(item, fin) == Decimal("1500.00")
    assert monthly_payment(item, fin) == Decimal("150.00")
    assert total_cost(item, fin) == Decimal("1800.00")
    assert total_cost(item, _opt(M.full_checking)) == Decimal("1800.00")
    later = _item(trade="200.00", trade_on=date(2027, 2, 1))
    assert total_cost(later, _opt(M.full_checking)) == Decimal("1800.00")   # 2000 out, 200 back later
    assert monthly_payment(item, _opt(M.full_checking)) is None


def test_add_months_clamps_to_month_end():
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2027, 1, 15), 13) == date(2028, 2, 15)


def test_flows_full_checking_and_full_card():
    item = _item(trade="300.00")
    buy = date(2027, 3, 10)
    assert option_flows(item, _opt(M.full_checking), buy, {}) == [(buy, Decimal("-1700.00"))]
    card = _card()
    # charge 3/10 -> statement closes 3/28 -> due 4/25
    assert option_flows(item, _opt(M.full_card, card_id=1), buy, {1: card}) == [(date(2027, 4, 25), Decimal("-1700.00"))]


def test_flows_financed_from_checking_and_on_card_plus_later_trade_in():
    item = _item(price="1200.00", trade="100.00", trade_on=date(2027, 5, 1))
    buy = date(2027, 3, 31)
    fl = option_flows(item, _opt(M.financed, months=3, apr="0", down="0"), buy, {})
    assert fl == [(date(2027, 4, 30), Decimal("-400.00")), (date(2027, 5, 31), Decimal("-400.00")),
                  (date(2027, 6, 30), Decimal("-400.00")), (date(2027, 5, 1), Decimal("100.00"))]
    card = _card()
    fl_card = option_flows(_item(price="600.00"), _opt(M.financed, months=2, apr="0", down="100.00", card_id=1),
                           date(2027, 3, 10), {1: card})
    # down 3/10 -> due 4/25; payment 4/10 -> due 5/25; payment 5/10 -> due 6/25
    assert fl_card == [(date(2027, 4, 25), Decimal("-100.00")), (date(2027, 5, 25), Decimal("-250.00")),
                       (date(2027, 6, 25), Decimal("-250.00"))]
