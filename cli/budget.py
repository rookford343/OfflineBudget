#!/usr/bin/env python3
"""
OfflineBudget CLI — shares the same service layer as the web API.
Run from the project root: python cli/budget.py <command>
"""
import sys
import os

# Make sure imports resolve from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import typer
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from backend.database import SessionLocal, create_tables
from backend.auth import hash_password
from backend import models
from backend.services.forecast_engine import build_forecast, build_quarters

app = typer.Typer(help="OfflineBudget command-line interface", rich_markup_mode="rich")
console = Console()

def get_db():
    create_tables()
    return SessionLocal()


# ── Users ─────────────────────────────────────────────────────────────────────

users_app = typer.Typer(help="Manage users")
app.add_typer(users_app, name="users")

@users_app.command("create")
def create_user(
    username: str = typer.Argument(..., help="Login username"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Password"),
    display_name: str = typer.Option("", help="Display name"),
):
    """Create a new user account."""
    db = get_db()
    if db.query(models.User).filter(models.User.username == username).first():
        console.print(f"[red]Username '{username}' already taken.[/red]")
        raise typer.Exit(1)
    from backend.seed import seed_default_categories
    user = models.User(
        username=username,
        hashed_password=hash_password(password),
        display_name=display_name or username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    seed_default_categories(db, user)
    console.print(f"[green]✓ Created user '{username}' (id={user.id})[/green]")


@users_app.command("list")
def list_users():
    """List all users."""
    db = get_db()
    users = db.query(models.User).all()
    t = Table("ID", "Username", "Display Name", "Created", box=box.ROUNDED)
    for u in users:
        t.add_row(str(u.id), u.username, u.display_name, u.created_at.strftime("%Y-%m-%d"))
    console.print(t)


# ── Accounts ──────────────────────────────────────────────────────────────────

accounts_app = typer.Typer(help="Manage accounts")
app.add_typer(accounts_app, name="accounts")

@accounts_app.command("list")
def list_accounts(username: str = typer.Option(..., help="Username")):
    """List checking and savings accounts."""
    db = get_db()
    user = _require_user(db, username)
    accs = db.query(models.Account).filter(models.Account.user_id == user.id, models.Account.is_active == True).all()
    t = Table("ID", "Name", "Type", "Balance", box=box.ROUNDED)
    for a in accs:
        t.add_row(str(a.id), a.name, a.type.value, f"${a.current_balance:,.2f}")
    console.print(t)


@accounts_app.command("add")
def add_account(
    username: str = typer.Option(..., help="Username"),
    name: str = typer.Argument(...),
    type: str = typer.Option("checking", help="checking | savings | money_market"),
    balance: float = typer.Option(0.0, help="Current balance"),
):
    """Add a new account."""
    db = get_db()
    user = _require_user(db, username)
    acc = models.Account(user_id=user.id, name=name, type=type, current_balance=Decimal(str(balance)))
    db.add(acc)
    db.commit()
    console.print(f"[green]✓ Added account '{name}' (id={acc.id})[/green]")


# ── Recurring ─────────────────────────────────────────────────────────────────

recurring_app = typer.Typer(help="Manage recurring items")
app.add_typer(recurring_app, name="recurring")

@recurring_app.command("list")
def list_recurring(username: str = typer.Option(..., help="Username")):
    """List all recurring income and expenses."""
    db = get_db()
    user = _require_user(db, username)
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
    ).order_by(models.RecurringItem.day_of_month).all()
    t = Table("ID", "Name", "Type", "Amount", "Day", "Account", box=box.ROUNDED)
    for i in items:
        t.add_row(str(i.id), i.name, i.type.value, f"${i.amount:,.2f}", str(i.day_of_month) if i.day_of_month else "last", i.account.name)
    console.print(t)


# ── Forecast ──────────────────────────────────────────────────────────────────

forecast_app = typer.Typer(help="View forecasts")
app.add_typer(forecast_app, name="forecast")

@forecast_app.command("show")
def show_forecast(
    username: str = typer.Option(..., help="Username"),
    account: str = typer.Option(..., help="Account name"),
    start: str = typer.Option(date.today().strftime("%Y-%m-01"), help="Start date YYYY-MM-DD"),
    end: str = typer.Option(None, help="End date YYYY-MM-DD (default: end of start month)"),
    quarter: str = typer.Option(None, help="Quarter shortcut, e.g. Q1-2026"),
):
    """Show day-by-day balance forecast."""
    db = get_db()
    user = _require_user(db, username)

    acc = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.name == account,
    ).first()
    if not acc:
        console.print(f"[red]Account '{account}' not found.[/red]")
        raise typer.Exit(1)

    if quarter:
        q_num, yr = quarter.split("-")
        q = int(q_num[1])
        yr = int(yr)
        from calendar import monthrange
        m_start = (q - 1) * 3 + 1
        start_date = date(yr, m_start, 1)
        m_end = m_start + 2
        end_date = date(yr, m_end, monthrange(yr, m_end)[1])
    else:
        start_date = date.fromisoformat(start)
        if end:
            end_date = date.fromisoformat(end)
        else:
            from calendar import monthrange
            end_date = date(start_date.year, start_date.month, monthrange(start_date.year, start_date.month)[1])

    entries = build_forecast(db, user.id, acc.id, start_date, end_date)
    t = Table("Date", "Transactions", "Balance", box=box.ROUNDED)
    for e in entries:
        if not e.transactions:
            continue
        txn_str = "\n".join(
            f"{'[green]+' if t.amount > 0 else '[red]-'}${abs(t.amount):,.2f}[/] {t.name}"
            for t in e.transactions
        )
        t.add_row(
            e.date.strftime("%b %d"),
            txn_str,
            f"[bold]${e.projected_balance:,.2f}[/bold]",
        )
    console.print(t)


@forecast_app.command("quarters")
def show_quarters(
    username: str = typer.Option(..., help="Username"),
    account: str = typer.Option(..., help="Account name"),
    year: int = typer.Option(date.today().year),
):
    """Show quarterly forecast summary."""
    db = get_db()
    user = _require_user(db, username)
    acc = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.name == account,
    ).first()
    if not acc:
        console.print(f"[red]Account '{account}' not found.[/red]")
        raise typer.Exit(1)

    quarters = build_quarters(db, user.id, acc.id, year)
    t = Table("Quarter", "Open", "Close", "Income", "Expenses", "Net", box=box.ROUNDED)
    for q in quarters:
        net_color = "green" if q.net >= 0 else "red"
        t.add_row(
            f"Q{q.quarter} {q.year}",
            f"${q.open_balance:,.2f}",
            f"${q.close_balance:,.2f}",
            f"[green]${q.total_income:,.2f}[/green]",
            f"[red]${q.total_expenses:,.2f}[/red]",
            f"[{net_color}]${q.net:,.2f}[/{net_color}]",
        )
    console.print(t)


# ── Cards ─────────────────────────────────────────────────────────────────────

cards_app = typer.Typer(help="Manage credit cards")
app.add_typer(cards_app, name="cards")

@cards_app.command("list")
def list_cards(username: str = typer.Option(..., help="Username")):
    """List all credit cards."""
    db = get_db()
    user = _require_user(db, username)
    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()
    t = Table("ID", "Name", "Balance", "Due", "Limit", "Util%", box=box.ROUNDED)
    for c in cards:
        util = float(c.current_balance) / float(c.credit_limit) * 100 if c.credit_limit else 0
        t.add_row(str(c.id), c.name, f"${c.current_balance:,.2f}", f"${c.balance_due:,.2f}", f"${c.credit_limit:,.2f}", f"{util:.1f}%")
    console.print(t)


# ── Import ────────────────────────────────────────────────────────────────────

import_app = typer.Typer(help="Import transactions from CSV or OFX/QFX files")
app.add_typer(import_app, name="import")


@import_app.command("csv")
def import_file(
    file: Path = typer.Argument(..., help="Path to CSV, OFX, or QFX file"),
    username: str = typer.Option(..., envvar="BUDGET_USER", help="Username (or set BUDGET_USER env var)"),
    account_id: Optional[int] = typer.Option(None, "--account-id", help="Checking/savings account ID"),
    card_id: Optional[int] = typer.Option(None, "--card-id", help="Credit card ID"),
    auto_confirm: bool = typer.Option(False, "--auto-confirm", help="Skip confirmation prompt (for scripts/cron)"),
):
    """Import transactions from a CSV, OFX, or QFX bank file."""
    if not account_id and not card_id:
        console.print("[red]Error: provide --account-id or --card-id[/red]")
        raise typer.Exit(1)

    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    db = get_db()
    user = _require_user(db, username)

    content = file.read_bytes()
    ext = file.suffix.lower()

    try:
        if ext in (".ofx", ".qfx"):
            from backend.services.ofx_parser import parse_ofx
            parsed_rows = parse_ofx(content)
            fmt = "OFX/QFX"
        else:
            from backend.services.csv_parser import parse_csv
            parsed_rows = parse_csv(content)
            fmt = "CSV"
    except Exception as e:
        console.print(f"[red]Failed to parse file: {e}[/red]")
        raise typer.Exit(1)

    if not parsed_rows:
        console.print("[yellow]No valid transactions found in file.[/yellow]")
        raise typer.Exit(0)

    from backend.services.import_service import build_preview, run_import
    from backend import schemas

    preview_rows = build_preview(db, user, parsed_rows)
    categorized = sum(1 for r in preview_rows if not r.needs_review)

    t = Table(
        "Date", "Description", "Amount", "Category", "Review",
        box=box.ROUNDED,
        title=f"{file.name} — {len(preview_rows)} transactions ({fmt})",
    )
    for r in preview_rows:
        amt_str = f"${abs(r.amount):,.2f}"
        amt = Text(f"+{amt_str}" if r.amount >= 0 else f"-{amt_str}")
        amt.stylize("green" if r.amount >= 0 else "red")
        review_flag = "[yellow]?[/yellow]" if r.needs_review else "[green]✓[/green]"
        t.add_row(
            r.date.strftime("%Y-%m-%d"),
            r.description[:48] + ("…" if len(r.description) > 48 else ""),
            amt,
            r.category_name or "—",
            review_flag,
        )
    console.print(t)
    console.print(
        f"[bold]{len(preview_rows)}[/bold] total  |  "
        f"[green]{categorized}[/green] auto-categorized  |  "
        f"[yellow]{len(preview_rows) - categorized}[/yellow] need review"
    )

    if not auto_confirm:
        typer.confirm(f"\nImport {len(preview_rows)} transactions?", abort=True)

    confirm_rows = [
        schemas.ImportConfirmRow(
            date=r.date,
            description=r.description,
            amount=r.amount,
            category_id=r.category_id,
        )
        for r in preview_rows
    ]

    try:
        result = run_import(db, user, confirm_rows, account_id, card_id)
    except Exception as e:
        console.print(f"[red]Import failed: {e}[/red]")
        raise typer.Exit(1)

    # Write audit log entry
    log = models.AuditLog(
        user_id=user.id,
        username=user.username,
        method="CLI",
        path=f"import {file.name}",
        status_code=200,
        duration_ms=0,
        body_summary=f"{file.name} → {result.imported} imported, {result.skipped_duplicates} skipped",
    )
    db.add(log)
    db.commit()

    console.print(
        f"\n[green]✓ Imported {result.imported} transactions[/green]"
        + (f"  [dim]({result.skipped_duplicates} duplicates skipped)[/dim]" if result.skipped_duplicates else "")
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_user(db, username: str) -> models.User:
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        console.print(f"[red]User '{username}' not found. Run: python cli/budget.py users create[/red]")
        raise typer.Exit(1)
    return user


if __name__ == "__main__":
    app()
