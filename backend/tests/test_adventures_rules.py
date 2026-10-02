from datetime import date
from decimal import Decimal
from backend import models
from backend.services.adventures import (
    ensure_adventures_seeded, CHASE_UR, STARTER_AIRLINES, STARTER_HOTELS, STARTER_TEMPLATE,
)


def _user(db, username="traveler"):
    u = models.User(username=username, hashed_password="x", display_name="T")
    db.add(u)
    db.flush()
    return u


def test_seeding_creates_programs_partners_and_template_once(db_session):
    user = _user(db_session)
    ensure_adventures_seeded(db_session, user.id)
    ensure_adventures_seeded(db_session, user.id)  # idempotent
    programs = db_session.query(models.LoyaltyProgram).filter_by(user_id=user.id).all()
    names = {p.name for p in programs}
    assert CHASE_UR in names
    assert set(STARTER_AIRLINES) <= names and set(STARTER_HOTELS) <= names
    assert len(programs) == 1 + len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert all(p.balance == 0 for p in programs)
    partners = db_session.query(models.TransferPartner).filter_by(user_id=user.id).all()
    assert len(partners) == len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert all(p.ratio == Decimal("1") and p.bonus_pct is None for p in partners)
    template = db_session.query(models.ChecklistTemplateItem).filter_by(user_id=user.id).all()
    assert len(template) == len(STARTER_TEMPLATE)


def test_seeding_is_per_kind_and_per_user(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    ensure_adventures_seeded(db_session, a.id)
    # a deletes the whole template; programs remain, so re-seeding restores only the template
    db_session.query(models.ChecklistTemplateItem).filter_by(user_id=a.id).delete()
    ensure_adventures_seeded(db_session, a.id)
    assert db_session.query(models.ChecklistTemplateItem).filter_by(user_id=a.id).count() == len(STARTER_TEMPLATE)
    assert db_session.query(models.LoyaltyProgram).filter_by(user_id=a.id).count() == 1 + len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert db_session.query(models.LoyaltyProgram).filter_by(user_id=b.id).count() == 0
