from decimal import Decimal
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend import models
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


@pytest.fixture()
def test_user(db_session):
    """A bare user row -- shared shape for tests that just need a valid
    user_id and don't care about identity details."""
    user = models.User(username="testuser", hashed_password="x", display_name="Test User")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def test_account(db_session, test_user):
    """A checking account owned by test_user, for tests that need a valid
    account_id."""
    account = models.Account(
        user_id=test_user.id, name="Test Checking",
        type=models.AccountType.checking, current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture()
def test_card(db_session, test_user):
    """A credit card owned by test_user, for tests that need a valid
    card_id."""
    card = models.CreditCard(
        user_id=test_user.id, name="Test Card", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("0.00"),
    )
    db_session.add(card)
    db_session.commit()
    return card
