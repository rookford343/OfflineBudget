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
    # Guards Review Focus #1: `settled_on` alone (no `actual_amount`) must
    # count as unpaid, not cleared. If `_is_cleared` ever regresses to check
    # only `settled_on`, this won't fail as a clean assertion below -- it
    # fails as an unhandled IntegrityError (NOT NULL on `amount`), because
    # the code would then try to build a refund-watch by copying
    # legs[0].actual_amount, which is None. That crash *is* the regression
    # signal here: a 500 on this delete means "didn't happen" started being
    # treated as cleared.
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

def test_deleting_an_anchor_with_an_existing_refund_watch_retargets_it(db_session):
    # Regression for the Critical bug a task reviewer found in this file's
    # first round: `_retarget_group`'s survivor list used to come only from
    # `cancel_installment_group`'s `siblings` query, which deliberately
    # excludes refund-watch rows. That's correct for cascade *decisions*
    # (a refund-watch never gets swept, never makes a group "still has
    # something to cancel"), but it also meant a refund-watch's own
    # installment_group_id was invisible to the retarget step -- so
    # deleting the anchor leg out from under an already-open refund-watch
    # left the refund-watch referencing a row that no longer existed, and
    # SQLite's FK check rejected the delete outright (an unhandled
    # IntegrityError surfacing as a 500 on a routine delete).
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("50.00")
    db_session.commit()
    client = _client(db_session, user)

    # legs[0] (the anchor) is cleared and survives; legs[1] gets swept and
    # opens a refund-watch against legs[0].
    assert client.delete(f"/planned-expenses/{legs[1].id}").status_code == 204
    refund = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.is_refund_watch.is_(True),
    ).one()
    assert refund.installment_group_id == legs[0].id

    # Now delete the anchor itself, with the refund-watch still open against
    # it. Must succeed (204, not an unhandled exception/500).
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204

    remaining = db_session.query(models.PlannedExpense).filter(models.PlannedExpense.user_id == user.id).all()
    assert [pe.id for pe in remaining] == [refund.id]  # only the refund-watch itself survives
    db_session.refresh(refund)
    # Whatever group id it carries now has to point at a row that actually
    # exists -- here, since nothing else survived, at itself.
    assert refund.installment_group_id == refund.id
    assert db_session.query(models.PlannedExpense.id).filter(
        models.PlannedExpense.id == refund.installment_group_id,
    ).first() is not None

def test_deleting_an_uncleared_anchor_retargets_two_cleared_survivors_at_once(db_session):
    # Coverage gap a task reviewer flagged: every other test in this file
    # uses a 2-leg group, so `_retarget_group`'s loop over *multiple*
    # survivors never actually ran with more than zero/one real survivor.
    # 3 legs: the anchor (legs[0]) is uncleared and gets swept; legs[1] and
    # legs[2] are both cleared and must both land on the same new anchor,
    # each with its own correctly-pointed refund-watch.
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00", "100.00"])
    legs[1].settled_on = date.today()
    legs[1].actual_amount = Decimal("72.00")
    legs[2].settled_on = date.today()
    legs[2].actual_amount = Decimal("98.50")
    db_session.commit()
    client = _client(db_session, user)

    assert legs[0].installment_group_id == legs[0].id  # legs[0] is the anchor
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204

    remaining = db_session.query(models.PlannedExpense).filter(models.PlannedExpense.user_id == user.id).all()
    assert len(remaining) == 4  # legs[1], legs[2], and one refund-watch each
    assert db_session.query(models.PlannedExpense).filter(models.PlannedExpense.id == legs[0].id).first() is None

    survivor_legs = {pe.id: pe for pe in remaining if not pe.is_refund_watch}
    assert set(survivor_legs) == {legs[1].id, legs[2].id}
    new_anchor_id = min(legs[1].id, legs[2].id)
    assert all(pe.installment_group_id == new_anchor_id for pe in remaining)  # all four, same new anchor

    refunds = {r.amount: r for r in remaining if r.is_refund_watch}
    assert set(refunds) == {Decimal("72.00"), Decimal("98.50")}
    for refund in refunds.values():
        assert refund.direction == models.PlannedDirection.inflow
        assert refund.installment_group_id == new_anchor_id

def test_deleting_the_anchor_refund_watch_retargets_the_sibling_refund_watch(db_session):
    # Regression for the Critical bug a final whole-branch review found:
    # once a cascade strips a group down to refund-watch rows only, one of
    # them ends up as the group's current anchor (installment_group_id ==
    # its own id), same as any ordinary leg would. The router's delete
    # endpoint sent every is_refund_watch=True row straight to the plain
    # TripItem-detach-then-delete branch with no retargeting at all, so
    # deleting that anchor refund-watch left the sibling refund-watch
    # referencing a row that no longer existed -- an unhandled
    # IntegrityError surfacing as a 500 on a routine delete.
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00", "40.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("48.00")
    legs[1].settled_on = date.today()
    legs[1].actual_amount = Decimal("73.00")
    db_session.commit()
    client = _client(db_session, user)

    # Delete the remaining uncleared leg -- opens a refund-watch for each
    # of the two cleared legs, both pointing at legs[0] (the anchor).
    assert client.delete(f"/planned-expenses/{legs[2].id}").status_code == 204
    refunds = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.is_refund_watch.is_(True),
    ).all()
    assert len(refunds) == 2
    assert all(r.installment_group_id == legs[0].id for r in refunds)

    # Delete both cleared history legs in turn -- each goes through
    # cancel_installment_group's "fully resolved" branch (no uncleared
    # sibling left either time), which retargets the open refund-watches
    # off the departing anchor on the way out.
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204
    assert client.delete(f"/planned-expenses/{legs[1].id}").status_code == 204

    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.user_id == user.id,
    ).all()
    assert len(remaining) == 2
    assert all(pe.is_refund_watch for pe in remaining)
    anchor = next(pe for pe in remaining if pe.installment_group_id == pe.id)
    other = next(pe for pe in remaining if pe.id != anchor.id)
    assert other.installment_group_id == anchor.id

    # Delete the anchor refund-watch directly. Must succeed (204, not an
    # unhandled exception/500), and the sibling left behind must land on a
    # new anchor that actually exists -- here, since it's the only row
    # left, its own id.
    assert client.delete(f"/planned-expenses/{anchor.id}").status_code == 204

    assert db_session.query(models.PlannedExpense.id).filter(
        models.PlannedExpense.id == anchor.id,
    ).first() is None
    db_session.refresh(other)
    assert other.installment_group_id == other.id
    assert db_session.query(models.PlannedExpense.id).filter(
        models.PlannedExpense.id == other.installment_group_id,
    ).first() is not None

def test_re_cancelling_a_group_does_not_double_the_same_refund_watch(db_session):
    # Regression: cancel_installment_group always created a fresh
    # refund-watch for every currently-cleared sibling, with no check for
    # one already open against it. Reachable without fabricating any state
    # -- just real endpoint calls:
    #   1. Clear two of three legs (X and Y); delete the third, uncleared
    #      anchor leg. That single cascade sweeps the anchor and opens one
    #      refund-watch each for X and Y (both now cleared survivors).
    #   2. Unsettle Y (POST .../unsettle) -- it goes back to uncleared, but
    #      its refund-watch from step 1 is untouched.
    #   3. Delete Y again. Y is uncleared again, so this is a real cascade,
    #      not the "fully resolved" branch -- and X is still cleared, still
    #      carrying its refund-watch from step 1. Without the dedupe guard,
    #      the loop re-adds a second "X -- refund expected" row for X, even
    #      though nothing about X changed between step 1 and step 3.
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00", "40.00"])
    anchor, x, y = legs
    x.settled_on = date.today()
    x.actual_amount = Decimal("73.00")
    y.settled_on = date.today()
    y.actual_amount = Decimal("38.00")
    db_session.commit()
    client = _client(db_session, user)

    # Step 1: delete the uncleared anchor -- opens one refund-watch each for
    # x and y, retargeted onto a new anchor (the lower-id cleared survivor).
    assert client.delete(f"/planned-expenses/{anchor.id}").status_code == 204
    refunds_after_first_cascade = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.is_refund_watch.is_(True),
    ).all()
    assert len(refunds_after_first_cascade) == 2
    x_refund_name = f"{x.name} — refund expected"
    assert sum(1 for r in refunds_after_first_cascade if r.name == x_refund_name) == 1

    # Step 2: unsettle y -- back to uncleared, x and its refund-watch
    # untouched.
    assert client.post(f"/planned-expenses/{y.id}/unsettle").status_code == 200
    db_session.refresh(y)
    assert y.settled_on is None and y.actual_amount is None

    # Step 3: delete y again. y is uncleared, so this is a real cascade
    # (not "fully resolved"); x is still cleared and still has its
    # refund-watch from step 1 untouched -- this must not spawn a second one.
    assert client.delete(f"/planned-expenses/{y.id}").status_code == 204

    x_refunds = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.is_refund_watch.is_(True),
        models.PlannedExpense.name == x_refund_name,
    ).all()
    assert len(x_refunds) == 1  # not 2
