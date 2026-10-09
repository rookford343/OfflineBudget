import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import MonthlySummary, WeeklyDigest, ForecastRisk
from backend.services.forecast_engine import build_forecast, find_balance_risk, _next_occurrence_on_or_after
from backend.services.budget_snapshot import compute_budget_snapshot, spending_breakdown
from backend.services.upcoming_bills import upcoming_bills
from backend.services.primary_account import primary_checking

_STALE_SYNC_HOURS = 24


def _fmt(v: Decimal) -> str:
    return f"${v:,.2f}"


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


def generate_daily_summary(
    db: Session, user: models.User, *, weekly_digest: WeeklyDigest | None = None,
) -> tuple[str, str]:
    """Return (html_body, text_body) for a daily budget summary email.

    Pass `weekly_digest` (from `generate_weekly_digest`) on the day the
    Weekly Digest runs -- its spending-by-category/top-merchants/balance-risk
    sections get appended to this same email instead of going out as a
    separate one.
    """
    today = date.today()
    month_start = today.replace(day=1)

    accounts = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.is_active == True,
        models.Account.type == models.AccountType.checking,
    ).order_by(models.Account.id).all()
    primary_account = primary_checking(db, user.id)
    snap = compute_budget_snapshot(db, user, primary_account.id, as_of=today) if primary_account else None

    all_recurring = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
    ).all()
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

    mtd_txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.date >= month_start,
        models.Transaction.date <= today,
        models.Transaction.amount < 0,
        models.Transaction.is_actual == True,
    ).all()
    mtd_expenses = sum(abs(t.amount) for t in mtd_txns)
    monthly_income = sum(r.amount for r in all_recurring if r.type == models.RecurringType.income)

    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()

    stale_connections = _stale_bank_connections(db, user.id)

    fmt = _fmt

    def _connection_label(c: models.BankConnection) -> str:
        names = [link.simplefin_account_name for link in c.links if link.simplefin_account_name]
        return ", ".join(names) if names else f"Bank connection #{c.id}"

    stale_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{_connection_label(c)}</td>"
        f"<td style='padding:4px 0;color:#991b1b'>"
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
        f"<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin-bottom:16px'>"
        f"<p style='margin:0 0 6px;color:#991b1b;font-weight:600;font-size:13px'>⚠ Stale bank data</p>"
        f"<table style='width:100%;font-size:13px'>{stale_rows}</table>"
        f"<p style='margin:6px 0 0;color:#991b1b;font-size:12px'>Balances and transactions below may not reflect today's activity.</p>"
        f"</div>"
    ) if stale_connections else ""

    acct_last_txn = _last_txn_dates(db, models.Transaction.account_id, models.Transaction.date, [a.id for a in accounts])

    acct_rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0;color:#374151'>{a.name}"
        f"<br><span style='color:#9ca3af;font-size:11px;font-weight:400'>{_last_txn_label(acct_last_txn.get(a.id))}</span></td>"
        f"<td style='padding:6px 0;text-align:right'><b style='color:#111827'>{fmt(a.current_balance)}</b></td></tr>"
        for a in accounts
    ) or "<tr><td style='color:#9ca3af'>No checking accounts</td></tr>"

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
                f"<tr><td style='padding:6px 12px 6px 0;color:#9ca3af;font-size:12px;white-space:nowrap;vertical-align:top'>{_day_label(b.due_date)}</td>"
                f"<td style='padding:6px 12px 6px 0;color:#374151'>{b.name}</td>"
                f"<td style='padding:6px 0;text-align:right;white-space:nowrap'>"
                f"<b style='color:{'#059669' if is_income else '#dc2626'}'>{'+' if is_income else '−'}{fmt(b.amount)}</b>"
                + (" <span style='color:#9ca3af;font-size:10px'>actual</span>" if b.is_actual else "")
                + "</td></tr>"
            )
        )(b.type == models.RecurringType.income)
        for b in upcoming
    ) or "<tr><td style='color:#9ca3af'>None in the next 7 days</td></tr>"

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
        he can still steer. Same arithmetic budget_snapshot uses for
        new_spending_total, so the email and Left to Spend can never disagree
        about what counts as new spend.

        balance_due is manual-entry only (bank sync never writes it), so it
        goes stale after a payment and can exceed current_balance -- which
        makes the subtraction negative. That negative IS the staleness
        signal, so report it as one rather than rendering it.
        """
        sc = snap_cards_by_id.get(c.id)
        balance_due = sc.balance_due if sc else c.balance_due
        pending = sc.pending_charges if sc else c.pending_charges
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
        util_color = "#dc2626" if util >= 80 else "#d97706" if util >= 50 else "#6b7280"
        pending = sc.pending_charges if sc else Decimal("0")
        pending_html = f" <span style='color:#9ca3af'>(+{fmt(pending)} pending)</span>" if pending else ""
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
            f"<tr><td style='padding:6px 12px 6px 0;color:#374151'>{c.name}"
            f"<br><span style='color:#9ca3af;font-size:11px;font-weight:400'>{_last_txn_label(card_last_txn.get(c.id))}</span>"
            f"<br><span style='color:#6b7280;font-size:11px;font-weight:400'>{breakdown}</span></td>"
            f"<td style='padding:6px 0;text-align:right;vertical-align:top'><b style='color:#111827'>{fmt(c.current_balance)}</b>{pending_html}</td>"
            f"<td style='padding:6px 0 6px 12px;text-align:right;white-space:nowrap;font-size:12px;vertical-align:top'>"
            f"<span style='color:{util_color}'>{util:.0f}% used</span>"
            + (f" <span style='color:#9ca3af'>&middot; {due_in}</span>" if due_in else "")
            + "</td></tr>"
        )

    card_rows = "".join(_card_row(c) for c in cards) or "<tr><td colspan='3' style='color:#9ca3af'>No credit cards</td></tr>"

    if snap is not None:
        spendable_color = "#059669" if snap.on_pace else "#dc2626"
        pace_color = "#10b981" if snap.on_pace else "#ef4444"
        margin_color = "#dc2626" if snap.safety_margin_weekly < 0 else "#d97706"

        # Only Safety Margin signals savings moves now. Left to Spend answers
        # "am I on budget", and mixing a savings instruction into it made the
        # two numbers say overlapping things.
        pull_savings_html = ""
        if snap.savings_pull_needed > 0:
            pull_savings_html = (
                f"<p style='margin:6px 0 0;color:#dc2626;font-size:11px'>"
                f"Pull {fmt(snap.savings_pull_needed)} from savings</p>"
            )
        spendable_today_sign = "−" if snap.spendable_today < 0 else ""
        # The quarter trough is the sanity check behind the weekly number: it is
        # what says whether a big purchase is safe. the user's spreadsheet keeps the
        # amount and its date together ('2026 Overview'!B23:C27).
        trough_html = ""
        if snap.lookahead_minimum_date is not None:
            trough_color = "#dc2626" if snap.lookahead_minimum < 0 else "#065f46"
            trough_html = (
                f"<p style='color:#047857;font-size:12px;margin:12px 0 0;text-align:center'>"
                f"Lowest projected balance in the next 3 months: "
                f"<b style='color:{trough_color}'>{fmt(snap.lookahead_minimum)}</b> on "
                f"{snap.lookahead_minimum_date.strftime('%b %-d')}</p>"
            )
        household_html = f"""
<div style='background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:16px;margin-bottom:20px'>
  <h3 style='margin:0 0 12px;color:#065f46;font-size:15px'>Household Snapshot</h3>
  <table style='width:100%;border-collapse:separate' cellspacing='8' cellpadding='0'>
    <tr>
      <td style='width:50%;background:#ffffff;border-radius:8px;padding:14px;text-align:center;vertical-align:top'>
        <p style='margin:0 0 6px;color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:.03em'>Spendable this week</p>
        <p style='margin:0;color:{spendable_color};font-size:24px;font-weight:700'>{fmt(snap.left_to_spend_weekly)}</p>
        <p style='margin:6px 0 0;color:{pace_color};font-size:12px'>{spendable_today_sign}{fmt(abs(snap.spendable_today))}/day &middot; {"on pace" if snap.on_pace else "over pace"}</p>
        <p style='margin:4px 0 0;color:#9ca3af;font-size:11px'>{fmt(snap.left_to_spend)} this month</p>
      </td>
      <td style='width:50%;background:#ffffff;border-radius:8px;padding:14px;text-align:center;vertical-align:top'>
        <p style='margin:0 0 6px;color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:.03em'>Safety Margin (this week)</p>
        <p style='margin:0;color:{margin_color};font-size:24px;font-weight:700'>{fmt(snap.safety_margin_weekly)}</p>
        <p style='margin:6px 0 0;color:#9ca3af;font-size:11px'>{fmt(snap.safety_margin)} this month</p>
        {pull_savings_html}
      </td>
    </tr>
  </table>
  {trough_html}
</div>"""
    else:
        household_html = (
            "<div style='background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin-bottom:20px'>"
            "<h3 style='margin:0 0 4px;color:#374151;font-size:15px'>Household Snapshot</h3>"
            "<p style='color:#9ca3af;margin:0'>No checking account to compute a snapshot from.</p></div>"
        )

    weekly_html, weekly_text = _weekly_digest_section(weekly_digest) if weekly_digest else ("", "")

    net_color = "#059669" if monthly_income - mtd_expenses >= 0 else "#dc2626"

    def _section(icon: str, title: str, body: str) -> str:
        return (
            f"<div style='margin-bottom:22px'>"
            f"<h3 style='margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid #e5e7eb;"
            f"color:#111827;font-size:14px;font-weight:600'>{icon}&nbsp; {title}</h3>"
            f"{body}</div>"
        )

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
    month_section_html = _section("📊", month_title, (
        f"<p style='font-size:14px;color:#374151;margin:0 0 8px'>Total spent: "
        f"<b style='color:#111827'>{fmt(month.total)}</b></p>{month_tables_html}"
    ))
    month_section_text = f"{month_title.upper()}\n  Total spent: {fmt(month.total)}\n{month_tables_text}\n"

    html = f"""<!DOCTYPE html>
<html><body style='font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#f3f4f6;margin:0;padding:24px 0'>
<div style='max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;padding:24px;color:#1f2937'>
<h2 style='color:#4f46e5;margin:0 0 4px;font-size:19px'>OfflineBudget Daily Summary</h2>
<p style='color:#6b7280;margin:0 0 20px;font-size:13px'>{today.strftime("%A, %B %-d, %Y")}</p>

{stale_html}
{household_html}
{month_section_html}
{_section("🏦", "Checking Accounts", f"<table style='width:100%;font-size:14px'>{acct_rows}</table>")}
{_section("📅", "Upcoming (next 7 days)", f"<table style='width:100%;font-size:14px'>{upcoming_rows}</table>")}
{_section("📊", "Month-to-Date Spending", (
    f"<table style='width:100%;font-size:14px'><tr>"
    f"<td style='padding:4px 12px 4px 0;color:#374151'>Expenses</td>"
    f"<td style='padding:4px 0;text-align:right'><b style='color:#dc2626'>{fmt(mtd_expenses)}</b></td></tr>"
    f"<tr><td style='padding:4px 12px 4px 0;color:#374151'>Monthly income</td>"
    f"<td style='padding:4px 0;text-align:right'><b style='color:#059669'>{fmt(monthly_income)}</b></td></tr>"
    f"<tr><td style='padding:4px 12px 4px 0;color:#374151;border-top:1px solid #f3f4f6'>Net so far</td>"
    f"<td style='padding:4px 0;text-align:right;border-top:1px solid #f3f4f6'><b style='color:{net_color}'>{fmt(monthly_income - mtd_expenses)}</b></td></tr>"
    f"</table>"
))}
{_section("💳", "Credit Cards", f"<table style='width:100%;font-size:14px'>{card_rows}</table>")}
{weekly_html}
<p style='color:#9ca3af;font-size:11px;margin-top:24px;text-align:center'>Sent by OfflineBudget</p>
</div>
</body></html>"""

    acct_text = "\n".join(
        f"  {a.name}: {fmt(a.current_balance)} ({_last_txn_label(acct_last_txn.get(a.id))})" for a in accounts
    ) or "  No checking accounts"
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
        household_text = (
            "HOUSEHOLD SNAPSHOT\n"
            f"  Spendable this week: {fmt(snap.left_to_spend_weekly)}\n"
            + f"  Safety margin (this week): {fmt(snap.safety_margin_weekly)}"
            + ("" if snap.savings_pull_needed <= 0 else
               f"  (pull {fmt(snap.savings_pull_needed)} from savings)")
            + "\n"
            f"  Monthly: {fmt(snap.left_to_spend)} left to spend, {fmt(snap.safety_margin)} before your spending starts eating into savings.\n"
            + (
                f"  Lowest projected balance in the next 3 months: {fmt(snap.lookahead_minimum)}"
                f" on {snap.lookahead_minimum_date.strftime('%b %-d')}.\n"
                if snap.lookahead_minimum_date is not None else ""
            )
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

    text = f"""OfflineBudget Daily Summary — {today.strftime("%B %-d, %Y")}
{stale_text}
{household_text}
{month_section_text}
CHECKING ACCOUNTS
{acct_text}

UPCOMING BILLS (next 7 days)
{upcoming_text}

MONTH-TO-DATE
  Expenses: {fmt(mtd_expenses)} | Monthly income: {fmt(monthly_income)} | Net so far: {fmt(monthly_income - mtd_expenses)}

CREDIT CARDS
{card_text}
{weekly_text}"""
    return html, text


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
    heading = "margin:{top}px 0 4px;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.03em"
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
<h3 style='margin:24px 0 8px;padding-bottom:6px;border-bottom:1px solid #e5e7eb;color:#111827;font-size:14px;font-weight:600'>🗓️&nbsp; Weekly Digest — {digest.week_start.strftime('%B %-d')}–{digest.week_end.strftime('%B %-d, %Y')}</h3>
<p style='font-size:14px;color:#374151;margin:0 0 8px'>Total spent this week: <b style='color:#111827'>{fmt(digest.total_spent)}</b></p>
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
    """Returns (spending_by_category_id, total_debits, total_credits).

    Includes both checking transactions and credit card charges so totals
    match the budget overview rather than being understated.
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    checking_txns = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
        )
        .all()
    )

    card_txns = (
        db.query(models.CreditCardTransaction)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
        )
        .all()
    )

    by_cat: dict[int, Decimal] = defaultdict(Decimal)
    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for t in checking_txns:
        if t.amount < 0:
            total_debits += abs(t.amount)
            if t.category_id:
                by_cat[t.category_id] += abs(t.amount)
        else:
            total_credits += t.amount

    for t in card_txns:
        if t.amount > 0:
            total_debits += t.amount
            if t.category_id:
                by_cat[t.category_id] += t.amount

    return dict(by_cat), total_debits, total_credits


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


    account = db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user.id,
    ).first()
    threshold = account.low_balance_threshold if account and account.low_balance_threshold is not None else Decimal("0")
    forecast_entries = build_forecast(db, user.id, account_id, today, today + timedelta(days=90))
    risk_dict = find_balance_risk(forecast_entries, threshold)
    risk = ForecastRisk(**risk_dict)

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
