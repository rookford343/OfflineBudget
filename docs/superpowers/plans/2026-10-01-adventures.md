# Adventures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Adventures page under Planning. It plans trips from a reusable checklist and tracks loyalty points (with transfer partners and bonuses). A committed trip's cash cost goes into the Forecast as Planned One-Offs.

**Architecture:**
- Five new SQLAlchemy tables, created additively by `create_all`. No existing table is altered.
- `backend/services/adventures.py` holds the pure money and points rules, the wallet math and the seeding.
- `backend/services/adventures_lifecycle.py` turns a committed trip into `PlannedExpense` rows and keeps them in sync, and handles finishing a trip and the optional `SavingsGoal` fund.
- `backend/routers/adventures.py` exposes it. The React page lives at `/adventures`.

**Tech stack:** FastAPI, SQLAlchemy 2 (SQLite), Pydantic v2, pytest; React + TypeScript + TanStack Query + Tailwind + Radix Dialog + lucide-react; bun.

**Spec:** `docs/superpowers/specs/2026-10-01-adventures-design.md`

## Global Constraints

- **Additive schema only.** Add new tables via `Base.metadata.create_all`. No `ALTER TABLE` on any existing table, no new columns on `planned_expenses`, `users` or `savings_goals`.
- **Live backend.** It runs `uvicorn --reload` against the live `data/budget.db`, so saving `models.py` creates the new tables in live data. The controller takes a backup before Task 1 is dispatched. Never touch `data/` or `backend/*.db` directly.
- **No changes to `backend/services/forecast_engine.py`.**
- **Scoping.** Every query and endpoint is scoped by `user_id`; every endpoint checks ownership and returns 404 for another user's rows.
- **Public repo.**
  - Tests use generic names and amounts.
  - Commit messages describe behaviour, never real balances, amounts or places.
  - Each commit message ends with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Transfer rounding.** Source points needed round **up** (ceiling). Partner points received round **down** (floor).
- **Bonus expiry.** A bonus is active when `bonus_pct` is set and (`bonus_ends_on` is null or `today <= bonus_ends_on`).
- **Masking.** All money **and points** values in the UI go through `maskIfHidden(useBalancesHidden(), …)`.
- **Tooling.** Use bun/bunx only, never npm.
- **Gates.**
  - Backend: `cd backend && python3 -m pytest -q` finishes with 0 failures.
  - Frontend: `cd frontend && bunx tsc -b --force 2>&1 | grep -oE "^src/[^(]+" | sort | uniq -c` stays at the baseline of 39 errors in 11 files, and new files add 0 errors.
- **Branching.** Work directly on `main` (repo convention). Don't push.

## File structure

| File | Responsibility |
|---|---|
| `backend/models.py` (append) | Enums `LoyaltyKind`, `TripStatus`, `TripCategory`, `TripPricing`, `TripPayment`; models `LoyaltyProgram`, `TransferPartner`, `Trip`, `TripItem`, `ChecklistTemplateItem` |
| `backend/services/adventures.py` | Pure rules (multiplier, cash_price, cash_owed, points_used, value_cpp, buffer, ratios), wallet math (reserved, available, trip points summary, suggest_transfer), `ensure_adventures_seeded` |
| `backend/services/adventures_lifecycle.py` | `sync_trip_planned_expenses`, `commit_trip`, `uncommit_trip`, `set_item_paid`, `delete_item`, `delete_trip`, `finish_trip`, fund create/update/remove, `create_trip_from_template` |
| `backend/schemas.py` (append) | Request and response models for the router |
| `backend/routers/adventures.py` | `/adventures/*` endpoints |
| `backend/main.py` | Register the router |
| `backend/tests/test_adventures_rules.py` | Task 2 tests |
| `backend/tests/test_adventures_wallet.py` | Task 3 tests |
| `backend/tests/test_adventures_lifecycle.py` | Task 4 tests |
| `backend/tests/test_adventures_api.py` | Task 5 tests |
| `frontend/src/api/index.ts` | `adventuresApi` |
| `frontend/src/lib/navItems.ts`, `frontend/src/App.tsx` | Nav entry and route |
| `frontend/src/pages/Adventures.tsx` | Page shell: wallet strip, trip list, selected trip |
| `frontend/src/components/adventures/WalletStrip.tsx` | Points chips plus the Partners dialog |
| `frontend/src/components/adventures/TripDetail.tsx` | Trip header, item rows, totals bar, lifecycle actions |
| `docs/USER_GUIDE.md`, `docs/PRIVACY.md` | Docs |

---

### Task 1: Models and seeding

**Files:**
- Modify: `backend/models.py` (append at end of file)
- Create: `backend/services/adventures.py` (seeding section only in this task)
- Test: `backend/tests/test_adventures_rules.py` (seeding tests only in this task)

**Interfaces:**
- Produces:
  - The models and enums named below, with the exact field names.
  - `ensure_adventures_seeded(db: Session, user_id: int) -> None`
  - The constants `CHASE_UR = "Chase Ultimate Rewards"`, `STARTER_AIRLINES: list[str]`, `STARTER_HOTELS: list[str]`, and `STARTER_TEMPLATE: list[tuple[TripCategory, str, TripPricing]]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_adventures_rules.py`:

```python
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.adventures import (
    ensure_adventures_seeded, CHASE_UR, STARTER_AIRLINES, STARTER_HOTELS, STARTER_TEMPLATE,
)


def _user(db, username="traveler"):
    u = models.User(username=username, hashed_password="x", display_name="T")
    db.add(u)
    db.flush()
    return u


def test_seeding_creates_programs_partners_and_template_once(db_session):
    user = _user(db_session)
    ensure_adventures_seeded(db_session, user.id)
    ensure_adventures_seeded(db_session, user.id)  # idempotent
    programs = db_session.query(models.LoyaltyProgram).filter_by(user_id=user.id).all()
    names = {p.name for p in programs}
    assert CHASE_UR in names
    assert set(STARTER_AIRLINES) <= names and set(STARTER_HOTELS) <= names
    assert len(programs) == 1 + len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert all(p.balance == 0 for p in programs)
    partners = db_session.query(models.TransferPartner).filter_by(user_id=user.id).all()
    assert len(partners) == len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert all(p.ratio == Decimal("1") and p.bonus_pct is None for p in partners)
    template = db_session.query(models.ChecklistTemplateItem).filter_by(user_id=user.id).all()
    assert len(template) == len(STARTER_TEMPLATE)


def test_seeding_is_per_kind_and_per_user(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    ensure_adventures_seeded(db_session, a.id)
    # a deletes the whole template; programs remain, so re-seeding restores only the template
    db_session.query(models.ChecklistTemplateItem).filter_by(user_id=a.id).delete()
    ensure_adventures_seeded(db_session, a.id)
    assert db_session.query(models.ChecklistTemplateItem).filter_by(user_id=a.id).count() == len(STARTER_TEMPLATE)
    assert db_session.query(models.LoyaltyProgram).filter_by(user_id=a.id).count() == 1 + len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert db_session.query(models.LoyaltyProgram).filter_by(user_id=b.id).count() == 0
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_rules.py`
Expected: an ERROR at import time, because `backend.services.adventures` doesn't exist yet.

- [ ] **Step 3: Append the models to `backend/models.py`**

```python
# ── Adventures (trip planning with points) ───────────────────────────────────
# All additive tables, created by create_all: no existing table is altered.
# A committed trip's cash cost reaches the Forecast as ordinary PlannedExpense
# rows (linked from TripItem.planned_expense_id), so forecast_engine is
# untouched. Spec: docs/superpowers/specs/2026-10-01-adventures-design.md


class LoyaltyKind(str, PyEnum):
    bank = "bank"
    airline = "airline"
    hotel = "hotel"
    other = "other"


class TripStatus(str, PyEnum):
    planning = "planning"
    committed = "committed"
    done = "done"


class TripCategory(str, PyEnum):
    getting_there = "getting_there"
    staying = "staying"
    daily = "daily"
    before = "before"
    while_there = "while_there"


class TripPricing(str, PyEnum):
    flat = "flat"
    per_day = "per_day"
    per_night = "per_night"
    per_person = "per_person"
    per_person_day = "per_person_day"


class TripPayment(str, PyEnum):
    cash = "cash"
    points = "points"
    mix = "mix"


class LoyaltyProgram(Base):
    __tablename__ = "loyalty_programs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[LoyaltyKind] = mapped_column(Enum(LoyaltyKind), nullable=False)
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TransferPartner(Base):
    __tablename__ = "transfer_partners"
    __table_args__ = (UniqueConstraint("user_id", "from_program_id", "to_program_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    from_program_id: Mapped[int] = mapped_column(Integer, ForeignKey("loyalty_programs.id"), nullable=False)
    to_program_id: Mapped[int] = mapped_column(Integer, ForeignKey("loyalty_programs.id"), nullable=False)
    ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("1"), nullable=False)
    bonus_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    bonus_ends_on: Mapped[date | None] = mapped_column(Date)

    from_program: Mapped[LoyaltyProgram] = relationship(foreign_keys=[from_program_id])
    to_program: Mapped[LoyaltyProgram] = relationship(foreign_keys=[to_program_id])


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(128))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    travelers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[TripStatus] = mapped_column(Enum(TripStatus), default=TripStatus.planning, nullable=False)
    default_card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    fund_goal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("savings_goals.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["TripItem"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="TripItem.sort_order",
    )


class TripItem(Base):
    __tablename__ = "trip_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[int] = mapped_column(Integer, ForeignKey("trips.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    category: Mapped[TripCategory] = mapped_column(Enum(TripCategory), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pricing: Mapped[TripPricing] = mapped_column(Enum(TripPricing), default=TripPricing.flat, nullable=False)
    unit_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payment: Mapped[TripPayment] = mapped_column(Enum(TripPayment), default=TripPayment.cash, nullable=False)
    points_program_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("loyalty_programs.id"))
    points_price: Mapped[int | None] = mapped_column(Integer)
    cash_copay: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    mix_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    charge_date: Mapped[date | None] = mapped_column(Date)
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    transfer_from_program_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("loyalty_programs.id"))
    transfer_points: Mapped[int | None] = mapped_column(Integer)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    planned_expense_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("planned_expenses.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    trip: Mapped[Trip] = relationship(back_populates="items")


class ChecklistTemplateItem(Base):
    __tablename__ = "checklist_template_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    category: Mapped[TripCategory] = mapped_column(Enum(TripCategory), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pricing: Mapped[TripPricing] = mapped_column(Enum(TripPricing), default=TripPricing.flat, nullable=False)
    unit_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```

- [ ] **Step 4: Create `backend/services/adventures.py` with the seeding section**

```python
"""Adventures: pure trip money/points rules, wallet math, and seeding.

Spec: docs/superpowers/specs/2026-10-01-adventures-design.md. The rules here
are pure functions of ORM rows (no writes) except `ensure_adventures_seeded`.
Lifecycle writes (commit, sync, finish, fund) live in adventures_lifecycle.py.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from sqlalchemy.orm import Session

from backend import models
from backend.models import TripCategory as C, TripPricing as P

CHASE_UR = "Chase Ultimate Rewards"
STARTER_AIRLINES = [
    "Aer Lingus AerClub", "Air Canada Aeroplan", "Air France/KLM Flying Blue",
    "British Airways Executive Club", "Emirates Skywards", "Iberia Plus",
    "JetBlue TrueBlue", "Singapore KrisFlyer", "Southwest Rapid Rewards",
    "United MileagePlus", "Virgin Atlantic Flying Club",
]
STARTER_HOTELS = ["World of Hyatt", "Marriott Bonvoy", "IHG One Rewards"]

STARTER_TEMPLATE: list[tuple[C, str, P]] = [
    (C.getting_there, "Flights", P.per_person),
    (C.getting_there, "Airport parking or rides", P.flat),
    (C.getting_there, "Checked bags", P.per_person),
    (C.getting_there, "Rental car or trains", P.flat),
    (C.getting_there, "Gas & tolls", P.flat),
    (C.staying, "Lodging", P.per_night),
    (C.staying, "Resort / city taxes", P.per_night),
    (C.daily, "Food", P.per_person_day),
    (C.daily, "Local transport", P.per_day),
    (C.daily, "Tips", P.per_day),
    (C.before, "Passports / visas", P.per_person),
    (C.before, "Travel insurance", P.flat),
    (C.before, "International phone plan", P.flat),
    (C.before, "Dog boarding", P.per_night),
    (C.before, "Kid gear rental", P.flat),
    (C.while_there, "Activities & tickets", P.flat),
    (C.while_there, "Souvenirs", P.flat),
    (C.while_there, "Buffer", P.flat),
]


def ensure_adventures_seeded(db: Session, user_id: int) -> None:
    """Seed starter programs+partners and the checklist template, each only
    when the user has zero rows of that kind -- idempotent with no flag column
    (spec: `users` is not altered)."""
    has_programs = db.query(models.LoyaltyProgram.id).filter(
        models.LoyaltyProgram.user_id == user_id).first() is not None
    if not has_programs:
        chase = models.LoyaltyProgram(user_id=user_id, name=CHASE_UR,
                                      kind=models.LoyaltyKind.bank, balance=0, sort_order=0)
        db.add(chase)
        db.flush()
        order = 1
        for kind, names in ((models.LoyaltyKind.airline, STARTER_AIRLINES),
                            (models.LoyaltyKind.hotel, STARTER_HOTELS)):
            for name in names:
                p = models.LoyaltyProgram(user_id=user_id, name=name, kind=kind,
                                          balance=0, sort_order=order)
                db.add(p)
                db.flush()
                db.add(models.TransferPartner(user_id=user_id, from_program_id=chase.id,
                                              to_program_id=p.id, ratio=Decimal("1")))
                order += 1
    has_template = db.query(models.ChecklistTemplateItem.id).filter(
        models.ChecklistTemplateItem.user_id == user_id).first() is not None
    if not has_template:
        for i, (category, name, pricing) in enumerate(STARTER_TEMPLATE):
            db.add(models.ChecklistTemplateItem(user_id=user_id, category=category, name=name,
                                                pricing=pricing, unit_cash=None, sort_order=i))
    db.flush()
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_rules.py`
Expected: `2 passed`.

- [ ] **Step 6: Run the full suite, then commit**

Run: `cd backend && python3 -m pytest -q`. Expected: 0 failures.

```bash
git add backend/models.py backend/services/adventures.py backend/tests/test_adventures_rules.py
git commit -m "feat: Adventures tables and starter points programs/checklist seeding

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Pure money and points rules

**Files:**
- Modify: `backend/services/adventures.py` (add the rules section above the seeding section)
- Test: `backend/tests/test_adventures_rules.py` (append)

**Interfaces:**
- Consumes: the models from Task 1.
- Produces:
  - `nights(trip) -> int`, `days(trip) -> int`
  - `multiplier(item, trip) -> int`
  - `is_auto_buffer(item) -> bool`
  - `cash_price(item, trip) -> Decimal`, `cash_owed(item, trip) -> Decimal`
  - `points_used(item) -> int`
  - `value_cpp(item, trip) -> Decimal | None`
  - `buffer_amount(trip) -> Decimal`
  - `trip_cash_total(trip) -> Decimal`
  - `bonus_active(partner, today) -> bool`
  - `effective_ratio(partner, today) -> Decimal`
  - `source_points_needed(partner, target_points: int, today) -> int`
  - `partner_points_received(partner, source_points: int, today) -> int`

  All of these are pure functions. `trip` must have `.items` loaded.

- [ ] **Step 1: Write the failing tests (append to `test_adventures_rules.py`)**

```python
from backend.services.adventures import (
    nights, days, multiplier, cash_price, cash_owed, points_used, value_cpp,
    buffer_amount, trip_cash_total, effective_ratio, source_points_needed,
    partner_points_received, bonus_active,
)
TP = models.TripPricing
PAY = models.TripPayment


def _trip(**kw):
    return models.Trip(name="Trip", start_date=kw.get("start", date(2027, 3, 1)),
                       end_date=kw.get("end", date(2027, 3, 5)), travelers=kw.get("travelers", 2),
                       status=models.TripStatus.planning, items=[])


def _item(trip, name="Thing", pricing=TP.flat, unit="100.00", payment=PAY.cash, **kw):
    it = models.TripItem(name=name, category=models.TripCategory.while_there, pricing=pricing,
                         unit_cash=None if unit is None else Decimal(unit), payment=payment,
                         points_price=kw.get("points"), cash_copay=Decimal(kw.get("copay", "0")),
                         mix_cash=None if kw.get("mix") is None else Decimal(kw["mix"]),
                         is_paid=False, sort_order=0)
    trip.items.append(it)
    return it


def test_nights_days_and_multipliers():
    t = _trip()  # 4 nights, 5 days, 2 travelers
    assert (nights(t), days(t)) == (4, 5)
    expected = {TP.flat: 1, TP.per_day: 5, TP.per_night: 4, TP.per_person: 2, TP.per_person_day: 10}
    for pricing, m in expected.items():
        assert multiplier(_item(t, pricing=pricing), t) == m


def test_cash_price_and_cash_owed_per_payment_mode():
    t = _trip()
    cash = _item(t, pricing=TP.per_person, unit="300.00")
    pts = _item(t, unit="1000.00", payment=PAY.points, points=50000, copay="85.20")
    mix = _item(t, unit="400.00", payment=PAY.mix, points=10000, mix="150.00", copay="10.00")
    assert cash_price(cash, t) == Decimal("600.00") and cash_owed(cash, t) == Decimal("600.00")
    assert cash_owed(pts, t) == Decimal("85.20")
    assert cash_owed(mix, t) == Decimal("160.00")
    assert points_used(cash) == 0 and points_used(pts) == 50000 and points_used(mix) == 10000


def test_value_cpp_and_its_none_cases():
    t = _trip()
    pts = _item(t, unit="1000.00", payment=PAY.points, points=50000, copay="85.20")
    assert value_cpp(pts, t) == Decimal("1.83")          # (1000-85.20)/50000*100
    mix = _item(t, unit="400.00", payment=PAY.mix, points=10000, mix="150.00", copay="10.00")
    assert value_cpp(mix, t) == Decimal("2.40")          # (400-150-10)/10000*100
    assert value_cpp(_item(t), t) is None                 # cash item
    assert value_cpp(_item(t, unit="50.00", payment=PAY.points, points=1000, copay="60.00"), t) is None
    assert value_cpp(_item(t, unit="50.00", payment=PAY.points, points=0), t) is None


def test_auto_buffer_is_ten_percent_of_other_cash_and_user_value_wins():
    t = _trip()
    _item(t, unit="1000.00")
    _item(t, unit="234.50")
    buf = _item(t, name="Buffer", unit=None)
    assert buffer_amount(t) == Decimal("123.45")
    assert cash_owed(buf, t) == Decimal("123.45")
    assert trip_cash_total(t) == Decimal("1357.95")
    buf.unit_cash = Decimal("50.00")
    assert cash_owed(buf, t) == Decimal("50.00")


def _partner(ratio="1", bonus=None, ends=None):
    return models.TransferPartner(ratio=Decimal(ratio),
                                  bonus_pct=None if bonus is None else Decimal(bonus),
                                  bonus_ends_on=ends)


def test_effective_ratio_bonus_window_including_end_date():
    today = date(2027, 1, 10)
    assert effective_ratio(_partner(), today) == Decimal("1")
    assert effective_ratio(_partner(bonus="30", ends=date(2027, 1, 10)), today) == Decimal("1.30")
    assert effective_ratio(_partner(bonus="30", ends=date(2027, 1, 9)), today) == Decimal("1")
    assert effective_ratio(_partner(bonus="30"), today) == Decimal("1.30")   # no end date
    assert bonus_active(_partner(bonus="30", ends=date(2027, 1, 9)), today) is False


def test_transfer_rounding_ceil_for_source_floor_for_received():
    today = date(2027, 1, 10)
    p = _partner(bonus="30")
    assert source_points_needed(p, 70000, today) == 53847      # 70000/1.3 = 53846.15 -> up
    assert partner_points_received(p, 53847, today) == 70001   # 53847*1.3 = 70001.1 -> down
    assert source_points_needed(_partner(), 70000, today) == 70000
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_rules.py`
Expected: an ImportError on `nights`.

- [ ] **Step 3: Implement (insert into `adventures.py` after the imports, before `CHASE_UR`)**

```python
CENT = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def nights(trip: models.Trip) -> int:
    return max((trip.end_date - trip.start_date).days, 0)


def days(trip: models.Trip) -> int:
    return nights(trip) + 1


def multiplier(item: models.TripItem, trip: models.Trip) -> int:
    p = item.pricing
    if p == models.TripPricing.per_day:
        return days(trip)
    if p == models.TripPricing.per_night:
        return nights(trip)
    if p == models.TripPricing.per_person:
        return trip.travelers
    if p == models.TripPricing.per_person_day:
        return trip.travelers * days(trip)
    return 1


def is_auto_buffer(item: models.TripItem) -> bool:
    return (item.name.strip().lower() == "buffer"
            and item.pricing == models.TripPricing.flat and item.unit_cash is None)


def points_used(item: models.TripItem) -> int:
    if item.payment in (models.TripPayment.points, models.TripPayment.mix):
        return int(item.points_price or 0)
    return 0


def _raw_cash_price(item: models.TripItem, trip: models.Trip) -> Decimal:
    return _q(Decimal(item.unit_cash or 0) * multiplier(item, trip))


def _owed_from_price(item: models.TripItem, price: Decimal) -> Decimal:
    copay = Decimal(item.cash_copay or 0)
    if item.payment == models.TripPayment.points:
        return _q(copay)
    if item.payment == models.TripPayment.mix:
        return _q(Decimal(item.mix_cash or 0) + copay)
    return price


def buffer_amount(trip: models.Trip) -> Decimal:
    """10% of the cash owed on every non-auto-buffer item (spec Rules)."""
    others = sum((_owed_from_price(i, _raw_cash_price(i, trip))
                  for i in trip.items if not is_auto_buffer(i)), Decimal("0"))
    return _q(others * Decimal("0.10"))


def cash_price(item: models.TripItem, trip: models.Trip) -> Decimal:
    if is_auto_buffer(item):
        return buffer_amount(trip)
    return _raw_cash_price(item, trip)


def cash_owed(item: models.TripItem, trip: models.Trip) -> Decimal:
    return _owed_from_price(item, cash_price(item, trip))


def trip_cash_total(trip: models.Trip) -> Decimal:
    return sum((cash_owed(i, trip) for i in trip.items), Decimal("0"))


def value_cpp(item: models.TripItem, trip: models.Trip) -> Decimal | None:
    pts = points_used(item)
    if pts <= 0:
        return None
    numerator = cash_price(item, trip) - Decimal(item.cash_copay or 0)
    if item.payment == models.TripPayment.mix:
        numerator -= Decimal(item.mix_cash or 0)
    if numerator <= 0:
        return None
    return _q(numerator / Decimal(pts) * 100)


def bonus_active(partner: models.TransferPartner, today: date) -> bool:
    return partner.bonus_pct is not None and (
        partner.bonus_ends_on is None or today <= partner.bonus_ends_on)


def effective_ratio(partner: models.TransferPartner, today: date) -> Decimal:
    ratio = Decimal(partner.ratio)
    if bonus_active(partner, today):
        ratio = ratio * (1 + Decimal(partner.bonus_pct) / 100)
    return ratio


def source_points_needed(partner: models.TransferPartner, target_points: int, today: date) -> int:
    """Rounded UP so a transfer is never short (Global Constraints)."""
    return int((Decimal(target_points) / effective_ratio(partner, today)).to_integral_value(rounding=ROUND_CEILING))


def partner_points_received(partner: models.TransferPartner, source_points: int, today: date) -> int:
    """Rounded DOWN -- programs credit whole points only."""
    return int((Decimal(source_points) * effective_ratio(partner, today)).to_integral_value(rounding=ROUND_FLOOR))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_rules.py`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/adventures.py backend/tests/test_adventures_rules.py
git commit -m "feat: Adventures cash/points rules, redemption value, transfer ratios

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Wallet math — reserved, available, shortfall, transfer suggestion

**Files:**
- Modify: `backend/services/adventures.py` (append the wallet section)
- Test: `backend/tests/test_adventures_wallet.py`

**Interfaces:**
- Consumes: Task 2 functions.
- Produces:
  - `reserved_by_program(db, user_id, exclude_trip_id: int | None = None) -> dict[int, int]`
  - `wallet(db, user_id, today) -> list[dict]`. Each dict has keys `id, name, kind, balance, reserved, available, balance_updated_at, age_days, is_active, sort_order`.
  - `trip_points_summary(db, trip, today) -> dict[int, dict]`. Each value has keys `program_id, name, needed, available, incoming, shortfall`.
  - `suggest_transfer(db, item, trip, today) -> dict | None`, with keys `from_program_id, from_program_name, source_points, partner_points, bonus_pct`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_adventures_wallet.py`:

```python
from datetime import date, datetime
from decimal import Decimal
from backend import models
from backend.services.adventures import (
    reserved_by_program, wallet, trip_points_summary, suggest_transfer,
)

TODAY = date(2027, 1, 10)
PAY = models.TripPayment


def _user(db, name="w"):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.flush(); return u


def _prog(db, user, name, balance, kind=models.LoyaltyKind.airline):
    p = models.LoyaltyProgram(user_id=user.id, name=name, kind=kind, balance=balance)
    db.add(p); db.flush(); return p


def _trip(db, user, status=models.TripStatus.planning, name="Trip"):
    t = models.Trip(user_id=user.id, name=name, start_date=date(2027, 3, 1),
                    end_date=date(2027, 3, 5), travelers=1, status=status)
    db.add(t); db.flush(); return t


def _pts_item(db, trip, program, points, **kw):
    it = models.TripItem(trip_id=trip.id, user_id=trip.user_id, name=kw.get("name", "Flight"),
                         category=models.TripCategory.getting_there, unit_cash=Decimal("1000"),
                         payment=PAY.points, points_program_id=program.id, points_price=points,
                         transfer_from_program_id=kw.get("transfer_from"),
                         transfer_points=kw.get("transfer_points"))
    db.add(it); db.flush(); db.refresh(trip); return it


def test_reserved_counts_planning_and_committed_but_not_done(db_session):
    u = _user(db_session)
    air = _prog(db_session, u, "Air", 100000)
    _pts_item(db_session, _trip(db_session, u), air, 30000)
    _pts_item(db_session, _trip(db_session, u, models.TripStatus.committed), air, 20000)
    _pts_item(db_session, _trip(db_session, u, models.TripStatus.done), air, 50000)
    assert reserved_by_program(db_session, u.id) == {air.id: 50000}
    row = next(r for r in wallet(db_session, u.id, TODAY) if r["id"] == air.id)
    assert (row["balance"], row["reserved"], row["available"]) == (100000, 50000, 50000)


def test_transfer_points_reserve_the_source_program(db_session):
    u = _user(db_session)
    bank = _prog(db_session, u, "Bank", 80000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 0)
    _pts_item(db_session, _trip(db_session, u), air, 70000,
              transfer_from=bank.id, transfer_points=53847)
    assert reserved_by_program(db_session, u.id) == {air.id: 70000, bank.id: 53847}


def test_wallet_age_days(db_session):
    u = _user(db_session)
    p = _prog(db_session, u, "Air", 10)
    p.balance_updated_at = datetime(2026, 12, 1, 9, 0)
    row = wallet(db_session, u.id, TODAY)[0]
    assert row["age_days"] == 40


def test_shortfall_is_net_of_other_trips_and_attached_transfers(db_session):
    u = _user(db_session)
    bank = _prog(db_session, u, "Bank", 100000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 20000)
    db_session.add(models.TransferPartner(user_id=u.id, from_program_id=bank.id,
                                          to_program_id=air.id, ratio=Decimal("1")))
    other = _trip(db_session, u, name="Other")
    _pts_item(db_session, other, air, 5000)              # reserves 5k Air elsewhere
    trip = _trip(db_session, u)
    _pts_item(db_session, trip, air, 70000)
    s = trip_points_summary(db_session, trip, TODAY)[air.id]
    assert (s["needed"], s["available"], s["incoming"], s["shortfall"]) == (70000, 15000, 0, 55000)
    second = _pts_item(db_session, trip, air, 0, name="Attach",
                       transfer_from=bank.id, transfer_points=55000)
    second.payment = PAY.cash
    db_session.flush(); db_session.refresh(trip)
    s = trip_points_summary(db_session, trip, TODAY)
    assert s[air.id]["incoming"] == 0   # transfer only counts toward the item's own program


def test_suggest_transfer_picks_fewest_source_points_that_can_cover(db_session):
    u = _user(db_session)
    small = _prog(db_session, u, "SmallBank", 10000, models.LoyaltyKind.bank)
    big = _prog(db_session, u, "BigBank", 200000, models.LoyaltyKind.bank)
    rich = _prog(db_session, u, "RichBank", 200000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 0)
    for src, ratio, bonus in ((small, "2", None), (big, "1", "30"), (rich, "1", None)):
        db_session.add(models.TransferPartner(user_id=u.id, from_program_id=src.id, to_program_id=air.id,
                                              ratio=Decimal(ratio),
                                              bonus_pct=None if bonus is None else Decimal(bonus)))
    trip = _trip(db_session, u)
    item = _pts_item(db_session, trip, air, 70000)
    s = suggest_transfer(db_session, item, trip, TODAY)
    # small (ratio 2 -> 35000 needed) can't cover with 10000; big with +30% needs 53847
    assert s == {"from_program_id": big.id, "from_program_name": "BigBank",
                 "source_points": 53847, "partner_points": 70001, "bonus_pct": Decimal("30.00")}


def test_no_suggestion_when_covered_or_already_attached(db_session):
    u = _user(db_session)
    air = _prog(db_session, u, "Air", 100000)
    trip = _trip(db_session, u)
    assert suggest_transfer(db_session, _pts_item(db_session, trip, air, 1000), trip, TODAY) is None


def test_wallet_is_user_scoped(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    _prog(db_session, b, "Theirs", 5)
    assert wallet(db_session, a.id, TODAY) == []
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_wallet.py`
Expected: an ImportError.

- [ ] **Step 3: Implement (append to `adventures.py`)**

```python
# ── Wallet math ──────────────────────────────────────────────────────────────

_OPEN = (models.TripStatus.planning, models.TripStatus.committed)


def reserved_by_program(db: Session, user_id: int, exclude_trip_id: int | None = None) -> dict[int, int]:
    """Points spoken for by open (planning/committed) trips: each item's own
    points, plus source points of any attached transfer."""
    q = db.query(models.Trip).filter(models.Trip.user_id == user_id, models.Trip.status.in_(_OPEN))
    if exclude_trip_id is not None:
        q = q.filter(models.Trip.id != exclude_trip_id)
    out: dict[int, int] = {}
    for trip in q.all():
        for it in trip.items:
            used = points_used(it)
            if used and it.points_program_id:
                out[it.points_program_id] = out.get(it.points_program_id, 0) + used
            if it.transfer_from_program_id and it.transfer_points:
                out[it.transfer_from_program_id] = out.get(it.transfer_from_program_id, 0) + int(it.transfer_points)
    return out


def wallet(db: Session, user_id: int, today: date) -> list[dict]:
    reserved = reserved_by_program(db, user_id)
    rows = []
    for p in db.query(models.LoyaltyProgram).filter(
            models.LoyaltyProgram.user_id == user_id).order_by(
            models.LoyaltyProgram.sort_order, models.LoyaltyProgram.id).all():
        r = reserved.get(p.id, 0)
        rows.append({
            "id": p.id, "name": p.name, "kind": p.kind.value, "balance": p.balance,
            "reserved": r, "available": p.balance - r,
            "balance_updated_at": p.balance_updated_at,
            "age_days": (today - p.balance_updated_at.date()).days if p.balance_updated_at else None,
            "is_active": p.is_active, "sort_order": p.sort_order,
        })
    return rows


def _partner_for(db: Session, user_id: int, from_id: int, to_id: int) -> models.TransferPartner | None:
    return db.query(models.TransferPartner).filter(
        models.TransferPartner.user_id == user_id,
        models.TransferPartner.from_program_id == from_id,
        models.TransferPartner.to_program_id == to_id).first()


def trip_points_summary(db: Session, trip: models.Trip, today: date) -> dict[int, dict]:
    """Per program this trip touches: points needed (items' own points plus
    transfer source points), what's available after OTHER open trips,
    partner points arriving from attached transfers, and the shortfall."""
    others = reserved_by_program(db, trip.user_id, exclude_trip_id=trip.id)
    needed: dict[int, int] = {}
    incoming: dict[int, int] = {}
    for it in trip.items:
        used = points_used(it)
        if used and it.points_program_id:
            needed[it.points_program_id] = needed.get(it.points_program_id, 0) + used
        if it.transfer_from_program_id and it.transfer_points:
            src = it.transfer_from_program_id
            needed[src] = needed.get(src, 0) + int(it.transfer_points)
            if used and it.points_program_id:
                partner = _partner_for(db, trip.user_id, src, it.points_program_id)
                if partner:
                    got = partner_points_received(partner, int(it.transfer_points), today)
                    incoming[it.points_program_id] = incoming.get(it.points_program_id, 0) + got
    out: dict[int, dict] = {}
    for pid in needed:
        prog = db.get(models.LoyaltyProgram, pid)
        if prog is None or prog.user_id != trip.user_id:
            continue
        avail = prog.balance - others.get(pid, 0)
        inc = incoming.get(pid, 0)
        out[pid] = {"program_id": pid, "name": prog.name, "needed": needed[pid],
                    "available": avail, "incoming": inc,
                    "shortfall": max(needed[pid] - avail - inc, 0)}
    return out


def suggest_transfer(db: Session, item: models.TripItem, trip: models.Trip, today: date) -> dict | None:
    if points_used(item) <= 0 or not item.points_program_id or item.transfer_from_program_id:
        return None
    summary = trip_points_summary(db, trip, today)
    short = summary.get(item.points_program_id, {}).get("shortfall", 0)
    if short <= 0:
        return None
    best = None
    for partner in db.query(models.TransferPartner).filter(
            models.TransferPartner.user_id == trip.user_id,
            models.TransferPartner.to_program_id == item.points_program_id).all():
        src = partner.from_program
        if src is None or not src.is_active:
            continue
        need = source_points_needed(partner, short, today)
        src_left = summary[src.id]["available"] - summary[src.id]["needed"] if src.id in summary \
            else src.balance - reserved_by_program(db, trip.user_id).get(src.id, 0)
        if src_left < need:
            continue
        if best is None or need < best["source_points"]:
            best = {"from_program_id": src.id, "from_program_name": src.name,
                    "source_points": need,
                    "partner_points": partner_points_received(partner, need, today),
                    "bonus_pct": Decimal(partner.bonus_pct).quantize(CENT) if bonus_active(partner, today) else None}
    return best
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_wallet.py`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/adventures.py backend/tests/test_adventures_wallet.py
git commit -m "feat: Adventures points wallet, per-trip shortfall and transfer suggestion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Lifecycle — commit, sync, paid, uncommit, finish, delete, fund

**Files:**
- Create: `backend/services/adventures_lifecycle.py`
- Test: `backend/tests/test_adventures_lifecycle.py`

**Interfaces:**
- Consumes:
  - From Task 2: `cash_owed`, `trip_cash_total`, `points_used`, `partner_points_received`.
  - From Task 3: `_partner_for`.
- Produces (every function takes `db: Session` first; none commit, callers commit):
  - `class LifecycleError(ValueError)`
  - `create_trip_from_template(db, user_id, *, name, destination, start_date, end_date, travelers, default_card_id) -> Trip`
  - `sync_trip_planned_expenses(db, trip) -> None`
  - `commit_trip(db, trip) -> None`
  - `uncommit_trip(db, trip) -> None`
  - `set_item_paid(db, trip, item, paid: bool, today: date) -> None`
  - `delete_item(db, trip, item) -> None`
  - `delete_trip(db, trip) -> None`
  - `finish_plan(db, trip, today) -> dict[int, int]` (the default per-program balance deltas)
  - `finish_trip(db, trip, points_used_by_program: dict[int, int] | None, force: bool, today: date) -> dict[int, int]`
  - `create_trip_fund(db, trip) -> SavingsGoal`
  - `update_trip_fund_target(db, trip) -> SavingsGoal`
  - `remove_trip_fund(db, trip, delete_goal: bool) -> None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_adventures_lifecycle.py`:

```python
from datetime import date, timedelta
from decimal import Decimal
import pytest
from backend import models
from backend.services.adventures import ensure_adventures_seeded, STARTER_TEMPLATE
from backend.services.adventures_lifecycle import (
    LifecycleError, create_trip_from_template, sync_trip_planned_expenses, commit_trip,
    uncommit_trip, set_item_paid, delete_item, delete_trip, finish_plan, finish_trip,
    create_trip_fund, update_trip_fund_target, remove_trip_fund,
)
from backend.services.forecast_engine import build_forecast

TODAY = date(2027, 1, 10)
PAY = models.TripPayment


def _setup(db):
    u = models.User(username="life", hashed_password="x", display_name="L")
    db.add(u); db.flush()
    acct = models.Account(user_id=u.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("10000.00"))
    card = models.CreditCard(user_id=u.id, name="Card A", credit_limit=Decimal("5000.00"),
                             statement_day=28, due_day=25, current_balance=Decimal("0.00"))
    db.add_all([acct, card]); db.flush()
    ensure_adventures_seeded(db, u.id)
    trip = create_trip_from_template(db, u.id, name="Beach", destination="Coast",
                                     start_date=date(2027, 3, 1), end_date=date(2027, 3, 5),
                                     travelers=2, default_card_id=card.id)
    return u, acct, card, trip


def _by_name(trip, name):
    return next(i for i in trip.items if i.name == name)


def _pes(db, user):
    return db.query(models.PlannedExpense).filter_by(user_id=user.id).order_by(models.PlannedExpense.id).all()


def test_create_from_template_copies_every_item(db_session):
    u, _, _, trip = _setup(db_session)
    assert [i.name for i in trip.items] == [n for _, n, _ in STARTER_TEMPLATE]
    assert trip.status == models.TripStatus.planning


def test_planning_trip_creates_no_planned_expenses(db_session):
    u, _, _, trip = _setup(db_session)
    _by_name(trip, "Lodging").unit_cash = Decimal("200.00")
    sync_trip_planned_expenses(db_session, trip)
    assert _pes(db_session, u) == []


def test_commit_creates_one_offs_with_amount_date_and_card(db_session):
    u, _, card, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")       # 4 nights = 800
    flights = _by_name(trip, "Flights"); flights.unit_cash = Decimal("500.00")       # 2 people
    flights.payment = PAY.points; flights.points_price = 60000; flights.cash_copay = Decimal("11.20")
    flights.charge_date = date(2027, 1, 20)
    commit_trip(db_session, trip)
    pes = {pe.name: pe for pe in _pes(db_session, u)}
    # Buffer is 10% of other cash owed: (800 + 11.20) * 0.10 = 81.12
    assert set(pes) == {"Beach: Lodging", "Beach: Flights", "Beach: Buffer"}
    assert pes["Beach: Lodging"].amount == Decimal("800.00")
    assert pes["Beach: Lodging"].expected_date == date(2027, 3, 1)
    assert pes["Beach: Flights"].amount == Decimal("11.20")
    assert pes["Beach: Flights"].expected_date == date(2027, 1, 20)
    assert all(pe.card_id == card.id and pe.direction == models.PlannedDirection.outflow for pe in pes.values())
    assert pes["Beach: Buffer"].amount == Decimal("81.12")
    assert trip.status == models.TripStatus.committed


def test_sync_after_edit_is_idempotent_and_removes_zeroed_items(db_session):
    u, _, _, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    commit_trip(db_session, trip)
    lodging.unit_cash = Decimal("250.00")
    sync_trip_planned_expenses(db_session, trip)
    sync_trip_planned_expenses(db_session, trip)
    pes = {pe.name: pe for pe in _pes(db_session, u)}
    assert pes["Beach: Lodging"].amount == Decimal("1000.00") and len(pes) == 2   # + Buffer
    lodging.unit_cash = None
    sync_trip_planned_expenses(db_session, trip)
    assert _pes(db_session, u) == [] and lodging.planned_expense_id is None


def test_mark_paid_settles_and_forecast_drops_it(db_session):
    u, acct, _, trip = _setup(db_session)
    trip.default_card_id = None   # straight to checking so the forecast effect is direct
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    _by_name(trip, "Buffer").unit_cash = Decimal("0")
    commit_trip(db_session, trip)
    db_session.commit()

    def lodging_lines():
        days = build_forecast(db_session, u.id, acct.id, date(2027, 2, 25), date(2027, 3, 5))
        return [t for d in days for t in d.transactions if "Lodging" in t.name]

    assert len(lodging_lines()) == 1
    set_item_paid(db_session, trip, lodging, True, TODAY)
    set_item_paid(db_session, trip, lodging, True, TODAY)   # no-op
    db_session.commit()
    pe = db_session.get(models.PlannedExpense, lodging.planned_expense_id)
    assert pe.settled_on == TODAY and pe.actual_amount == Decimal("800.00")
    assert lodging_lines() == []
    set_item_paid(db_session, trip, lodging, False, TODAY)
    assert pe.settled_on is None and pe.actual_amount is None


def test_uncommit_removes_unsettled_only(db_session):
    u, _, _, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    food = _by_name(trip, "Food"); food.unit_cash = Decimal("10.00")
    commit_trip(db_session, trip)
    set_item_paid(db_session, trip, lodging, True, TODAY)
    uncommit_trip(db_session, trip)
    pes = _pes(db_session, u)
    assert [pe.name for pe in pes] == ["Beach: Lodging"] and pes[0].settled_on == TODAY
    assert food.planned_expense_id is None and lodging.planned_expense_id is None
    assert trip.status == models.TripStatus.planning


def test_delete_item_and_trip_clean_up_one_offs(db_session):
    u, _, _, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    commit_trip(db_session, trip)
    delete_item(db_session, trip, lodging)
    assert [pe.name for pe in _pes(db_session, u)] == []   # buffer fell to 0 too
    _by_name(trip, "Food").unit_cash = Decimal("10.00")
    sync_trip_planned_expenses(db_session, trip)
    delete_trip(db_session, trip)
    db_session.flush()
    assert _pes(db_session, u) == [] and db_session.query(models.Trip).count() == 0


def test_status_guards(db_session):
    u, _, _, trip = _setup(db_session)
    with pytest.raises(LifecycleError):
        uncommit_trip(db_session, trip)
    with pytest.raises(LifecycleError):
        finish_trip(db_session, trip, None, False, TODAY)
    commit_trip(db_session, trip)
    with pytest.raises(LifecycleError):
        commit_trip(db_session, trip)


def _program(db, user, name):
    return db.query(models.LoyaltyProgram).filter_by(user_id=user.id, name=name).one()


def test_finish_deducts_points_with_transfer_and_refuses_negative(db_session):
    u, _, _, trip = _setup(db_session)
    chase = _program(db_session, u, "Chase Ultimate Rewards"); chase.balance = 60000
    virgin = _program(db_session, u, "Virgin Atlantic Flying Club"); virgin.balance = 1000
    partner = db_session.query(models.TransferPartner).filter_by(
        user_id=u.id, from_program_id=chase.id, to_program_id=virgin.id).one()
    partner.bonus_pct = Decimal("30")
    flights = _by_name(trip, "Flights"); flights.unit_cash = Decimal("900.00")
    flights.payment = PAY.points; flights.points_program_id = virgin.id; flights.points_price = 70000
    flights.transfer_from_program_id = chase.id; flights.transfer_points = 53847
    commit_trip(db_session, trip)
    assert finish_plan(db_session, trip, TODAY) == {chase.id: -53847, virgin.id: 70001 - 70000}
    finish_trip(db_session, trip, None, False, TODAY)
    assert (chase.balance, virgin.balance) == (60000 - 53847, 1000 + 1)
    assert trip.status == models.TripStatus.done and chase.balance_updated_at is not None


def test_finish_refuses_negative_unless_forced(db_session):
    u, _, _, trip = _setup(db_session)
    hyatt = _program(db_session, u, "World of Hyatt"); hyatt.balance = 1000
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    lodging.payment = PAY.points; lodging.points_program_id = hyatt.id; lodging.points_price = 5000
    commit_trip(db_session, trip)
    with pytest.raises(LifecycleError):
        finish_trip(db_session, trip, None, False, TODAY)
    assert hyatt.balance == 1000 and trip.status == models.TripStatus.committed
    finish_trip(db_session, trip, {hyatt.id: 900}, False, TODAY)   # confirmed lower usage
    assert hyatt.balance == 100


def test_trip_fund_create_update_remove(db_session):
    u, _, _, trip = _setup(db_session)
    _by_name(trip, "Lodging").unit_cash = Decimal("200.00")
    goal = create_trip_fund(db_session, trip)
    assert goal.name == "Beach fund" and goal.target_amount == Decimal("880.00")   # 800 + 10% buffer
    assert goal.target_date == date(2027, 3, 1) - timedelta(days=7)
    with pytest.raises(LifecycleError):
        create_trip_fund(db_session, trip)
    _by_name(trip, "Lodging").unit_cash = Decimal("300.00")
    assert goal.target_amount == Decimal("880.00")            # never silently changes
    assert update_trip_fund_target(db_session, trip).target_amount == Decimal("1320.00")
    remove_trip_fund(db_session, trip, delete_goal=True)
    db_session.flush()
    assert trip.fund_goal_id is None and db_session.query(models.SavingsGoal).count() == 0
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_lifecycle.py`
Expected: an ImportError on `backend.services.adventures_lifecycle`.

- [ ] **Step 3: Implement `backend/services/adventures_lifecycle.py`**

```python
"""Adventures lifecycle writes. Spec: docs/superpowers/specs/2026-10-01-adventures-design.md

A committed trip is mirrored 1:1 into PlannedExpense rows (one per item that
still owes cash), so the Forecast needs no changes. Links live on
TripItem.planned_expense_id. Callers own the transaction (no commits here).
FK enforcement is ON in production and tests, so a link is always nulled and
flushed BEFORE its PlannedExpense is deleted.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services.adventures import (
    cash_owed, trip_cash_total, points_used, partner_points_received, _partner_for,
)


class LifecycleError(ValueError):
    pass


def create_trip_from_template(db: Session, user_id: int, *, name: str, destination: str | None,
                              start_date: date, end_date: date, travelers: int,
                              default_card_id: int | None) -> models.Trip:
    if end_date < start_date:
        raise LifecycleError("end date is before start date")
    trip = models.Trip(user_id=user_id, name=name, destination=destination, start_date=start_date,
                       end_date=end_date, travelers=max(travelers, 1),
                       status=models.TripStatus.planning, default_card_id=default_card_id)
    db.add(trip)
    db.flush()
    template = db.query(models.ChecklistTemplateItem).filter(
        models.ChecklistTemplateItem.user_id == user_id).order_by(
        models.ChecklistTemplateItem.sort_order, models.ChecklistTemplateItem.id).all()
    for i, t in enumerate(template):
        trip.items.append(models.TripItem(user_id=user_id, category=t.category, name=t.name,
                                          pricing=t.pricing, unit_cash=t.unit_cash,
                                          payment=models.TripPayment.cash, cash_copay=Decimal("0"),
                                          is_paid=False, sort_order=i))
    db.flush()
    return trip


def _unlink_and_delete(db: Session, item: models.TripItem, *, keep_settled: bool = True) -> None:
    if item.planned_expense_id is None:
        return
    pe = db.get(models.PlannedExpense, item.planned_expense_id)
    item.planned_expense_id = None
    db.flush()
    if pe is not None and not (keep_settled and pe.settled_on is not None):
        db.delete(pe)
        db.flush()


def sync_trip_planned_expenses(db: Session, trip: models.Trip) -> None:
    """Reconcile a COMMITTED trip's one-offs with its items. Idempotent. Paid
    items keep their (settled) row untouched. No-op unless committed."""
    if trip.status != models.TripStatus.committed:
        return
    for item in trip.items:
        if item.is_paid:
            continue
        owed = cash_owed(item, trip)
        pe = db.get(models.PlannedExpense, item.planned_expense_id) if item.planned_expense_id else None
        if owed <= 0:
            _unlink_and_delete(db, item)
            continue
        fields = dict(name=f"{trip.name}: {item.name}"[:128], amount=owed,
                      expected_date=item.charge_date or trip.start_date,
                      card_id=item.card_id or trip.default_card_id)
        if pe is None:
            pe = models.PlannedExpense(user_id=trip.user_id, direction=models.PlannedDirection.outflow,
                                       **fields)
            db.add(pe)
            db.flush()
            item.planned_expense_id = pe.id
        else:
            for k, v in fields.items():
                setattr(pe, k, v)
    db.flush()


def commit_trip(db: Session, trip: models.Trip) -> None:
    if trip.status != models.TripStatus.planning:
        raise LifecycleError("only a planning trip can be committed")
    trip.status = models.TripStatus.committed
    db.flush()
    sync_trip_planned_expenses(db, trip)


def uncommit_trip(db: Session, trip: models.Trip) -> None:
    if trip.status != models.TripStatus.committed:
        raise LifecycleError("only a committed trip can go back to planning")
    for item in trip.items:
        _unlink_and_delete(db, item)
    trip.status = models.TripStatus.planning
    db.flush()


def set_item_paid(db: Session, trip: models.Trip, item: models.TripItem, paid: bool, today: date) -> None:
    if item.is_paid == paid:
        return
    item.is_paid = paid
    pe = db.get(models.PlannedExpense, item.planned_expense_id) if item.planned_expense_id else None
    if pe is not None:
        pe.settled_on = today if paid else None
        pe.actual_amount = pe.amount if paid else None
    db.flush()
    if not paid:
        sync_trip_planned_expenses(db, trip)


def delete_item(db: Session, trip: models.Trip, item: models.TripItem) -> None:
    _unlink_and_delete(db, item)
    trip.items.remove(item)
    db.flush()
    sync_trip_planned_expenses(db, trip)


def delete_trip(db: Session, trip: models.Trip) -> None:
    for item in trip.items:
        _unlink_and_delete(db, item)
    db.delete(trip)
    db.flush()


def finish_plan(db: Session, trip: models.Trip, today: date) -> dict[int, int]:
    """Default balance deltas per program: transfers move points source ->
    partner, then each item's points come off its own program."""
    deltas: dict[int, int] = {}
    for it in trip.items:
        used = points_used(it)
        if it.transfer_from_program_id and it.transfer_points:
            deltas[it.transfer_from_program_id] = deltas.get(it.transfer_from_program_id, 0) - int(it.transfer_points)
            if it.points_program_id:
                partner = _partner_for(db, trip.user_id, it.transfer_from_program_id, it.points_program_id)
                if partner:
                    got = partner_points_received(partner, int(it.transfer_points), today)
                    deltas[it.points_program_id] = deltas.get(it.points_program_id, 0) + got
        if used and it.points_program_id:
            deltas[it.points_program_id] = deltas.get(it.points_program_id, 0) - used
    return deltas


def finish_trip(db: Session, trip: models.Trip, points_used_by_program: dict[int, int] | None,
                force: bool, today: date) -> dict[int, int]:
    """committed -> done. `points_used_by_program` overrides the items'
    points per program (the user's confirmed spend); transfers still apply."""
    if trip.status != models.TripStatus.committed:
        raise LifecycleError("only a committed trip can be finished")
    deltas = finish_plan(db, trip, today)
    if points_used_by_program:
        planned_use: dict[int, int] = {}
        for it in trip.items:
            if points_used(it) and it.points_program_id:
                planned_use[it.points_program_id] = planned_use.get(it.points_program_id, 0) + points_used(it)
        for pid, confirmed in points_used_by_program.items():
            deltas[pid] = deltas.get(pid, 0) + planned_use.get(pid, 0) - int(confirmed)
    programs = {pid: db.get(models.LoyaltyProgram, pid) for pid in deltas}
    negative = [p.name for pid, p in programs.items()
                if p is not None and p.user_id == trip.user_id and p.balance + deltas[pid] < 0]
    if negative and not force:
        raise LifecycleError("would go negative: " + ", ".join(sorted(negative)))
    now = datetime.now()   # local, matches date.today() in age_days
    for pid, p in programs.items():
        if p is None or p.user_id != trip.user_id or deltas[pid] == 0:
            continue
        p.balance = p.balance + deltas[pid]
        p.balance_updated_at = now
    trip.status = models.TripStatus.done
    db.flush()
    return deltas


def create_trip_fund(db: Session, trip: models.Trip) -> models.SavingsGoal:
    if trip.fund_goal_id is not None:
        raise LifecycleError("trip already has a fund")
    goal = models.SavingsGoal(user_id=trip.user_id, name=f"{trip.name} fund"[:128],
                              target_amount=trip_cash_total(trip),
                              target_date=trip.start_date - timedelta(days=7),
                              current_amount=Decimal("0"), is_active=True)
    db.add(goal)
    db.flush()
    trip.fund_goal_id = goal.id
    db.flush()
    return goal


def update_trip_fund_target(db: Session, trip: models.Trip) -> models.SavingsGoal:
    if trip.fund_goal_id is None:
        raise LifecycleError("trip has no fund")
    goal = db.get(models.SavingsGoal, trip.fund_goal_id)
    goal.target_amount = trip_cash_total(trip)
    goal.target_date = trip.start_date - timedelta(days=7)
    db.flush()
    return goal


def remove_trip_fund(db: Session, trip: models.Trip, delete_goal: bool) -> None:
    if trip.fund_goal_id is None:
        return
    goal = db.get(models.SavingsGoal, trip.fund_goal_id)
    trip.fund_goal_id = None
    db.flush()
    if delete_goal and goal is not None:
        db.delete(goal)
        db.flush()
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_lifecycle.py`
Expected: `12 passed`.

If `test_mark_paid_settles_and_forecast_drops_it` fails because `build_forecast` returns no Lodging line before it is paid, read how `forecast_engine.py` loads PlannedExpense (around line 429: `settled_on IS NULL`, `card_id`, `account_id`). Then fix the **test fixture**, never `forecast_engine.py`. For example, set the PlannedExpense's `account_id` if the engine needs it for checking outflows. Record what you changed in your report.

- [ ] **Step 5: Run the full suite, then commit**

Run: `cd backend && python3 -m pytest -q`. Expected: 0 failures.

```bash
git add backend/services/adventures_lifecycle.py backend/tests/test_adventures_lifecycle.py
git commit -m "feat: Adventures trip lifecycle feeding the Forecast via planned one-offs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: API router

**Files:**
- Modify: `backend/schemas.py` (append), `backend/main.py` (import and include the router)
- Create: `backend/routers/adventures.py`
- Test: `backend/tests/test_adventures_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces the HTTP contract that Tasks 6–7 rely on. All paths are under `/adventures`; JSON numbers are decimals serialised as strings, which is Pydantic's Decimal default in this codebase.

| Method & path | Body | Returns |
|---|---|---|
| `GET /wallet` | – | `WalletRow[]`. Calls `ensure_adventures_seeded` first. |
| `PATCH /programs/{id}` | `{name?, balance?, is_active?, sort_order?}` | `WalletRow`. Writing `balance` stamps `balance_updated_at = datetime.now()` (local time, the same clock as `date.today()`). |
| `POST /programs` | `{name, kind}` | `WalletRow` |
| `DELETE /programs/{id}` | – | 204. Returns 409 if any trip item references the program; otherwise deletes its partner rows, then the program. |
| `GET /partners` | – | `PartnerOut[]`: `{id, from_program_id, from_program_name, to_program_id, to_program_name, ratio, bonus_pct, bonus_ends_on, bonus_active}` |
| `POST /partners` | `{from_program_id, to_program_id, ratio=1, bonus_pct?, bonus_ends_on?}` | `PartnerOut`. Returns 422 if from == to and 409 on a duplicate. |
| `PATCH /partners/{id}` | `{ratio?, bonus_pct?, bonus_ends_on?}` (explicit null clears) | `PartnerOut` |
| `DELETE /partners/{id}` | – | 204 |
| `GET /template` | – | `TemplateItemOut[]` |
| `POST /template` | `{category, name, pricing, unit_cash?}` | `TemplateItemOut` |
| `DELETE /template/{id}` | – | 204 |
| `POST /template/reset` | – | `TemplateItemOut[]`. Deletes all template rows, then re-seeds the template. |
| `GET /trips` | – | `TripSummary[]`: `{id, name, destination, start_date, end_date, travelers, status, cash_total, cash_remaining, points_by_program: {program_id: points}, fund_goal_id, fund_current, fund_target}` |
| `POST /trips` | `{name, destination?, start_date, end_date, travelers=1, default_card_id?}` | `TripDetail` (201) |
| `GET /trips/{id}` | – | `TripDetail` |
| `PATCH /trips/{id}` | `{name?, destination?, start_date?, end_date?, travelers?, default_card_id?, notes?}` | `TripDetail`. Syncs one-offs. |
| `DELETE /trips/{id}` | – | 204 |
| `POST /trips/{id}/items` | `TripItemIn` | `TripDetail` |
| `PATCH /trips/{id}/items/{item_id}` | partial `TripItemIn` plus `is_paid?` | `TripDetail` |
| `DELETE /trips/{id}/items/{item_id}?remove_from_template=false` | – | `TripDetail`. With `true`, also deletes template rows with the same category and name. |
| `POST /trips/{id}/commit`, `/uncommit` | – | `TripDetail`. A `LifecycleError` becomes 409. |
| `GET /trips/{id}/finish-plan` | – | `{program_id: delta}` |
| `POST /trips/{id}/finish` | `{points_used_by_program?: {id: int}, force=false}` | `TripDetail`. Returns 409 with the message if a balance would go negative. |
| `POST /trips/{id}/fund`, `POST /trips/{id}/fund/update`, `DELETE /trips/{id}/fund?delete_goal=false` | – | `TripDetail` |

`TripDetail` = `TripSummary` plus:
- `default_card_id`, `notes`
- `items: TripItemOut[]`
- `points_summary: PointsSummaryRow[]` (the values of `trip_points_summary`)

`TripItemOut` = the item's stored fields plus the derived fields `cash_price`, `cash_owed`, `points_used`, `value_cpp`, `is_auto_buffer`, `multiplier` and `suggestion` (`suggest_transfer` or null).

Items on a `done` trip are read-only: item writes, PATCH trip and fund changes return 409.

`TripItemIn` is `{category, name, pricing=flat, unit_cash?, payment=cash, points_program_id?, points_price?, cash_copay=0, mix_cash?, charge_date?, card_id?, transfer_from_program_id?, transfer_points?}`. Validation:
- a `points_program_id` must belong to the user; the same goes for any card id
- `points` and `mix` require `points_program_id` and `points_price > 0`
- `transfer_points` requires `transfer_from_program_id`

Any violation returns 422.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_adventures_api.py`:

```python
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import adventures as adventures_router
from backend.dependencies import get_db, get_current_user


def _client(db, user):
    app = FastAPI()
    app.include_router(adventures_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _user(db, name="api"):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.commit(); db.refresh(u); return u


def _new_trip(c):
    r = c.post("/adventures/trips", json={"name": "Lake", "start_date": "2027-06-01",
                                          "end_date": "2027-06-04", "travelers": 2})
    assert r.status_code == 201, r.text
    return r.json()


def test_wallet_seeds_and_balance_patch_stamps_time(db_session):
    c = _client(db_session, _user(db_session))
    rows = c.get("/adventures/wallet").json()
    assert any(r["name"] == "Chase Ultimate Rewards" for r in rows)
    pid = rows[0]["id"]
    r = c.patch(f"/adventures/programs/{pid}", json={"balance": 12345}).json()
    assert r["balance"] == 12345 and r["balance_updated_at"] is not None and r["age_days"] == 0


def test_trip_create_copies_template_and_reports_derived_fields(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    assert t["status"] == "planning" and len(t["items"]) == 18
    food = next(i for i in t["items"] if i["name"] == "Food")
    r = c.patch(f"/adventures/trips/{t['id']}/items/{food['id']}", json={"unit_cash": "20.00"}).json()
    food = next(i for i in r["items"] if i["name"] == "Food")
    assert food["multiplier"] == 8 and Decimal(food["cash_owed"]) == Decimal("160.00")
    assert Decimal(r["cash_total"]) == Decimal("176.00")   # + 10% buffer


def test_points_item_validation_and_commit_flow(db_session):
    u = _user(db_session)
    c = _client(db_session, u)
    wallet = c.get("/adventures/wallet").json()
    virgin = next(r for r in wallet if r["name"] == "Virgin Atlantic Flying Club")
    t = _new_trip(c)
    flights = next(i for i in t["items"] if i["name"] == "Flights")
    bad = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}", json={"payment": "points"})
    assert bad.status_code == 422
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"payment": "points", "points_program_id": virgin["id"], "points_price": 70000,
                      "cash_copay": "50.00", "unit_cash": "600.00"}).json()
    f = next(i for i in r["items"] if i["name"] == "Flights")
    assert Decimal(f["value_cpp"]) == Decimal("1.64") and f["suggestion"] is None  # no Chase balance
    assert c.post(f"/adventures/trips/{t['id']}/commit").json()["status"] == "committed"
    assert c.post(f"/adventures/trips/{t['id']}/commit").status_code == 409
    pes = db_session.query(models.PlannedExpense).filter_by(user_id=u.id).all()
    assert {pe.name for pe in pes} == {"Lake: Flights", "Lake: Buffer"}


def test_suggestion_appears_and_can_be_attached(db_session):
    c = _client(db_session, _user(db_session))
    wallet = c.get("/adventures/wallet").json()
    chase = next(r for r in wallet if r["name"] == "Chase Ultimate Rewards")
    virgin = next(r for r in wallet if r["name"] == "Virgin Atlantic Flying Club")
    c.patch(f"/adventures/programs/{chase['id']}", json={"balance": 100000})
    partner = next(p for p in c.get("/adventures/partners").json() if p["to_program_id"] == virgin["id"])
    c.patch(f"/adventures/partners/{partner['id']}", json={"bonus_pct": "30"})
    t = _new_trip(c)
    flights = next(i for i in t["items"] if i["name"] == "Flights")
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"payment": "points", "points_program_id": virgin["id"], "points_price": 70000,
                      "unit_cash": "600.00"}).json()
    s = next(i for i in r["items"] if i["name"] == "Flights")["suggestion"]
    assert s["from_program_id"] == chase["id"] and s["source_points"] == 53847
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"transfer_from_program_id": chase["id"], "transfer_points": 53847}).json()
    summary = {row["program_id"]: row for row in r["points_summary"]}
    assert summary[virgin["id"]]["shortfall"] == 0


def test_remove_item_from_template_too(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    dog = next(i for i in t["items"] if i["name"] == "Dog boarding")
    r = c.delete(f"/adventures/trips/{t['id']}/items/{dog['id']}", params={"remove_from_template": "true"})
    assert all(i["name"] != "Dog boarding" for i in r.json()["items"])
    assert all(x["name"] != "Dog boarding" for x in c.get("/adventures/template").json())
    assert len(c.post("/adventures/template/reset").json()) == 18


def test_finish_and_done_is_read_only(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    c.post(f"/adventures/trips/{t['id']}/commit")
    assert c.post(f"/adventures/trips/{t['id']}/finish", json={}).json()["status"] == "done"
    item = t["items"][0]
    assert c.patch(f"/adventures/trips/{t['id']}/items/{item['id']}", json={"unit_cash": "1"}).status_code == 409


def test_fund_endpoints(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    r = c.post(f"/adventures/trips/{t['id']}/fund").json()
    assert r["fund_goal_id"] is not None and Decimal(r["fund_target"]) == Decimal("0.00")
    assert c.delete(f"/adventures/trips/{t['id']}/fund", params={"delete_goal": "true"}).json()["fund_goal_id"] is None


def test_everything_is_user_scoped(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    ca, cb = _client(db_session, a), _client(db_session, b)
    ca.get("/adventures/wallet")
    t = _new_trip(ca)
    pid = ca.get("/adventures/wallet").json()[0]["id"]
    assert cb.get(f"/adventures/trips/{t['id']}").status_code == 404
    assert cb.patch(f"/adventures/programs/{pid}", json={"balance": 1}).status_code == 404
    assert cb.get("/adventures/trips").json() == []
    item = t["items"][0]
    assert cb.delete(f"/adventures/trips/{t['id']}/items/{item['id']}").status_code == 404
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_api.py`
Expected: an ImportError on `backend.routers.adventures`.

- [ ] **Step 3: Append the schemas to `backend/schemas.py`**

```python
# ── Adventures ───────────────────────────────────────────────────────────────

class WalletRow(BaseModel):
    id: int
    name: str
    kind: str
    balance: int
    reserved: int
    available: int
    balance_updated_at: datetime | None
    age_days: int | None
    is_active: bool
    sort_order: int


class ProgramCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: models.LoyaltyKind


class ProgramUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    balance: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    sort_order: int | None = None


class PartnerIn(BaseModel):
    from_program_id: int
    to_program_id: int
    ratio: Decimal = Field(default=Decimal("1"), gt=0)
    bonus_pct: Decimal | None = Field(default=None, ge=0)
    bonus_ends_on: date | None = None


class PartnerUpdate(BaseModel):
    ratio: Decimal | None = Field(default=None, gt=0)
    bonus_pct: Decimal | None = Field(default=None, ge=0)
    bonus_ends_on: date | None = None


class PartnerOut(BaseModel):
    id: int
    from_program_id: int
    from_program_name: str
    to_program_id: int
    to_program_name: str
    ratio: Decimal
    bonus_pct: Decimal | None
    bonus_ends_on: date | None
    bonus_active: bool


class TemplateItemIn(BaseModel):
    category: models.TripCategory
    name: str = Field(min_length=1, max_length=128)
    pricing: models.TripPricing = models.TripPricing.flat
    unit_cash: Decimal | None = Field(default=None, ge=0)


class TemplateItemOut(TemplateItemIn):
    id: int
    sort_order: int
    model_config = ConfigDict(from_attributes=True)


class TripCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    destination: str | None = Field(default=None, max_length=128)
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1, le=20)
    default_card_id: int | None = None


class TripUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    destination: str | None = Field(default=None, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    travelers: int | None = Field(default=None, ge=1, le=20)
    default_card_id: int | None = None
    notes: str | None = None


class TripItemIn(BaseModel):
    category: models.TripCategory | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    pricing: models.TripPricing | None = None
    unit_cash: Decimal | None = Field(default=None, ge=0)
    payment: models.TripPayment | None = None
    points_program_id: int | None = None
    points_price: int | None = Field(default=None, ge=0)
    cash_copay: Decimal | None = Field(default=None, ge=0)
    mix_cash: Decimal | None = Field(default=None, ge=0)
    charge_date: date | None = None
    card_id: int | None = None
    transfer_from_program_id: int | None = None
    transfer_points: int | None = Field(default=None, ge=0)
    is_paid: bool | None = None


class TransferSuggestion(BaseModel):
    from_program_id: int
    from_program_name: str
    source_points: int
    partner_points: int
    bonus_pct: Decimal | None


class TripItemOut(BaseModel):
    id: int
    category: models.TripCategory
    name: str
    pricing: models.TripPricing
    unit_cash: Decimal | None
    payment: models.TripPayment
    points_program_id: int | None
    points_price: int | None
    cash_copay: Decimal
    mix_cash: Decimal | None
    charge_date: date | None
    card_id: int | None
    transfer_from_program_id: int | None
    transfer_points: int | None
    is_paid: bool
    planned_expense_id: int | None
    sort_order: int
    multiplier: int
    is_auto_buffer: bool
    cash_price: Decimal
    cash_owed: Decimal
    points_used: int
    value_cpp: Decimal | None
    suggestion: TransferSuggestion | None


class PointsSummaryRow(BaseModel):
    program_id: int
    name: str
    needed: int
    available: int
    incoming: int
    shortfall: int


class TripSummary(BaseModel):
    id: int
    name: str
    destination: str | None
    start_date: date
    end_date: date
    travelers: int
    status: models.TripStatus
    cash_total: Decimal
    cash_remaining: Decimal
    points_by_program: dict[int, int]
    fund_goal_id: int | None
    fund_current: Decimal | None
    fund_target: Decimal | None


class TripDetail(TripSummary):
    default_card_id: int | None
    notes: str | None
    items: list[TripItemOut]
    points_summary: list[PointsSummaryRow]


class FinishRequest(BaseModel):
    points_used_by_program: dict[int, int] | None = None
    force: bool = False
```

Before appending, check that `schemas.py` already imports `Field`, `ConfigDict`, `date`, `datetime`, `Decimal` and `from backend import models`. Add any import that is missing, at the top of the file.

- [ ] **Step 4: Implement `backend/routers/adventures.py`**

```python
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services import adventures as adv
from backend.services import adventures_lifecycle as life

router = APIRouter(prefix="/adventures", tags=["adventures"])


def _today() -> date:
    # Indirection so tests can pin "today" without patching the date class.
    return date.today()


def _own(db: Session, model, obj_id: int, user: models.User):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def _conflict(e: Exception):
    raise HTTPException(status_code=409, detail=str(e))


def _wallet_row(db, user, program_id):
    return next(r for r in adv.wallet(db, user.id, _today()) if r["id"] == program_id)


def _partner_out(p: models.TransferPartner) -> dict:
    return {"id": p.id, "from_program_id": p.from_program_id, "from_program_name": p.from_program.name,
            "to_program_id": p.to_program_id, "to_program_name": p.to_program.name,
            "ratio": p.ratio, "bonus_pct": p.bonus_pct, "bonus_ends_on": p.bonus_ends_on,
            "bonus_active": adv.bonus_active(p, _today())}


def _summary(db: Session, trip: models.Trip) -> dict:
    total = adv.trip_cash_total(trip)
    remaining = sum((adv.cash_owed(i, trip) for i in trip.items if not i.is_paid), Decimal("0"))
    pts: dict[int, int] = {}
    for i in trip.items:
        if adv.points_used(i) and i.points_program_id:
            pts[i.points_program_id] = pts.get(i.points_program_id, 0) + adv.points_used(i)
    goal = db.get(models.SavingsGoal, trip.fund_goal_id) if trip.fund_goal_id else None
    return {"id": trip.id, "name": trip.name, "destination": trip.destination,
            "start_date": trip.start_date, "end_date": trip.end_date, "travelers": trip.travelers,
            "status": trip.status, "cash_total": total, "cash_remaining": remaining,
            "points_by_program": pts, "fund_goal_id": trip.fund_goal_id,
            "fund_current": goal.current_amount if goal else None,
            "fund_target": goal.target_amount if goal else None}


def _detail(db: Session, trip: models.Trip) -> dict:
    today = _today()
    items = []
    for i in trip.items:
        items.append({
            **{k: getattr(i, k) for k in (
                "id", "category", "name", "pricing", "unit_cash", "payment", "points_program_id",
                "points_price", "cash_copay", "mix_cash", "charge_date", "card_id",
                "transfer_from_program_id", "transfer_points", "is_paid", "planned_expense_id",
                "sort_order")},
            "multiplier": adv.multiplier(i, trip), "is_auto_buffer": adv.is_auto_buffer(i),
            "cash_price": adv.cash_price(i, trip), "cash_owed": adv.cash_owed(i, trip),
            "points_used": adv.points_used(i), "value_cpp": adv.value_cpp(i, trip),
            "suggestion": adv.suggest_transfer(db, i, trip, today),
        })
    return {**_summary(db, trip), "default_card_id": trip.default_card_id, "notes": trip.notes,
            "items": items, "points_summary": list(adv.trip_points_summary(db, trip, today).values())}


def _not_done(trip: models.Trip):
    if trip.status == models.TripStatus.done:
        raise HTTPException(status_code=409, detail="Trip is done and read-only")


def _check_refs(db, user, *, program_ids=(), card_ids=()):
    for pid in program_ids:
        if pid is not None:
            p = db.get(models.LoyaltyProgram, pid)
            if p is None or p.user_id != user.id:
                raise HTTPException(status_code=422, detail="Unknown points program")
    for cid in card_ids:
        if cid is not None:
            c = db.get(models.CreditCard, cid)
            if c is None or c.user_id != user.id:
                raise HTTPException(status_code=422, detail="Unknown card")


# ── Wallet / programs ────────────────────────────────────────────────────────

@router.get("/wallet", response_model=list[schemas.WalletRow])
def get_wallet(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    adv.ensure_adventures_seeded(db, user.id)
    db.commit()
    return adv.wallet(db, user.id, _today())


@router.post("/programs", response_model=schemas.WalletRow, status_code=201)
def create_program(body: schemas.ProgramCreate, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = models.LoyaltyProgram(user_id=user.id, name=body.name, kind=body.kind, balance=0,
                              sort_order=1000)
    db.add(p); db.commit()
    return _wallet_row(db, user, p.id)


@router.patch("/programs/{program_id}", response_model=schemas.WalletRow)
def update_program(program_id: int, body: schemas.ProgramUpdate, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = _own(db, models.LoyaltyProgram, program_id, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    if "balance" in data:
        # Local time, matching date.today() used for age_days (UTC would read
        # "-1 days ago" on US evenings).
        p.balance_updated_at = datetime.now()
    db.commit()
    return _wallet_row(db, user, p.id)


@router.delete("/programs/{program_id}", status_code=204)
def delete_program(program_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = _own(db, models.LoyaltyProgram, program_id, user)
    used = db.query(models.TripItem).filter(
        models.TripItem.user_id == user.id,
        (models.TripItem.points_program_id == p.id) | (models.TripItem.transfer_from_program_id == p.id),
    ).first()
    if used:
        raise HTTPException(status_code=409, detail="Program is used by a trip item")
    db.query(models.TransferPartner).filter(
        models.TransferPartner.user_id == user.id,
        (models.TransferPartner.from_program_id == p.id) | (models.TransferPartner.to_program_id == p.id),
    ).delete(synchronize_session=False)
    db.delete(p); db.commit()
    return Response(status_code=204)


# ── Partners ─────────────────────────────────────────────────────────────────

@router.get("/partners", response_model=list[schemas.PartnerOut])
def list_partners(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    rows = db.query(models.TransferPartner).filter(models.TransferPartner.user_id == user.id).all()
    return [_partner_out(p) for p in sorted(rows, key=lambda p: (p.from_program.name, p.to_program.name))]


@router.post("/partners", response_model=schemas.PartnerOut, status_code=201)
def create_partner(body: schemas.PartnerIn, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    if body.from_program_id == body.to_program_id:
        raise HTTPException(status_code=422, detail="A program can't transfer to itself")
    _check_refs(db, user, program_ids=(body.from_program_id, body.to_program_id))
    if adv._partner_for(db, user.id, body.from_program_id, body.to_program_id):
        raise HTTPException(status_code=409, detail="Partner already exists")
    p = models.TransferPartner(user_id=user.id, **body.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return _partner_out(p)


@router.patch("/partners/{partner_id}", response_model=schemas.PartnerOut)
def update_partner(partner_id: int, body: schemas.PartnerUpdate, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = _own(db, models.TransferPartner, partner_id, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return _partner_out(p)


@router.delete("/partners/{partner_id}", status_code=204)
def delete_partner(partner_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    db.delete(_own(db, models.TransferPartner, partner_id, user)); db.commit()
    return Response(status_code=204)


# ── Template ─────────────────────────────────────────────────────────────────

def _template(db, user):
    return db.query(models.ChecklistTemplateItem).filter(
        models.ChecklistTemplateItem.user_id == user.id).order_by(
        models.ChecklistTemplateItem.sort_order, models.ChecklistTemplateItem.id).all()


@router.get("/template", response_model=list[schemas.TemplateItemOut])
def get_template(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _template(db, user)


@router.post("/template", response_model=schemas.TemplateItemOut, status_code=201)
def add_template_item(body: schemas.TemplateItemIn, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_user)):
    t = models.ChecklistTemplateItem(user_id=user.id, sort_order=1000, **body.model_dump())
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.delete("/template/{template_id}", status_code=204)
def delete_template_item(template_id: int, db: Session = Depends(get_db),
                         user: models.User = Depends(get_current_user)):
    db.delete(_own(db, models.ChecklistTemplateItem, template_id, user)); db.commit()
    return Response(status_code=204)


@router.post("/template/reset", response_model=list[schemas.TemplateItemOut])
def reset_template(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.query(models.ChecklistTemplateItem).filter(
        models.ChecklistTemplateItem.user_id == user.id).delete(synchronize_session=False)
    adv.ensure_adventures_seeded(db, user.id)
    db.commit()
    return _template(db, user)


# ── Trips ────────────────────────────────────────────────────────────────────

@router.get("/trips", response_model=list[schemas.TripSummary])
def list_trips(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trips = db.query(models.Trip).filter(models.Trip.user_id == user.id).order_by(
        models.Trip.start_date).all()
    return [_summary(db, t) for t in trips]


@router.post("/trips", response_model=schemas.TripDetail, status_code=201)
def create_trip(body: schemas.TripCreate, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    _check_refs(db, user, card_ids=(body.default_card_id,))
    adv.ensure_adventures_seeded(db, user.id)
    try:
        trip = life.create_trip_from_template(db, user.id, **body.model_dump())
    except life.LifecycleError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.get("/trips/{trip_id}", response_model=schemas.TripDetail)
def get_trip(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _detail(db, _own(db, models.Trip, trip_id, user))


@router.patch("/trips/{trip_id}", response_model=schemas.TripDetail)
def update_trip(trip_id: int, body: schemas.TripUpdate, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, user, card_ids=(data.get("default_card_id"),))
    for k, v in data.items():
        setattr(trip, k, v)
    if trip.end_date < trip.start_date:
        raise HTTPException(status_code=422, detail="end date is before start date")
    life.sync_trip_planned_expenses(db, trip)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    life.delete_trip(db, _own(db, models.Trip, trip_id, user)); db.commit()
    return Response(status_code=204)


def _validate_item(db: Session, item: models.TripItem):
    """Rolls back before raising so a rejected edit never lingers in the session."""
    problem = None
    if item.payment in (models.TripPayment.points, models.TripPayment.mix):
        if not item.points_program_id or not item.points_price:
            problem = "Points items need a program and a points price"
    if item.transfer_points and not item.transfer_from_program_id:
        problem = "A transfer needs a source program"
    if problem:
        db.rollback()
        raise HTTPException(status_code=422, detail=problem)


@router.post("/trips/{trip_id}/items", response_model=schemas.TripDetail, status_code=201)
def add_item(trip_id: int, body: schemas.TripItemIn, db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    data = body.model_dump(exclude_unset=True, exclude={"is_paid"})
    if not data.get("category") or not data.get("name"):
        raise HTTPException(status_code=422, detail="category and name are required")
    _check_refs(db, user, program_ids=(data.get("points_program_id"), data.get("transfer_from_program_id")),
                card_ids=(data.get("card_id"),))
    item = models.TripItem(user_id=user.id, cash_copay=Decimal("0"), is_paid=False,
                           sort_order=len(trip.items), **data)
    _validate_item(db, item)
    trip.items.append(item)
    db.flush()
    life.sync_trip_planned_expenses(db, trip)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.patch("/trips/{trip_id}/items/{item_id}", response_model=schemas.TripDetail)
def update_item(trip_id: int, item_id: int, body: schemas.TripItemIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    item = _own(db, models.TripItem, item_id, user)
    if item.trip_id != trip.id:
        raise HTTPException(status_code=404, detail="Not found")
    _not_done(trip)
    data = body.model_dump(exclude_unset=True)
    paid = data.pop("is_paid", None)
    _check_refs(db, user, program_ids=(data.get("points_program_id"), data.get("transfer_from_program_id")),
                card_ids=(data.get("card_id"),))
    for k, v in data.items():
        setattr(item, k, v if k != "cash_copay" or v is not None else Decimal("0"))
    _validate_item(db, item)
    db.flush()
    if paid is not None:
        life.set_item_paid(db, trip, item, paid, _today())
    life.sync_trip_planned_expenses(db, trip)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.delete("/trips/{trip_id}/items/{item_id}", response_model=schemas.TripDetail)
def remove_item(trip_id: int, item_id: int, remove_from_template: bool = Query(False),
                db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    item = _own(db, models.TripItem, item_id, user)
    if item.trip_id != trip.id:
        raise HTTPException(status_code=404, detail="Not found")
    _not_done(trip)
    if remove_from_template:
        db.query(models.ChecklistTemplateItem).filter(
            models.ChecklistTemplateItem.user_id == user.id,
            models.ChecklistTemplateItem.category == item.category,
            models.ChecklistTemplateItem.name == item.name,
        ).delete(synchronize_session=False)
    life.delete_item(db, trip, item)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/commit", response_model=schemas.TripDetail)
def commit(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    try:
        life.commit_trip(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/uncommit", response_model=schemas.TripDetail)
def uncommit(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    try:
        life.uncommit_trip(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.get("/trips/{trip_id}/finish-plan", response_model=dict[int, int])
def finish_plan(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return life.finish_plan(db, _own(db, models.Trip, trip_id, user), _today())


@router.post("/trips/{trip_id}/finish", response_model=schemas.TripDetail)
def finish(trip_id: int, body: schemas.FinishRequest, db: Session = Depends(get_db),
           user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    try:
        life.finish_trip(db, trip, body.points_used_by_program, body.force, _today())
    except life.LifecycleError as e:
        db.rollback()
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/fund", response_model=schemas.TripDetail)
def create_fund(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    try:
        life.create_trip_fund(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/fund/update", response_model=schemas.TripDetail)
def update_fund(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    try:
        life.update_trip_fund_target(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.delete("/trips/{trip_id}/fund", response_model=schemas.TripDetail)
def delete_fund(trip_id: int, delete_goal: bool = Query(False), db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    life.remove_trip_fund(db, trip, delete_goal)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)
```

- [ ] **Step 5: Register the router in `backend/main.py`**

Next to the other `from backend.routers import X as X_router_module` lines, add:

```python
from backend.routers import adventures as adventures_router_module
```

After the last `app.include_router(...)` line, add:

```python
app.include_router(adventures_router_module.router)
```

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `cd backend && python3 -m pytest -q tests/test_adventures_api.py`
Expected: `8 passed`.

- [ ] **Step 7: Run the full suite, then commit**

Run: `cd backend && python3 -m pytest -q`. Expected: 0 failures.

```bash
git add backend/schemas.py backend/routers/adventures.py backend/main.py backend/tests/test_adventures_api.py
git commit -m "feat: Adventures API for wallet, partners, template, trips and lifecycle

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — API client, nav, page shell, wallet strip, trip list

**Files:**
- Modify: `frontend/src/api/index.ts`, `frontend/src/lib/navItems.ts`, `frontend/src/App.tsx`
- Create: `frontend/src/pages/Adventures.tsx`, `frontend/src/components/adventures/WalletStrip.tsx`, `frontend/src/components/adventures/types.ts`

**Interfaces:**
- Consumes: the Task 5 HTTP contract.
- Produces: `adventuresApi` (below), the types in `components/adventures/types.ts`, and an `Adventures` page that renders `<TripDetail tripId={selectedId} onClose={...} />`. `TripDetail` is created in Task 7; this task ships a temporary stub so the page compiles.

- [ ] **Step 1: Add the API client to `frontend/src/api/index.ts` (append)**

```ts
// ── Adventures ───────────────────────────────────────────────────────────────
export const adventuresApi = {
  wallet: () => api.get("/adventures/wallet").then((r) => r.data),
  createProgram: (data: object) => api.post("/adventures/programs", data).then((r) => r.data),
  updateProgram: (id: number, data: object) => api.patch(`/adventures/programs/${id}`, data).then((r) => r.data),
  removeProgram: (id: number) => api.delete(`/adventures/programs/${id}`),
  partners: () => api.get("/adventures/partners").then((r) => r.data),
  createPartner: (data: object) => api.post("/adventures/partners", data).then((r) => r.data),
  updatePartner: (id: number, data: object) => api.patch(`/adventures/partners/${id}`, data).then((r) => r.data),
  removePartner: (id: number) => api.delete(`/adventures/partners/${id}`),
  template: () => api.get("/adventures/template").then((r) => r.data),
  resetTemplate: () => api.post("/adventures/template/reset").then((r) => r.data),
  trips: () => api.get("/adventures/trips").then((r) => r.data),
  trip: (id: number) => api.get(`/adventures/trips/${id}`).then((r) => r.data),
  createTrip: (data: object) => api.post("/adventures/trips", data).then((r) => r.data),
  updateTrip: (id: number, data: object) => api.patch(`/adventures/trips/${id}`, data).then((r) => r.data),
  removeTrip: (id: number) => api.delete(`/adventures/trips/${id}`),
  addItem: (id: number, data: object) => api.post(`/adventures/trips/${id}/items`, data).then((r) => r.data),
  updateItem: (id: number, itemId: number, data: object) =>
    api.patch(`/adventures/trips/${id}/items/${itemId}`, data).then((r) => r.data),
  removeItem: (id: number, itemId: number, fromTemplate = false) =>
    api.delete(`/adventures/trips/${id}/items/${itemId}`, { params: { remove_from_template: fromTemplate } }).then((r) => r.data),
  commit: (id: number) => api.post(`/adventures/trips/${id}/commit`).then((r) => r.data),
  uncommit: (id: number) => api.post(`/adventures/trips/${id}/uncommit`).then((r) => r.data),
  finishPlan: (id: number) => api.get(`/adventures/trips/${id}/finish-plan`).then((r) => r.data),
  finish: (id: number, data: object) => api.post(`/adventures/trips/${id}/finish`, data).then((r) => r.data),
  createFund: (id: number) => api.post(`/adventures/trips/${id}/fund`).then((r) => r.data),
  updateFund: (id: number) => api.post(`/adventures/trips/${id}/fund/update`).then((r) => r.data),
  removeFund: (id: number, deleteGoal: boolean) =>
    api.delete(`/adventures/trips/${id}/fund`, { params: { delete_goal: deleteGoal } }).then((r) => r.data),
};
```

- [ ] **Step 2: Create `frontend/src/components/adventures/types.ts`**

```ts
export type Payment = "cash" | "points" | "mix";
export type Pricing = "flat" | "per_day" | "per_night" | "per_person" | "per_person_day";
export type Category = "getting_there" | "staying" | "daily" | "before" | "while_there";
export type TripStatus = "planning" | "committed" | "done";

export interface WalletRow {
  id: number; name: string; kind: "bank" | "airline" | "hotel" | "other";
  balance: number; reserved: number; available: number;
  balance_updated_at: string | null; age_days: number | null; is_active: boolean; sort_order: number;
}
export interface PartnerRow {
  id: number; from_program_id: number; from_program_name: string; to_program_id: number;
  to_program_name: string; ratio: string; bonus_pct: string | null; bonus_ends_on: string | null;
  bonus_active: boolean;
}
export interface Suggestion {
  from_program_id: number; from_program_name: string; source_points: number;
  partner_points: number; bonus_pct: string | null;
}
export interface TripItem {
  id: number; category: Category; name: string; pricing: Pricing; unit_cash: string | null;
  payment: Payment; points_program_id: number | null; points_price: number | null;
  cash_copay: string; mix_cash: string | null; charge_date: string | null; card_id: number | null;
  transfer_from_program_id: number | null; transfer_points: number | null; is_paid: boolean;
  planned_expense_id: number | null; sort_order: number; multiplier: number; is_auto_buffer: boolean;
  cash_price: string; cash_owed: string; points_used: number; value_cpp: string | null;
  suggestion: Suggestion | null;
}
export interface PointsSummaryRow {
  program_id: number; name: string; needed: number; available: number; incoming: number; shortfall: number;
}
export interface TripSummary {
  id: number; name: string; destination: string | null; start_date: string; end_date: string;
  travelers: number; status: TripStatus; cash_total: string; cash_remaining: string;
  points_by_program: Record<string, number>; fund_goal_id: number | null;
  fund_current: string | null; fund_target: string | null;
}
export interface TripDetailData extends TripSummary {
  default_card_id: number | null; notes: string | null; items: TripItem[];
  points_summary: PointsSummaryRow[];
}

export const CATEGORY_LABEL: Record<Category, string> = {
  getting_there: "Getting there", staying: "Staying", daily: "Daily",
  before: "Before you go", while_there: "While there",
};
export const PRICING_HINT: Record<Pricing, string> = {
  flat: "", per_day: "per day", per_night: "per night", per_person: "per person",
  per_person_day: "per person / day",
};
export const pts = (n: number) => n.toLocaleString("en-US");
export const shortDate = (d: string) =>
  new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
```

- [ ] **Step 3: Create `frontend/src/components/adventures/WalletStrip.tsx`**

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowRightLeft, ChevronDown, ChevronUp, X } from "lucide-react";
import { adventuresApi } from "../../api";
import { maskIfHidden, useBalancesHidden } from "../../store/balanceVisibility";
import { PartnerRow, WalletRow, pts } from "./types";

function ProgramChip({ p }: { p: WalletRow }) {
  const qc = useQueryClient();
  const hidden = useBalancesHidden();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(p.balance));
  const save = useMutation({
    mutationFn: () => adventuresApi.updateProgram(p.id, { balance: Math.max(0, parseInt(value || "0", 10)) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["adventures"] }); setEditing(false); },
  });
  const stale = p.age_days !== null && p.age_days > 30;
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 min-w-[180px]">
      <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{p.name}</p>
      {editing ? (
        <div className="flex items-center gap-1 mt-1">
          <input className="input py-0.5 w-28 text-sm" type="number" min={0} value={value} autoFocus
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save.mutate(); if (e.key === "Escape") setEditing(false); }} />
          <button className="btn-primary text-xs px-2 py-0.5" onClick={() => save.mutate()}>Save</button>
        </div>
      ) : (
        <button className="text-lg font-bold tabular-nums text-gray-900 dark:text-gray-100 hover:text-indigo-600"
          title="Edit balance" onClick={() => { setValue(String(p.balance)); setEditing(true); }}>
          {maskIfHidden(hidden, pts(p.balance))}
        </button>
      )}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {p.reserved > 0 && <>{maskIfHidden(hidden, pts(p.available))} available · </>}
        <span className={stale ? "text-amber-600 dark:text-amber-400" : ""}>
          {p.age_days === null ? "never updated" : p.age_days === 0 ? "updated today" : `updated ${p.age_days}d ago`}
        </span>
      </p>
    </div>
  );
}

function PartnersDialog({ programs }: { programs: WalletRow[] }) {
  const qc = useQueryClient();
  const { data: partners = [] } = useQuery<PartnerRow[]>({ queryKey: ["adventures", "partners"], queryFn: adventuresApi.partners });
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => adventuresApi.updatePartner(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adventures"] }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => adventuresApi.removePartner(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["adventures"] }),
  });
  const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [ratio, setRatio] = useState("1");
  const add = useMutation({
    mutationFn: () => adventuresApi.createPartner({ from_program_id: Number(from), to_program_id: Number(to), ratio }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["adventures"] }); setTo(""); },
  });
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button className="btn-secondary text-xs flex items-center gap-1"><ArrowRightLeft size={14} /> Partners & bonuses</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-4 focus:outline-none">
          <div className="card w-full max-w-2xl max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <Dialog.Title className="font-bold text-gray-900 dark:text-gray-100">Transfer partners & bonuses</Dialog.Title>
              <Dialog.Close aria-label="Close" className="text-gray-400 hover:text-gray-600"><X size={18} /></Dialog.Close>
            </div>
            <Dialog.Description className="text-xs text-gray-500 mb-3">
              Ratio is partner points per source point. A bonus applies through its end date; leave the end blank for an open-ended bonus.
            </Dialog.Description>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-gray-500 border-b border-gray-100 dark:border-gray-700">
                <th className="py-1">From → To</th><th>Ratio</th><th>Bonus %</th><th>Ends</th><th /></tr></thead>
              <tbody>
                {partners.map((p) => (
                  <tr key={p.id} className="border-b border-gray-50 dark:border-gray-800">
                    <td className="py-1 pr-2">{p.from_program_name} → {p.to_program_name}</td>
                    <td><input className="input py-0.5 w-16 text-xs" defaultValue={p.ratio}
                      onBlur={(e) => e.target.value !== p.ratio && update.mutate({ id: p.id, data: { ratio: e.target.value } })} /></td>
                    <td><input className={`input py-0.5 w-16 text-xs ${p.bonus_pct && !p.bonus_active ? "line-through text-gray-400" : ""}`}
                      defaultValue={p.bonus_pct ?? ""} placeholder="—"
                      onBlur={(e) => update.mutate({ id: p.id, data: { bonus_pct: e.target.value === "" ? null : e.target.value } })} /></td>
                    <td><input className="input py-0.5 text-xs" type="date" defaultValue={p.bonus_ends_on ?? ""}
                      onBlur={(e) => update.mutate({ id: p.id, data: { bonus_ends_on: e.target.value || null } })} /></td>
                    <td><button aria-label="Remove partner" className="text-gray-400 hover:text-red-500 px-1" onClick={() => remove.mutate(p.id)}><X size={14} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex flex-wrap items-center gap-2 mt-3 text-sm">
              <select className="input py-1 text-sm" value={from} onChange={(e) => setFrom(e.target.value)}>
                <option value="">From…</option>{programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <select className="input py-1 text-sm" value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">To…</option>{programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <input className="input py-1 w-20 text-sm" value={ratio} onChange={(e) => setRatio(e.target.value)} />
              <button className="btn-primary text-xs" disabled={!from || !to || from === to} onClick={() => add.mutate()}>Add partner</button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function WalletStrip() {
  const { data: programs = [] } = useQuery<WalletRow[]>({ queryKey: ["adventures", "wallet"], queryFn: adventuresApi.wallet });
  const [showOthers, setShowOthers] = useState(false);
  const inUse = programs.filter((p) => p.is_active && (p.balance > 0 || p.reserved > 0 || p.kind === "bank"));
  const others = programs.filter((p) => !inUse.includes(p));
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">Points wallet</h3>
        <PartnersDialog programs={programs} />
      </div>
      <div className="flex flex-wrap gap-2">{inUse.map((p) => <ProgramChip key={p.id} p={p} />)}</div>
      {others.length > 0 && (
        <div className="mt-3">
          <button className="text-xs text-indigo-600 flex items-center gap-1" onClick={() => setShowOthers(!showOthers)}>
            {showOthers ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Other programs ({others.length})
          </button>
          {showOthers && <div className="flex flex-wrap gap-2 mt-2">{others.map((p) => <ProgramChip key={p.id} p={p} />)}</div>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/src/pages/Adventures.tsx` and a temporary TripDetail stub**

Create `frontend/src/components/adventures/TripDetail.tsx`. It is a stub, replaced in Task 7:

```tsx
export default function TripDetail({ tripId, onClose }: { tripId: number; onClose: () => void }) {
  return <div className="card">Trip {tripId} <button onClick={onClose}>Close</button></div>;
}
```

Create `frontend/src/pages/Adventures.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plane, Plus } from "lucide-react";
import { adventuresApi, cardsApi } from "../api";
import { fmt } from "../lib/utils";
import { maskIfHidden, useBalancesHidden } from "../store/balanceVisibility";
import WalletStrip from "../components/adventures/WalletStrip";
import TripDetail from "../components/adventures/TripDetail";
import { TripSummary, WalletRow, pts, shortDate } from "../components/adventures/types";

const STATUS_PILL: Record<string, string> = {
  planning: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  committed: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300",
  done: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
};

function NewTripForm({ onCreated }: { onCreated: (id: number) => void }) {
  const qc = useQueryClient();
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const [f, setF] = useState({ name: "", destination: "", start_date: "", end_date: "", travelers: "2", default_card_id: "" });
  const create = useMutation({
    mutationFn: () => adventuresApi.createTrip({
      name: f.name, destination: f.destination || null, start_date: f.start_date, end_date: f.end_date,
      travelers: parseInt(f.travelers || "1", 10), default_card_id: f.default_card_id ? Number(f.default_card_id) : null,
    }),
    onSuccess: (trip) => { qc.invalidateQueries({ queryKey: ["adventures"] }); onCreated(trip.id); },
  });
  const ok = f.name && f.start_date && f.end_date && f.end_date >= f.start_date;
  return (
    <div className="card grid grid-cols-1 md:grid-cols-6 gap-2 items-end text-sm">
      <label className="md:col-span-2">Name<input className="input w-full" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      <label>Destination<input className="input w-full" value={f.destination} onChange={(e) => setF({ ...f, destination: e.target.value })} /></label>
      <label>Start<input type="date" className="input w-full" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
      <label>End<input type="date" className="input w-full" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></label>
      <label>Travelers<input type="number" min={1} className="input w-full" value={f.travelers} onChange={(e) => setF({ ...f, travelers: e.target.value })} /></label>
      <label className="md:col-span-2">Charge to
        <select className="input w-full" value={f.default_card_id} onChange={(e) => setF({ ...f, default_card_id: e.target.value })}>
          <option value="">Checking</option>{cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <button className="btn-primary md:col-span-1" disabled={!ok || create.isPending} onClick={() => create.mutate()}>Create</button>
    </div>
  );
}

export default function Adventures() {
  const hidden = useBalancesHidden();
  const { data: trips = [] } = useQuery<TripSummary[]>({ queryKey: ["adventures", "trips"], queryFn: adventuresApi.trips });
  const { data: programs = [] } = useQuery<WalletRow[]>({ queryKey: ["adventures", "wallet"], queryFn: adventuresApi.wallet });
  const [selected, setSelected] = useState<number | null>(null);
  const [showNew, setShowNew] = useState(false);
  const progName = (id: string) => programs.find((p) => String(p.id) === id)?.name ?? "points";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Plane size={20} /> Adventures</h2>
        <button className="btn-primary text-sm flex items-center gap-1" onClick={() => setShowNew(!showNew)}><Plus size={14} /> New adventure</button>
      </div>
      <WalletStrip />
      {showNew && <NewTripForm onCreated={(id) => { setShowNew(false); setSelected(id); }} />}
      {trips.length === 0 && !showNew && (
        <div className="card text-center text-sm text-gray-400 py-8">No adventures yet. Plan one to see what it really costs in cash and points.</div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {trips.map((t) => (
          <button key={t.id} onClick={() => setSelected(selected === t.id ? null : t.id)}
            className={`card text-left ${selected === t.id ? "ring-2 ring-indigo-500" : ""}`}>
            <div className="flex items-center justify-between">
              <span className="font-semibold text-gray-900 dark:text-gray-100">{t.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_PILL[t.status]}`}>{t.status}</span>
            </div>
            <p className="text-xs text-gray-500">{t.destination ? `${t.destination} · ` : ""}{shortDate(t.start_date)} – {shortDate(t.end_date)} · {t.travelers} traveler{t.travelers === 1 ? "" : "s"}</p>
            <p className="text-sm mt-2">Cash remaining <strong className="tabular-nums">{maskIfHidden(hidden, fmt(t.cash_remaining))}</strong></p>
            {Object.entries(t.points_by_program).map(([pid, n]) => (
              <p key={pid} className="text-xs text-gray-500">{maskIfHidden(hidden, pts(n))} {progName(pid)}</p>
            ))}
            {t.fund_goal_id && t.fund_target && (
              <p className="text-xs text-gray-500 mt-1">Fund {maskIfHidden(hidden, fmt(t.fund_current ?? "0"))} / {maskIfHidden(hidden, fmt(t.fund_target))}</p>
            )}
          </button>
        ))}
      </div>
      {selected !== null && <TripDetail tripId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
```

- [ ] **Step 5: Add the nav entry and route**

In `frontend/src/lib/navItems.ts`, add `Plane` to the lucide-react import list. Then add this to the `planning` items after Scenarios:

```ts
      { to: "/adventures", icon: Plane, label: "Adventures" },
```

In `frontend/src/App.tsx`, add `import Adventures from "./pages/Adventures";` next to the other page imports, and add this route after the scenarios route:

```tsx
          <Route path="adventures" element={<Adventures />} />
```

- [ ] **Step 6: Run the type-check gate**

Run: `cd frontend && bunx tsc -b --force 2>&1 | grep -oE "^src/[^(]+" | sort | uniq -c`
Expected: identical to the baseline of 39 errors in 11 files. No line may mention `Adventures.tsx` or `components/adventures/`. If `cardsApi` isn't exported under that name, check `src/api/index.ts` and use the exported name.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/lib/navItems.ts frontend/src/App.tsx frontend/src/pages/Adventures.tsx frontend/src/components/adventures/
git commit -m "feat: Adventures page with points wallet, partners dialog and trip list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Frontend — trip detail

**Files:**
- Modify (replace stub): `frontend/src/components/adventures/TripDetail.tsx`

**Interfaces:**
- Consumes: `adventuresApi`, the types from Task 6, `HowCalculated` (`import HowCalculated, { type Explanation } from "../HowCalculated"`), and `cardsApi.list`.
- Produces: `export default function TripDetail({ tripId, onClose }: { tripId: number; onClose: () => void })`

- [ ] **Step 1: Replace `TripDetail.tsx`**

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";
import { adventuresApi, cardsApi } from "../../api";
import { fmt } from "../../lib/utils";
import { maskIfHidden, useBalancesHidden } from "../../store/balanceVisibility";
import HowCalculated, { type Explanation } from "../HowCalculated";
import {
  CATEGORY_LABEL, Category, PRICING_HINT, Payment, TripDetailData, TripItem, WalletRow, pts, shortDate,
} from "./types";

const CATEGORIES: Category[] = ["getting_there", "staying", "daily", "before", "while_there"];

function ItemRow({ trip, item, programs, onChange }: {
  trip: TripDetailData; item: TripItem; programs: WalletRow[]; onChange: (d: TripDetailData) => void;
}) {
  const hidden = useBalancesHidden();
  const [err, setErr] = useState<string | null>(null);
  const done = trip.status === "done";
  const save = useMutation({
    mutationFn: (data: object) => adventuresApi.updateItem(trip.id, item.id, data),
    onSuccess: (d) => { setErr(null); onChange(d); },
    onError: (e: any) => setErr(e?.response?.data?.detail ?? "Couldn't save"),
  });
  const remove = useMutation({
    mutationFn: (fromTemplate: boolean) => adventuresApi.removeItem(trip.id, item.id, fromTemplate),
    onSuccess: onChange,
  });
  const setPayment = (payment: Payment) => {
    if (payment === "cash") return save.mutate({ payment });
    if (!item.points_program_id || !item.points_price) {
      // Need a program and price first: switch locally by sending both with a sensible default.
      const first = programs.find((p) => p.kind !== "bank") ?? programs[0];
      return save.mutate({ payment, points_program_id: item.points_program_id ?? first?.id, points_price: item.points_price || 1 });
    }
    save.mutate({ payment });
  };
  const blurNum = (field: string, current: string | number | null) => (e: React.FocusEvent<HTMLInputElement>) => {
    const v = e.target.value.trim();
    if (v === String(current ?? "")) return;
    save.mutate({ [field]: v === "" ? null : v });
  };
  return (
    <div className={`py-2 border-b border-gray-50 dark:border-gray-800 ${item.is_paid ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-gray-900 dark:text-gray-100 w-44 truncate" title={item.name}>{item.name}</span>
        <div className="inline-flex rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden text-xs" role="group" aria-label={`${item.name} payment`}>
          {(["cash", "points", "mix"] as Payment[]).map((p) => (
            <button key={p} disabled={done} onClick={() => setPayment(p)}
              className={`px-2 py-0.5 ${item.payment === p ? "bg-indigo-600 text-white" : "text-gray-600 dark:text-gray-300"}`}>{p}</button>
          ))}
        </div>
        <label className="text-xs text-gray-500 flex items-center gap-1">$
          <input className="input py-0.5 w-24 text-xs" disabled={done} defaultValue={item.unit_cash ?? ""}
            placeholder={item.is_auto_buffer ? "10% auto" : "0"} onBlur={blurNum("unit_cash", item.unit_cash)} />
          {PRICING_HINT[item.pricing] && <span>{PRICING_HINT[item.pricing]} ×{item.multiplier}</span>}
        </label>
        {item.payment !== "cash" && (
          <>
            <select className="input py-0.5 text-xs" disabled={done} value={item.points_program_id ?? ""}
              onChange={(e) => save.mutate({ points_program_id: Number(e.target.value) })}>
              {programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <label className="text-xs text-gray-500 flex items-center gap-1">pts
              <input className="input py-0.5 w-24 text-xs" disabled={done} defaultValue={item.points_price ?? ""}
                onBlur={blurNum("points_price", item.points_price)} /></label>
            <label className="text-xs text-gray-500 flex items-center gap-1">taxes $
              <input className="input py-0.5 w-20 text-xs" disabled={done} defaultValue={item.cash_copay}
                onBlur={blurNum("cash_copay", item.cash_copay)} /></label>
            {item.payment === "mix" && (
              <label className="text-xs text-gray-500 flex items-center gap-1">+ cash $
                <input className="input py-0.5 w-20 text-xs" disabled={done} defaultValue={item.mix_cash ?? ""}
                  onBlur={blurNum("mix_cash", item.mix_cash)} /></label>
            )}
            {item.value_cpp && <span className="badge-blue">{item.value_cpp}¢/pt</span>}
          </>
        )}
        <span className="ml-auto font-semibold tabular-nums">{maskIfHidden(hidden, fmt(item.cash_owed))}</span>
        {trip.status === "committed" && (
          <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={item.is_paid}
            onChange={(e) => save.mutate({ is_paid: e.target.checked })} /> paid</label>
        )}
        {!done && (
          <button aria-label={`Remove ${item.name}`} className="text-gray-400 hover:text-red-500"
            onClick={() => remove.mutate(window.confirm(`Also remove "${item.name}" from your checklist template for future trips?`))}>
            <X size={14} />
          </button>
        )}
      </div>
      {item.transfer_from_program_id && item.transfer_points ? (
        <p className="text-xs text-indigo-600 dark:text-indigo-300 mt-1">
          Transfer {maskIfHidden(hidden, pts(item.transfer_points))} from {programs.find((p) => p.id === item.transfer_from_program_id)?.name}
          {!done && <button className="ml-2 underline" onClick={() => save.mutate({ transfer_from_program_id: null, transfer_points: null })}>detach</button>}
        </p>
      ) : item.suggestion && !done ? (
        <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
          Short on points: transfer {maskIfHidden(hidden, pts(item.suggestion.source_points))} {item.suggestion.from_program_name} →{" "}
          {maskIfHidden(hidden, pts(item.suggestion.partner_points))}{item.suggestion.bonus_pct ? ` (+${parseFloat(item.suggestion.bonus_pct)}% bonus)` : ""}
          <button className="ml-2 underline" onClick={() => save.mutate({
            transfer_from_program_id: item.suggestion!.from_program_id, transfer_points: item.suggestion!.source_points,
          })}>attach</button>
        </p>
      ) : null}
      {err && <p className="text-xs text-red-500 mt-1">{err}</p>}
    </div>
  );
}

function AddItem({ trip, category, onChange }: { trip: TripDetailData; category: Category; onChange: (d: TripDetailData) => void }) {
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => adventuresApi.addItem(trip.id, { category, name }),
    onSuccess: (d) => { setName(""); onChange(d); },
  });
  if (trip.status === "done") return null;
  return (
    <div className="flex gap-2 mt-2">
      <input className="input py-0.5 text-xs flex-1" placeholder="Add an item…" value={name} onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && name.trim() && add.mutate()} />
      <button className="btn-secondary text-xs" disabled={!name.trim()} onClick={() => add.mutate()}>Add</button>
    </div>
  );
}

export default function TripDetail({ tripId, onClose }: { tripId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const hidden = useBalancesHidden();
  const key = ["adventures", "trip", tripId];
  const { data: trip } = useQuery<TripDetailData>({ queryKey: key, queryFn: () => adventuresApi.trip(tripId) });
  const { data: programs = [] } = useQuery<WalletRow[]>({ queryKey: ["adventures", "wallet"], queryFn: adventuresApi.wallet });
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const [err, setErr] = useState<string | null>(null);
  const onChange = (d: TripDetailData) => {
    qc.setQueryData(key, d);
    qc.invalidateQueries({ queryKey: ["adventures", "trips"] });
    qc.invalidateQueries({ queryKey: ["adventures", "wallet"] });
    qc.invalidateQueries({ queryKey: ["forecast"] });
    qc.invalidateQueries({ queryKey: ["goals"] });
  };
  const act = useMutation({
    mutationFn: (fn: () => Promise<TripDetailData>) => fn(),
    onSuccess: (d) => { setErr(null); onChange(d); },
    onError: (e: any) => setErr(e?.response?.data?.detail ?? "Something went wrong"),
  });
  const del = useMutation({
    mutationFn: () => adventuresApi.removeTrip(tripId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["adventures"] }); qc.invalidateQueries({ queryKey: ["forecast"] }); onClose(); },
  });
  if (!trip) return <div className="card text-sm text-gray-400">Loading…</div>;

  const owing = trip.items.filter((i) => parseFloat(i.cash_owed) > 0 && !i.is_paid).length;
  const finish = async () => {
    const plan: Record<string, number> = await adventuresApi.finishPlan(trip.id);
    const lines = Object.entries(plan).map(([pid, d]) => `${programs.find((p) => String(p.id) === pid)?.name}: ${d > 0 ? "+" : ""}${pts(d)}`);
    if (!window.confirm(`Finish this trip and update balances?\n\n${lines.join("\n") || "No points change."}`)) return;
    try {
      onChange(await adventuresApi.finish(trip.id, {}));
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? "Couldn't finish";
      if (window.confirm(`${msg}\n\nFinish anyway and allow a negative balance?`)) onChange(await adventuresApi.finish(trip.id, { force: true }));
    }
  };
  const cashExplain: Explanation = {
    title: "Trip cash", result: trip.cash_total,
    rows: [
      ...trip.items.filter((i) => parseFloat(i.cash_owed) > 0).map((i, idx) => ({
        op: (idx === 0 ? "start" : "add") as "start" | "add", label: i.name, amount: i.cash_owed,
      })),
      { op: "result" as const, label: "Trip cash", amount: trip.cash_total },
    ],
  };

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-bold text-gray-900 dark:text-gray-100">{trip.name}</h3>
          <p className="text-xs text-gray-500">{trip.destination ? `${trip.destination} · ` : ""}{shortDate(trip.start_date)} – {shortDate(trip.end_date)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label>Start <input type="date" className="input py-0.5 text-xs" disabled={trip.status === "done"} defaultValue={trip.start_date}
            onBlur={(e) => e.target.value !== trip.start_date && act.mutate(() => adventuresApi.updateTrip(trip.id, { start_date: e.target.value }))} /></label>
          <label>End <input type="date" className="input py-0.5 text-xs" disabled={trip.status === "done"} defaultValue={trip.end_date}
            onBlur={(e) => e.target.value !== trip.end_date && act.mutate(() => adventuresApi.updateTrip(trip.id, { end_date: e.target.value }))} /></label>
          <label>Travelers <input type="number" min={1} className="input py-0.5 w-14 text-xs" disabled={trip.status === "done"} defaultValue={trip.travelers}
            onBlur={(e) => Number(e.target.value) !== trip.travelers && act.mutate(() => adventuresApi.updateTrip(trip.id, { travelers: Number(e.target.value) }))} /></label>
          <label>Charge to <select className="input py-0.5 text-xs" disabled={trip.status === "done"} value={trip.default_card_id ?? ""}
            onChange={(e) => act.mutate(() => adventuresApi.updateTrip(trip.id, { default_card_id: e.target.value ? Number(e.target.value) : null }))}>
            <option value="">Checking</option>{cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          {trip.status === "planning" && (
            <button className="btn-primary text-xs" title={`Adds ${owing} one-off${owing === 1 ? "" : "s"} to the Forecast`}
              onClick={() => window.confirm(`Commit to forecast? This adds ${owing} planned one-off${owing === 1 ? "" : "s"} to the Forecast.`) && act.mutate(() => adventuresApi.commit(trip.id))}>
              Commit to forecast</button>
          )}
          {trip.status === "committed" && (
            <>
              <button className="btn-secondary text-xs" onClick={() => act.mutate(() => adventuresApi.uncommit(trip.id))}>Back to planning</button>
              <button className="btn-primary text-xs" onClick={finish}>Done</button>
            </>
          )}
          <button aria-label="Delete trip" className="text-gray-400 hover:text-red-500"
            onClick={() => window.confirm(`Delete "${trip.name}"? Its unpaid one-offs leave the Forecast too.`) && del.mutate()}><Trash2 size={16} /></button>
          <button aria-label="Close trip" className="text-gray-400 hover:text-gray-600" onClick={onClose}><X size={18} /></button>
        </div>
      </div>
      {err && <p className="text-sm text-red-500">{err}</p>}

      <div className="flex flex-wrap items-center gap-4 text-sm rounded-lg bg-gray-50 dark:bg-gray-800/60 px-3 py-2 sticky top-0 z-10">
        <span className="flex items-center gap-1">Cash <strong className="tabular-nums">{maskIfHidden(hidden, fmt(trip.cash_total))}</strong>
          <HowCalculated title="Trip cash" explanations={[cashExplain]} /></span>
        <span>Remaining <strong className="tabular-nums">{maskIfHidden(hidden, fmt(trip.cash_remaining))}</strong></span>
        {trip.points_summary.map((s) => (
          <span key={s.program_id} className={s.shortfall > 0 ? "text-red-600" : ""}>
            {s.name}: {maskIfHidden(hidden, pts(s.needed))}{s.shortfall > 0 && <> · short {maskIfHidden(hidden, pts(s.shortfall))}</>}
          </span>
        ))}
        <span className="ml-auto text-xs">
          {trip.fund_goal_id ? (
            <>Fund {maskIfHidden(hidden, fmt(trip.fund_current ?? "0"))} / {maskIfHidden(hidden, fmt(trip.fund_target ?? "0"))}
              {trip.status !== "done" && <>
                <button className="ml-2 underline" onClick={() => act.mutate(() => adventuresApi.updateFund(trip.id))}>Update fund target</button>
                <button className="ml-2 underline" onClick={() => act.mutate(() => adventuresApi.removeFund(trip.id, window.confirm("Also delete the savings goal?")))}>Remove fund</button>
              </>}</>
          ) : trip.status !== "done" ? (
            <button className="underline" onClick={() => act.mutate(() => adventuresApi.createFund(trip.id))}>Set up a trip fund</button>
          ) : null}
        </span>
      </div>

      {CATEGORIES.map((cat) => {
        const items = trip.items.filter((i) => i.category === cat);
        return (
          <div key={cat}>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">{CATEGORY_LABEL[cat]}</p>
            {items.map((i) => <ItemRow key={`${i.id}-${i.payment}-${i.unit_cash}-${i.points_price}`} trip={trip} item={i} programs={programs} onChange={onChange} />)}
            <AddItem trip={trip} category={cat} onChange={onChange} />
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Run the type-check gate**

Run: `cd frontend && bunx tsc -b --force 2>&1 | grep -oE "^src/[^(]+" | sort | uniq -c`
Expected: the baseline of 39 errors in 11 files, with none in the adventures files. If `HowCalculated` doesn't export the `Explanation` type under that name, read the file and use its exported name.

- [ ] **Step 3: Run the browser check in the Interceptor test profile**

Run `bash ~/.claude/skills/Interceptor/Tools/PreflightIsolation.sh`. The Interceptor CLI may need the sandbox disabled. Then use:

`source ~/.claude/LIFEOS/USER/CUSTOMIZATIONS/SKILLS/Interceptor/preferences.env; interceptor eval --main --context "$INTERCEPTOR_TEST_CONTEXT_ID" "<js>"`

Run these checks against `http://localhost:5173/adventures`:
1. "Adventures" appears in the sidebar, and the wallet shows "Chase Ultimate Rewards".
2. Create a trip called "Interceptor test trip" (dates next year, 2 travelers, charge to the first card). It shows 18 items.
3. Set Lodging to $100, and switch Flights to points with a program and a points price. A ¢/pt badge appears.
4. Commit. Then GET `/forecast/planned` (or whatever the Planned One-Offs list endpoint is, see `plannedExpensesApi` in `api/index.ts`) and confirm the "Interceptor test trip: Lodging" one-off exists.
5. Mark Lodging paid, then use Back to planning. The unpaid one-offs are gone.
6. **Delete the test trip** so no test data stays in the user's live DB. Confirm `GET /adventures/trips` no longer lists it.
7. No console errors were captured. Never use screencapture or osascript.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/adventures/TripDetail.tsx
git commit -m "feat: Adventures trip detail with cash/points items, transfers, commit and fund

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/USER_GUIDE.md`, `docs/PRIVACY.md`

- [ ] **Step 1: Add an Adventures section to `docs/USER_GUIDE.md`**

Match the heading levels the file already uses. Add a section titled `## Adventures (trip planning with points)` that covers:
- **The points wallet:** typing balances and the "updated N days ago" age.
- **Partners & bonuses:** the ratio, and the bonus that ends on its end date.
- **New adventure:** the checklist template, and removing an item from the trip vs. from the template.
- **Cash / points / mix:** taxes and fees count as cash, and ¢/pt = (cash − taxes) ÷ points.
- **Transfer suggestions and Attach.**
- **Commit to forecast:** each unpaid item that owes cash becomes a Planned One-Off on its charge date and card. Editing a committed trip updates them, and Back to planning removes them.
- **Paid** and **Done:** what each does to the one-offs and to points balances.
- **The optional trip fund:** a Goal targeted 7 days before the trip, updated only when you press "Update fund target".

- [ ] **Step 2: Add this line to `docs/PRIVACY.md`, in its "what's stored" list**

```markdown
- **Adventures:** trips, checklist items, loyalty-program balances and transfer partners you enter. Stored only in the local database; nothing is looked up online.
```

- [ ] **Step 3: Commit**

```bash
git add docs/USER_GUIDE.md docs/PRIVACY.md
git commit -m "docs: Adventures user guide and privacy note

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
