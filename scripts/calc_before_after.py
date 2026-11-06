"""Compare headline money figures between the current tree and an earlier git ref.

Usage (always on a COPY of the database, never the live file):

    uv run --locked python -c "from backend.services.db_backup import backup_database; \
backup_database('data/budget.db', '/path/outside/repo/copy.db')"
    uv run --locked python scripts/calc_before_after.py --db /path/outside/repo/copy.db \
--user 2 --ref HEAD~3

Both trees compute on their own private copy of --db (so a migration in an
older tree cannot touch your copy). The old ref is checked out with
`git worktree add --detach` into a temp dir, and removed on exit.
See docs/architecture.md, "Tracing a mismatch".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE_DB = (ROOT / "data" / "budget.db").resolve()

# Runs inside each tree (python -I, tree root inserted on sys.path). Prints one
# JSON object of metric -> string. In strict mode (the current tree) any error
# propagates; otherwise (the old ref) a missing function reports "n/a".
SNIPPET = r"""
import json, sys, calendar
from datetime import date, timedelta
sys.path.insert(0, sys.argv[1])
user_id = int(sys.argv[2])
strict = sys.argv[3] == 'strict'
out = {}

from backend.database import SessionLocal
from backend import models

db = SessionLocal()
try:
    today = date.today()
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise SystemExit("user %d not found" % user_id)

    from backend.services.summary_generator import primary_checking
    account = primary_checking(db, user_id)

    try:
        from backend.services.budget_snapshot import compute_budget_snapshot
        snap = compute_budget_snapshot(db, user, account.id, today)
        for f in ("leftover", "left_to_spend", "safety_margin",
                  "next_month_minimum", "lookahead_minimum"):
            out[f] = str(getattr(snap, f))
    except Exception as exc:
        if strict:
            raise
        for f in ("leftover", "left_to_spend", "safety_margin",
                  "next_month_minimum", "lookahead_minimum"):
            out[f] = "n/a (%s)" % type(exc).__name__

    try:
        from backend.services.forecast_engine import build_forecast
        cards = db.query(models.CreditCard).filter(
            models.CreditCard.user_id == user_id,
            models.CreditCard.is_active == True,
        ).order_by(models.CreditCard.id).all()
        entries = build_forecast(db, user_id, account.id, today, today + timedelta(days=75))
        seen = {}
        for e in entries:
            for t in e.transactions:
                if t.is_cc_payment and t.name not in seen:
                    seen[t.name] = (e.date, t.amount)
        for c in cards:
            hit = next((v for k, v in seen.items() if c.name in k), None)
            out["next payment: " + c.name] = str(abs(hit[1])) if hit else "none"
    except Exception as exc:
        if strict:
            raise
        out["next payment"] = "n/a (%s)" % type(exc).__name__

    try:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        from backend.services import summary_generator as sg
        _, debits, _ = sg._month_spending_by_category(db, user_id, last_prev.year, last_prev.month)
        out["last full month spend"] = str(debits)
    except Exception as exc:
        if strict:
            raise
        out["last full month spend"] = "n/a (%s)" % type(exc).__name__
finally:
    db.close()
print("@@METRICS@@" + json.dumps(out))
"""


def _run_tree(tree: Path, db_copy: Path, user_id: int, *, strict: bool) -> dict[str, str]:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_copy}",
        "JWT_SECRET": "x",
    }
    # --project keeps one locked environment for both trees; code comes from `tree`.
    cmd = ["uv", "run", "--locked", "--project", str(ROOT), "python", "-I", "-c", SNIPPET,
           str(tree), str(user_id), "strict" if strict else "lenient"]
    proc = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    for line in proc.stdout.splitlines():
        if line.startswith("@@METRICS@@"):
            return json.loads(line[len("@@METRICS@@"):])
    raise SystemExit(f"metrics run failed in {tree}:\n{proc.stderr[-2000:]}")


def is_na(value: str) -> bool:
    return value.startswith("n/a")


def _delta(new: str, old: str) -> str:
    # A figure that could not be computed on either side is never "no change".
    if is_na(new) or is_na(old):
        return "n/a"
    try:
        return f"{Decimal(new) - Decimal(old):.2f}"
    except (InvalidOperation, ValueError):
        return "0.00" if new == old else "differs"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout  # noqa: S603,S607


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="path to a COPY of the database")
    ap.add_argument("--user", required=True, type=int, help="user id")
    ap.add_argument("--ref", required=True, help="git ref for the 'before' tree")
    args = ap.parse_args(argv)

    db_path = Path(args.db).resolve()
    if db_path == LIVE_DB or (LIVE_DB.exists() and db_path.exists() and db_path.samefile(LIVE_DB)):
        print("Refusing to run on the live database. Make a copy with "
              "backend.services.db_backup.backup_database first.", file=sys.stderr)
        return 2
    if not db_path.is_file():
        print(f"Database copy not found: {db_path}", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="calc-before-after-"))
    wt = tmp / "before"
    added = False
    try:
        _git("worktree", "add", "--detach", str(wt), args.ref)
        added = True
        new_db, old_db = tmp / "new.db", tmp / "old.db"
        shutil.copyfile(db_path, new_db)
        shutil.copyfile(db_path, old_db)

        new = _run_tree(ROOT, new_db, args.user, strict=True)
        old = _run_tree(wt, old_db, args.user, strict=False)
    finally:
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, check=False)  # noqa: S603,S607
        shutil.rmtree(tmp, ignore_errors=True)

    keys = list(dict.fromkeys([*new.keys(), *old.keys()]))
    width = max(len(k) for k in keys)
    print(f"{'metric'.ljust(width)}  {'current':>14}  {args.ref[:14]:>14}  {'delta':>10}")
    changed = 0
    uncomputed: list[str] = []
    for k in keys:
        n, o = new.get(k, "n/a"), old.get(k, "n/a")
        d = _delta(n, o)
        if d != "0.00":
            changed += 1
        for side, val in (("current tree", n), (args.ref, o)):
            if is_na(val):
                uncomputed.append(f"could not compute '{k}' on {side}: {val}")
        print(f"{k.ljust(width)}  {n:>14}  {o:>14}  {d:>10}")
    print(f"\n{changed} row(s) differ.")
    if uncomputed:
        print("\n".join(uncomputed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
