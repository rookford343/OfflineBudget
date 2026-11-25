# Change History — Safety Margin Full Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Safety Margin headline a full itemized "receipt" (old value, new value, named causes, reconciling math lines) in the daily email's closing "What changed since last email" section, while the other four headlines keep today's plain delta-only line with no cause list.

**Architecture:** The math this needs already exists and is already correct in production — it powers the in-app "What changed" popup via `metric_diff.math_lines()`/`explain_change()`. This plan plumbs that same math through the email's `explain_since_last_email()` for one specific metric key, then gives `summary_generator.py`'s closing section a second rendering path (a dedicated receipt block) alongside its existing flattened, deduped reasons list — splitting on whether a figure's old/new value was captured, not on its key, so every existing test stays green by construction.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend only — no frontend change). `uv` for Python.

**Spec:** No separate design doc — Dan explicitly chose to skip one for this change (brainstormed in chat 2026-11-16, approved as a "small change"). The settled scope, in his own words:
- The complaint: the email's closing section flattens causes across every moved headline into one shared, deduped list tagged "Moved: X, Y, Z" — "not easy to read through the math of what changed and why." He wants it to read "like line items on a receipt."
- "The exact dollar breakdown with a clean read" — reuse the existing popup's math; do not invent new attribution logic.
- Asked whether to fully itemize all five headlines or cap it: **"Cap it."**
- Asked which headline(s) get the full treatment: **"Safety margin get full receipt"** — only Safety Margin (`safety_margin_week`, the figure the email already tracks under `SINCE_MARGIN`). The other four headlines (Spendable this week, Lowest next month, 3-month low, Checking balance) keep today's existing behavior unchanged — a plain delta-only line, no cause list, which was my proposed default and Dan did not object to it.
- Must land in both the HTML and plain-text email bodies.
- Must not touch: the bold headline block at the top of the email, the in-app popup (`frontend/src/components/WhatChanged.tsx`, `/history` router, `statement_for()`), or the other four headlines' existing rendering.

## Global Constraints

- Backend only, no frontend changes.
- `uv run --locked`; `ruff check` must stay clean; coverage floor in `backend/.coveragerc` never lowered.
- No new money math: old/new values come straight from readings `metric_history.py` already collects, and the reconciling math reuses `metric_diff.math_lines()` verbatim — this plan only adds plumbing and rendering.
- Commits go directly to `main` — no feature branches, no git worktree (this repo's convention).
- No real account/card names, balances, or amounts in commits or test fixtures — invented placeholders only (matches existing fixtures in `backend/tests/test_email_since_lines.py` and `test_history_statement.py`).
- A failure computing the receipt (a malformed stored `explain_json`, a `math_lines()` exception) must never break the daily email send — mirror the existing defensive pattern in `metric_diff._statement_math()`.

## Review Focus

- **Safety Margin didn't move since the last email.** No receipt section should render at all (same as today, when nothing moved) — no stray empty block. Covered in Task 2.
- **The receipt's math computation fails** (bad stored `explain_json`, or any exception from `math_lines()`). The figure's causes and old/new values must still show; only the reconciling math list is dropped. Covered in Task 1, which catches the failure before it ever reaches the email renderer.
- **A batch of causes under the receipt is large** (many pending charges moving Safety Margin at once). The receipt's own cause list must cap and say "and N more," the same way the existing flattened list already does — an uncapped receipt could make a single figure's section longer than the whole rest of the email. Covered in Task 2.
- **Safety Margin's cause/merchant text contains characters that need HTML-escaping** (a merchant name with `<`/`&`). The receipt's HTML body must escape them exactly like the existing flattened list already does. Covered in Task 2.
- **Safety Margin's own parent figure (`safety_margin`, the monthly figure) is also present in the explained changes.** The receipt must show Safety Margin's own real causes, never collapse to the existing "Same causes as `safety_margin`" placeholder that normal (non-receipt) derived figures get — the whole point of a receipt is its own detail. Covered in Task 1.

---

### Task 1: Receipt data in `metric_diff.explain_since_last_email`

**Files:**
- Modify: `backend/services/metric_diff.py` — `EmailChange` dataclass (~line 464), `explain_since_last_email()` (~line 680)
- Test: `backend/tests/test_email_since_lines.py` (add to the existing file; it already covers this function)

**Interfaces:**
- Consumes: nothing new — reuses `math_lines(old: schemas.Explanation, new: schemas.Explanation) -> list[schemas.HistoryMathLine]` and `_causes_or_fallback()`, both already in this file.
- Produces: `EmailChange.old_value: Decimal | None` (default `None`), `EmailChange.new_value: Decimal | None` (default `None`), `EmailChange.math: tuple[schemas.HistoryMathLine, ...]` (default `()`); all three populated only for a key passed in the new `receipt_keys` parameter. `explain_since_last_email(..., receipt_keys: frozenset[str] = frozenset())` — a new keyword-only parameter, empty by default so every existing caller and test is unaffected.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_email_since_lines.py — extend the existing file

def _explained(db, user, keys=None, receipt_keys=frozenset()):
    from backend.services.metric_diff import explain_since_last_email
    return explain_since_last_email(
        db, user, collect_headline_metrics(db, user, TODAY), keys=keys, receipt_keys=receipt_keys,
    )

def test_receipt_key_carries_old_new_and_math(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch)
    changes = _explained(db_session, user, receipt_keys=frozenset({"safety_margin_week"}))
    change = next(c for c in changes if c.key == "safety_margin_week")
    assert change.old_value is not None and change.new_value is not None
    assert change.new_value - change.old_value == change.delta
    assert len(change.math) > 0

def test_non_receipt_keys_keep_the_old_defaults(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch, pending=1)
    _set_previous(db_session, user, "next_month_minimum", D("-16.00"))
    changes = _explained(db_session, user, receipt_keys=frozenset({"safety_margin_week"}))
    other = next(c for c in changes if c.key == "next_month_minimum")
    assert other.old_value is None and other.new_value is None and other.math == ()

def test_receipt_key_keeps_its_own_causes_even_with_its_parent_also_listed(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch)
    _set_previous(db_session, user, "safety_margin", D("-400.00"))
    changes = {c.key: c for c in _explained(db_session, user, receipt_keys=frozenset({"safety_margin_week"}))}
    child = changes["safety_margin_week"]
    assert child.causes[0].parent_key == ""
    assert not any(c.text.startswith("Same causes as") for c in child.causes)

def test_a_broken_math_lines_call_drops_only_the_math(db_session, monkeypatch):
    from backend.services import metric_diff
    user = _moved_world(db_session, monkeypatch)

    def boom(*a, **kw):
        raise ValueError("bad receipt")

    monkeypatch.setattr(metric_diff, "math_lines", boom)
    changes = _explained(db_session, user, receipt_keys=frozenset({"safety_margin_week"}))
    change = next(c for c in changes if c.key == "safety_margin_week")
    assert change.old_value is not None and change.new_value is not None
    assert change.math == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_email_since_lines.py -k "receipt" -v`
Expected: FAIL — `explain_since_last_email() got an unexpected keyword argument 'receipt_keys'`

- [ ] **Step 3: Add the fields and the parameter**

In `EmailChange`, add the three fields with the defaults given in Interfaces above (after the existing `causes` field).

In `explain_since_last_email`, add the keyword-only parameter `receipt_keys: frozenset[str] = frozenset()`. In the existing loop that builds `moved`, capture `old_value = Decimal(str(prev.value))` (replacing the inline `Decimal(str(prev.value))` currently used only for the delta calculation) and, when `reading.key in receipt_keys`, compute `math` by calling `math_lines()` on `schemas.Explanation.model_validate_json(prev.explain_json)` (old) and `reading.explain` (new — already a live `schemas.Explanation`, no parsing needed), wrapped in the same `(ValueError, KeyError, TypeError, AttributeError, ArithmeticError)` catch `_statement_math()` already uses a few hundred lines up in this file, falling back to `()` on failure. Carry `old_value` and `math` alongside the existing `(reading, delta, causes)` tuple into `moved`.

In the final loop that builds `out`: skip the `_ancestor_key()` substitution entirely when `reading.key in receipt_keys` (keep the real causes), and set `old_value`/`new_value`/`math` on the `EmailChange` only for keys in `receipt_keys` (`new_value` is simply `reading.value`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_email_since_lines.py -v`
Expected: all pass, including every pre-existing test in this file unchanged

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/metric_diff.py backend/tests/test_email_since_lines.py
git commit -m "feat: optional full-receipt data (old/new value, math lines) in explain_since_last_email"
```

---

### Task 2: Safety Margin's receipt block in the daily email

**Files:**
- Modify: `backend/services/summary_generator.py` — near `SINCE_KEYS` (~line 87), `_changes_section()` (~line 740)
- Modify: `backend/main.py` — the `explain_since_last_email(...)` call (~line 206)
- Test: `backend/tests/test_email_since_lines.py`

**Interfaces:**
- Consumes: `EmailChange.old_value`/`new_value`/`math` (Task 1).
- Produces: `summary_generator.SINCE_RECEIPT_KEYS: frozenset[str]` — the set of keys that get the full-receipt treatment, consumed by `main.py`'s call site.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_email_since_lines.py — extend the existing file

def _receipt_chg(key, label, causes, math, old, new, delta):
    from backend.services.metric_diff import EmailChange
    return EmailChange(key=key, label=label, delta=D(delta), causes=causes,
                        old_value=D(old), new_value=D(new), math=tuple(math))

def _math_line(label, old, new, parts=()):
    from backend.schemas import HistoryMathLine, HistoryMathPart
    return HistoryMathLine(label=label, old=D(old) if old is not None else None,
                            new=D(new) if new is not None else None,
                            parts=[HistoryMathPart(label=n, delta=D(d)) for n, d in parts])

def test_receipt_figure_gets_its_own_breakdown(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    receipt = _receipt_chg(
        "safety_margin_week", "Safety Margin (this week)",
        [_cause(text="new pending Test Visa charge")],
        [_math_line("Pending charges", "0.00", "400.00")],
        old="1234.56", new="834.56", delta="-400.00",
    )
    html, text = generate_daily_summary(db_session, user, since_changes=[receipt])
    block = html[html.index(CHANGES_TITLE):]
    assert "$1,234.56" in block and "$834.56" in block and "−$400.00" in block
    assert "How the number moved" in block and "new pending Test Visa charge" in block
    tail = text[text.index(CHANGES_TITLE.upper()):]
    assert "How the number moved" in tail and "$1,234.56" in tail and "$834.56" in tail

def test_receipt_figure_is_excluded_from_the_shared_reasons_list(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    shared = _cause(text="Only normal reason")
    other = _chg("k1", "Figure A", [shared])
    receipt = _receipt_chg("safety_margin_week", "Safety Margin (this week)", [_cause(text="receipt-only reason")],
                           [], old="100.00", new="50.00", delta="-50.00")
    html, text = generate_daily_summary(db_session, user, since_changes=[other, receipt])
    top_line = text[text.index(CHANGES_TITLE.upper()):].splitlines()[1]
    assert "Safety Margin" not in top_line
    assert "receipt-only reason" not in text[:text.index("How the number moved")]

def test_receipt_only_change_still_renders_the_section(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    receipt = _receipt_chg("safety_margin_week", "Safety Margin (this week)", [_cause(text="a cause")],
                           [], old="100.00", new="50.00", delta="-50.00")
    html, text = generate_daily_summary(db_session, user, since_changes=[receipt])
    assert CHANGES_TITLE in html and CHANGES_TITLE.upper() in text
    assert " · " not in html[html.index(CHANGES_TITLE):]  # no empty shared top-line

def test_no_receipt_section_when_safety_margin_did_not_move(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    other = _chg("k1", "Figure A", [_cause(text="a cause")])
    html, text = generate_daily_summary(db_session, user, since_changes=[other])
    assert "How the number moved" not in html and "How the number moved" not in text

def test_receipt_causes_are_capped_like_the_shared_list(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    causes = [_cause(text=f"Reason number {i}") for i in range(8)]
    receipt = _receipt_chg("safety_margin_week", "Safety Margin (this week)", causes, [],
                           old="100.00", new="50.00", delta="-50.00")
    html, text = generate_daily_summary(db_session, user, since_changes=[receipt])
    assert "and 3 more" in html and "and 3 more" in text

def test_receipt_text_is_escaped(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    receipt = _receipt_chg("safety_margin_week", "Safety Margin (this week)",
                           [_cause(text="Shop <b>Bold</b>")], [], old="100.00", new="50.00", delta="-50.00")
    html, _ = generate_daily_summary(db_session, user, since_changes=[receipt])
    assert "Shop &lt;b&gt;Bold&lt;/b&gt;" in html and "<b>Bold</b>" not in html

def test_math_figures_one_sided_and_no_change():
    from backend.services.summary_generator import _math_figures
    from backend.services.metric_diff import money, signed_money
    assert _math_figures(None, D("20.00"), money, signed_money) == f"added, {money(D('20.00'))}"
    assert _math_figures(D("20.00"), None, money, signed_money) == f"removed, was {money(D('20.00'))}"
    assert _math_figures(D("20.00"), D("20.00"), money, signed_money) == f"{money(D('20.00'))}, no change"
    assert _math_figures(D("20.00"), D("30.00"), money, signed_money) == f"{money(D('20.00'))} → {money(D('30.00'))}"

def test_safety_margin_gets_the_full_receipt_end_to_end(db_session, monkeypatch):
    from backend.services.summary_generator import SINCE_RECEIPT_KEYS
    user = _moved_world(db_session, monkeypatch)
    changes = _explained(db_session, user, keys=None, receipt_keys=SINCE_RECEIPT_KEYS)
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    block = html[html.index(CHANGES_TITLE):]
    assert "How the number moved" in block and "Safety Margin (this week)" in block
    assert "How the number moved" in text[text.index(CHANGES_TITLE.upper()):]

def test_the_send_loop_gives_safety_margin_the_full_receipt(db_session, monkeypatch):
    _moved_world(db_session, monkeypatch)
    bodies = []

    def send(db, to, subject, html, text, *a, **kw):
        bodies.append(html)
        return (True, None)

    _run_send(db_session, monkeypatch, send)
    assert "How the number moved" in bodies[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_email_since_lines.py -k "receipt or math_figures" -v`
Expected: FAIL — `SINCE_RECEIPT_KEYS` / `_math_figures` don't exist yet, and the shared-list/empty-section assertions fail against today's single rendering path

- [ ] **Step 3: Add `SINCE_RECEIPT_KEYS`, `_math_figures`, and the receipt block**

In `summary_generator.py` next to `SINCE_KEYS` (~line 87): `SINCE_RECEIPT_KEYS = frozenset({SINCE_MARGIN})`.

Add `_math_figures(old: Decimal | None, new: Decimal | None, money, signed_money) -> str`, mirroring `frontend/src/lib/historyMoney.ts`'s `mathFigures()`: `None` old → `f"added, {money(new)}"`; `None` new → `f"removed, was {money(old)}"`; `old == new` → `f"{money(old)}, no change"`; else → `f"{money(old)} → {money(new)}"`.

Add `_receipt_block(ch, money, signed_money, esc, wrap) -> tuple[str, list[str]]` returning `("", [])` when `ch` is `None`. Its header is `f"{esc(ch.label)}: {money(ch.old_value)} → {money(ch.new_value)} ({signed_money(ch.delta)})"`. Below it, a "What changed" sub-section lists `ch.causes` using the same per-cause markup `_changes_section` already builds for a reason (grouped `head`/`rows` vs. plain `text`, capped at `CHANGES_MAX_ITEMS` with an "and N more" line) — reuse that rendering rather than re-deriving it, factoring it into a small shared helper if duplicating it verbatim would violate this codebase's DRY conventions, otherwise one duplicate pass is acceptable (same call made in the Contingency Planning design for an analogous nesting block). Below that, a "How the number moved" sub-section lists `ch.math`, each line as `f"{esc(m.label)}: {_math_figures(m.old, m.new, money, signed_money)}"` with its `m.parts` indented beneath as `f"{esc(p.label)} {signed_money(p.delta)}"`, ending with one bold total row `f"{esc(ch.label)}: {_math_figures(ch.old_value, ch.new_value, money, signed_money)}"`. Omit the "How the number moved" sub-section entirely when `ch.math` is empty (mirrors `WhatChanged.tsx`'s `row.math.length > 0` guard).

In `_changes_section`: split the incoming `changes` into `receipt = next((ch for ch in changes if ch.old_value is not None), None)` and `others = [ch for ch in changes if ch.old_value is None]`. Build the existing top-line + `_reasons()` body exactly as today, but scoped to `others`, and skip building it entirely (empty string) when `others` is empty — the current unconditional construction would otherwise render an empty `<p><b></b></p>` when every moved figure is the receipt figure. Call `_receipt_block` with `receipt`. Concatenate both bodies (HTML and text) before wrapping in `section(...)`. The function's existing `if not changes: return "", ""` guard stays keyed on the original, unsplit `changes` list.

In `backend/main.py` (~line 206), add `receipt_keys=SINCE_RECEIPT_KEYS` to the existing `explain_since_last_email(db, user, readings, keys=SINCE_KEYS)` call, importing `SINCE_RECEIPT_KEYS` alongside the existing `SINCE_KEYS` import on the line above it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_email_since_lines.py -v`
Expected: all pass, including every pre-existing test in this file unchanged

- [ ] **Step 5: Run the full backend suite and lint**

Run: `cd backend && uv run --locked python -m pytest -q && uv run --locked ruff check .`
Expected: all tests pass, ruff clean, coverage floor met

- [ ] **Step 6: Commit**

```bash
git add backend/services/summary_generator.py backend/main.py backend/tests/test_email_since_lines.py
git commit -m "feat: full itemized receipt for Safety Margin in the daily email's What Changed section"
```
