"""Plain-language causes for a change between two readings of one figure.

`explain_change` compares two stored readings (value receipts and the sources
record kept beside them, see services/metric_history.py) and names what moved:
a new month, a rules change, pending or posted rows that arrived or went away,
and the receipt lines whose amounts differ. It reads stored snapshots and the
few posted rows between them; it never recomputes a figure.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from itertools import combinations
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.calc_version import CALC_CHANGELOG, CALC_VERSION
from backend.services.metric_history import (
    MetricReadingData,
    collect_sources,
    latest_snapshot,
)
from backend.services.primary_account import primary_checking

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
MINUS = "−"
# Receipt rows that restate other rows rather than carry money of their own.
SKIPPED_OPS = frozenset({"result", "divide"})
_LOWS = ("next_month_minimum", "lookahead_minimum")
_PREFIXES = ("safety_margin",)


@dataclass(frozen=True)
class LineChange:
    label: str
    old: Decimal | None  # None = the line was absent
    new: Decimal | None


@dataclass(frozen=True)
class Cause:
    """One reason, as text. A grouped cause also carries its head and items so
    `summarize` can cut it to a number of items."""
    text: str
    amount: Decimal | None
    head: str = ""
    items: tuple[str, ...] = ()
    rows: tuple[tuple[str, Decimal | None], ...] = ()  # (name, amount) per item, for the app
    short: str = ""  # headline form of a line cause, without its amount
    parent_key: str = ""  # set on a "Same causes as ..." placeholder: the listed figure it points at


def money(amount: Decimal) -> str:
    return f"${abs(amount):,.2f}"


def signed_money(amount: Decimal) -> str:
    return f"{MINUS if amount.quantize(CENT) < 0 else '+'}{money(amount)}"


# ── Receipt lines ────────────────────────────────────────────────────────────

def _differs(old: Decimal | None, new: Decimal | None) -> bool:
    if old is None and new is None:
        return False
    if old is None or new is None:
        return abs(old if new is None else new) >= CENT
    return abs(new - old) >= CENT


def _keyed(items) -> dict[tuple[str, int], object]:
    """Items by (label, nth time the label appears), so repeated labels never collide."""
    seen: dict[str, int] = {}
    out: dict[tuple[str, int], object] = {}
    for item in items:
        n = seen.get(item.label, 0)
        seen[item.label] = n + 1
        out[(item.label, n)] = item
    return out


def _rows(explanation: schemas.Explanation) -> dict[tuple[str, int], schemas.ExplainRow]:
    return _keyed(r for r in explanation.rows if r.op not in SKIPPED_OPS)


def _kids(row: schemas.ExplainRow) -> dict[tuple[str, int], schemas.ExplainChild]:
    return _keyed([*row.children, *row.informational_children])


def diff_explanations(old: schemas.Explanation, new: schemas.Explanation) -> list[LineChange]:
    """The deepest receipt lines whose amounts differ. A row whose children
    changed is reported by those children, not by the row itself."""
    old_rows, new_rows = _rows(old), _rows(new)
    changes: list[LineChange] = []
    for key in [*old_rows, *(k for k in new_rows if k not in old_rows)]:
        before, after = old_rows.get(key), new_rows.get(key)
        if before is None or after is None:
            line = LineChange(
                key[0],
                None if before is None else before.amount,
                None if after is None else after.amount,
            )
            if _differs(line.old, line.new):
                changes.append(line)
            continue
        old_kids, new_kids = _kids(before), _kids(after)
        child_changes = []
        for ckey in [*old_kids, *(k for k in new_kids if k not in old_kids)]:
            c_old = old_kids[ckey].amount if ckey in old_kids else None
            c_new = new_kids[ckey].amount if ckey in new_kids else None
            if _differs(c_old, c_new):
                child_changes.append(LineChange(ckey[0], c_old, c_new))
        if child_changes:
            changes.extend(child_changes)
        elif _differs(before.amount, after.amount):
            changes.append(LineChange(key[0], before.amount, after.amount))
    return changes


def _line_cause(change: LineChange) -> Cause:
    if change.old is None:
        return Cause(f"{change.label} added ({money(change.new)})", change.new,
                     short=f"{change.label} added")
    if change.new is None:
        return Cause(f"{change.label} removed ({money(change.old)})", -change.old,
                     short=f"{change.label} removed")
    delta = change.new - change.old
    return Cause(f"{change.label} {signed_money(delta)}", delta, short=f"{change.label} changed")


# ── Source events ────────────────────────────────────────────────────────────

def _feeds_card(metric_key: str, card_id: int) -> bool:
    if metric_key.startswith("card_payment:"):
        return metric_key == f"card_payment:{card_id}"
    return (
        metric_key in ("left_to_spend", "available_to_spend", *_LOWS)
        or metric_key.startswith(("spendable_", *_PREFIXES))
    )


def _feeds_checking_posted(metric_key: str) -> bool:
    return metric_key in ("available_to_spend", "checking_balance", *_LOWS) or metric_key.startswith(_PREFIXES)


def _feeds_checking_pending(metric_key: str) -> bool:
    return metric_key in ("checking_balance", *_LOWS) or metric_key.startswith(_PREFIXES)


@dataclass
class _Item:
    owner_id: int
    owner: str
    name: str
    amount: Decimal


def _load(sources_json: str) -> dict:
    return json.loads(sources_json)


def _pending_items(rows: list[dict], owner_id_key: str, owner_key: str, name_key: str) -> dict[str, _Item]:
    return {
        r["external_id"]: _Item(r[owner_id_key], r[owner_key], r[name_key], Decimal(r["amount"]))
        for r in rows
    }


def _take_match(posted: list[_Item], pending: _Item) -> bool:
    """Remove and report a posted row on the same card/account with the same amount."""
    for i, row in enumerate(posted):
        if row.owner_id == pending.owner_id and row.amount == pending.amount:
            del posted[i]
            return True
    return False


def _unmatched(pending: list[_Item], posted: list[_Item]) -> list[_Item]:
    return [p for p in pending if not _take_match(posted, p)]


_SPLIT_MAX_PARTS = 4
_SPLIT_MAX_ROWS = 12


def _total(rows: list[_Item]) -> Decimal:
    return sum((row.amount for row in rows), Decimal("0"))


def _take_split(posted: list[_Item], pending: _Item) -> bool:
    """Remove 2-4 posted rows on the same card/account that sum exactly to `pending`.

    A merchant sometimes posts one pending charge as several rows, all of the
    pending amount's sign. Smallest subset
    wins; among equal sizes the earliest rows (list order). Skipped when the owner
    has more than _SPLIT_MAX_ROWS candidates, to cap the search.
    """
    owned = [i for i, row in enumerate(posted) if row.owner_id == pending.owner_id]
    if len(owned) > _SPLIT_MAX_ROWS:
        return False
    # A posted row of the opposite sign (a refund beside charges) is never a part.
    idx = [i for i in owned if (posted[i].amount < 0) == (pending.amount < 0)]
    for size in range(2, _SPLIT_MAX_PARTS + 1):
        for combo in combinations(idx, size):
            if _total([posted[i] for i in combo]) == pending.amount:
                for i in reversed(combo):
                    del posted[i]
                return True
    return False


def _unmatched_gone(pending: list[_Item], posted: list[_Item]) -> list[_Item]:
    """Gone pending: exact one-to-one first for all, then split matching on the rest."""
    left = _unmatched(pending, posted)
    return [p for p in left if not _take_split(posted, p)]


def _group(kind_text: str, owner: str, items: list[_Item], *, plural: str, singular: str) -> Cause:
    noun = singular if len(items) == 1 else plural
    head = kind_text.format(owner=owner, noun=noun)
    shown = tuple(f"{i.name} {money(i.amount)}" for i in items)
    rows = tuple((i.name, i.amount) for i in items)
    return Cause(f"{head}: {', '.join(shown)}", None, head=head, items=shown, rows=rows)


def _by_owner(items: list[_Item]) -> list[tuple[int, str, list[_Item]]]:
    grouped: dict[int, tuple[str, list[_Item]]] = {}
    for item in items:
        grouped.setdefault(item.owner_id, (item.owner, []))[1].append(item)
    return [(oid, name, rows) for oid, (name, rows) in sorted(grouped.items())]


def _source_causes(
    db: Session, user_id: int, metric_key: str, prev: models.MetricSnapshot, cur: models.MetricSnapshot,
) -> list[Cause]:
    old, new = _load(prev.sources_json), _load(cur.sources_json)
    causes: list[Cause] = []
    # Posted rows count as new when they were added to the database between the
    # two recordings (created_at, naive UTC like taken_at) and dated no earlier
    # than the previous reading's month, so an old-dated import is not blamed.
    # Rows without a created_at never match. Row ids are not used: they are
    # reused after "clear all transactions".
    window_start = prev.as_of.replace(day=1)

    # Card rows: pending that appeared or went away, and posted rows in between.
    old_p = _pending_items(old["card_pending"], "card_id", "card", "merchant")
    new_p = _pending_items(new["card_pending"], "card_id", "card", "merchant")
    new_pending = [v for k, v in new_p.items() if k not in old_p]
    gone_pending = [v for k, v in old_p.items() if k not in new_p]
    posted_rows = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.created_at > prev.taken_at,
        models.CreditCardTransaction.created_at <= cur.taken_at,
        models.CreditCardTransaction.date >= window_start,
    ).order_by(models.CreditCardTransaction.id).all()
    card_names = {c.id: c.name for c in db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id).all()}
    posted = [
        _Item(r.card_id, card_names.get(r.card_id, "card"), r.merchant, Decimal(str(r.amount)))
        for r in posted_rows
    ]
    new_pending = _unmatched(new_pending, posted)
    gone_pending = _unmatched_gone(gone_pending, posted)
    causes += _grouped_causes(
        new_pending, gone_pending, posted, lambda oid: _feeds_card(metric_key, oid),
        pending_noun=("charge", "charges"), posted_noun=("transaction", "transactions"),
    )

    # Checking rows, on the primary checking account.
    old_c = _pending_items(old["checking_pending"], "account_id", "account", "description")
    new_c = _pending_items(new["checking_pending"], "account_id", "account", "description")
    c_new = [v for k, v in new_c.items() if k not in old_c]
    c_gone = [v for k, v in old_c.items() if k not in new_c]
    account = primary_checking(db, user_id)
    c_posted: list[_Item] = []
    if account is not None:
        rows = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.account_id == account.id,
            models.Transaction.is_actual == True,  # noqa: E712
            models.Transaction.created_at > prev.taken_at,
            models.Transaction.created_at <= cur.taken_at,
            models.Transaction.date >= window_start,
        ).order_by(models.Transaction.id).all()
        c_posted = [_Item(account.id, account.name, r.description, Decimal(str(r.amount))) for r in rows]
    c_new = _unmatched(c_new, c_posted)
    c_gone = _unmatched_gone(c_gone, c_posted)
    causes += _grouped_causes(
        c_new, c_gone, c_posted,
        lambda _oid: _feeds_checking_pending(metric_key),
        pending_noun=("charge", "charges"), posted_noun=("transaction", "transactions"),
        posted_feeds=lambda _oid: _feeds_checking_posted(metric_key),
    )
    return causes


def _grouped_causes(new_pending, gone_pending, posted, feeds, *, pending_noun, posted_noun,
                    posted_feeds=None) -> list[Cause]:
    posted_feeds = posted_feeds or feeds
    owners = sorted({i.owner_id for i in [*new_pending, *gone_pending, *posted]})
    out: list[Cause] = []
    for oid in owners:
        for rows, text, noun, gate in (
            (new_pending, "new pending {owner} {noun}", pending_noun, feeds),
            (gone_pending, "pending {owner} {noun} dropped", pending_noun, feeds),
            (posted, "new {owner} {noun}", posted_noun, posted_feeds),
        ):
            mine = [r for r in rows if r.owner_id == oid]
            if mine and gate(oid):
                out.append(_group(text, mine[0].owner, mine, singular=noun[0], plural=noun[1]))
    return out


# ── Public ───────────────────────────────────────────────────────────────────

# A week or day figure is its parent figure divided down, so its receipt has
# the parent as a row. That row's only cause would read "<parent> $X"; the
# parent's own causes explain it instead. Verified against the receipts built
# in budget_snapshot.py: each tree starts with its parent's label.
DERIVED_FROM: dict[str, str] = {
    "spendable_week": "left_to_spend",
    "spendable_today": "spendable_week",
    "safety_margin_week": "safety_margin",
    "safety_margin_today": "safety_margin_week",
}
_MAX_INHERIT_DEPTH = 3
_NOTHING_NAMED = "inputs changed"


def _reading_of(snapshot: models.MetricSnapshot, key: str) -> models.MetricReading | None:
    return next((r for r in snapshot.readings if r.metric_key == key), None)


def _inherited(cause: Cause) -> Cause:
    """A parent's cause shown under its derived figure: in the parent's units,
    so no amount is carried (grouped items keep their names only)."""
    if cause.head:
        names = tuple(name for name, _ in cause.rows)
        return Cause(f"{cause.head}: {', '.join(names)}", None, head=cause.head, items=names,
                     rows=tuple((name, None) for name in names))
    return Cause(cause.short or cause.text, None, short=cause.short)


def _parent_causes(
    db: Session, user_id: int, metric_key: str, prev: models.MetricReading, cur: models.MetricReading,
    own: list[Cause], depth: int,
) -> tuple[str, list[Cause]] | None:
    """(parent row label, the parent's causes not already in `own`), or None
    when this figure has no parent, the parent is missing from either snapshot,
    or the parent has nothing nameable."""
    parent_key = DERIVED_FROM.get(metric_key)
    if parent_key is None or depth >= _MAX_INHERIT_DEPTH:
        return None
    prev_parent, cur_parent = _reading_of(prev.snapshot, parent_key), _reading_of(cur.snapshot, parent_key)
    if prev_parent is None or cur_parent is None:
        return None
    parent = explain_change(db, user_id, parent_key, prev_parent, cur_parent, _depth=depth + 1)
    texts = {c.text for c in own}
    fresh = [c for c in parent if c.text not in texts and c.text != _NOTHING_NAMED]
    return (cur_parent.label, fresh) if fresh else None


def explain_change(
    db: Session, user_id: int, metric_key: str,
    prev: models.MetricReading, cur: models.MetricReading, *, _depth: int = 0,
) -> list[Cause]:
    """Why `metric_key` differs between two readings: calculation change first,
    then source events, then receipt lines by size. A derived figure's line for
    its parent is replaced by the parent's causes (see DERIVED_FROM).
    `[Cause("inputs changed")]` when nothing nameable differs."""
    prev_snap, cur_snap = prev.snapshot, cur.snapshot
    causes: list[Cause] = []
    if prev_snap.calc_version != cur_snap.calc_version:
        note = CALC_CHANGELOG.get(cur_snap.calc_version, "the rules changed")
        causes.append(Cause(
            f"calculation changed (v{prev_snap.calc_version} → v{cur_snap.calc_version}: {note})",
            None,
        ))
    causes.extend(_source_causes(db, user_id, metric_key, prev_snap, cur_snap))
    if (prev_snap.as_of.year, prev_snap.as_of.month) != (cur_snap.as_of.year, cur_snap.as_of.month):
        causes.append(Cause(f"new month ({cur_snap.as_of:%b})", None))
    else:
        lines = diff_explanations(
            schemas.Explanation.model_validate_json(prev.explain_json),
            schemas.Explanation.model_validate_json(cur.explain_json),
        )
        ordered = sorted(lines, key=lambda c: abs(_line_cause(c).amount), reverse=True)
        inherit = _parent_causes(db, user_id, metric_key, prev, cur, causes, _depth)
        for line in ordered:
            if inherit is not None and line.label == inherit[0]:
                causes.extend(_inherited(c) for c in inherit[1])
            else:
                causes.append(_line_cause(line))
    seen: set[str] = set()
    unique = [c for c in causes if not (c.text in seen or seen.add(c.text))]
    return unique or [Cause(_NOTHING_NAMED, None)]


def summarize(label: str, delta: Decimal, since_text: str, causes: list[Cause], *, max_items: int) -> str:
    """One line: "<label> <signed delta> <since>: <cause>; <cause>", cut to
    `max_items` items (a grouped cause counts each of its items)."""
    units = [(i, item) for i, c in enumerate(causes) for item in (c.items or (None,))]
    kept = units[:max_items]
    extra = len(units) - len(kept)
    parts: list[str] = []
    for i, c in enumerate(causes):
        mine = [item for j, item in kept if j == i]
        if not mine:
            continue
        parts.append(f"{c.head}: {', '.join(mine)}" if c.items else c.text)
    body = "; ".join(parts) or "inputs changed"
    if extra > 0:
        body += f" and {extra} more"
    lead = f"{label} " if label else ""
    return f"{lead}{signed_money(delta)} {since_text}: {body}"


def headline(causes: list[Cause]) -> str:
    """Short label for a collapsed history row: the first cause (a group's head,
    a line's short form without its amount, or the text), capitalized, plus " + N more" for the other causes."""
    if not causes:
        return "Inputs changed"
    first = causes[0]
    text = first.head or first.short or first.text
    text = text[:1].upper() + text[1:]
    more = len(causes) - 1
    return f"{text} + {more} more" if more else text


def _history_cause(c: Cause) -> schemas.HistoryCause:
    return schemas.HistoryCause(
        text=c.text, amount=c.amount, head=c.head or None,
        items=[schemas.HistoryCauseItem(name=n, amount=a) for n, a in c.rows],
    )


def _since_text(prev_taken: datetime, cur_taken: datetime) -> str:
    """"since 7:00 AM" on the same local day, else "since Mon 7:00 AM", in the
    server's local zone (stored times are naive UTC)."""
    def local(t: datetime) -> datetime:
        return t.replace(tzinfo=timezone.utc).astimezone()
    prev_local, cur_local = local(prev_taken), local(cur_taken)
    fmt = "%-I:%M %p" if prev_local.date() == cur_local.date() else "%a %-I:%M %p"
    return "since " + prev_local.strftime(fmt)


def _causes_or_fallback(
    db: Session, user_id: int, metric_key: str, prev: models.MetricReading, cur: models.MetricReading,
) -> list[Cause]:
    """`explain_change`, degrading to "inputs changed" when a stored receipt or
    sources record is malformed or from an older shape."""
    try:
        return explain_change(db, user_id, metric_key, prev, cur)
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
        logger.warning("Change history: unreadable reading for %s, listing without causes", metric_key)
        return [Cause("inputs changed", None)]


def changes_for(
    db: Session, user_id: int, metric_key: str, limit: int,
) -> list[schemas.MetricChangeOut]:
    """Consecutive readings of one figure, newest change first, only where the
    value moved by at least a cent."""
    readings = (
        db.query(models.MetricReading)
        .join(models.MetricSnapshot, models.MetricReading.snapshot_id == models.MetricSnapshot.id)
        .filter(models.MetricSnapshot.user_id == user_id, models.MetricReading.metric_key == metric_key)
        .order_by(models.MetricSnapshot.taken_at.desc(), models.MetricSnapshot.id.desc())
        .all()
    )
    out: list[schemas.MetricChangeOut] = []
    for cur, prev in zip(readings, readings[1:]):
        if len(out) >= limit:
            break
        old_value, new_value = Decimal(str(prev.value)), Decimal(str(cur.value))
        delta = new_value - old_value
        if abs(delta) < CENT:
            continue
        causes = _causes_or_fallback(db, user_id, metric_key, prev, cur)
        prev_snap, cur_snap = prev.snapshot, cur.snapshot
        out.append(schemas.MetricChangeOut(
            taken_at=cur_snap.taken_at, previous_taken_at=prev_snap.taken_at,
            trigger=cur_snap.trigger, old_value=old_value, new_value=new_value, delta=delta,
            summary=summarize(
                cur.label, delta, _since_text(prev_snap.taken_at, cur_snap.taken_at), causes, max_items=3,
            ),
            headline=headline(causes),
            causes=[_history_cause(c) for c in causes],
            calc_changed=prev_snap.calc_version != cur_snap.calc_version,
        ))
    return out


# ── The daily email's "since last email" lines ───────────────────────────────

def since_last_email(
    db: Session, user: models.User, readings: list[MetricReadingData],
) -> dict[str, str]:
    """Metric key -> "<signed amount> since last email" for each figure that
    moved (by a cent or more) since the last "email" snapshot; `{}` when there
    is none. The line has no leading label: the email prints it under the
    figure's own, and names no cause."""
    previous = latest_snapshot(db, user.id, "email")
    if previous is None:
        return {}
    before = {r.metric_key: r for r in previous.readings}
    out: dict[str, str] = {}
    for reading in readings:
        prev = before.get(reading.key)
        if prev is None:
            continue
        try:
            delta = reading.value - Decimal(str(prev.value))
            if abs(delta) < CENT:
                continue
            out[reading.key] = f"{signed_money(delta)} since last email"
        except Exception:  # noqa: BLE001 -- one bad stored reading drops only its own line
            logger.exception("Change history: no since-last-email line for %s", reading.key)
    return out


@dataclass(frozen=True)
class EmailChange:
    """One figure that moved since the last email, with what moved it."""
    key: str
    label: str
    delta: Decimal
    causes: list[Cause]


def _transient_reading(
    user_id: int, reading: MetricReadingData, sources_json: str, as_of: date, taken_at: datetime,
) -> models.MetricReading:
    """The reading as it would be stored, without adding it to any session, so
    `explain_change` can compare it with a stored one before the email goes."""
    snapshot = models.MetricSnapshot(
        user_id=user_id, taken_at=taken_at, trigger="email", calc_version=CALC_VERSION,
        as_of=as_of, sources_json=sources_json,
    )
    row = models.MetricReading(
        metric_key=reading.key, label=reading.label, value=reading.value,
        explain_json=reading.explain.model_dump_json(),
    )
    row.snapshot = snapshot
    return row


def _ancestor_key(key: str, labels: dict[str, str]) -> str | None:
    """Key of the nearest figure up the DERIVED_FROM chain that is also listed."""
    parent = DERIVED_FROM.get(key)
    for _ in range(_MAX_INHERIT_DEPTH):
        if parent is None:
            return None
        if parent in labels:
            return parent
        parent = DERIVED_FROM.get(parent)
    return None


def explain_since_last_email(
    db: Session, user: models.User, readings: list[MetricReadingData], *,
    keys: tuple[str, ...] | None = None, as_of: date | None = None,
) -> list[EmailChange]:
    """What moved each figure (by a cent or more) since the last "email"
    snapshot, in the order of `readings`; `[]` when there is none. `keys`
    limits it to the figures the email shows. A figure whose parent (see
    DERIVED_FROM) is also listed gets one cause pointing at the parent."""
    previous = latest_snapshot(db, user.id, "email")
    if previous is None:
        return []
    as_of = as_of or date.today()
    taken_at = datetime.now(timezone.utc).replace(tzinfo=None)
    sources_json = json.dumps(collect_sources(db, user, as_of), sort_keys=True)
    before = {r.metric_key: r for r in previous.readings}
    moved: list[tuple[MetricReadingData, Decimal, list[Cause]]] = []
    for reading in readings:
        prev = before.get(reading.key)
        if prev is None or (keys is not None and reading.key not in keys):
            continue
        try:
            delta = reading.value - Decimal(str(prev.value))
            if abs(delta) < CENT:
                continue
            cur = _transient_reading(user.id, reading, sources_json, as_of, taken_at)
            moved.append((reading, delta, _causes_or_fallback(db, user.id, reading.key, prev, cur)))
        except Exception:  # noqa: BLE001 -- one bad stored reading drops only its own entry
            logger.exception("Change history: no since-last-email changes for %s", reading.key)
    labels = {r.key: r.label for r, _, _ in moved}
    out: list[EmailChange] = []
    for reading, delta, causes in moved:
        parent = _ancestor_key(reading.key, labels)
        if parent is not None:
            causes = [Cause(f"Same causes as {labels[parent]}", None, parent_key=parent)]
        out.append(EmailChange(reading.key, reading.label, delta, causes))
    return out
