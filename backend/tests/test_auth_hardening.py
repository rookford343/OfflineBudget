"""Auth hardening: self-registration only bootstraps an empty install, one
password rule everywhere, login attempts are rate limited, and the View Only
role is read-only on every data endpoint."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.auth import create_access_token, hash_password
from backend.dependencies import get_db
from backend.routers import accounts as accounts_router_module
from backend.routers import admin as admin_router_module
from backend.routers import auth as auth_router_module
from backend.services.rate_limiter import _reset_for_tests


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    for r in (auth_router_module, admin_router_module, accounts_router_module):
        app.include_router(r.router)
    app.dependency_overrides[get_db] = lambda: db_session
    _reset_for_tests()
    return TestClient(app)


def _user(db, username, role=models.UserRole.admin, linked_to=None):
    u = models.User(username=username, hashed_password=hash_password("good-password"),
                    display_name=username, role=role, linked_to_user_id=linked_to)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.username)}"}


def _register(client, password="good-password", username="first"):
    return client.post("/auth/register", json={"username": username, "password": password,
                                                 "display_name": username})


def test_first_user_can_register_and_is_admin(client):
    resp = _register(client)
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "admin"


def test_registration_is_closed_once_any_user_exists(client, db_session):
    _user(db_session, "owner")
    resp = _register(client, username="stranger")
    assert resp.status_code == 403
    assert db_session.query(models.User).filter_by(username="stranger").first() is None


def test_stranger_cannot_take_over_an_existing_account(client, db_session):
    owner = _user(db_session, "owner")
    assert _register(client, username="stranger").status_code == 403
    resp = client.post(f"/admin/users/{owner.id}/reset-password", json={"new_password": "pwned123"})
    assert resp.status_code == 401


@pytest.mark.parametrize("call", ["register", "change", "admin_create", "admin_reset"])
def test_short_passwords_are_rejected_everywhere(client, db_session, call):
    if call == "register":
        resp = _register(client, password="x")
    else:
        admin = _user(db_session, "owner")
        if call == "change":
            resp = client.patch("/auth/me/password", headers=_auth(admin),
                                json={"current_password": "good-password", "new_password": "x"})
        elif call == "admin_create":
            resp = client.post("/admin/users", headers=_auth(admin),
                               json={"username": "kid", "password": "x", "display_name": "Kid"})
        else:
            resp = client.post(f"/admin/users/{admin.id}/reset-password", headers=_auth(admin),
                               json={"new_password": "x"})
    assert resp.status_code == 400


def test_login_is_rate_limited_after_ten_failures(client, db_session):
    _user(db_session, "owner")
    bad = {"username": "owner", "password": "wrong-password"}
    for _ in range(10):
        assert client.post("/auth/login", json=bad).status_code == 401
    assert client.post("/auth/login", json=bad).status_code == 429
    good = {"username": "owner", "password": "good-password"}
    assert client.post("/auth/login", json=good).status_code == 429


def test_view_only_member_can_read_but_not_write_owner_data(client, db_session):
    owner = _user(db_session, "owner")
    viewer = _user(db_session, "viewer", role=models.UserRole.viewer, linked_to=owner.id)
    assert client.get("/accounts", headers=_auth(viewer)).status_code == 200
    resp = client.post("/accounts", headers=_auth(viewer),
                       json={"name": "Sneaky", "type": "checking", "current_balance": "1"})
    assert resp.status_code == 403
    assert db_session.query(models.Account).count() == 0


def test_view_only_member_can_still_change_their_own_password(client, db_session):
    owner = _user(db_session, "owner")
    viewer = _user(db_session, "viewer", role=models.UserRole.viewer, linked_to=owner.id)
    resp = client.patch("/auth/me/password", headers=_auth(viewer),
                        json={"current_password": "good-password", "new_password": "new-password"})
    assert resp.status_code == 204
