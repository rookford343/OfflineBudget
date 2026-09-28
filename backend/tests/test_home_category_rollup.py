"""Test Utilities → Home rename migration and keyword updates."""
from backend import models
from backend.database import rename_utilities_to_home
from backend.services.auto_categorizer import categorize

E = models.CategoryType.expense


def _tree(db, parent_name, child_names):
    user = models.User(username=f"u-{parent_name}", hashed_password="x", display_name="U")
    db.add(user); db.flush()
    parent = models.Category(user_id=user.id, name=parent_name, type=E)
    db.add(parent); db.flush()
    children = [models.Category(user_id=user.id, parent_id=parent.id, name=n, type=E) for n in child_names]
    db.add_all(children); db.commit()
    return [c.id for c in children]


def _run_migration(db):
    rename_utilities_to_home(db.connection())
    db.commit()
    db.expire_all()


def _name(db, cid):
    return db.get(models.Category, cid).name


def test_utilities_under_necessities_becomes_home_keeping_its_id(db_session):
    (util_id,) = _tree(db_session, "Necessities", ["Utilities"])
    _run_migration(db_session)
    assert _name(db_session, util_id) == "Home"


def test_rename_is_idempotent_and_skips_when_home_exists(db_session):
    util_id, home_id = _tree(db_session, "Necessities", ["Utilities", "Home"])
    _run_migration(db_session)
    _run_migration(db_session)
    assert _name(db_session, util_id) == "Utilities"
    assert _name(db_session, home_id) == "Home"


def test_utilities_elsewhere_is_untouched(db_session):
    (util_id,) = _tree(db_session, "Business", ["Utilities"])
    _run_migration(db_session)
    assert _name(db_session, util_id) == "Utilities"


def _cats():
    return [
        models.Category(id=1, user_id=1, name="Home", type=models.CategoryType.expense),
        models.Category(id=2, user_id=1, name="Subscriptions", type=models.CategoryType.expense),
        models.Category(id=3, user_id=1, name="Transportation", type=models.CategoryType.expense),
    ]


def test_energy_and_home_service_keywords_land_in_home():
    for desc in ["DUKE ENERGY PAYMENT", "WASTE MANAGEMENT 8812", "CITY STORMWATER FEE", "GREENIX PEST CONTROL", "METRONET"]:
        assert categorize(desc, _cats()).name == "Home", desc


def test_gas_station_and_hoagie_are_not_home():
    r = categorize("SHELL GAS STATION 443", _cats())
    assert r is None or r.name != "Home"
    r = categorize("JERSEY MIKES HOAGIE", _cats())
    assert r is None or r.name != "Home"


def test_streaming_still_lands_in_subscriptions():
    assert categorize("NETFLIX.COM", _cats()).name == "Subscriptions"
