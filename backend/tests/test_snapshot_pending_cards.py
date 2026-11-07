"""The budget snapshot reports how many active cards carry fresh pending
charges and their total, through the same accessor and freshness rule the
forecast uses (services/pending.card_pending)."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from backend import models
from backend.schemas import ForecastEntry
from backend.services.budget_snapshot import compute_budget_snapshot

AS_OF = date(2026, 8, 7)


def _card(user, name, pending, stamped, active=True):
    return models.CreditCard(
        user_id=user.id, name=name, credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, is_active=active,
        pending_charges=Decimal(pending), pending_charges_updated_at=stamped,
    )


def test_counts_only_fresh_nonzero_active_cards(db_session):
    user = models.User(username="pc", hashed_password="x", display_name="PC")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    fresh = datetime(2026, 8, 6, 9, 0)
    db_session.add_all([
        checking,
        _card(user, "A", "86.00", fresh),
        _card(user, "B", "0", fresh),
        _card(user, "Inactive", "10.00", fresh, active=False),
        _card(user, "Stale", "40.00", datetime(2026, 8, 7) - timedelta(days=8)),
    ])
    db_session.commit()
    flat = [ForecastEntry(date=AS_OF, projected_balance=Decimal("500.00"), transactions=[])]
    with patch("backend.services.forecast_walk.build_forecast", return_value=flat):
        snap = compute_budget_snapshot(db_session, user, checking.id, as_of=AS_OF)
    assert snap.pending_cards_count == 1
    assert snap.pending_cards_total == Decimal("86.00")


def test_no_cards_defaults_to_zero(db_session):
    user = models.User(username="pc2", hashed_password="x", display_name="PC2")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    db_session.add(checking)
    db_session.commit()
    flat = [ForecastEntry(date=AS_OF, projected_balance=Decimal("500.00"), transactions=[])]
    with patch("backend.services.forecast_walk.build_forecast", return_value=flat):
        snap = compute_budget_snapshot(db_session, user, checking.id, as_of=AS_OF)
    assert (snap.pending_cards_count, snap.pending_cards_total) == (0, Decimal("0"))
