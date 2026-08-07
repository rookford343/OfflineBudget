import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.database import Base


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite session per test — no fixtures shared across tests.

    StaticPool keeps a single physical connection alive for the whole engine
    (instead of SQLAlchemy's default one-connection-per-thread pool for
    `:memory:` URLs), so a TestClient dispatching a request onto a worker
    thread sees the same schema/data the fixture set up on the main thread."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
