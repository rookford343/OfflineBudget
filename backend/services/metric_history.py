"""Every headline figure with its explain tree, collected for change history.

`collect_headline_metrics` is the one place that lists which figures history
records; each reading is the value and receipt another surface already shows
(the snapshot, the month summary, Available to Spend, the pending-adjusted
checking balance, each card's next payment), never a second recipe.
`collect_sources` records what those figures were computed from (pending rows
and the newest row ids) so a later diff can say what changed underneath.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.available_to_spend import available_to_spend
from backend.services.budget_snapshot import _cc_basis_note, compute_budget_snapshot
from backend.services.calc_version import CALC_VERSION
from backend.services.card_payment_model import card_payments
from backend.services.explain import ExplainBuilder
from backend.services.month_summary import build_month_summary
from backend.services.pending import checking_balance_with_pending, checking_pending_rows
from backend.services.primary_account import primary_checking
from backend.services.real_spend import active_cards
from backend.schemas import ExplainChild

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
RETENTION_DAYS = 395  # about 13 months
CENT = Decimal("0.01")
# Triggers that are stored even when nothing changed since the last snapshot.
ALWAYS_STORE_TRIGGERS = frozenset({"email"})
CARD_WINDOW_DAYS = 75

# Fixed headline keys, in recording order. Card payments follow as
# `card_payment:<card id>`, one per active card.
METRIC_KEYS: tuple[str, ...] = (
    "leftover", "left_to_spend", "spendable_week", "spendable_today",
    "safety_margin", "safety_margin_week", "safety_margin_today", "next_month_minimum",
    "lookahead_minimum", "available_to_spend", "checking_balance",
)


@dataclass(frozen=True)
class MetricReadingData:
    key: str
    label: str
    value: Decimal
    explain: schemas.Explanation


def _checking_balance_reading(
    db: Session, account: models.Account, as_of: date,
) -> MetricReadingData:
    posted = Decimal(str(account.current_balance))
    value = checking_balance_with_pending(db, account, as_of)
    builder = ExplainBuilder("Checking balance").start("Posted balance", posted)
    if value != posted:
        children = [
            ExplainChild(label=r.description, amount=Decimal(str(r.amount)))
            for r in checking_pending_rows(db, account, as_of)
        ]
        builder.add("Pending", value - posted, children=children)
    return MetricReadingData(
        "checking_balance", "Checking balance", value, builder.build(value),
    )


def _card_payment_readings(
    db: Session, user: models.User, account: models.Account, as_of: date,
) -> list[MetricReadingData]:
    payments = card_payments(
        db, user, account, as_of, as_of + timedelta(days=CARD_WINDOW_DAYS),
        include_unbilled_card_bills=True, today=as_of,
    )
    next_by_card: dict[int, object] = {}
    for p in sorted(payments, key=lambda p: p.due):
        next_by_card.setdefault(p.card_id, p)
    out: list[MetricReadingData] = []
    for card in sorted(active_cards(db, user.id), key=lambda c: c.id):
        p = next_by_card.get(card.id)
        if p is None:
            value = ZERO
            explain = (
                ExplainBuilder(f"{card.name} next payment")
                .start(f"No payment due in the next {CARD_WINDOW_DAYS} days", value)
                .build(value)
            )
        else:
            value = abs(p.amount)
            explain = (
                ExplainBuilder(f"{card.name} next payment")
                .start(f"Next payment, due {p.due:%b %-d}", value, note=_cc_basis_note(p))
                .build(value)
            )
        out.append(MetricReadingData(
            f"card_payment:{card.id}", f"{card.name} next payment", value, explain,
        ))
    return out


def collect_headline_metrics(
    db: Session, user: models.User, as_of: date,
) -> list[MetricReadingData]:
    """Every headline figure with its receipt; `[]` without a primary checking account."""
    account = primary_checking(db, user.id)
    if account is None:
        return []
    snap = compute_budget_snapshot(db, user, account.id, as_of)
    month = build_month_summary(db, user.id, as_of.year, as_of.month)
    available = available_to_spend(db, user, as_of)

    def reading(key: str, label: str, value: Decimal, explain: schemas.Explanation):
        return MetricReadingData(key, label, value, explain)

    ex = snap.explain
    readings = [
        reading("leftover", "Leftover", month.left_over, month.explain["left_over"]),
        reading("left_to_spend", "Left to Spend", snap.left_to_spend, ex["left_to_spend"]),
        reading("spendable_week", "Spendable this week", snap.left_to_spend_weekly, ex["spendable_week"]),
        reading("spendable_today", "Spendable today", snap.spendable_today, ex["spendable_today"]),
        reading("safety_margin", "Safety Margin", snap.safety_margin, ex["safety_margin"]),
        reading("safety_margin_week", "Safety Margin (this week)", snap.safety_margin_weekly,
                ex["safety_margin_week"]),
        reading("safety_margin_today", "Safety Margin today", snap.safety_margin_today,
                ex["safety_margin_today"]),
        reading("next_month_minimum", "Lowest next month", snap.next_month_minimum,
                ex["next_month_minimum"]),
        reading("lookahead_minimum", "3-month low", snap.lookahead_minimum, ex["lookahead_minimum"]),
        reading("available_to_spend", "Available to Spend", available.available, available.explain),
        _checking_balance_reading(db, account, as_of),
    ]
    return readings + _card_payment_readings(db, user, account, as_of)


def collect_sources(db: Session, user: models.User, as_of: date) -> dict:
    """What the figures were computed from, JSON-safe (amounts as strings):
    pending rows on active cards and the primary checking, plus the newest
    actual transaction and card transaction ids."""
    cards = {c.id: c for c in active_cards(db, user.id)}
    card_pending = []
    if cards:
        pending_rows = db.query(models.CardPendingTransaction).filter(
            models.CardPendingTransaction.user_id == user.id,
            models.CardPendingTransaction.card_id.in_(list(cards)),
        ).order_by(models.CardPendingTransaction.card_id, models.CardPendingTransaction.id).all()
        card_pending = [
            {
                "card_id": r.card_id, "card": cards[r.card_id].name,
                "external_id": r.external_id, "merchant": r.merchant,
                "amount": str(Decimal(str(r.amount))),
            }
            for r in pending_rows
        ]
    account = primary_checking(db, user.id)
    checking_pending = []
    if account is not None:
        checking_pending = [
            {
                "account_id": account.id, "account": account.name,
                "external_id": r.external_id, "description": r.description,
                "amount": str(Decimal(str(r.amount))),
            }
            for r in checking_pending_rows(db, account, as_of)
        ]
    max_txn = db.query(func.max(models.Transaction.id)).filter(
        models.Transaction.user_id == user.id, models.Transaction.is_actual == True,
    ).scalar()
    max_card_txn = db.query(func.max(models.CreditCardTransaction.id)).filter(
        models.CreditCardTransaction.user_id == user.id,
    ).scalar()
    return {
        "card_pending": card_pending,
        "checking_pending": checking_pending,
        "max_txn_id": max_txn or 0,
        "max_card_txn_id": max_card_txn or 0,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def latest_snapshot(
    db: Session, user_id: int, trigger: str | None = None,
) -> models.MetricSnapshot | None:
    q = db.query(models.MetricSnapshot).filter(models.MetricSnapshot.user_id == user_id)
    if trigger is not None:
        q = q.filter(models.MetricSnapshot.trigger == trigger)
    return q.order_by(models.MetricSnapshot.taken_at.desc(), models.MetricSnapshot.id.desc()).first()


def _reading_set(rows) -> set[tuple[str, Decimal, str]]:
    return {(key, Decimal(str(value)).quantize(CENT), explain) for key, value, explain in rows}


def _same_as_latest(
    latest: models.MetricSnapshot, sources_json: str, readings: list[MetricReadingData],
    explain_jsons: list[str],
) -> bool:
    if latest.calc_version != CALC_VERSION or latest.sources_json != sources_json:
        return False
    old = _reading_set((r.metric_key, r.value, r.explain_json) for r in latest.readings)
    new = _reading_set(
        (r.key, r.value, ex) for r, ex in zip(readings, explain_jsons)
    )
    return old == new


def prune_history(db: Session, now: datetime) -> int:
    """Delete snapshots older than the retention window, readings first."""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    old_ids = [
        row[0] for row in db.query(models.MetricSnapshot.id)
        .filter(models.MetricSnapshot.taken_at < cutoff).all()
    ]
    if not old_ids:
        return 0
    db.query(models.MetricReading).filter(
        models.MetricReading.snapshot_id.in_(old_ids),
    ).delete(synchronize_session=False)
    db.query(models.MetricSnapshot).filter(
        models.MetricSnapshot.id.in_(old_ids),
    ).delete(synchronize_session=False)
    db.commit()
    return len(old_ids)


def record_snapshot(
    db: Session, user: models.User, trigger: str, *,
    as_of: date | None = None, now: datetime | None = None,
    readings: list[MetricReadingData] | None = None,
) -> models.MetricSnapshot | None:
    """Store every headline figure as of now. Commits. Returns None when
    nothing was stored: no primary checking, or (outside the always-store
    triggers) the figures and their sources equal the latest snapshot's."""
    as_of = as_of or date.today()
    now = now or _utc_now()
    if readings is None:
        readings = collect_headline_metrics(db, user, as_of)
    if not readings:
        return None
    sources_json = json.dumps(collect_sources(db, user, as_of), sort_keys=True)
    explain_jsons = [r.explain.model_dump_json() for r in readings]
    if trigger not in ALWAYS_STORE_TRIGGERS:
        latest = latest_snapshot(db, user.id)
        if latest is not None and _same_as_latest(latest, sources_json, readings, explain_jsons):
            return None
    snapshot = models.MetricSnapshot(
        user_id=user.id, taken_at=now, trigger=trigger, calc_version=CALC_VERSION,
        as_of=as_of, sources_json=sources_json,
    )
    snapshot.readings = [
        models.MetricReading(metric_key=r.key, label=r.label, value=r.value, explain_json=ex)
        for r, ex in zip(readings, explain_jsons)
    ]
    db.add(snapshot)
    db.commit()
    prune_history(db, now)
    return snapshot


def record_for_users(db: Session, user_ids: Iterable[int], trigger: str) -> None:
    """Record for each user; never raises. A failure rolls back and moves on."""
    for user_id in sorted(set(user_ids)):
        try:
            user = db.get(models.User, user_id)
            if user is not None:
                record_snapshot(db, user, trigger)
        except Exception:  # noqa: BLE001 -- history must never fail the sync that triggered it
            logger.exception("Change-history snapshot failed for user %s", user_id)
            db.rollback()


def record_if_calc_changed(db: Session) -> None:
    """Record once per active user whose latest snapshot predates CALC_VERSION."""
    users = db.query(models.User).filter(models.User.is_active == True).all()  # noqa: E712
    for user in users:
        latest = latest_snapshot(db, user.id)
        if latest is None or latest.calc_version == CALC_VERSION:
            continue
        try:
            record_snapshot(db, user, "calc_change")
        except Exception:  # noqa: BLE001 -- one user's failure must not stop the others
            logger.exception("Change-history calc_change snapshot failed for user %s", user.id)
            db.rollback()
