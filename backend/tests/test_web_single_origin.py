"""Single origin: API under /api, SPA fallback for client routes, security headers."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.main as main
from backend.web import SecurityHeadersMiddleware, mount_frontend

HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "content-security-policy": (
        "default-src 'self'; script-src 'self' https://cdn.plaid.com; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self' https://*.plaid.com; manifest-src 'self'; worker-src 'self'; "
        "frame-src https://cdn.plaid.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
def client(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("SPA")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(main.api_router)
    mount_frontend(app, str(dist))
    return TestClient(app)


def test_api_routes_live_under_api(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    assert client.get("/health").text == "SPA"  # not the health JSON


def test_spa_fallback_serves_index_for_client_routes(client):
    for path in ("/dashboard", "/forecast"):
        resp = client.get(path)
        assert resp.status_code == 200 and resp.text == "SPA"


def test_spa_fallback_is_get_only(client):
    assert client.post("/dashboard").status_code in (404, 405)
    assert client.post("/dashboard").text != "SPA"


def test_unknown_api_path_is_json_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.text != "SPA"


def test_static_asset_served(client):
    assert client.get("/assets/app.js").status_code == 200


@pytest.mark.parametrize("path", ["/api/health", "/dashboard"])
def test_security_headers_on_api_and_static(client, path):
    resp = client.get(path)
    for name, value in HEADERS.items():
        assert resp.headers[name] == value, name


def test_main_app_sends_security_headers():
    resp = TestClient(main.app).get("/api/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
