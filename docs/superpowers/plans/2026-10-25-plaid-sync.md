# Plaid Bank Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Plaid as a second bank-sync provider for Chase. It syncs transactions, balances,
pending card charges and card statements 4× a day. The first import is a deduplicating cutover
from SimpleFIN that the user previews before it applies.

**Architecture:** A thin `httpx` client (`plaid_client.py`) maps Plaid's JSON into small
dataclasses. `plaid_sync_service.py` feeds them through the existing
`build_preview`/`run_import` pipeline, using balance and pending helpers pulled out of
`bank_sync_service.py`. `cutover_match.py` matches Plaid rows against rows already imported by
SimpleFIN or CSV. `sync_connection` dispatches on a new `BankConnection.provider` column.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite, httpx 0.28.1, APScheduler, React +
TanStack Query, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-plaid-sync-design.md`

## Global Constraints

- **Dependencies:** no Plaid SDK, and no new Python dependency. The client uses `httpx`
  (already pinned). The frontend loads only `https://cdn.plaid.com/link/v2/stable/link-initialize.js`,
  on demand.
- **Configuration:** `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (`sandbox` | `production`,
  default `production`) come from the backend `.env` via `backend/config.py`. Any other
  `PLAID_ENV` fails at startup. The base URL comes only from the constant
  `{"sandbox": "https://sandbox.plaid.com", "production": "https://production.plaid.com"}`.
- **Secrets:** access tokens are stored only via `crypto.encrypt`. A token, `PLAID_SECRET` or
  any request body must never appear in a log line, API response, exception message or
  `last_error`.
- **External ids:** Plaid's are stored as `plaid:<transaction_id>`.
- **Signs:** Plaid's positive amount means money out. App rows use positive = credit on
  checking. `CreditCardTransaction` and `CardPendingTransaction` use positive = charge. The
  sign flips exactly once, in `plaid_client`.
- **Statement auto-clear stays off:** `AUTO_CLEAR_STATEMENTS_IN_SYNC` stays `False`.
- **Cutover window:** rows dated before `cutover_date − 10 days` are ignored. Rows from
  `cutover_date − 10` through `cutover_date + 3` go through cross-provider matching. Later rows
  use external-id dedup only.
- **Matching rule:** same local account or card, equal amount, and a date within ±3 days of
  Plaid's `date` or `authorized_date`. The description must match in one of three ways:
  normalized descriptions are equal, they share at least one `_evidence_tokens` token, or the
  lowercased `merchant_name` is a substring of the stored description. Matching is 1:1, closest
  date first, ties broken by lower id.
- **Schedule:**
  - Full sync (both providers) at 07:00.
  - Plaid-only at 11:00, 15:00 and 19:00.
  - The 15:17 cards-only job is removed.
  - Every run holds `_bank_sync_lock`.
- **Test data:** tests and commit messages use invented figures only. The repo is public.
- **Gates:** `uv run --locked ruff check .` and `uv run --locked pytest backend/tests -q` must
  pass, and the coverage floor in `backend/.coveragerc` must hold. Every new security test is
  shown to fail once against broken code.
- **Plan-level decisions (where the spec left a choice):**
  - The Link and exchange endpoints use the existing `get_current_user`, which already refuses
    viewers on POST.
  - `exchange` sets `cutover_date = date.today()`.
  - A Plaid connection whose `sync_cursor` is NULL has not had its first import. Scheduled and
    Sync Now runs skip it, and only the first-import endpoint (preview, then confirm) can run it.

## Review Focus

1. **Plaid sends `modified` for a row that became posted under the same id.** It must update in
   place: date, amount, description. It must not duplicate the row. Tested in Task 4.
2. **A `removed` id that belongs to a row the user has edited** (category set by hand or notes
   present) is kept, and a warning is logged. Tested in Task 4.
3. **The first import's dry run writes nothing:** no rows, no cursor, no balance, no anchor.
   Tested in Task 4.
4. **`ITEM_LOGIN_REQUIRED`** sets the connection to `error` with a plain-language message, and
   the other connections still sync. Tested in Task 4.
5. **A sync interrupted mid-pagination** (an error on page 2) must not save a cursor past the
   rows it didn't commit. Tested in Task 2 and Task 4.

---

### Task 1: Schema, config and shared sync helpers

**Files:**
- Modify: `backend/models.py` (BankConnection ~978, BankConnectionAccountLink ~993,
  CreditCard, Transaction ~413, CreditCardTransaction ~507)
- Modify: `backend/database.py` (`upgrade_schema` stmts list, end of list near line 309)
- Modify: `backend/config.py` (Settings)
- Modify: `backend/services/bank_sync_service.py`
- Test: `backend/tests/test_plaid_schema.py`, `backend/tests/test_bank_sync_service.py` (existing, must stay green)

**Interfaces:**
- Produces:
  - Model columns:
    - `BankConnection`: `provider: str` (default `"simplefin"`), `plaid_item_id: str | None`,
      `sync_cursor: str | None`, `cutover_date: date | None`
    - `BankConnectionAccountLink`: `is_active: bool` (default True)
    - `CreditCard`: `last_statement_issue_date: date | None`,
      `minimum_payment_amount: Decimal | None`
    - `Transaction` and `CreditCardTransaction`: `alt_external_id: str | None` (String 128)
  - `settings.PLAID_CLIENT_ID: str | None`, `settings.PLAID_SECRET: str | None`,
    `settings.PLAID_ENV: str = "production"`, with a validator that rejects values outside
    `{"sandbox", "production"}`.
  - In `bank_sync_service.py`:
    - `@dataclass PendingCharge(external_id: str, date: date, amount: Decimal, merchant: str)`.
      `amount` uses card convention, positive = charge.
    - `replace_pending_snapshot(db, user, card, pending: list[PendingCharge]) -> bool`: the
      renamed `_replace_pending_snapshot`, now taking `PendingCharge`. The SimpleFIN caller
      maps `t.id`, `t.posted.date()`, `-t.amount`, `t.description[:256]`.
    - `apply_account_balance(db, user, account, balance: Decimal, balance_date: datetime | None, imported: int) -> None`:
      the account branch of `_sync_link`, moved verbatim, covering the anchor and late-fold
      logic.
    - `apply_card_balance(db, user, card, balance_owed: Decimal, balance_date: datetime | None, pending: list[PendingCharge], imported: int) -> None`:
      the card branch of `_sync_link`. It takes a positive amount owed; the SimpleFIN caller
      passes `-balance`.
  - `sync_all(db, *, cards_only=False, providers: set[str] | None = None)` skips links with
    `is_active == False`. It also skips connections whose `provider` isn't in `providers`
    (None = all).

- [ ] **Step 1: Back up the live DB before any model change** (the controller does this before
  dispatch, because the live `uvicorn --reload` migrates on save):
  `uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('data/budget.db','data/backups/budget-pre-plaid-20261025.db')"`
  Expected: the path prints.
- [ ] **Step 2: Write the failing tests** in `test_plaid_schema.py`:
  - `test_new_columns_default`: a new `BankConnection` has `provider == "simplefin"` and
    `cutover_date is None`; a new link has `is_active is True`.
  - `test_upgrade_schema_adds_plaid_columns`: build an old-shape SQLite DB without the new
    columns, run `upgrade_schema`, and assert each of the 8 columns exists via
    `PRAGMA table_info`.
  - `test_plaid_env_rejects_unknown`: `Settings(PLAID_ENV="staging")` raises a
    `ValidationError`.
  - `test_sync_all_skips_inactive_links`: a SimpleFIN connection with one inactive link means
    `fetch_transactions` is never called (patched).
  - `test_sync_all_provider_filter`: with `providers={"plaid"}`, a SimpleFIN connection is not
    synced.
- [ ] **Step 3: Run them.** `uv run --locked pytest backend/tests/test_plaid_schema.py -q`
  should FAIL with AttributeError or missing columns.
- [ ] **Step 4: Implement** the columns, the ALTER statements (one per column, appended to
  `stmts`), the config fields and validator, and the helper extraction and filters. Update the
  `BankConnection.access_url_encrypted` and `simplefin_account_id` docstrings to say they hold
  the credential and account id for either provider.
- [ ] **Step 5: Run the tests.**
  `uv run --locked pytest backend/tests/test_plaid_schema.py backend/tests/test_bank_sync_service.py backend/tests/test_bank_sync_router.py -q`
  Expected: PASS. The existing sync tests prove the extraction changed no behaviour.
- [ ] **Step 6: Commit.** `git commit -m "feat(sync): provider column, link activation and shared balance helpers for a second bank provider"`

### Task 2: Plaid HTTP client

**Files:**
- Create: `backend/services/plaid_client.py`
- Test: `backend/tests/test_plaid_client.py`

**Interfaces:**
- Consumes: `settings.PLAID_*` (Task 1).
- Produces:
  - Errors:
    - `class PlaidError(Exception)` with `.code: str` and `.message: str`. `str()` is
      `f"{code}: {message}"`, and never includes a request body.
    - `class PlaidRateLimited(PlaidError)`, raised on HTTP 429 or the `RATE_LIMIT_EXCEEDED`
      code.
    - `class PlaidNotConfigured(PlaidError)`, raised when the client id or secret is missing.
  - Dataclasses:
    - `PlaidTransaction(id: str, account_id: str, date: date, authorized_date: date | None, amount: Decimal, description: str, merchant_name: str | None, pending: bool)`.
      `amount` uses app checking convention, negative = money out, so it is
      `-Decimal(str(plaid_amount))`. `description` is `original_description or name`.
    - `PlaidAccount(id: str, name: str, mask: str | None, type: str, subtype: str | None, current: Decimal | None, available: Decimal | None, limit: Decimal | None)`
    - `PlaidCardStatement(account_id: str, last_statement_balance: Decimal | None, last_statement_issue_date: date | None, next_payment_due_date: date | None, minimum_payment_amount: Decimal | None)`
    - `PlaidSyncPage(added: list[PlaidTransaction], modified: list[PlaidTransaction], removed: list[str], next_cursor: str, has_more: bool)`
  - Functions (each takes an optional `transport: httpx.BaseTransport | None = None` for tests):
    - `create_link_token(client_user_id: str, *, access_token: str | None = None) -> str`.
      With `access_token`, it builds an update-mode token and sends no `products`.
    - `exchange_public_token(public_token: str) -> tuple[str, str]` returns
      `(access_token, item_id)`.
    - `sync_page(access_token: str, cursor: str | None) -> PlaidSyncPage`: ONE page, with
      `count: 500` and `options.include_original_description: true`. The caller loops, so it
      controls when the cursor is saved.
    - `get_accounts(access_token: str) -> list[PlaidAccount]`
    - `get_last_successful_update(access_token: str) -> datetime | None`, from `/item/get`
      `status.transactions.last_successful_update`.
    - `get_card_statements(access_token: str) -> list[PlaidCardStatement]` uses
      `/liabilities/get`. It returns `[]` on `PRODUCTS_NOT_SUPPORTED` or
      `NO_LIABILITY_ACCOUNTS`.
    - `refresh_transactions(access_token: str) -> None`
    - `remove_item(access_token: str) -> None`
- Link-token body:
  - `client_name: "OfflineBudget"`, `language: "en"`, `country_codes: ["US"]`,
    `user.client_user_id`
  - New links only: `products: ["transactions"]`, `optional_products: ["liabilities"]`,
    `transactions.days_requested: 90`
  - Every request: POST JSON with `client_id` and `secret` in the body, `timeout=20.0`.

- [ ] **Step 1: Write the failing tests** with `httpx.MockTransport` and invented figures:
  - `test_amount_sign_flipped`: Plaid `amount: 12.5` gives `Decimal("-12.50")`, and
    `-3.0` (a refund) gives `Decimal("3.00")`.
  - `test_description_prefers_original`, and the fallback to `name` when
    `original_description` is null.
  - `test_sync_page_sends_cursor_and_options`: the handler asserts the body has `cursor`,
    `count == 500`, and `options.include_original_description is True`.
  - `test_error_body_mapped`: a 400 with `{"error_code":"ITEM_LOGIN_REQUIRED","error_message":"x"}`
    raises a `PlaidError` with that code. `str()` doesn't contain the secret or the access token
    (assert both test strings are absent).
  - `test_429_raises_rate_limited`
  - `test_base_url_from_env`: with `PLAID_ENV="sandbox"` the request host is
    `sandbox.plaid.com`.
  - `test_missing_keys_raise_not_configured`
  - `test_liabilities_not_supported_returns_empty`
  - `test_update_mode_link_token_has_no_products`
- [ ] **Step 2: Run them.** `uv run --locked pytest backend/tests/test_plaid_client.py -q`
  should FAIL with ImportError.
- [ ] **Step 3: Implement** `plaid_client.py`. Parse money with
  `Decimal(str(x)).quantize(Decimal("0.01"))`. Treat a missing or null field as `None`, never
  as a crash.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(sync): Plaid API client on httpx"`

### Task 3: Cross-provider cutover matcher

**Files:**
- Create: `backend/services/cutover_match.py`
- Modify: `backend/services/import_service.py`. The external-id lookups in
  `_find_duplicate_transaction` and `_find_duplicate_card_transaction` also match
  `alt_external_id == row.external_id`.
- Test: `backend/tests/test_cutover_match.py`

**Interfaces:**
- Consumes: `_normalize_desc` and `_evidence_tokens` from `import_service`. The
  `alt_external_id` columns come from Task 1.
- Produces:
  - `WINDOW_BEFORE_DAYS = 10`, `WINDOW_AFTER_DAYS = 3`, `MATCH_DAYS = 3`
  - `def cutover_zone(row_date: date, cutover: date) -> Literal["ignore", "match", "normal"]`
  - `def find_match(db, user_id: int, *, account_id: int | None, card_id: int | None, txn: PlaidTransaction, consumed: set[int]) -> models.Transaction | models.CreditCardTransaction | None`:
    - Checking side: compares `Transaction.amount == txn.amount` and `Transaction.description`.
    - Card side: compares `CreditCardTransaction.amount == -txn.amount` and `.merchant`.
    - It considers every existing row regardless of `external_id`. That is the whole point:
      SimpleFIN rows carry their own ids.

- [ ] **Step 1: Write the failing tests:**
  - `test_zone_boundaries`, with cutover 2026-03-20:
    - 03-09 gives `"ignore"`
    - 03-10 gives `"match"`
    - 03-23 gives `"match"`
    - 03-24 gives `"normal"`
  - `test_matches_simplefin_row_with_token_overlap`: stored `"COFFEE SHOP 1234"`, -4.50,
    03-15 (external_id `"sf-1"`). Plaid `"Coffee Shop"`, -4.50, 03-16 matches.
  - `test_amount_mismatch_no_match`
  - `test_authorized_date_only_match`: date 03-25 (out of range), authorized_date 03-15
    (in range). It matches.
  - `test_two_identical_charges_match_one_to_one`: two stored, two Plaid rows give two
    distinct matches. With three Plaid rows, the third gets `None`.
  - `test_merchant_name_substring_match`
  - `test_card_side_sign`: a stored card charge of 20.00 matches a Plaid txn with amount
    -20.00.
  - `test_alt_external_id_found_by_dedup`: set `alt_external_id="plaid:abc"` on a stored row.
    `_find_duplicate_transaction` with `external_id="plaid:abc"` returns it.
- [ ] **Step 2: Run them.** `uv run --locked pytest backend/tests/test_cutover_match.py -q`
  should FAIL.
- [ ] **Step 3: Implement.** Query candidates on account or card, amount, and date in
  `[min(date, auth) − 3, max(date, auth) + 3]`. Filter by the description rule in Global
  Constraints, exclude `consumed`, and pick the closest by
  `min(|c.date − date|, |c.date − auth|)`, then by id.
- [ ] **Step 4: Run the tests**, plus `backend/tests/test_import_service*.py`. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(sync): match a new provider's rows against existing imports at cutover"`

### Task 4: Plaid sync service

**Files:**
- Create: `backend/services/plaid_sync_service.py`
- Modify: `backend/services/bank_sync_service.py`. `sync_connection` dispatches
  `provider == "plaid"` to `sync_plaid_connection`. Plaid connections with
  `sync_cursor is None` return `(0, 0)` untouched (first import not done yet).
- Test: `backend/tests/test_plaid_sync_service.py`

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 client (patch `backend.services.plaid_sync_service.plaid_client`
  in tests), Task 3 `cutover_zone` and `find_match`.
- Produces:
  - `@dataclass ImportReportRow(date: date, amount: Decimal, description: str, outcome: Literal["imported","matched","ignored"], target: str)`
  - `@dataclass PlaidSyncReport(imported: int, matched: int, ignored: int, rows: list[ImportReportRow])`
  - `def sync_plaid_connection(db, connection, *, first_import: bool = False, dry_run: bool = False) -> PlaidSyncReport`
- What one run does, in this order:
  1. **Page loop.** Call `sync_page` from the stored cursor (None on a first import) until
     `has_more` is false, collecting every page before writing anything. If any page raises,
     write nothing and keep the old cursor.
  2. **Route rows.** Map each row's `account_id` to its active link. Rows for unmapped
     accounts are dropped.
  3. **Pending rows** become `PendingCharge(f"plaid:{id}", date, -amount, description[:256])`
     for card links only. They are never imported.
  4. **Posted `added` rows:**
     - Only when `first_import` or `connection.cutover_date` is set, zone them with
       `cutover_zone`. `ignore` is dropped and counted. For `match`, `find_match`, and on a hit
       set `alt_external_id = "plaid:<id>"` on the existing row and count it as matched.
     - Everything else goes through `build_preview`/`run_import` with
       `external_id="plaid:<id>"` and `source=bank_sync`, as `_sync_link` does.
  5. **`modified` rows:** find the stored row by `external_id` or `alt_external_id`, and update
     date, amount and description or merchant. If it isn't found, treat it as added.
  6. **`removed` ids:** delete the stored row by `external_id` or `alt_external_id`, unless it
     has `notes`, or a `category_id` that differs from what `build_preview` would suggest now.
     In that case keep it and log a warning with the row id only.
  7. **Balances:** call `get_accounts` and `get_last_successful_update`. Checking and savings
     use `apply_account_balance(current)`. Cards use
     `apply_card_balance(balance_owed=current, balance_date=last_update, pending=…)`.
  8. **Statements:** `get_card_statements`. For each linked card whose
     `last_statement_issue_date` is newer than the stored one (or the stored one is None), set
     `balance_due`, `last_statement_issue_date`, `next_payment_date`, `minimum_payment_amount`,
     and `balance_due_updated_at = utcnow()`. An unchanged issue date touches nothing.
  9. **Finish:** save `sync_cursor = final next_cursor`, set the link and connection
     `last_synced_at`, `status = active`, `last_error = None`, and commit. Then call
     `refresh_transactions`. A `PlaidRateLimited` there is logged and ignored.
  10. **`dry_run=True`:** runs steps 1–4 as classification only and **writes nothing**.
      `run_import` commits internally (`import_service.py:555`), so a rollback can't undo it.
      - **Never call:** `run_import`, the `alt_external_id` assignment, steps 5–9 or
        `refresh_transactions`.
      - **Classify each posted row** with `cutover_zone`, `find_match`, then
        `_find_duplicate_transaction` / `_find_duplicate_card_transaction` (which do no writes):
        - `ignored`: the zone says ignore
        - `matched`: `find_match` hits, or there is an external-id duplicate
        - `imported`: otherwise
      - Report the outcomes and leave the session clean (`db.rollback()` at the end, as a
        belt-and-braces step).
- Errors:
  - A `PlaidError` with code `ITEM_LOGIN_REQUIRED` sets `status=error` and
    `last_error="Chase needs you to log in again. Use Reconnect in Settings → Accounts."`.
    Other `PlaidError`s set `last_error=str(exc)`.
  - A 429 at any step before the commit leaves state untouched and sets
    `last_error="Plaid rate limit reached; will retry next run"`.

- [ ] **Step 1: Write the failing tests** (fixtures modelled on `_make_connection` in
  `test_bank_sync_service.py`, with a Plaid connection, checking, savings and card links,
  invented figures):
  - `test_posted_rows_imported_with_plaid_prefix`
  - `test_pending_card_rows_snapshot_not_imported`
  - `test_first_import_ignores_old_matches_overlap_imports_rest`: cutover 2026-03-20; rows on
    03-01 (ignored), 03-15 (matches an existing SimpleFIN row, which gets `alt_external_id`),
    and 03-21 with no match (imported). Report counts are 1/1/1.
  - `test_dry_run_writes_nothing`: after a dry run the transaction count, `sync_cursor`,
    account balance, `ForecastDayCheckpoint` count and card `pending_charges` are all
    unchanged, and `refresh_transactions` was not called.
  - `test_modified_updates_in_place`
  - `test_removed_deletes_unless_user_edited`
  - `test_page_error_keeps_cursor`: page 1 OK, page 2 raises `PlaidError`. The cursor is
    unchanged and no rows are written.
  - `test_login_required_sets_error_message`, and that a second connection in `sync_all` still
    syncs.
  - `test_new_statement_sets_balance_due`
  - `test_same_statement_keeps_reduced_balance_due`: stored issue date equals Plaid's, and the
    stored `balance_due` (reduced by `record_payment`) is unchanged.
  - `test_card_balance_not_sign_flipped`: Plaid current 250.00 gives `current_balance` 250.00.
  - `test_refresh_called_after_commit`, and that a `PlaidRateLimited` from refresh still leaves
    the sync successful.
  - `test_sync_connection_skips_plaid_without_cursor`
- [ ] **Step 2: Run them.** `uv run --locked pytest backend/tests/test_plaid_sync_service.py -q`
  should FAIL.
- [ ] **Step 3: Implement** `plaid_sync_service.py` and the dispatch in `sync_connection`.
- [ ] **Step 4: Run the tests**, plus `test_bank_sync_service.py`. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(sync): Plaid transaction, balance, pending and statement sync with a previewable first import"`

### Task 5: API endpoints and security regressions

**Files:**
- Modify: `backend/routers/bank_sync.py`, `backend/schemas.py`
- Test: `backend/tests/test_bank_sync_router.py`, `backend/tests/test_security_regressions.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces (all under `/bank-sync`, all `Depends(get_current_user)`):
  - `POST /plaid/link-token`, body `{connection_id: int | null}`, returns `{link_token: str}`.
    With `connection_id` (owned, provider plaid) it builds an update-mode token. Returns 400 if
    Plaid isn't configured, with the message "Plaid isn't set up: add PLAID_CLIENT_ID and
    PLAID_SECRET to the backend .env".
  - `POST /plaid/exchange`, body `{public_token: str}`, returns the existing
    `BankConnectionConnectResponse`. It checks `assert_encryption_configured()` first. It
    creates `BankConnection(provider="plaid", plaid_item_id, cutover_date=date.today(),
    access_url_encrypted=encrypt(token))` and lists accounts via `get_accounts`.
    `BankConnectionAccountOut` gets new optional fields `mask: str | None` and
    `kind: str | None` (type/subtype). `org_name` is "Plaid", and `balance` is `current or 0`.
  - `GET /{connection_id}/accounts` dispatches on provider.
  - `POST /{connection_id}/link` gains `switch_existing: bool = False` on
    `BankConnectionLinkRequest`. If another ACTIVE link anywhere for this user targets the same
    local account or card:
    - without `switch_existing`, it returns 409 with
      `detail={"message": "…already synced by another connection", "existing_link_id": id}`;
    - with it, that link gets `is_active = False` first.
  - `POST /{connection_id}/plaid/first-import?confirm=false`, returning
    `{imported, matched, ignored, rows: [{date, amount, description, outcome, target}]}`.
    - `confirm=false` runs `dry_run=True`.
    - `confirm=true` runs `first_import=True` under `_bank_sync_lock` (409 if busy).
    - Returns 409 if `sync_cursor` is already set.
  - `BankConnectionStatusOut` gains `provider: str`. `BankConnectionLinkOut` gains
    `is_active: bool`.
  - `DELETE /{connection_id}` on a Plaid connection calls `remove_item` first. If that fails,
    it logs and still deletes locally.
- [ ] **Step 1: Write the failing tests:**
  - Router: exchange stores an encrypted token that differs from the plain token, sets
    `cutover_date`, and lists accounts. The link 409 includes `existing_link_id`, and the
    switch deactivates the old link. A first-import preview writes nothing; confirm imports;
    confirming twice gives 409. Update-mode link-token works. Delete calls `remove_item`.
  - Security (`test_security_regressions.py`, each with a one-line docstring entry):
    - `test_plaid_token_never_in_responses`: the token string is absent from every
      `/bank-sync` response body in a flow.
    - `test_plaid_token_never_logged`: `caplog` across exchange, sync and error paths. Neither
      the token nor `PLAID_SECRET` appears.
    - `test_plaid_endpoints_refuse_viewer_and_anonymous`: link-token, exchange and first-import
      give 401 anonymous and 403 viewer.
    - `test_plaid_error_detail_has_no_request_body`: a mocked exchange failure's `detail`
      doesn't contain the public token.
    - `test_plaid_link_token_other_users_connection_404`: update mode on someone else's
      connection gives 404.
- [ ] **Step 2: Run them.**
  `uv run --locked pytest backend/tests/test_bank_sync_router.py backend/tests/test_security_regressions.py -q`
  should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests**, then break one guard (for example, return the token in
  exchange). The matching security test must fail. Restore it, then run again. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(sync): Plaid link, exchange, account mapping and first-import endpoints"`

### Task 6: Scheduler

**Files:**
- Modify: `backend/main.py`, around lines 68–76 and 217–367
- Test: `backend/tests/test_scheduler_job_locks.py`, plus a new
  `backend/tests/test_plaid_schedule.py`

**Interfaces:**
- Consumes: `sync_all(..., providers=)` (Task 1).
- Produces:
  - `_PLAID_EXTRA_HOURS = (11, 15, 19)`
  - `_run_plaid_sync()` takes `_bank_sync_lock` non-blocking, skips if busy, and calls
    `sync_all(db, providers={"plaid"})`. It has no missed-run retry.
  - The 07:00 `_run_bank_sync` stays as is, covering all providers.
  - `_run_card_refresh` and its job are deleted, along with `_CARD_REFRESH_HOUR` and
    `_CARD_REFRESH_MINUTE`.
- [ ] **Step 1: Write the failing tests:**
  - `test_jobs_registered`: `_scheduler.get_jobs()` has a Plaid job for each of 11, 15 and 19,
    and nothing at 15:17.
  - `test_plaid_job_skips_when_locked`
  - `test_plaid_job_only_plaid_provider`: `sync_all` is called with `providers={"plaid"}`.
  - Update or delete the existing card-refresh tests.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run --locked pytest backend/tests -q -k "schedul or lock or plaid"`.
  Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(sync): Plaid syncs at 7, 11, 3 and 7; drop the cards-only afternoon refresh"`

### Task 7: Frontend: connect, map, preview, reconnect

**Files:**
- Create: `frontend/src/lib/plaidLink.ts`
- Modify: `frontend/src/api/index.ts` (`bankSyncApi`), `frontend/src/pages/settings/AccountsTab.tsx`

**Interfaces:**
- Consumes: Task 5 endpoints.
- Produces:
  - `loadPlaidLink(): Promise<void>` injects the CDN script once, and rejects on error.
  - `openPlaidLink(linkToken: string): Promise<{publicToken: string} | null>` returns `null`
    when the user exits.
  - `bankSyncApi.plaidLinkToken(connectionId?: number)`, `bankSyncApi.plaidExchange(publicToken)`,
    `bankSyncApi.plaidFirstImport(connectionId, confirm: boolean)`
  - `bankSyncApi.link` passes `switch_existing`.
- UI in the Bank Connections card:
  - **Connect.** A "Connect with Plaid" button, shown next to the SimpleFIN setup-token form.
    It runs link-token, then Link, then exchange, then shows the existing account-mapping list.
    Each row shows `name ••mask (kind)`.
  - **Switching a link.** A 409 with `existing_link_id` turns into an inline prompt, "Already
    synced by SimpleFIN. Switch to Plaid?", which re-POSTs with `switch_existing: true`.
  - **First-import preview.** After mapping, a "Preview first import" button calls
    `plaidFirstImport(id, false)`. It shows counts plus a scrollable table of rows (date,
    description, amount masked under the existing hide-balances setting, outcome, target),
    then a "Confirm import" button calls `confirm=true`.
  - **Per connection:** a provider badge ("Plaid" or "SimpleFIN"). When Plaid status is `error`,
    a "Reconnect" button opens Link with an update-mode token.
  - **Inactive links** are shown dimmed, with "(switched to another connection)".
  - **Copy:** the schedule text becomes "Plaid accounts sync at 7am, 11am, 3pm and 7pm.
    SimpleFIN accounts sync at 7am."
- [ ] **Step 1:** Implement, then run `cd frontend && bun run build`. Expected: the build
  succeeds with no TypeScript errors.
- [ ] **Step 2:** Run the dev frontend against the demo DB (ports 8001/5174, as in prior
  screenshot work). Confirm with Interceptor that the Connect with Plaid button renders, and
  that a SimpleFIN-only connection still renders unchanged. The full Link flow needs real keys
  and is verified at cutover.
- [ ] **Step 3: Commit.** `git commit -m "feat(sync): connect, map, preview and reconnect Plaid in Settings"`

### Task 8: Docs

**Files:**
- Modify: `docs/SETUP.md`, `docs/USER_GUIDE.md`, `docs/PRIVACY.md`, `README.md` (feature
  list), `.env.example`

**Content:**
- **`.env.example`:** `PLAID_CLIENT_ID=`, `PLAID_SECRET=`, `PLAID_ENV=production`, each with a
  comment.
- **SETUP:**
  1. Sign up at dashboard.plaid.com as "Personal use" (Trial plan, free, up to 10 linked
     logins).
  2. Copy the Production keys into `.env`.
  3. In Link customization, turn off any data types beyond transactions and liabilities.
- **USER_GUIDE:**
  - Connecting with Plaid, and switching an account from SimpleFIN
  - Previewing and confirming the first import
  - Reconnecting
  - The schedule
- **PRIVACY:**
  - Plaid stores your account and transaction history on its servers.
  - The access token is encrypted at rest in the app.
  - Revoke access at my.plaid.com, or with Disconnect (which calls Plaid's item removal).
- [ ] **Step 1:** Write the docs. Grep them for dollar figures:
  `grep -nE '\$[0-9]' docs/SETUP.md docs/USER_GUIDE.md docs/PRIVACY.md` should find none
  beyond the Plaid/SimpleFIN pricing.
- [ ] **Step 2: Commit.** `git commit -m "docs: Plaid setup, use and privacy"`

---

## After all tasks (controller)

1. **Final review:** one final whole-branch review, then exactly one fix wave. Any re-review
   finding goes to the user.
2. **Cutover (needs the user's explicit go-ahead):**
   1. Take a `backup_database()` copy.
   2. The user adds the keys to the backend `.env`.
   3. The user connects Plaid in Settings and maps the three Chase accounts with "Switch to
      Plaid".
   4. Preview the first import, and the user reviews the rows.
   5. Confirm.
3. **Verify** the balances against the probe's figures.
4. **Remove the probe's Plaid Item** with `bun probe.ts remove`. This happens after the app's
   own Item is linked.
