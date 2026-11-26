import calendar
import html as html_lib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import BankConnectionStatusOut, MonthlySummary, MonthlyDigest, WeeklyDigest, ForecastRisk
from backend.services.cushion import cushion_for
from backend.services.forecast_engine import _next_occurrence_on_or_after
from backend.services.forecast_walk import standard_walk, walk_risk
from backend.services.budget_snapshot import compute_budget_snapshot, spending_breakdown, _round_up_to_thousand  # noqa: F401 -- re-exported so `from backend.services.summary_generator import _round_up_to_thousand` keeps working
from backend.services.pending import card_pending
from backend.services.upcoming_bills import upcoming_bills
from backend.services.primary_account import primary_checking
from backend.services.real_spend import spend_totals

_STALE_SYNC_HOURS = 24


def _fmt(v: Decimal) -> str:
    """"$1,234.56" for a non-negative amount, "−$1,234.56" (a real minus
    sign, U+2212, before the $) for a negative one -- never Python's default
    "$-1,234.56". Every money figure in the email goes through this (or
    through fmt(abs(...)) with the sign prepended separately, which already
    produces the same character)."""
    if v < 0:
        return f"−${abs(v):,.2f}"
    return f"${v:,.2f}"


def _move_to_checking_line(snap) -> str | None:
    """"Move $Y into checking by <1st of next month>" when next month's low
    is projected to dip below $0, else None. Y is `snap.move_to_checking_needed`,
    computed once in budget_snapshot.py so the email and dashboard agree."""
    if snap.next_month_minimum_date is None or snap.move_to_checking_needed <= 0:
        return None
    move_by = snap.next_month_minimum_date.replace(day=1)
    return f"Move {_fmt(snap.move_to_checking_needed)} into checking by {move_by.strftime('%b %-d')}"


def email_subject(snap, today: date, with_weekly: bool, *, stale: bool = False) -> str:
    """Amount-free subject that leads with the answer. `snap` is the same
    snapshot the email body was built from (None when there is no checking
    account, which gives the plain subject). `stale` is True when any bank
    connection is stale (generate_daily_summary's `stale_out`); it outranks the
    low-point heads-up but not a needed savings pull."""
    tail = f"Daily Budget Summary — {today.strftime('%B %-d, %Y')}"
    if snap is None:
        subject = tail
    elif snap.savings_pull_needed > 0:
        subject = f"Action needed: pull from savings · {tail}"
    elif stale:
        subject = f"Heads up: bank data stale · {tail}"
    elif snap.lookahead_status in ("danger", "warning") or _move_to_checking_line(snap):
        subject = f"Heads up: low point ahead · {tail}"
    else:
        subject = f"Covered this week · {tail}"
    return subject + (" + Weekly Digest" if with_weekly else "")


def _lowest_balance_rows(snap) -> list[tuple[str, Decimal, date]]:
    """[(label, amount, date), ...] for the "lowest balance" lines below the
    Household Snapshot cards -- shared ordering/same-date logic for both the
    HTML and text bodies so the two can never drift apart. `label` is the
    full "Lowest ..." prefix; the caller formats/colors `amount` and appends
    " on <date>" itself.

    When next month's low and the 3-month low land on the same date for the
    same amount, next month's low IS the 3-month low, so this collapses to
    one combined row instead of two identical-looking ones.
    """
    if snap.lookahead_minimum_date is None and snap.next_month_minimum_date is None:
        return []

    quarter_row = (
        ("Lowest in the next 3 months", snap.lookahead_minimum, snap.lookahead_minimum_date)
        if snap.lookahead_minimum_date is not None else None
    )
    if snap.next_month_minimum_date is None:
        return [quarter_row] if quarter_row else []

    nm_label = snap.next_month_label or "next month"
    same = (
        quarter_row is not None
        and snap.next_month_minimum_date == snap.lookahead_minimum_date
        and snap.next_month_minimum == snap.lookahead_minimum
    )
    if same:
        return [(
            f"Lowest next month ({nm_label}) and in the next 3 months",
            snap.next_month_minimum, snap.next_month_minimum_date,
        )]

    rows = [(f"Lowest next month ({nm_label})", snap.next_month_minimum, snap.next_month_minimum_date)]
    if quarter_row:
        rows.append(quarter_row)
    return rows


# The headline keys that have a place in the email, for `since_lines`.
SINCE_SPENDABLE = "spendable_week"
SINCE_MARGIN = "safety_margin_week"
SINCE_NEXT_MONTH = "next_month_minimum"
SINCE_QUARTER = "lookahead_minimum"
SINCE_CHECKING = "checking_balance"
SINCE_KEYS = (SINCE_SPENDABLE, SINCE_MARGIN, SINCE_NEXT_MONTH, SINCE_QUARTER, SINCE_CHECKING)

# Keys that get the full itemized receipt (old/new value + math lines) in the
# "What changed" section below, instead of being folded into its shared
# top-line + reasons list -- see explain_since_last_email's receipt_keys.
SINCE_RECEIPT_KEYS = frozenset({SINCE_MARGIN})


def _lowest_row_since(label: str, since: dict[str, str]) -> str | None:
    """The since line for a `_lowest_balance_rows` row: next month's low, the
    3-month low, or (on the combined row, which shows both) whichever moved."""
    if label.startswith("Lowest next month"):
        keys = [SINCE_NEXT_MONTH] + ([SINCE_QUARTER] if _is_lookahead_row(label) else [])
    else:
        keys = [SINCE_QUARTER]
    return next((since[k] for k in keys if k in since), None)


def _since_html(line: str | None, margin: str = "3px 0 0", align: str = "") -> str:
    if not line:
        return ""
    return (
        f"<p class='ob-muted' style='margin:{margin};color:#64748b;font-size:11px;line-height:1.4;{align}"
        f"white-space:normal;word-break:break-word;overflow-wrap:break-word'>{html_lib.escape(line)}</p>"
    )


def _since_text(line: str | None) -> str:
    return f"    {line}\n" if line else ""


def _lookahead_warning(snap) -> str | None:
    """The short phrase that flags the 3-month low against the user's safety
    cushion, or None when it's fine (snap.lookahead_status == "ok"). The
    status itself is decided once in budget_snapshot.lookahead_status; this
    only words it, for both the HTML and text bodies."""
    if snap.lookahead_status == "danger":
        return "below $0"
    if snap.lookahead_status == "warning":
        return f"below your {_fmt(snap.safety_cushion)} cushion"
    return None


def _is_lookahead_row(label: str) -> bool:
    """Whether a _lowest_balance_rows row carries the 3-month low (alone or
    combined with next month's) -- the row the cushion warning belongs to."""
    return "next 3 months" in label


def _last_txn_dates(db: Session, id_col, date_col, ids: list[int]) -> dict[int, date]:
    """Most recent transaction date per id, keyed off actual transaction rows
    rather than a bank-sync timestamp -- this way a manually-imported account
    gets the same freshness signal as a SimpleFIN-linked one."""
    if not ids:
        return {}
    rows = db.query(id_col, func.max(date_col)).filter(id_col.in_(ids)).group_by(id_col).all()
    return dict(rows)


def _last_txn_label(d: date | None) -> str:
    return f"last txn {d.strftime('%b %-d')}" if d else "no transactions yet"


# ── Daily email summary ───────────────────────────────────────────────────────

def _stale_bank_connections(db: Session, user_id: int, now: datetime | None = None) -> list[models.BankConnection]:
    """Connections either actively erroring, or that haven't completed a
    sync in the last 24 hours -- data the Daily Summary is built from could
    be out of date without any other signal to the user. A deliberately
    `disconnected` connection is excluded: that's a user action, not a
    failure, and shouldn't nag daily forever after."""
    now = now or datetime.utcnow()
    threshold = now - timedelta(hours=_STALE_SYNC_HOURS)
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.user_id == user_id,
        models.BankConnection.status != models.BankConnectionStatus.disconnected,
    ).all()
    return [
        c for c in connections
        if c.status == models.BankConnectionStatus.error
        or c.last_synced_at is None
        or c.last_synced_at < threshold
    ]


def _utc_to_local(d: datetime) -> datetime:
    """A stored UTC-naive timestamp as naive local time. The email is built
    on the household's own machine, so its local zone is the user's."""
    return d.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _friendly_time(local: datetime, now_local: datetime) -> str:
    """"today 7:00 AM", "yesterday 3:00 PM", otherwise "Oct 27 7:00 AM"."""
    days = (now_local.date() - local.date()).days
    day = "today" if days == 0 else "yesterday" if days == 1 else local.strftime("%b %-d")
    return f"{day} {local.strftime('%-I:%M %p')}"


def _last_pull_line(
    db: Session, user_id: int, *, now_local: datetime | None = None, to_local=_utc_to_local,
) -> str | None:
    """Plain-text "Bank data updated <time> · <names> (<provider>) ✓ · ..."
    line, the same meaning as the Dashboard's: the time is
    BankConnectionStatusOut.last_success_at (newest active-link stamp, which
    only a committed import writes), never last_synced_at, which a failed
    run also stamps. A failing connection reads "⚠ last good: <time>". None
    when no connection has an active link."""
    now_local = now_local or datetime.now()
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.user_id == user_id,
        models.BankConnection.status != models.BankConnectionStatus.disconnected,
    ).order_by(models.BankConnection.id).all()
    parts: list[str] = []
    successes: list[datetime] = []
    for c in connections:
        active = [link for link in c.links if link.is_active]
        if not active:
            continue
        names: list[str] = []
        for link in active:
            name = (
                (link.local_account.name if link.local_account else None)
                or (link.local_credit_card.name if link.local_credit_card else None)
                or link.simplefin_account_name
            )
            if name and name not in names:
                names.append(name)
        provider = {"plaid": "Plaid", "simplefin": "SimpleFIN"}.get(c.provider, c.provider)
        label = f"{', '.join(names)} ({provider})"
        last_success = BankConnectionStatusOut.model_validate(c).last_success_at
        if last_success:
            successes.append(last_success)
        if c.last_error or c.status == models.BankConnectionStatus.error:
            when = f"last good: {_friendly_time(to_local(last_success), now_local)}" if last_success else "sync failing"
            parts.append(f"{label} ⚠ {when}")
        else:
            parts.append(f"{label} ✓")
    if not parts:
        return None
    head = (
        f"Bank data updated {_friendly_time(to_local(max(successes)), now_local)}"
        if successes else "Bank data not pulled yet"
    )
    return " · ".join([head, *parts])


def _next_fire_date(item: models.RecurringItem, today: date, days_ahead: int = 7) -> date | None:
    """The next date within [today, today+days_ahead] this item fires, or
    None. The single source of truth _fires_soon delegates to (bool) and the
    email's Upcoming list reads from directly (to show and sort by the real
    date, not day_of_month alone).

    Honours frequency. Matching on day-of-month alone made every yearly item
    look due in every month: once the annual card subscriptions and insurance
    renewals were entered, the email's "upcoming bills" list showed all nine of
    them ($4,313, including a $2,800 vehicle-insurance renewal) every single
    week regardless of month. Weekly/biweekly items step from start_date, and
    quarterly/yearly only fire in their designated month(s) -- the same rules
    forecast_engine._fires_on uses.
    """
    if not item.is_active:
        return None
    for offset in range(days_ahead + 1):
        d = today + timedelta(days=offset)
        if item.start_date > d:
            continue
        if item.end_date and item.end_date < d:
            continue
        if item.frequency == models.RecurringFrequency.weekly:
            if (d - item.start_date).days % 7 == 0:
                return d
            continue
        if item.frequency == models.RecurringFrequency.biweekly:
            if (d - item.start_date).days % 14 == 0:
                return d
            continue
        if item.frequency == models.RecurringFrequency.quarterly:
            if item.month_of_year and (d.month - item.month_of_year) % 3 != 0:
                continue
        elif item.frequency == models.RecurringFrequency.yearly and item.month_of_year != d.month:
            continue
        target_day = item.day_of_month or calendar.monthrange(d.year, d.month)[1]
        target_day = min(target_day, calendar.monthrange(d.year, d.month)[1])
        if d.day == target_day:
            return d
    return None


def _fires_soon(item: models.RecurringItem, today: date, days_ahead: int = 7) -> bool:
    """Whether a recurring item is due in the next `days_ahead` days."""
    return _next_fire_date(item, today, days_ahead) is not None


_WRAP = "word-break:break-word;overflow-wrap:break-word"
_CARD_STYLE = (
    "background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;"
    "margin-bottom:14px;color:#0f172a"
)
BAR_MAX_PX = 48
BAR_STUB_PX = 3


def _email_section(title: str, body: str) -> str:
    """A titled card: plain 14px semibold title (no emoji), body below."""
    return (
        f"<div class='ob-card' style='{_CARD_STYLE}'>"
        f"<p class='ob-ink' style='margin:0 0 8px;font-size:14px;font-weight:600;color:#0f172a'>{title}</p>"
        f"{body}</div>"
    )


def _weekly_lows_bars_html(lows, cushion: Decimal) -> str:
    """Email-safe weekly-lows bars: one table cell per week, bottom-aligned,
    each a fixed-size div (no SVG/canvas, which mail clients strip).

    Height = amount / max(largest positive low, cushion) x 48px; a week at or
    below $0 is a 3px stub. Colour: danger red, warning amber, the lowest `ok`
    week (earliest on a tie) the accent, the rest neutral. A week with no
    amount (every day masked) is an empty cell. Returns "" with nothing to draw.
    """
    amounts = [w.amount for w in lows if w.amount is not None]
    if not amounts:
        return ""
    denom = max(max((a for a in amounts if a > 0), default=Decimal("0")), cushion)
    ok_idx = [i for i, w in enumerate(lows) if w.amount is not None and w.status == "ok"]
    lowest_ok = min(ok_idx, key=lambda i: (lows[i].amount, i)) if ok_idx else None
    cells = []
    for i, w in enumerate(lows):
        if w.amount is None:
            cells.append("<td valign='bottom' height='48'></td>")
            continue
        if w.amount <= 0 or denom <= 0:
            h = BAR_STUB_PX
        else:
            h = max(1, round(float(w.amount / denom) * BAR_MAX_PX))
        if w.status == "danger":
            color, cls = "#dc2626", ""
        elif w.status == "warning":
            color, cls = "#d97706", ""
        elif i == lowest_ok:
            color, cls = "#0f766e", " class='ob-bar-acc'"
        else:
            color, cls = "#cbd5e1", " class='ob-bar'"
        cells.append(
            f"<td valign='bottom' height='48'><div{cls} style='width:16px;height:{h}px;"
            f"background:{color};border-radius:2px 2px 0 0'></div></td>"
        )
    return (
        "<table role='presentation' cellspacing='0' cellpadding='0' "
        "style='border-collapse:separate;border-spacing:3px 0;max-width:100%'>"
        f"<tr valign='bottom'>{''.join(cells)}</tr></table>"
    )


def generate_daily_summary(
    db: Session, user: models.User, *, weekly_digest: WeeklyDigest | None = None,
    since_lines: dict[str, str] | None = None, since_changes: list | None = None,
    snapshot_out: list | None = None, stale_out: list | None = None,
) -> tuple[str, str]:
    """Return (html_body, text_body) for a daily budget summary email.

    Pass `weekly_digest` (from `generate_weekly_digest`) on the day the
    Weekly Digest runs -- its spending-by-category/top-merchants/balance-risk
    sections get appended to this same email instead of going out as a
    separate one.

    `since_lines` maps a headline key (SINCE_KEYS) to a short "since last
    email" line (metric_diff.since_last_email), printed under that figure. `since_changes`
    (metric_diff.explain_since_last_email) adds a closing section naming what
    moved each figure; empty or None leaves it out.

    `snapshot_out`, when given, receives the snapshot used for the body (one
    item, or nothing when there is no checking account) so the caller builds
    the subject from the same numbers via `email_subject`. `stale_out`, when
    given, receives one bool: whether any bank connection is stale (the same
    check as the Needs attention warning), for `email_subject(stale=...)`.
    """
    since = since_lines or {}
    today = date.today()
    month_start = today.replace(day=1)

    accounts = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.is_active == True,
        models.Account.type == models.AccountType.checking,
    ).order_by(models.Account.id).all()
    primary_account = primary_checking(db, user.id)
    snap = compute_budget_snapshot(db, user, primary_account.id, as_of=today) if primary_account else None
    if snapshot_out is not None and snap is not None:
        snapshot_out.append(snap)

    # UpcomingBill rows, sorted chronologically by due_date -- not by
    # day_of_month, which sorts a window spanning a month boundary out of
    # order (an item firing 8/30, two days out, would previously sort AFTER
    # one firing 9/2, five days out, because 30 > 2). `types=None` keeps
    # every recurring type (income alongside expenses), matching this
    # section's row set from before upcoming_bills() existed -- unlike GET
    # /recurring/upcoming, which only ever showed expenses. amount already
    # has upcoming_bills()'s BillAmountOverride substitution applied, which
    # this list used to skip entirely (it read RecurringItem.amount
    # directly) -- bug found 2026-10-04, see .superpowers/sdd/sync-race/brief.md.
    upcoming = sorted(upcoming_bills(db, user.id, today, 7), key=lambda b: b.due_date)


    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()

    stale_connections = _stale_bank_connections(db, user.id)
    if stale_out is not None:
        stale_out.append(bool(stale_connections))
    last_pull = _last_pull_line(db, user.id)
    # Small and muted under the date; word-break so long names wrap inside
    # a 340px viewport instead of widening it, and a no-break space keeps
    # each ✓/⚠ on the same line as the connection it marks.
    last_pull_html = (
        f"<p class='ob-muted' style='color:#64748b;margin:0 0 14px;font-size:11px;line-height:1.4;"
        f"{_WRAP}'>{html_lib.escape(last_pull).replace(' ✓', '&nbsp;✓').replace(' ⚠', '&nbsp;⚠')}</p>"
    ) if last_pull else ""

    fmt = _fmt

    def _connection_label(c: models.BankConnection) -> str:
        names = [link.simplefin_account_name for link in c.links if link.simplefin_account_name]
        return ", ".join(names) if names else f"Bank connection #{c.id}"

    stale_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{_connection_label(c)}</td>"
        f"<td style='padding:4px 0'>"
        + (
            f"failing: {c.last_error}" if c.status == models.BankConnectionStatus.error and c.last_error
            else "sync failing" if c.status == models.BankConnectionStatus.error
            else "no sync in 24+ hours" if c.last_synced_at is None
            else f"last synced {c.last_synced_at.strftime('%b %-d, %-I:%M %p')} UTC"
        )
        + "</td></tr>"
        for c in stale_connections
    )
    stale_html = (
        f"<p style='margin:0 0 4px;font-weight:600;font-size:13px'>Stale bank data</p>"
        f"<table style='width:100%;font-size:13px;color:#92400e'>{stale_rows}</table>"
        f"<p style='margin:4px 0 0;font-size:12px'>Balances and transactions below may not reflect today's activity.</p>"
    ) if stale_connections else ""

    acct_last_txn = _last_txn_dates(db, models.Transaction.account_id, models.Transaction.date, [a.id for a in accounts])

    acct_rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0;color:#0f172a'>{a.name}"
        f"<br><span style='color:#64748b;font-size:11px;font-weight:400'>{_last_txn_label(acct_last_txn.get(a.id))}</span>"
        + (_since_html(since.get(SINCE_CHECKING), "2px 0 0", "font-weight:400;")
           if primary_account is not None and a.id == primary_account.id else "")
        + "</td>"
        f"<td style='padding:6px 0;text-align:right'><b style='color:#0f172a'>{fmt(a.current_balance)}</b></td></tr>"
        for a in accounts
    ) or "<tr><td style='color:#64748b'>No checking accounts</td></tr>"

    def _day_label(d: date) -> str:
        offset = (d - today).days
        if offset == 0:
            return "Today"
        if offset == 1:
            return "Tomorrow"
        return d.strftime("%a %b %-d")

    upcoming_rows = "".join(
        (
            lambda is_income: (
                f"<tr><td style='padding:6px 12px 6px 0;color:#64748b;font-size:12px;white-space:nowrap;vertical-align:top'>{_day_label(b.due_date)}</td>"
                f"<td style='padding:6px 12px 6px 0;color:#0f172a'>{b.name}</td>"
                f"<td style='padding:6px 0;text-align:right;white-space:nowrap'>"
                f"<b style='color:{'#059669' if is_income else '#dc2626'}'>{'+' if is_income else '−'}{fmt(b.amount)}</b>"
                + (" <span style='color:#64748b;font-size:10px'>actual</span>" if b.is_actual else "")
                + "</td></tr>"
            )
        )(b.type == models.RecurringType.income)
        for b in upcoming
    ) or "<tr><td style='color:#64748b'>None in the next 7 days</td></tr>"

    # snap.cards carries utilization_pct and pending_charges already computed
    # for the exact same reason the Dashboard's card list does -- reusing it
    # here means the email and the app can never quietly disagree about a
    # card's numbers the way two independent computations eventually would.
    snap_cards_by_id = {c.id: c for c in snap.cards} if snap is not None else {}
    card_last_txn = _last_txn_dates(db, models.CreditCardTransaction.card_id, models.CreditCardTransaction.date, [c.id for c in cards])

    def _cycle_breakdown(c: models.CreditCard) -> tuple[Decimal, Decimal, bool]:
        """(balance_due, spend since that statement closed, statement-looks-stale).

        A card's current_balance blends two things that call for different
        reactions: balance_due is already-statemented debt that leaves on the
        due date no matter what the user does now, while the remainder is new spend
        he can still steer. This is the statement cycle, not Left to Spend's
        figure: since 2026-10-30 Left to Spend counts card purchases by
        calendar month instead.

        balance_due is manual-entry only (bank sync never writes it), so it
        goes stale after a payment and can exceed current_balance -- which
        makes the subtraction negative. That negative IS the staleness
        signal, so report it as one rather than rendering it.
        """
        sc = snap_cards_by_id.get(c.id)
        balance_due = sc.balance_due if sc else c.balance_due
        pending = sc.pending_charges if sc else card_pending(c, today)
        cycle_spend = c.current_balance - balance_due + pending
        if cycle_spend < 0:
            return balance_due, Decimal("0"), True
        return balance_due, cycle_spend, False

    def _due_label(c: models.CreditCard) -> str:
        """"due Sep 25" -- the date the statement actually leaves checking."""
        if not c.due_day:
            return "due"
        due_date = _next_occurrence_on_or_after(c.due_day, today)
        return f"due {due_date.strftime('%b %-d')}"

    def _card_row(c: models.CreditCard) -> str:
        sc = snap_cards_by_id.get(c.id)
        util = sc.utilization_pct if sc else (
            round(float(c.current_balance) / float(c.credit_limit) * 100, 1) if c.credit_limit else 0.0
        )
        util_color = "#dc2626" if util >= 80 else "#d97706" if util >= 50 else "#64748b"
        pending = sc.pending_charges if sc else Decimal("0")
        pending_html = f" <span style='color:#64748b'>(+{fmt(pending)} pending)</span>" if pending else ""
        due_in = None
        if c.due_day:
            # Same next-occurrence helper _due_label uses below, so "due in
            # Nd" and "due Mon D" can never disagree about which date is
            # next (the old modulo-days-in-month math clamped differently
            # than the date itself near short months -- e.g. due_day 31 on
            # Sep 30 said "due in 1d" next to "due Sep 30").
            days_out = (_next_occurrence_on_or_after(c.due_day, today) - today).days
            due_in = "due today" if days_out == 0 else f"due in {days_out}d"
        balance_due, cycle_spend, stale = _cycle_breakdown(c)
        breakdown = (
            f"{fmt(balance_due)} {_due_label(c)} &middot; {fmt(cycle_spend)} spent this cycle"
            + (" &middot; <span style='color:#d97706'>statement figure may be stale</span>" if stale else "")
        )
        return (
            f"<tr><td style='padding:6px 12px 6px 0;color:#0f172a'>{c.name}"
            f"<br><span style='color:#64748b;font-size:11px;font-weight:400'>{_last_txn_label(card_last_txn.get(c.id))}</span>"
            f"<br><span style='color:#64748b;font-size:11px;font-weight:400'>{breakdown}</span></td>"
            f"<td style='padding:6px 0;text-align:right;vertical-align:top'><b style='color:#0f172a'>{fmt(c.current_balance)}</b>{pending_html}</td>"
            f"<td style='padding:6px 0 6px 12px;text-align:right;white-space:nowrap;font-size:12px;vertical-align:top'>"
            f"<span style='color:{util_color}'>{util:.0f}% used</span>"
            + (f" <span style='color:#64748b'>&middot; {due_in}</span>" if due_in else "")
            + "</td></tr>"
        )

    card_rows = "".join(_card_row(c) for c in cards) or "<tr><td colspan='3' style='color:#64748b'>No credit cards</td></tr>"

    attention_items: list[str] = []
    if stale_html:
        attention_items.append(stale_html)
    if snap is not None:
        # Owner ruling 2026-11-26: figures carry semantic colour. Safety
        # Margin is green at $0 or above, red below; Spendable green while
        # on pace (>= $0), amber when over. Never amber on the Safety Margin.
        margin_color, margin_cls = ("#dc2626", "ob-neg") if snap.safety_margin_weekly < 0 else ("#059669", "ob-pos")
        spend_color, spend_cls = ("#b45309", "ob-amber") if snap.left_to_spend_weekly < 0 else ("#059669", "ob-pos")

        # Only Safety Margin signals savings moves now. Left to Spend answers
        # "am I on budget", and mixing a savings instruction into it made the
        # two numbers say overlapping things.
        pull_line = f"Pull {fmt(snap.savings_pull_needed)} from savings" if snap.savings_pull_needed > 0 else ""
        spendable_today_sign = "−" if snap.spendable_today < 0 else ""
        margin_today_sign = "−" if snap.safety_margin_today < 0 else ""
        # The "lowest balance" lines (the sanity check behind the weekly
        # numbers -- whether a big purchase is safe) plus the move-to-checking
        # line when next month's low dips below $0. Shared with the text body
        # via _lowest_balance_rows/_move_to_checking_line so the two can't drift.
        lowest_rows = _lowest_balance_rows(snap)
        move_line = _move_to_checking_line(snap)
        # The 3-month row is plain info when lookahead_status is "ok", amber
        # below the cushion and red below $0, with a short phrase saying which.
        lookahead_warning = _lookahead_warning(snap)
        lookahead_color = {"warning": "#d97706", "danger": "#dc2626"}.get(snap.lookahead_status)
        lowest_html_parts: list[str] = []
        for i, (label, amount, d) in enumerate(lowest_rows):
            row_color = "#dc2626" if amount < 0 else "#0f172a"
            warning_html = ""
            if lookahead_warning and _is_lookahead_row(label):
                row_color = lookahead_color
                warning_html = (
                    f" <span class='{'ob-neg' if lookahead_color == '#dc2626' else 'ob-amber'}' "
                    f"style='color:{lookahead_color};font-weight:600'>"
                    f"&middot; {lookahead_warning}</span>"
                )
                attention_items.append(
                    f"<p style='margin:0;font-size:13px;{_WRAP}'>{label}: {fmt(amount)} on "
                    f"{d.strftime('%b %-d')} &middot; {lookahead_warning}</p>"
                )
            row_cls = "ob-neg" if row_color == "#dc2626" else "ob-amber" if row_color == "#d97706" else "ob-ink"
            lowest_html_parts.append(
                f"<p class='ob-muted' style='color:#64748b;font-size:13px;margin:{'10px' if i == 0 else '6px'} 0 0;"
                f"{_WRAP}'>{label}: "
                f"<b class='{row_cls}' style='color:{row_color}'>{fmt(amount)}</b> on {d.strftime('%b %-d')}{warning_html}</p>"
                + _since_html(_lowest_row_since(label, since), "2px 0 0")
            )
            if i == 0 and move_line:
                lowest_html_parts.append(
                    f"<p class='ob-neg' style='color:#dc2626;font-size:12px;margin:4px 0 0;{_WRAP}'>{move_line}</p>"
                )
        lowest_html = "".join(lowest_html_parts)
        if move_line:
            attention_items.append(f"<p style='margin:0;font-size:13px;{_WRAP}'>{move_line}</p>")
        if pull_line:
            attention_items.append(f"<p style='margin:0;font-size:13px;{_WRAP}'>{pull_line}</p>")

        pending_html = (
            f"<p class='ob-muted' style='margin:0;color:#64748b;font-size:13px;{_WRAP}'>"
            f"Includes pending charges on {snap.pending_cards_count} card"
            f"{'' if snap.pending_cards_count == 1 else 's'} ({fmt(snap.pending_cards_total)})</p>"
        ) if snap.pending_cards_count > 0 else ""
        pull_pill = (
            f"<p style='margin:8px 0 0;display:inline-block;background:#fef3c7;color:#92400e;font-size:13px;"
            f"padding:5px 10px;border-radius:8px'>{pull_line}</p>"
        ) if pull_line else ""
        pace_color = "#64748b" if snap.on_pace else "#92400e"
        pace_cls = "ob-muted" if snap.on_pace else "ob-warn-text"
        bars_html = _weekly_lows_bars_html(snap.weekly_lows, snap.safety_cushion)
        bars_block = (
            f"<p class='ob-muted' style='margin:14px 0 6px;color:#64748b;font-size:11px;letter-spacing:.04em'>"
            f"CHECKING LOW POINT EACH WEEK &middot; NEXT 3 MONTHS</p>{bars_html}"
        ) if bars_html else ""

        # Mobile-first inline sizes; the <head> @media block only enlarges
        # for wide screens and supplies the dark palette -- never functionality.
        household_html = f"""
<div class='ob-card ob-hero' style='background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:14px;color:#0f172a'>
  <p class='ob-ink' style='margin:0 0 8px;color:#0f172a;font-size:14px;font-weight:600'>Household Snapshot</p>
  <p class='ob-muted' style='margin:0;color:#64748b;font-size:13px'>Safety Margin (this week)</p>
  <p class='{margin_cls}' data-ob='margin-figure' style='margin:2px 0;color:{margin_color};font-size:32px;font-weight:700;line-height:1.1;{_WRAP}'>{fmt(snap.safety_margin_weekly)}</p>
  <p class='ob-muted' style='margin:0;color:#64748b;font-size:13px;{_WRAP}'>{margin_today_sign}{fmt(abs(snap.safety_margin_today))}/day &middot; {fmt(snap.safety_margin)} this month</p>
  {_since_html(since.get(SINCE_MARGIN), "2px 0 0")}
  {pending_html}
  {pull_pill}
  <div class='ob-line' style='border-top:1px solid #e2e8f0;margin-top:12px;padding-top:10px'>
    <p class='ob-muted' style='margin:0;color:#64748b;font-size:13px'>Spendable this week</p>
    <p class='{spend_cls}' data-ob='spendable-figure' style='margin:2px 0 0;color:{spend_color};font-size:20px;font-weight:600;{_WRAP}'>{fmt(snap.left_to_spend_weekly)}</p>
    <p class='{pace_cls}' style='margin:0;color:{pace_color};font-size:13px;{_WRAP}'>{spendable_today_sign}{fmt(abs(snap.spendable_today))}/day &middot; {"on pace" if snap.on_pace else "over pace"}</p>
    <p class='ob-muted' style='margin:0;color:#64748b;font-size:13px;{_WRAP}'>{fmt(snap.left_to_spend)} this month</p>
    {_since_html(since.get(SINCE_SPENDABLE), "2px 0 0")}
  </div>
  {bars_block}
  {lowest_html}
</div>"""
    else:
        household_html = (
            f"<div class='ob-card' style='{_CARD_STYLE}'>"
            "<p style='margin:0 0 4px;font-size:14px;font-weight:600'>Household Snapshot</p>"
            "<p class='ob-muted' style='color:#64748b;margin:0'>No checking account to compute a snapshot from.</p></div>"
        )

    if attention_items:
        needs_html = (
            "<div class='ob-warn' style='background:#fef3c7;border:1px solid #fde68a;border-radius:12px;"
            "padding:12px 16px;margin-bottom:14px;color:#92400e'>"
            "<p style='margin:0 0 4px;font-weight:600;font-size:14px'>Needs attention</p>"
            + "".join(f"<div style='margin:0 0 6px'>{item}</div>" for item in attention_items)
            + "</div>"
        )
    else:
        needs_html = (
            f"<div class='ob-card' style='{_CARD_STYLE};padding:12px 16px'>"
            "<p class='ob-muted' style='margin:0;color:#64748b;font-size:13px'>Nothing needs you today.</p></div>"
        )

    weekly_html, weekly_text = _weekly_digest_section(weekly_digest) if weekly_digest else ("", "")


    # ── "Spending this month" ───────────────────────────────────────────
    # The weekly digest's breakdown over the month so far, from the same
    # spending_breakdown the Dashboard's digest card uses. On the 1st,
    # month_start == today -- a range would read "Oct 1–1", so show the date.
    month_range = (
        f"{month_start.strftime('%b')} {month_start.day}"
        if month_start == today
        else f"{month_start.strftime('%b')} {month_start.day}–{today.day}"
    )
    month = spending_breakdown(db, user.id, month_start, today)
    month_title = f"Spending this month ({month_range})"
    month_tables_html, month_tables_text = _breakdown_tables(month.categories, month.top_merchants, "this month")
    month_section_html = _email_section(month_title, (
        f"<p style='font-size:14px;color:#0f172a;margin:0 0 8px'>Total spent: "
        f"<b style='color:#0f172a'>{fmt(month.total)}</b></p>{month_tables_html}"
    ))
    month_section_text = f"{month_title.upper()}\n  Total spent: {fmt(month.total)}\n{month_tables_text}\n"

    changes_html, changes_text = _changes_section(since_changes, _email_section)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<meta name='color-scheme' content='light dark'>
<meta name='supported-color-schemes' content='light dark'>
<style>
/* Progressive enhancement only: every inline style is already a correct
   light-mode render, so a client that strips <style> loses nothing. */
@media (min-width: 600px) {{
  .ob-hero {{ padding: 20px !important; }}
}}
@media (prefers-color-scheme: dark) {{
  .ob-page {{ background: #0b1220 !important; }}
  .ob-card {{ background: #131c2e !important; border-color: #22304a !important; color: #e2e8f0 !important; }}
  .ob-line {{ border-color: #22304a !important; }}
  .ob-ink, [style*="color:#0f172a"] {{ color: #e2e8f0 !important; }}
  .ob-muted, [style*="color:#64748b"] {{ color: #94a3b8 !important; }}
  .ob-pos {{ color: #34d399 !important; }}
  .ob-neg {{ color: #f87171 !important; }}
  .ob-amber, .ob-warn-text {{ color: #fbbf24 !important; }}
  .ob-bar {{ background: #334155 !important; }}
  .ob-bar-acc {{ background: #2dd4bf !important; }}
  .ob-accent {{ color: #2dd4bf !important; }}
  .ob-warn {{ background: #2a1a06 !important; border-color: #78350f !important; color: #fcd34d !important; }}
  .ob-warn table, .ob-warn p, .ob-warn div {{ color: #fcd34d !important; }}
}}
</style>
</head>
<body class='ob-page' style='font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#f8fafc;margin:0;padding:16px 0;color:#0f172a'>
<div style='max-width:600px;margin:0 auto;padding:0 16px'>
<p class='ob-accent' style='margin:0 0 2px;color:#0f766e;font-weight:700;font-size:13px'>OfflineBudget Daily Summary</p>
<p class='ob-muted' style='color:#64748b;margin:0 0 14px;font-size:13px'>{today.strftime("%A, %B %-d, %Y")}</p>
{last_pull_html}
{household_html}
{needs_html}
{changes_html}
{_email_section("Checking Accounts", f"<table style='width:100%;font-size:14px'>{acct_rows}</table>")}
{_email_section("Upcoming (next 7 days)", f"<table style='width:100%;font-size:14px'>{upcoming_rows}</table>")}
{_email_section("Credit Cards", f"<table style='width:100%;font-size:14px'>{card_rows}</table>")}
{weekly_html}
{month_section_html}
<p class='ob-muted' style='color:#64748b;font-size:11px;margin-top:20px;text-align:center'>Sent by OfflineBudget</p>
</div>
</body></html>"""

    acct_text = "".join(
        f"  {a.name}: {fmt(a.current_balance)} ({_last_txn_label(acct_last_txn.get(a.id))})\n"
        + (_since_text(since.get(SINCE_CHECKING)) if primary_account is not None and a.id == primary_account.id else "")
        for a in accounts
    ).rstrip("\n") or "  No checking accounts"
    upcoming_text = "\n".join(
        f"  {_day_label(b.due_date):<10} {b.name}: {'+' if b.type == models.RecurringType.income else '-'}{fmt(b.amount)}"
        + (" (actual)" if b.is_actual else "")
        for b in upcoming
    ) or "  None in the next 7 days"
    def _card_text_row(c: models.CreditCard) -> str:
        balance_due, cycle_spend, stale = _cycle_breakdown(c)
        util = snap_cards_by_id.get(c.id).utilization_pct if snap_cards_by_id.get(c.id) else 0
        return (
            f"  {c.name}: {fmt(c.current_balance)} "
            f"({util:.0f}% used, due day {c.due_day}, {_last_txn_label(card_last_txn.get(c.id))})\n"
            f"    {fmt(balance_due)} {_due_label(c)} | {fmt(cycle_spend)} spent this cycle"
            + (" | statement figure may be stale" if stale else "")
        )

    card_text = "\n".join(_card_text_row(c) for c in cards) or "  No credit cards"

    if snap is not None:
        # Reuses lowest_rows/move_line computed above for household_html --
        # same same-date/combined-line/move-line logic, just rendered plain.
        lowest_text = "".join(
            f"  {label}: {fmt(amount)} on {d.strftime('%b %-d')}"
            + (f" ({lookahead_warning})" if lookahead_warning and _is_lookahead_row(label) else "")
            + ".\n"
            + _since_text(_lowest_row_since(label, since))
            + (f"  {move_line}.\n" if i == 0 and move_line else "")
            for i, (label, amount, d) in enumerate(lowest_rows)
        )
        household_text = (
            "HOUSEHOLD SNAPSHOT\n"
            + f"  Safety margin (this week): {fmt(snap.safety_margin_weekly)}"
            + f" ({margin_today_sign}{fmt(abs(snap.safety_margin_today))}/day)"
            + ("" if snap.savings_pull_needed <= 0 else
               f"  (pull {fmt(snap.savings_pull_needed)} from savings)")
            + "\n"
            + _since_text(since.get(SINCE_MARGIN))
            + (f"  Includes pending charges on {snap.pending_cards_count} card"
               f"{'' if snap.pending_cards_count == 1 else 's'} ({fmt(snap.pending_cards_total)})\n"
               if snap.pending_cards_count > 0 else "")
            + f"  Spendable this week: {fmt(snap.left_to_spend_weekly)}\n"
            + _since_text(since.get(SINCE_SPENDABLE))
            + f"  Monthly: {fmt(snap.left_to_spend)} left to spend, {fmt(snap.safety_margin)} before your spending starts eating into savings.\n"
            + lowest_text
        )
    else:
        household_text = "HOUSEHOLD SNAPSHOT\n  No checking account to compute a snapshot from.\n"

    def _stale_reason(c: models.BankConnection) -> str:
        if c.status == models.BankConnectionStatus.error:
            return f"failing: {c.last_error}" if c.last_error else "sync failing"
        if c.last_synced_at is None:
            return "no sync in 24+ hours"
        return f"last synced {c.last_synced_at.strftime('%b %-d, %-I:%M %p')} UTC"

    stale_text = (
        "\nSTALE BANK DATA -- balances/transactions below may not reflect today's activity\n"
        + "\n".join(f"  {_connection_label(c)}: {_stale_reason(c)}" for c in stale_connections) + "\n"
    ) if stale_connections else ""

    last_pull_text = f"{last_pull}\n" if last_pull else ""
    text = f"""OfflineBudget Daily Summary — {today.strftime("%B %-d, %Y")}
{last_pull_text}{stale_text}
{household_text}{changes_text}
CHECKING ACCOUNTS
{acct_text}

UPCOMING BILLS (next 7 days)
{upcoming_text}

CREDIT CARDS
{card_text}

{weekly_text}{month_section_text}"""
    return html, text


CHANGES_MAX_ITEMS = 5
CHANGES_MAX_REASONS = 6


def _reasons(changes) -> list[tuple]:
    """The distinct reasons across all moved figures, in order of first
    appearance: (cause, labels of the figures it moved, in `changes` order).
    A group matches on head + (name, amount) rows, a line on its text. A "Same causes
    as" placeholder is no reason; its figure counts as moved by every reason
    of the parent."""
    by_key = {ch.key: ch for ch in changes}

    def causes_of(ch, depth=0):
        if ch.causes and ch.causes[0].parent_key and depth < 8:
            parent = by_key.get(ch.causes[0].parent_key)
            return causes_of(parent, depth + 1) if parent is not None else []
        return [] if ch.causes and ch.causes[0].parent_key else ch.causes

    order: dict[tuple, list] = {}
    for ch in changes:
        for c in causes_of(ch):
            # Unlike statement_for's `not c.short` filter, this only drops a line
            # cause whose text is purely its own short form (no amount added) —
            # the popup has a math-lines fallback table for every line cause, the
            # email doesn't, so the email keeps any line cause that still names a
            # real figure. Deliberately different filters; don't unify them.
            if not c.head and c.text == c.short:
                continue
            ident = ("g", c.head, tuple(c.rows)) if c.head else ("l", c.text)
            entry = order.setdefault(ident, [c, []])
            if ch.label not in entry[1]:
                entry[1].append(ch.label)
    return [(c, labels) for c, labels in order.values()]


def _cause_item(c, esc, money) -> tuple[str, list[str]]:
    """One cause's own markup: its grouped `head` with up to CHANGES_MAX_ITEMS
    `rows` (then an "and N more" line), or its plain `text` -- the rendering
    a reason gets in the shared top-line list, reused verbatim for a receipt
    figure's own "What changed" causes (see `_receipt_block`), so the two
    lists can never render a cause differently."""
    rows = [(n, "" if a is None else money(a)) for n, a in c.rows] if c.head else []
    kept, hidden = rows[:CHANGES_MAX_ITEMS], max(len(rows) - CHANGES_MAX_ITEMS, 0)
    sub = "".join(
        f"<li style='margin:1px 0'>{esc(n)}{(' ' + esc(a)) if a else ''}</li>" for n, a in kept
    )
    if hidden:
        sub += f"<li style='margin:1px 0;color:#64748b'>and {hidden} more</li>"
    html = esc(c.head or c.text) + (f"<ul style='margin:2px 0;padding-left:16px'>{sub}</ul>" if sub else "")
    text_lines = [c.head or c.text] + [f"    {n}{(' ' + a) if a else ''}" for n, a in kept]
    if hidden:
        text_lines.append(f"    and {hidden} more")
    return html, text_lines


def _value_money(amount: Decimal, money) -> str:
    """A snapshot value's own figure (old or new -- never a delta), with a
    plain minus sign when it's negative and nothing extra otherwise (never a
    "+") -- the convention frontend/src/lib/historyMoney.ts's
    signedMoney(hidden, v, false) already uses for a value rather than a
    delta. `money()` alone is f"${{abs(amount):,.2f}}" and silently strips
    the sign, which is actively misleading for Safety Margin: it legitimately
    goes negative in production (this file already color-codes
    safety_margin_weekly < 0 elsewhere)."""
    from backend.services.metric_diff import CENT, MINUS
    return f"{MINUS if amount.quantize(CENT) < 0 else ''}{money(amount)}"


def _math_figures(old: Decimal | None, new: Decimal | None, money, signed_money) -> str:
    """One math line's before/after, worded for a line that appeared,
    vanished, held steady, or moved -- mirrors
    frontend/src/lib/historyMoney.ts's mathFigures(). `old`/`new` are
    snapshot values, not deltas, so they go through `_value_money`, not the
    unsigned `money()`."""
    if old is None:
        return f"added, {_value_money(new, money)}"
    if new is None:
        return f"removed, was {_value_money(old, money)}"
    if old == new:
        return f"{_value_money(old, money)}, no change"
    return f"{_value_money(old, money)} → {_value_money(new, money)}"


def _receipt_block(ch, money, signed_money, esc, wrap) -> tuple[str, list[str]]:
    """The full itemized receipt for the one figure (if any) whose key is in
    `receipt_keys` (see explain_since_last_email): its own header (old → new,
    signed delta), a "What changed" sub-section listing its own causes --
    never collapsed to "Same causes as ..." -- capped at CHANGES_MAX_ITEMS
    like the shared reasons list, and a "How the number moved" sub-section
    walking `ch.math` line by line with a bold total row. ("", []) when `ch`
    is None (nothing moved this batch, or the email names no receipt figure)
    or, for the math sub-section alone, when `ch.math` is empty (mirrors
    WhatChanged.tsx's `row.math.length > 0` guard)."""
    if ch is None:
        return "", []
    old_v, new_v = _value_money(ch.old_value, money), _value_money(ch.new_value, money)
    header_text = f"{ch.label}: {old_v} → {new_v} ({signed_money(ch.delta)})"
    header_html = f"{esc(ch.label)}: {old_v} → {new_v} ({signed_money(ch.delta)})"

    causes, extra = ch.causes[:CHANGES_MAX_ITEMS], max(len(ch.causes) - CHANGES_MAX_ITEMS, 0)
    cause_items_html = ""
    cause_text_lines: list[str] = []
    for c in causes:
        item_html, item_text_lines = _cause_item(c, esc, money)
        cause_items_html += f"<li style='margin:4px 0'>{item_html}</li>"
        cause_text_lines.append(f"- {item_text_lines[0]}")
        cause_text_lines += item_text_lines[1:]
    if extra > 0:
        cause_items_html += f"<li style='margin:4px 0;color:#64748b'>and {extra} more</li>"
        cause_text_lines.append(f"- and {extra} more")

    sub_heading = "margin:10px 0 2px;font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.03em"
    html = (
        f"<p style='margin:10px 0 4px;font-size:14px;color:#0f172a;{wrap}'><b>{header_html}</b></p>"
        f"<p style='{sub_heading}'>What changed</p>"
        f"<ul style='margin:0;padding-left:20px;font-size:13px;color:#0f172a;{wrap}'>{cause_items_html}</ul>"
    )
    text_lines = [header_text, "What changed", *cause_text_lines]

    if ch.math:
        total = _math_figures(ch.old_value, ch.new_value, money, signed_money)
        math_items_html = "".join(
            f"<li style='margin:2px 0'>{esc(m.label)}: {_math_figures(m.old, m.new, money, signed_money)}"
            + "".join(
                f"<div style='padding-left:16px;color:#64748b'>{esc(p.label)} {signed_money(p.delta)}</div>"
                for p in m.parts
            ) + "</li>"
            for m in ch.math
        )
        html += (
            f"<p style='{sub_heading}'>How the number moved</p>"
            f"<ul style='margin:0;padding-left:20px;font-size:13px;color:#0f172a;{wrap}'>"
            f"{math_items_html}<li style='margin:2px 0;font-weight:600'>{esc(ch.label)}: {total}</li></ul>"
        )
        text_lines.append("How the number moved")
        for m in ch.math:
            text_lines.append(f"  {m.label}: {_math_figures(m.old, m.new, money, signed_money)}")
            text_lines += [f"    {p.label} {signed_money(p.delta)}" for p in m.parts]
        text_lines.append(f"  {ch.label}: {total}")

    return html, text_lines


def _changes_section(changes: list | None, section) -> tuple[str, str]:
    """The closing "What changed since last email" section: (html, text),
    both empty when nothing moved. One line of moved figures, then each
    reason once, scoped to the figures that aren't getting the full receipt
    treatment below (see `_receipt_block`) -- the one figure in `changes`
    carrying its own old/new value and math (SINCE_RECEIPT_KEYS) gets its own
    itemized receipt instead of folding into this shared list."""
    if not changes:
        return "", ""
    from backend.services.metric_diff import money, signed_money
    esc = html_lib.escape
    title = "What changed since last email"
    wrap = "white-space:normal;word-break:break-word;overflow-wrap:break-word"
    receipt = next((ch for ch in changes if ch.old_value is not None), None)
    others = [ch for ch in changes if ch.old_value is None]

    others_html, others_text_lines = "", []
    if others:
        all_labels = [ch.label for ch in others]
        top_pairs = [f"{ch.label} {signed_money(ch.delta)}" for ch in others]
        reasons = _reasons(others)
        shown, extra = reasons[:CHANGES_MAX_REASONS], len(reasons) - CHANGES_MAX_REASONS
        top_html = " · ".join(f"<span style='white-space:nowrap'>{esc(t)}</span>" for t in top_pairs)
        others_text_lines = [" · ".join(top_pairs)]
        items_html = ""
        for c, labels in shown:
            item_html, item_text_lines = _cause_item(c, esc, money)
            moved = labels != all_labels
            note = f"Moved: {', '.join(labels)}" if moved else ""
            items_html += (
                f"<li style='margin:4px 0'>{item_html}"
                + (f"<div style='font-size:12px;color:#64748b'>{esc(note)}</div>" if note else "")
                + "</li>"
            )
            others_text_lines.append(f"- {item_text_lines[0]}")
            others_text_lines += item_text_lines[1:]
            if note:
                others_text_lines.append(f"    {note}")
        if extra > 0:
            items_html += f"<li style='margin:4px 0;color:#64748b'>and {extra} more reasons</li>"
            others_text_lines.append(f"- and {extra} more reasons")
        others_html = (
            f"<p style='margin:10px 0 4px;font-size:14px;color:#0f172a;{wrap}'><b>{top_html}</b></p>"
            f"<ul style='margin:0;padding-left:20px;font-size:13px;color:#0f172a;{wrap}'>{items_html}</ul>"
        )

    receipt_html, receipt_text_lines = _receipt_block(receipt, money, signed_money, esc, wrap)

    body = others_html + receipt_html
    text_lines = others_text_lines + receipt_text_lines
    return section(title, body), f"\n{title.upper()}\n" + "\n".join(text_lines) + "\n"


def _breakdown_tables(categories, merchants, period: str) -> tuple[str, str]:
    """The "Spending by Category" and "Top Merchants" tables shared by the
    weekly digest and the monthly section. `period` words the empty state
    ("this week" / "this month")."""
    fmt = _fmt
    cat_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.category_name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.total)}</td></tr>"
        for c in categories
    ) or f"<tr><td style='color:#888'>No categorized spending {period}</td></tr>"
    cat_text = "\n".join(
        f"  {c.category_name}: {fmt(c.total)}" for c in categories
    ) or f"  No categorized spending {period}"
    merchant_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{m.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(m.total)}</td></tr>"
        for m in merchants[:10]
    ) or f"<tr><td style='color:#888'>No merchant activity {period}</td></tr>"
    merchant_text = "\n".join(
        f"  {m.name}: {fmt(m.total)}" for m in merchants[:10]
    ) or f"  No merchant activity {period}"
    heading = "margin:{top}px 0 4px;font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.03em"
    html = (
        f"<h4 style='{heading.format(top=12)}'>Spending by Category</h4>"
        f"<table style='width:100%;font-size:14px'>{cat_rows}</table>"
        f"<h4 style='{heading.format(top=14)}'>Top Merchants</h4>"
        f"<table style='width:100%;font-size:14px'>{merchant_rows}</table>"
    )
    text = f"SPENDING BY CATEGORY ({period})\n{cat_text}\n\nTOP MERCHANTS ({period})\n{merchant_text}"
    return html, text


def _weekly_digest_section(digest: WeeklyDigest) -> tuple[str, str]:
    """Render the Weekly Digest's own content (spending by category, top
    merchants, balance risk) as an HTML/text fragment appended to that
    day's Daily Summary -- the Household Snapshot and Credit Cards sections
    already live in the Daily Summary itself, so they aren't repeated here.
    """
    fmt = _fmt
    tables_html, tables_text = _breakdown_tables(digest.categories, digest.top_merchants, "this week")

    risk_html = ""
    risk_text = ""
    if digest.risk.at_risk and digest.risk.date is not None:
        risk_html = (
            f"<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin:12px 0'>"
            f"<p style='margin:0;color:#991b1b;font-weight:600;font-size:13px'>Balance Risk</p>"
            f"<p style='margin:4px 0 0;color:#991b1b;font-size:13px'>Projected to drop to {fmt(digest.risk.amount)} on "
            f"{digest.risk.date.strftime('%B %-d, %Y')}.</p></div>"
        )
        risk_text = f"\n  Balance risk: projected to drop to {fmt(digest.risk.amount)} on {digest.risk.date.strftime('%B %-d, %Y')}\n"

    html = f"""
<div style='margin-bottom:22px'>
<h3 style='margin:24px 0 8px;padding-bottom:6px;border-bottom:1px solid #e2e8f0;color:#0f172a;font-size:14px;font-weight:600'>🗓️&nbsp; Weekly Digest — {digest.week_start.strftime('%B %-d')}–{digest.week_end.strftime('%B %-d, %Y')}</h3>
<p style='font-size:14px;color:#0f172a;margin:0 0 8px'>Total spent this week: <b style='color:#0f172a'>{fmt(digest.total_spent)}</b></p>
{risk_html}
{tables_html}
</div>
"""

    text = f"""
WEEKLY DIGEST — {digest.week_start.strftime('%B %-d')} to {digest.week_end.strftime('%B %-d, %Y')}
  Total spent this week: {fmt(digest.total_spent)}
{risk_text}
{tables_text}
"""
    return html, text


def _month_spending_by_category(
    db: Session, user_id: int, year: int, month: int
) -> tuple[dict[int, Decimal], Decimal, Decimal]:
    """Returns (spending_by_category_id, total_debits, total_credits) for the
    calendar month: real spending (net of refunds) per category, total real
    spending, and total income, all from the one real-spending rule
    (services/real_spend.spend_totals) the budget overview and Sankey use.
    Uncategorized spend counts in the total but has no category entry.
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    totals = spend_totals(db, user_id, start, end)
    by_cat = {cid: amt for cid, amt in totals.by_category.items() if cid is not None}
    return by_cat, totals.spend, totals.income


def generate_summary(db: Session, user_id: int, year: int, month: int) -> MonthlySummary:
    by_cat, total_debits, total_credits = _month_spending_by_category(db, user_id, year, month)

    if not by_cat and total_debits == 0 and total_credits == 0:
        return MonthlySummary(
            year=year,
            month=month,
            top_category=None,
            top_category_amount=None,
            mom_delta=None,
            mom_delta_pct=None,
            net_cashflow=Decimal("0"),
            text="Not enough data yet for this month.",
        )

    top_cat_id = max(by_cat, key=lambda k: by_cat[k]) if by_cat else None
    top_cat_name: str | None = None
    top_cat_amount: Decimal | None = None
    if top_cat_id:
        cat_map = {c.id: c.name for c in db.query(models.Category).filter(
            models.Category.user_id == user_id).all()}
        top_cat_name = cat_map.get(top_cat_id)
        top_cat_amount = by_cat[top_cat_id]

    prior_year, prior_month = (year - 1, 12) if month == 1 else (year, month - 1)
    _, prior_debits, _ = _month_spending_by_category(db, user_id, prior_year, prior_month)
    mom_delta = total_debits - prior_debits if prior_debits > 0 else None
    mom_delta_pct: Decimal | None = None
    if prior_debits > 0:
        mom_delta_pct = Decimal(str(round(float((total_debits - prior_debits) / prior_debits * 100), 1)))

    net_cashflow = total_credits - total_debits

    parts: list[str] = []

    if top_cat_name and top_cat_amount:
        parts.append(f"Your top spending category was {top_cat_name} at ${top_cat_amount:,.2f}.")

    if mom_delta is not None and mom_delta_pct is not None:
        direction = "up" if mom_delta > 0 else "down"
        label = "more" if mom_delta > 0 else "less"
        parts.append(
            f"Overall spending was {direction} {abs(mom_delta_pct):.1f}% "
            f"(${abs(mom_delta):,.2f} {label}) vs. last month."
        )

    if net_cashflow >= 0:
        parts.append(f"You came out ahead by ${net_cashflow:,.2f} this month.")
    else:
        parts.append(f"You spent ${abs(net_cashflow):,.2f} more than you earned this month.")

    return MonthlySummary(
        year=year,
        month=month,
        top_category=top_cat_name,
        top_category_amount=top_cat_amount,
        mom_delta=mom_delta,
        mom_delta_pct=mom_delta_pct,
        net_cashflow=net_cashflow,
        text=" ".join(parts),
    )


# ── Weekly digest ─────────────────────────────────────────────────────────────

def generate_weekly_digest(db: Session, user: models.User, account_id: int) -> WeeklyDigest:
    """Trailing 7 days of spending (category totals + top merchants) plus the
    forward-looking negative-balance risk for the given checking account.
    """
    today = date.today()
    week_start = today - timedelta(days=6)
    week_end = today


    threshold = cushion_for(user)
    walk = standard_walk(db, user.id, account_id, today, today + timedelta(days=90))
    risk_dict, status = walk_risk(db, user.id, walk, today, threshold)
    risk = ForecastRisk(**risk_dict, status=status)

    # The snapshot already carries the trailing-7-day spending_breakdown;
    # its category totals sum to the week's total.
    snapshot = compute_budget_snapshot(db, user, account_id, as_of=today)
    total_spent = sum((c.total for c in snapshot.categories), Decimal("0"))

    return WeeklyDigest(
        week_start=week_start,
        week_end=week_end,
        total_spent=total_spent,
        categories=snapshot.categories,
        top_merchants=snapshot.top_merchants,
        risk=risk,
        snapshot=snapshot,
    )


def generate_monthly_digest(db: Session, user: models.User, account_id: int) -> MonthlyDigest:
    """Month-to-date spending (1st through today): category totals + top
    merchants, from the same spending_breakdown the weekly digest uses. On the
    1st the window is that single day. Spending is user-wide, like the weekly
    digest's; account_id is accepted for API symmetry with it."""
    today = date.today()
    month_start = today.replace(day=1)
    breakdown = spending_breakdown(db, user.id, month_start, today, merchant_limit=10)
    total_spent = sum((c.total for c in breakdown.categories), Decimal("0"))
    return MonthlyDigest(
        month_start=month_start,
        month_end=today,
        total_spent=total_spent,
        categories=breakdown.categories,
        top_merchants=breakdown.top_merchants,
    )
