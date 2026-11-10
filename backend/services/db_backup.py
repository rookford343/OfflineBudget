"""WAL-safe SQLite backups.

`data/budget.db` runs in WAL mode, so the .db file alone is only current as
of SQLite's last checkpoint -- everything since lives in `budget.db-wal`.
Copying just the .db (shutil.copy2, `cp`) therefore produces a snapshot from
whenever that checkpoint happened, silently missing every write after it.
Found 2026-09-17: the main file was a month stale (2026-08-19) while 2.6MB of
live data sat in the WAL, which meant every "pre-change backup" this repo had
ever written was unrestorable.

sqlite3's own backup API reads through the WAL and writes a standalone file
with no sidecars, which is what a restore point has to be.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def backup_database(src_path: str | Path, dest_path: str | Path) -> Path:
    """Copy the SQLite database at `src_path` to `dest_path`, WAL included.

    Creates `dest_path`'s parent directories if needed. Returns `dest_path`.
    """
    src = Path(src_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(src)
    try:
        destination = sqlite3.connect(dest)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return dest


_STAMP = "%Y%m%d-%H%M%S"


def _snapshot_time(path: Path) -> datetime | None:
    """Timestamp encoded in a `startup-<stamp>.db` name; None if it doesn't parse."""
    try:
        return datetime.strptime(path.stem.removeprefix("startup-"), _STAMP)
    except ValueError:
        return None


def startup_backup(
    src_path: str | Path,
    backup_dir: str | Path,
    keep: int = 10,
    min_interval: timedelta = timedelta(minutes=10),
    retain: timedelta = timedelta(hours=48),
    now: datetime | None = None,
) -> Path | None:
    """Snapshot the live DB to `backup_dir/startup-<timestamp>.db` before the
    server starts (and migrates).

    - Returns None when `src_path` doesn't exist (fresh install).
    - Throttle: if a startup snapshot is younger than `min_interval` (and not
      future-dated),
      no new one is taken and that path is returned. Under a KeepAlive
      crash-restart loop this keeps the pre-crash snapshot from being rotated out.
    - Retention: a `startup-*.db` is deleted only if it is BOTH outside the
      newest `keep` AND older than `retain`. Other files are never touched.
    """
    src = Path(src_path)
    if not src.exists():
        return None
    out_dir = Path(backup_dir)
    # Naive UTC throughout: filenames carry UTC stamps, immune to DST/zone changes.
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    def _existing() -> list[tuple[datetime, Path]]:
        found = [(t, p) for p in out_dir.glob("startup-*.db")
                 if (t := _snapshot_time(p)) is not None]
        return sorted(found, key=lambda tp: tp[0], reverse=True)  # newest first

    existing = _existing()
    # Future-dated files (clock stepped backwards) never count as "recent",
    # otherwise they would suppress snapshots until the clock catches up.
    recent = [(t, p) for t, p in existing if timedelta(0) <= now - t < min_interval]
    if recent:
        print(f"startup_backup: skipped, recent snapshot {recent[0][1].name} exists")
        return recent[0][1]

    dest = backup_database(src, out_dir / f"startup-{now.strftime(_STAMP)}.db")
    for t, old in _existing()[keep:]:
        if max(now - t, timedelta(0)) > retain:
            old.unlink()
    return dest


def database_file_from_url(url: str) -> Path:
    """File path of a sqlite SQLAlchemy URL (relative paths resolve against the
    cwd, exactly as the app's engine resolves them). Raises ValueError otherwise."""
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database \
            or parsed.database == ":memory:":
        raise ValueError("DATABASE_URL is not a file-backed sqlite database")
    return Path(parsed.database)


def main() -> int:
    """Production pre-start snapshot of the database the app will actually open."""
    from backend.config import settings

    try:
        src = database_file_from_url(settings.DATABASE_URL)
    except ValueError as exc:
        print(f"ERROR: cannot snapshot: {exc}", file=sys.stderr)
        return 1
    path = startup_backup(src, "data/backups", keep=10)
    print("startup_backup:", path or "skipped (no database yet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
