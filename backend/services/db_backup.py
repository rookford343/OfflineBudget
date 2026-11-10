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
from datetime import datetime, timedelta
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
    - Throttle: if the newest startup snapshot is younger than `min_interval`,
      no new one is taken and that path is returned. Under a KeepAlive
      crash-restart loop this keeps the pre-crash snapshot from being rotated out.
    - Retention: a `startup-*.db` is deleted only if it is BOTH outside the
      newest `keep` AND older than `retain`. Other files are never touched.
    """
    src = Path(src_path)
    if not src.exists():
        return None
    out_dir = Path(backup_dir)
    now = now or datetime.now()

    def _existing() -> list[tuple[datetime, Path]]:
        found = [(t, p) for p in out_dir.glob("startup-*.db")
                 if (t := _snapshot_time(p)) is not None]
        return sorted(found, key=lambda tp: tp[0], reverse=True)  # newest first

    existing = _existing()
    if existing and now - existing[0][0] < min_interval:
        print(f"startup_backup: skipped, newest snapshot {existing[0][1].name} is recent")
        return existing[0][1]

    dest = backup_database(src, out_dir / f"startup-{now.strftime(_STAMP)}.db")
    for t, old in _existing()[keep:]:
        if now - t > retain:
            old.unlink()
    return dest
