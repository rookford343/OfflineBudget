"""Health under Necessities: Healthcare is renamed, a missing one is created."""
from backend import models
from backend.database import ensure_health_category
from backend.services.auto_categorizer import categorize

E = models.CategoryType.expense


def _tree(db, parent_name, child_names, username=None):
    user = models.User(username=username or f"u-{parent_name}", hashed_password="x", display_name="U")
    db.add(user); db.flush()
    parent = models.Category(user_id=user.id, name=parent_name, type=E, color="#3b82f6", sort_order=0)
    db.add(parent); db.flush()
    children = [
        models.Category(user_id=user.id, parent_id=parent.id, name=n, type=E, sort_order=i)
        for i, n in enumerate(child_names)
    ]
    db.add_all(children); db.commit()
    return user, parent, [c.id for c in children]


def _run(db):
    ensure_health_category(db.connection())
    db.commit()
    db.expire_all()


def _health(db, parent):
    return db.query(models.Category).filter(
        models.Category.parent_id == parent.id, models.Category.name == "Health",
    ).all()


def test_healthcare_is_renamed_keeping_its_id(db_session):
    _, parent, (hc_id,) = _tree(db_session, "Necessities", ["Healthcare"])
    _run(db_session)
    assert db_session.get(models.Category, hc_id).name == "Health"
    assert len(_health(db_session, parent)) == 1


def test_missing_health_is_created_under_necessities_as_committed(db_session):
    user, parent, _ = _tree(db_session, "Necessities", ["Home", "Insurance"])
    _run(db_session)
    (health,) = _health(db_session, parent)
    assert health.user_id == user.id
    assert health.type == E
    assert health.is_discretionary is False
    assert health.sort_order == 2  # after the existing children


def test_idempotent(db_session):
    _, parent, _ = _tree(db_session, "Necessities", ["Home"])
    _run(db_session)
    _run(db_session)
    assert len(_health(db_session, parent)) == 1


def test_healthcare_left_alone_when_health_already_exists(db_session):
    _, parent, (hc_id, h_id) = _tree(db_session, "Necessities", ["Healthcare", "Health"])
    _run(db_session)
    assert db_session.get(models.Category, hc_id).name == "Healthcare"
    assert len(_health(db_session, parent)) == 1


def test_other_parents_and_users_are_untouched(db_session):
    _, other, (hc_id,) = _tree(db_session, "Business", ["Healthcare"])
    _, nec, _ = _tree(db_session, "Necessities", [], username="second")
    _run(db_session)
    assert db_session.get(models.Category, hc_id).name == "Healthcare"
    assert _health(db_session, other) == []
    assert len(_health(db_session, nec)) == 1


def test_pharmacy_and_lab_keywords_land_in_health():
    cats = [models.Category(id=1, user_id=1, name="Health", type=E)]
    for desc in ["CVS/PHARMACY #1234", "WALGREENS 0042", "LABCORP"]:
        assert categorize(desc, cats).name == "Health", desc
