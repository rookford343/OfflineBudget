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
