# RiskBanner balance masking: implementation plan

Spec: the Impeccable Dashboard critique of 2026-11-25, P0: "RiskBanner ignores the balance-hidden setting". The saved copy is local-only, under `.impeccable/critique/`. Requirement: when "Hide balances" is on, no dollar figure in the risk banner renders in clear text.

## Global Constraints

- The frontend uses `bun` only. Tests use `bun:test` (see `frontend/src/lib/freshness.test.ts` for the style). Run them with `cd frontend && bun test`.
- Use the existing masking helpers. Don't add a new mask glyph or a new mechanism:
  - `useBalancesHidden()` and `maskIfHidden(hidden, text)` from `frontend/src/store/balanceVisibility.ts`, which masks to `••••••`
  - `fmt()` from `frontend/src/lib/utils.ts`
- When balances are shown, behavior and wording are unchanged, character for character.
- Dates, account names, and the warning and transfer structure stay visible when hidden. The date is the signal.
- The repo is public. Tests and commit messages use made-up amounts only.
- Commit directly to `main` and don't push. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The pre-push gate also runs `bunx vite build` for `frontend/`. Run it before reporting done.

## Task 1: Mask every amount in RiskBanner when balances are hidden

**Files:**
- Create `frontend/src/lib/riskBannerText.ts`
- Create `frontend/src/lib/riskBannerText.test.ts`
- Modify `frontend/src/components/RiskBanner.tsx`

**1. Extract the banner's text into pure functions** in `riskBannerText.ts`. Each takes the risk fields it needs plus `hidden: boolean`, and returns the exact string the component renders today, with every `fmt(...)` result wrapped in `maskIfHidden(hidden, ...)`. Move the private `formatDate` helper there too, and export it. The strings live in `RiskBanner.tsx`:

| Function | Source line(s) |
|---|---|
| `transferHeadline` | 107 ("Needs a … transfer from … around …") |
| `suggestionHeadline` | 122-124 (both the "Still short: top up by …" and "Suggested: move …" variants) |
| `alertHeadline` | 191-195 (all three variants: negative-threshold, danger, warning) |
| `projectedBalanceText` | 206 (the amount only; the component keeps the `Projected balance:` label and `<strong>`) |

**2. Update `RiskBanner.tsx`:**
- Call `const hidden = useBalancesHidden();` at the top, with the other hooks. It must come before the `if (!risk) return null;` early return, per the rules of hooks.
- Render every string through the new functions.

**3. Handle the editable suggestion Amount input** (lines 132-142). When `hidden` is true:
- Render a read-only `<span>` showing `••••••` in place of the `<input>`.
- Give it the title "Show balances to edit the amount".
- Leave the Date input, the Move-from select and the Accept button working. Accept uses the backend-suggested amount, which is the existing `effectiveAmount`.

When `hidden` is false, the input renders as it does today.

**4. Regression tests** in `riskBannerText.test.ts`. Use a fixture risk with made-up amounts, for example a threshold of 500, an amount of -123.45, a transfer of 750, and a suggested amount of 600.
- For each function and each variant, with `hidden=true`:
  - the output contains no `$`;
  - it contains none of the fixture's formatted amounts (such as `123.45`, `750.00`, `600.00` and `500.00`);
  - it does contain `••••••`.
- For each with `hidden=false`, the output equals the current wording exactly, including the formatted amount.
- Prove the test can fail: temporarily drop the `maskIfHidden` wrap in one function, watch the test fail, then restore it. Note this in the report.

**Verify:** `cd frontend && bun test` passes, and `bunx vite build` succeeds.

## Task 2: Fix the demo API URL in the docs

**Files:** modify `docs/demo-data.md`.

The "Loading the demo" section sets `VITE_API_URL="http://127.0.0.1:8001"`. The frontend's API client expects the `/api` prefix, so demo sign-in returns 404. Change both occurrences in that file to `VITE_API_URL="http://127.0.0.1:8001/api"`.

Before editing, confirm against `frontend/src/api/` how `VITE_API_URL` is consumed. If it turns out not to need `/api`, report that and change nothing. Commit separately.
