import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.database import Base


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite session per test — no fixtures shared across tests.

    StaticPool keeps a single physical connection alive for the whole engine
    (instead of SQLAlchemy's default one-connection-per-thread pool for
    `:memory:` URLs), so a TestClient dispatching a request onto a worker
    thread sees the same schema/data the fixture set up on the main thread.

    PRAGMA foreign_keys=ON mirrors database.py's production setting -- a test
    suite that runs looser than production can't catch an FK-violating delete
    before it ships."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
