from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module
from backend.services.recurring_detector import detect_patterns
from backend.services.recurring_triage import build_triage, duplicate_pair_key

E = models.CategoryType.expense
M = models.RecurringFrequency.monthly


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db):
    user = models.User(username="tr", hashed_password="x", display_name="TR")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    home = models.Category(user_id=user.id, name="Home", type=E)
    subs = models.Category(user_id=user.id, name="Subscriptions", type=E)
    pets = models.Category(user_id=user.id, name="Pets", type=E)
    db.add_all([acct, home, subs, pets]); db.flush()

    def item(name, amount, cat=None, freq=M):
        i = models.RecurringItem(
            user_id=user.id, account_id=acct.id, category_id=cat.id if cat else None, name=name,
            amount=Decimal(amount), type=models.RecurringType.expense, frequency=freq,
            day_of_month=5, start_date=date(2026, 1, 1),
        )
        db.add(i); db.flush()
        return i

    items = {
        "hulu": item("Hulu", "18.00"),
        "trash": item("Trash service", "25.00"),
        "vet": item("Vet Plan", "40.00"),
        "netflix": item("Netflix", "15.49", subs),
        "netflix2": item("Netflix Standard", "15.49", subs),
        "electric": item("Electric", "150.00", home),
    }
    db.add(models.TransactionRule(
        user_id=user.id, name="Auto: vet", field=models.RuleField.description,
        pattern_type=models.RulePatternType.contains, pattern="vet plan",
        action=models.RuleAction.set_category, category_id=pets.id,
    ))
    today = date.today()
    for n in range(3):
        db.add(models.Transaction(
            user_id=user.id, account_id=acct.id, date=today - timedelta(days=30 * n + 1),
            amount=Decimal("-9.99"), description="ACME CLOUD STORAGE", is_actual=True,
        ))
    db.commit()
    return user, acct, {"home": home, "subs": subs, "pets": pets}, items


def test_uncategorized_items_listed_with_best_guess(db_session):
    user, _, cats, items = _seed(db_session)
    out = build_triage(db_session, user.id)
    by_name = {u.name: u for u in out.uncategorized}
    assert set(by_name) == {"Hulu", "Trash service", "Vet Plan"}
    assert by_name["Hulu"].guess_category_name == "Subscriptions"   # keyword
    assert by_name["Vet Plan"].guess_category_name == "Pets"        # rule beats keyword
    assert by_name["Trash service"].guess_category_id is None       # no weak guess


def test_rule_beats_keyword_when_both_match(db_session):
    user, _, cats, _ = _seed(db_session)
    # "hulu" is a Subscriptions keyword; the user's rule says otherwise.
    db_session.add(models.TransactionRule(
        user_id=user.id, name="Auto: hulu", field=models.RuleField.description,
        pattern_type=models.RulePatternType.contains, pattern="hulu",
        action=models.RuleAction.set_category, category_id=cats["home"].id,
    ))
    db_session.commit()
    by_name = {u.name: u for u in build_triage(db_session, user.id).uncategorized}
    assert by_name["Hulu"].guess_category_name == "Home"


def test_badge_totals(db_session):
    user, *_ = _seed(db_session)
    out = build_triage(db_session, user.id)
    assert out.unclassified_count == 3
    assert out.unclassified_monthly_total == Decimal("83.00")


def test_untracked_patterns_carry_a_pattern_key(db_session):
    user, *_ = _seed(db_session)
    out = build_triage(db_session, user.id)
    assert [s.pattern_key for s in out.untracked] == ["acme cloud storage"]


def test_dismissed_pattern_is_hidden_from_detector(db_session):
    user, *_ = _seed(db_session)
    db_session.add(models.RecurringDismissal(user_id=user.id, pattern_key="acme cloud storage"))
    db_session.commit()
    assert detect_patterns(db_session, user.id) == []


def test_duplicates_flagged_and_dismissable(db_session):
    user, _, _, items = _seed(db_session)
    out = build_triage(db_session, user.id)
    key = duplicate_pair_key(items["netflix"].id, items["netflix2"].id)
    assert [d.pair_key for d in out.duplicates] == [key]

    db_session.add(models.RecurringDismissal(user_id=user.id, pattern_key=key))
    db_session.commit()
    assert build_triage(db_session, user.id).duplicates == []


def test_triage_route_is_not_swallowed_by_item_id_route(db_session):
    user, *_ = _seed(db_session)
    r = _client(db_session, user).get("/recurring/triage")
    assert r.status_code == 200
    assert r.json()["unclassified_count"] == 3
