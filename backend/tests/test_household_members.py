from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import household_members as household_members_router_module


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(checking)
    db_session.commit()
    db_session.refresh(checking)

    app = FastAPI()
    app.include_router(household_members_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking


def test_create_and_list_household_member(client):
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Test Member"})
    assert r.status_code == 201
    member_id = r.json()["id"]

    r2 = test_client.get("/household-members")
    assert any(m["id"] == member_id for m in r2.json())


def test_duplicate_name_rejected(client):
    test_client, user, checking = client

    test_client.post("/household-members", json={"name": "Test Member"})
    r = test_client.post("/household-members", json={"name": "Test Member"})
    assert r.status_code == 400


def test_recurring_item_owner_id_defaults_null(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.owner_id is None


def test_delete_blocked_while_referenced_by_recurring_item(client, db_session):
    """Mirrors categories.py's delete_category sub-category guard (400, not a
    raw FK-constraint 500) -- applied to the one FK relationship categories.py
    itself doesn't guard: RecurringItem.owner_id."""
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Spouse"})
    member_id = r.json()["id"]

    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Spouse's Car Payment",
        amount=Decimal("350.00"), type=models.RecurringType.expense,
        day_of_month=1, start_date=date(2026, 1, 1), owner_id=member_id,
    )
    db_session.add(item)
    db_session.commit()

    r2 = test_client.delete(f"/household-members/{member_id}")
    assert r2.status_code == 400
    assert r2.json()["detail"] == "Cannot delete a household member referenced by recurring items"

    # Still there -- the blocked delete must not have removed it.
    r3 = test_client.get("/household-members")
    assert any(m["id"] == member_id for m in r3.json())


def test_delete_unreferenced_household_member_succeeds(client):
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Kid"})
    member_id = r.json()["id"]

    r2 = test_client.delete(f"/household-members/{member_id}")
    assert r2.status_code == 204

    r3 = test_client.get("/household-members")
    assert not any(m["id"] == member_id for m in r3.json())


def test_delete_allowed_when_only_referencing_item_is_soft_deleted(client, db_session):
    """A recurring item that referenced this member but was later soft-deleted
    (is_active=False) must not count toward the delete guard -- the guard's
    reference count only considers active items, the same convention
    by_category/by_owner already use elsewhere for 'does this item count'.
    Otherwise a removed item permanently blocks deleting the member it once
    pointed at."""
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Former Roommate"})
    member_id = r.json()["id"]

    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Old Rent Split",
        amount=Decimal("300.00"), type=models.RecurringType.expense,
        day_of_month=1, start_date=date(2026, 1, 1), owner_id=member_id,
        is_active=False,
    )
    db_session.add(item)
    db_session.commit()

    r2 = test_client.delete(f"/household-members/{member_id}")
    assert r2.status_code == 204


def test_delete_ignores_other_users_recurring_item_pointing_at_this_member(client, db_session):
    """Defensive: the delete-guard's reference count is scoped to the
    caller's own recurring items, not just to this member's id. Create/update
    now block tagging another user's member via owner_id, but the guard
    stays user-scoped regardless -- so this user's own active items never
    block the delete based on another tenant's data.

    The bulk FK-clear that runs after the guard is also user-scoped: it must
    never mutate another tenant's row, even a stale cross-tenant reference
    like this test's `cross_user_item` (pre-dating recurring.py's ownership
    validation). Left untouched, that row's owner_id FK still points at this
    member, so the delete can't actually complete -- it must come back as
    the same 400 the guard above uses, not a silent 204 (which would mean
    the cross-user row got mutated) and not an unhandled 500 (a raw FK
    IntegrityError)."""
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Widely Tagged"})
    member_id = r.json()["id"]

    other = models.User(username="other-ho", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.flush()
    other_checking = models.Account(user_id=other.id, name="Other Checking", type=models.AccountType.checking)
    db_session.add(other_checking)
    db_session.flush()
    cross_user_item = models.RecurringItem(
        user_id=other.id, account_id=other_checking.id, name="Other's Item",
        amount=Decimal("50.00"), type=models.RecurringType.expense,
        day_of_month=1, start_date=date(2026, 1, 1), owner_id=member_id,
    )
    db_session.add(cross_user_item)
    db_session.commit()

    r2 = test_client.delete(f"/household-members/{member_id}")
    # The scoped bulk-clear correctly leaves this stale cross-tenant
    # reference alone, which means the member can't actually be deleted
    # (its row is still FK-referenced) -- the delete is refused with the
    # same 400 the active-item guard above uses, rather than silently
    # succeeding (which would require mutating another tenant's row) or
    # raising an unhandled FK IntegrityError.
    assert r2.status_code == 400

    # Confirm the member was NOT deleted and the cross-user item's owner_id
    # was left completely alone -- still pointing at the (still-existing)
    # member, since the delete never happened.
    db_session.refresh(cross_user_item)
    assert cross_user_item.owner_id == member_id
    assert db_session.get(models.HouseholdMember, member_id) is not None
