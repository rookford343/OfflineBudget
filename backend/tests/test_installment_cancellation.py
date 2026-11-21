from datetime import date, datetime, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.installment_plan import create_installment_group
from backend.services.planned_auto_settle import auto_settle_planned_expenses

def _seed(db):
    user = models.User(username="cancel", hashed_password="x", display_name="Cancel")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user, account

def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)

def _group(db, user, account, amounts):
    legs = create_installment_group(db, user, schemas.PlannedExpenseInstallmentsCreate(
        name="Dental", account_id=account.id, legs=[
            {"amount": a, "expected_date": (date.today() + timedelta(days=i * 30)).isoformat()}
            for i, a in enumerate(amounts)
        ],
    ))
    db.commit()
    return legs

def test_deleting_an_unpaid_leg_cancels_the_whole_group(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert remaining == []

def test_deleting_a_cleared_leg_sweeps_the_unpaid_sibling_and_opens_a_refund_watch(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    # Deliberately different from the $50.00 estimate -- the dentist charged
    # a bit less than planned -- so a refund-watch built from the estimate
    # instead of the actual would show up as a wrong amount below, not get
    # masked by the two numbers coincidentally matching.
    legs[0].actual_amount = Decimal("48.25")
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204

    group_rows = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert {pe.id for pe in group_rows} & {legs[1].id} == set()  # unpaid sibling swept
    assert any(pe.id == legs[0].id for pe in group_rows)  # cleared leg kept as history

    refund = next(pe for pe in group_rows if pe.is_refund_watch)
    assert refund.direction == models.PlannedDirection.inflow
    assert refund.amount == Decimal("48.25")
    assert refund.account_id == account.id
    assert refund.expected_date == date.today()

def test_settled_with_no_actual_amount_counts_as_unpaid(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()  # "didn't happen" -- no actual_amount
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[1].id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert remaining == []  # both swept, no refund-watch for the "didn't happen" leg

def test_deleting_the_refund_watch_itself_does_not_recascade(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("50.00")
    db_session.commit()
    client = _client(db_session, user)
    client.delete(f"/planned-expenses/{legs[0].id}")
    refund = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
        models.PlannedExpense.is_refund_watch.is_(True),
    ).one()

    # A completed cascade never actually leaves an uncleared leg sitting
    # next to a refund-watch row -- the sweep that spawned the refund-watch
    # already cleared every uncleared sibling out in the same pass. Plant
    # one anyway: without the router's `is_refund_watch` guard, deleting
    # `refund` below would see this row as an ordinary uncleared sibling of
    # the group and sweep it too, so this is what actually tells "the
    # refund-watch delete is exempt from the cascade" apart from "the group
    # had nothing left to sweep regardless."
    sentinel = models.PlannedExpense(
        user_id=user.id, name="Sentinel", amount=Decimal("5.00"),
        expected_date=date.today(), account_id=account.id,
        installment_group_id=legs[0].id,
    )
    db_session.add(sentinel)
    db_session.commit()

    assert client.delete(f"/planned-expenses/{refund.id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    # only the cleared leg and the untouched sentinel are left
    assert {pe.id for pe in remaining} == {legs[0].id, sentinel.id}

def test_deleting_history_after_the_group_already_fully_settled_does_not_spawn_a_refund(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    for leg, amt in zip(legs, (Decimal("50.00"), Decimal("75.00"))):
        leg.settled_on = date.today()
        leg.actual_amount = amt
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204
    # legs[0] was the group's anchor (installment_group_id == legs[0].id), so
    # it can't simply vanish while legs[1] still points at it -- the FK
    # would reject that delete. legs[1] survives re-pointed to a new anchor
    # (its own id), so "what's left" has to be queried by user, not by the
    # now-defunct old group id.
    assert db_session.query(models.PlannedExpense).filter(models.PlannedExpense.id == legs[0].id).first() is None
    remaining = db_session.query(models.PlannedExpense).filter(models.PlannedExpense.user_id == user.id).all()
    assert [pe.id for pe in remaining] == [legs[1].id]
    assert not any(pe.is_refund_watch for pe in remaining)

def test_plain_one_off_delete_is_unaffected(db_session):
    user, account = _seed(db_session)
    pe = models.PlannedExpense(
        user_id=user.id, name="Plain", amount=Decimal("10.00"),
        expected_date=date.today(), account_id=account.id,
    )
    db_session.add(pe)
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{pe.id}").status_code == 204
    assert db_session.query(models.PlannedExpense).filter(models.PlannedExpense.id == pe.id).first() is None

def test_refund_watch_settles_through_the_existing_auto_settle_matcher(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("50.00")
    db_session.commit()
    client = _client(db_session, user)
    client.delete(f"/planned-expenses/{legs[0].id}")
    refund = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
        models.PlannedExpense.is_refund_watch.is_(True),
    ).one()

    db_session.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id="refund-1", date=date.today(),
        amount=Decimal("50.00"), description="Dental refund", synced_at=datetime.utcnow(),
    ))
    db_session.commit()

    settlements = auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    assert any(s.planned_expense_id == refund.id for s in settlements)
    db_session.refresh(refund)
    assert refund.is_settled
