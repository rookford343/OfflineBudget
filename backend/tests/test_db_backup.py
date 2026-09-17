import sqlite3
from pathlib import Path

from backend.services.db_backup import backup_database


def _wal_db_with_uncheckpointed_write(path: Path) -> None:
    """A SQLite db in WAL mode whose newest row lives only in the -wal file.

    This is the real shape of data/budget.db: its main .db file was last
    checkpointed 2026-08-19 while ~2.6MB of live data sat in budget.db-wal.
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE plans (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # Written AFTER the checkpoint, so it exists only in the -wal file.
    conn.execute("INSERT INTO plans (id, name) VALUES (1, 'Rivian R2 purchase')")
    conn.commit()
    conn.close()


def test_backup_captures_rows_that_live_only_in_the_wal(tmp_path):
    """Real incident, 2026-09-17: every db backup this repo had taken used
    shutil.copy2/cp on the .db file alone, which silently omits the -wal --
    so each "restore point" was really a snapshot from whenever SQLite last
    checkpointed (a month earlier), and nobody noticed until a copy was
    opened and found to be missing a month of data."""
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)
    dest = tmp_path / "backup.db"

    backup_database(src, dest)

    rows = sqlite3.connect(dest).execute("SELECT name FROM plans").fetchall()
    assert rows == [("Rivian R2 purchase",)]


def test_backup_leaves_a_standalone_file_with_no_sidecars(tmp_path):
    """The backup has to be restorable on its own -- a copy that still needs
    its original's -wal alongside it isn't a restore point."""
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)
    dest = tmp_path / "backup.db"

    backup_database(src, dest)

    assert dest.exists()
    assert not (tmp_path / "backup.db-wal").exists()
    assert not (tmp_path / "backup.db-shm").exists()


def test_backup_returns_the_destination_path(tmp_path):
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)
    dest = tmp_path / "nested" / "backup.db"

    result = backup_database(src, dest)

    assert result == dest
    assert dest.exists(), "parent directories should be created"
