"""Run-script guards: production is HTTPS-only, dev is loopback-only and never the live DB."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "scripts" / "run-production.sh"
DEV = ROOT / "scripts" / "start.sh"


def _run(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    full_env.update(env or {})
    return subprocess.run(  # noqa: S603 - fixed bash + repo-owned script path, no user input
        ["/bin/bash", str(script), *args],
        capture_output=True, text=True, cwd=ROOT, env=full_env, check=False, timeout=60,
    )


@pytest.fixture
def prod_dirs(tmp_path: Path) -> dict[str, str]:
    ssl_dir = tmp_path / "ssl"
    dist = tmp_path / "dist"
    ssl_dir.mkdir()
    dist.mkdir()
    (ssl_dir / "server.crt").write_text("x")
    (ssl_dir / "server.key").write_text("x")
    (dist / "index.html").write_text("<html></html>")
    return {"OB_SSL_DIR": str(ssl_dir), "OB_DIST_DIR": str(dist)}


def test_production__no_cert__refuses(tmp_path: Path, prod_dirs: dict[str, str]) -> None:
    empty = tmp_path / "nossl"
    empty.mkdir()
    r = _run(PROD, "--check", env={**prod_dirs, "OB_SSL_DIR": str(empty)})
    assert r.returncode == 1
    assert "ssl/server.crt" in r.stderr


def test_production__no_dist__refuses(tmp_path: Path, prod_dirs: dict[str, str]) -> None:
    empty = tmp_path / "nodist"
    empty.mkdir()
    r = _run(PROD, "--check", env={**prod_dirs, "OB_DIST_DIR": str(empty)})
    assert r.returncode == 1
    assert "index.html" in r.stderr


def test_production__check__https_only_no_reload(prod_dirs: dict[str, str]) -> None:
    r = _run(PROD, "--check", env=prod_dirs)
    assert r.returncode == 0, r.stderr
    assert "--ssl-certfile" in r.stdout
    assert "--port 443" in r.stdout
    assert "--no-proxy-headers" in r.stdout
    assert "--reload" not in r.stdout
    assert "--port 8000" not in r.stdout


def test_dev__live_db__refuses() -> None:
    for url in (
        "sqlite:///./data/budget.db",
        f"sqlite:///{ROOT}/data/budget.db",
        "sqlite:///data/../data/budget.db",
    ):
        r = _run(DEV, "--check", env={"DATABASE_URL": url})
        assert r.returncode == 1, url
        assert "budget.db" in r.stderr


def test_dev__check__loopback_and_scheduler_off() -> None:
    r = _run(DEV, "--check")
    assert r.returncode == 0, r.stderr
    assert "--host 127.0.0.1" in r.stdout
    assert "SCHEDULER_ENABLED=false" in r.stdout
    assert "0.0.0.0" not in r.stdout  # noqa: S104 - asserting the absence of an all-interfaces bind
    assert "--reload" in r.stdout
