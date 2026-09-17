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
