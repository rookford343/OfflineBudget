import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from backend.services.db_backup import backup_database, startup_backup


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


def test_startup_backup_snapshot_contains_wal_only_row(tmp_path):
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)

    snap = startup_backup(src, tmp_path / "backups")

    assert snap is not None and snap.parent == tmp_path / "backups"
    assert snap.name.startswith("startup-") and snap.suffix == ".db"
    conn = sqlite3.connect(snap)
    try:
        rows = conn.execute("SELECT name FROM plans").fetchall()
    finally:
        conn.close()
    assert rows == [("Rivian R2 purchase",)]


def test_startup_backup_missing_source_returns_none(tmp_path):
    assert startup_backup(tmp_path / "nope.db", tmp_path / "backups") is None
    assert not (tmp_path / "backups").exists()


NOW = datetime(2026, 11, 9, 12, 0, 0)


def _touch_startup(backups: Path, when: datetime) -> Path:
    f = backups / f"startup-{when:%Y%m%d-%H%M%S}.db"
    f.write_text("old")
    return f


def test_startup_backup_throttles_rapid_calls_to_one_file(tmp_path):
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)
    backups = tmp_path / "backups"

    first = startup_backup(src, backups, now=NOW)
    second = startup_backup(src, backups, now=NOW + timedelta(seconds=10))
    third = startup_backup(src, backups, now=NOW + timedelta(minutes=9))
    later = startup_backup(src, backups, now=NOW + timedelta(minutes=11))

    assert second == first and third == first
    assert later != first
    assert len(list(backups.glob("startup-*.db"))) == 2


def test_startup_backup_retention_needs_outside_newest_ten_and_over_48h(tmp_path):
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = [_touch_startup(backups, NOW - timedelta(hours=49 + i)) for i in range(12)]
    recent = [_touch_startup(backups, NOW - timedelta(hours=h)) for h in (1, 2, 3)]
    other = backups / "pre-deploy-x.db"
    other.write_text("keep me")

    snap = startup_backup(src, backups, now=NOW)

    # 16 startup files total; newest 10 = new + 3 recent + the 6 newest old ones.
    # The 6 oldest old files are outside the newest 10 AND >48h, so they go.
    expected = {snap, *recent, *old[:6]}
    assert set(backups.glob("startup-*.db")) == expected
    assert other.read_text() == "keep me"


def test_startup_backup_keeps_recent_files_even_outside_newest_ten(tmp_path):
    src = tmp_path / "budget.db"
    _wal_db_with_uncheckpointed_write(src)
    backups = tmp_path / "backups"
    backups.mkdir()
    recent = [_touch_startup(backups, NOW - timedelta(hours=1, minutes=i)) for i in range(12)]

    startup_backup(src, backups, now=NOW)

    assert all(f.exists() for f in recent)  # all <48h: none deleted despite 13 > keep
