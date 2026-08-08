# Automated Bank Sync (SimpleFIN) — Design

## Problem

OfflineBudget requires manual CSV/OFX upload for every transaction today. Dan wants checking and credit card transactions pulled in automatically so the app stays current without him touching it daily, while keeping the "your data, your machine" model intact as much as possible.

Separately, Dan and his wife want a recurring email view of spending — this half is **already built** (see Prerequisite below) and just needs configuring, not building.

## Goals

- Checking and credit card transactions sync automatically from the bank, landing in the existing `Transaction` / `CreditCardTransaction` tables via the existing import pipeline (dedup, auto-categorizer, rules engine) — no new review queue.
- Bank credentials (SimpleFIN access token) stored encrypted at rest, never in plaintext, never in git.
- Sync runs on a daily schedule with no manual trigger required, plus a manual "sync now" escape hatch.
- Feature is optional and isolated: an install with no SimpleFIN token configured behaves exactly as today.

## Out of Scope

- **Weekly email digest to Dan + his wife** — already implemented (`backend/main.py:173` `_send_weekly_digest`, `backend/config.py` `DIGEST_RECIPIENTS`/`WEEKLY_DIGEST_DAY`/`WEEKLY_DIGEST_HOUR`). This build's only touchpoint is that synced transactions now feed it live. Activating it is a config change (SMTP + `DIGEST_RECIPIENTS` in `.env`), not code — called out here so it isn't rebuilt.
- Scheduled wake / suspend-when-idle for the backend. Explicitly deferred — this build assumes the always-on backend Dan approved, revisit later.
- Plaid or any provider other than SimpleFIN (see Decisions).
- Manual-review queue for synced transactions — auto-accept per Dan's choice; corrections happen in the existing transaction-edit UI same as any other transaction.
- Investment/brokerage accounts, or institutions SimpleFIN/MX doesn't cover.

## Prerequisite (not part of this build)

SMTP is unconfigured in `.env` and `DIGEST_RECIPIENTS` is empty, so the weekly digest is currently a no-op. Once bank sync is live, Dan should set `SMTP_*` and `DIGEST_RECIPIENTS=dan@…,wife@…` in `.env` to actually start receiving it. Flagging so it isn't a surprise that sync landing transactions doesn't itself cause an email to arrive.

## Design

### Data model (new, additive — no changes to existing tables)

- `BankConnection` — `id`, `user_id`, `access_url_encrypted` (Fernet ciphertext), `status` (`active`/`error`/`disconnected`), `last_synced_at`, `last_error`, `created_at`.
- `BankConnectionAccountLink` — `id`, `connection_id`, `simplefin_account_id` (external ID from SimpleFIN), `local_account_id` (nullable FK → `accounts.id`), `local_credit_card_id` (nullable FK → `credit_cards.id`), `last_txn_cursor` (SimpleFIN's pagination cursor, dedup aid). Exactly one of the two local FKs is set.
- `TransactionSource.bank_sync` and `CardTransactionSource.bank_sync` — new enum values, same pattern as existing `csv_import`.

### Encryption

- New `.env` var `BANK_TOKEN_ENCRYPTION_KEY` (Fernet key, generated the same way `JWT_SECRET` is: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Deliberately separate from `JWT_SECRET` so rotating one doesn't affect the other.
- New `backend/services/crypto.py`: `encrypt(str) -> str`, `decrypt(str) -> str`, thin Fernet wrapper. Access URL decrypted only in-memory for the duration of a sync call, never logged.
- Fails loudly, not silently: if `BANK_TOKEN_ENCRYPTION_KEY` is unset, the bank-connections router refuses to save a token (400) rather than falling back to plaintext.

### SimpleFIN client (`backend/services/simplefin_client.py`)

- `claim_setup_token(setup_token: str) -> str` — one-time exchange of the pasted setup token for a permanent access URL (per SimpleFIN protocol: setup token is base64 of a claim URL; POST once).
- `fetch_accounts(access_url: str) -> list[SimpleFinAccount]` — balances + external account IDs, for the initial link-mapping step.
- `fetch_transactions(access_url: str, account_id: str, since: datetime) -> list[SimpleFinTransaction]` — pulls new transactions past the stored cursor.
- All calls timeout at 15s and raise a typed `SimpleFinError` that callers catch per-account.

### Sync job (`backend/services/bank_sync_service.py`)

Runs daily via the existing APScheduler instance in `backend/main.py` (`_scheduler.add_job(_run_bank_sync, "cron", hour=5)` — sibling to `_send_daily_summaries`), plus an on-demand call from a "Sync now" button.

Per active `BankConnection`, per linked account:
1. Decrypt access URL, call `fetch_transactions` since `last_txn_cursor`.
2. Map each SimpleFIN transaction to the shape `import_service.py` already consumes (it's provider-agnostic today, driven by `ParsedRow` from the CSV path) and run it through the *same* `import_service` dedup + auto-categorize + rules pipeline, source tagged `bank_sync`.
3. Update the local `Account.current_balance` / `CreditCard.current_balance` from SimpleFIN's reported balance.
4. Update `last_txn_cursor` and `last_synced_at` only after a successful commit.

Each account link is wrapped in its own try/except — one broken link logs to `BankConnection.last_error` and continues to the next; it does not abort the whole job.

### Settings UI — new "Bank Connections" panel

Mirrors the existing Settings sub-pages (Accounts, Credit Cards):
- Paste-a-setup-token form (one-time per institution).
- List of linked SimpleFIN accounts → dropdown to map each to an existing local Account/CreditCard or create a new one.
- Status row per connection: last synced time, or the last error if sync is failing.
- "Sync now" button.
- "Disconnect" — deletes the `BankConnection` row (and its links); does not touch already-imported transactions.

### New router (`backend/routers/bank_sync.py`)

- `POST /bank-sync/connect` — body: setup token. Claims it, stores encrypted, returns discovered SimpleFIN accounts for mapping.
- `POST /bank-sync/link` — maps a SimpleFIN account ID to a local account/card (or creates one).
- `GET /bank-sync/status` — connection list with last-sync/error state, for the Settings panel.
- `POST /bank-sync/sync-now` — triggers the same job function synchronously for immediate feedback.
- `DELETE /bank-sync/{connection_id}` — disconnect.

## Data Flow

```
Dan pastes SimpleFIN setup token (Settings)
  → POST /bank-sync/connect → claim → encrypt → store BankConnection
  → GET SimpleFIN accounts → Dan maps to local Account/CreditCard (POST /bank-sync/link)

Daily @ 5am (APScheduler) or "Sync now":
  → for each BankConnection → for each linked account:
      decrypt access URL → fetch_transactions(since=last_cursor)
      → import_service pipeline (dedup, auto-categorize, rules) → commit, source=bank_sync
      → update Account/CreditCard.current_balance
      → update last_txn_cursor, last_synced_at

Existing Friday weekly digest job reads Transaction/CreditCardTransaction tables
  → unchanged, now reflects synced data automatically
```

## Error Handling

- SimpleFIN unreachable, token revoked, or malformed response: caught per-account, written to `BankConnection.last_error`, surfaced in the Settings panel banner. Sync job continues for other accounts/connections.
- Encryption key missing: connection endpoint refuses to save a token rather than storing plaintext.
- Dedup: same matching logic CSV import already uses, so an overlapping re-pull (e.g. after a failed sync retried the next day) does not double-import.
- A sync day with zero new transactions is a normal no-op, not an error.

## Testing

- `simplefin_client.py`: parsing tests against recorded fixture JSON (account list, transaction list, error responses).
- `crypto.py`: encrypt/decrypt round-trip test, and a test asserting the connect endpoint 400s when the key is unset.
- `bank_sync_service.py`: integration test with SimpleFIN HTTP calls mocked — asserts dedup on re-run, per-account failure isolation, balance updates, cursor advancement.
- No changes to the digest/email test surface since that code path is untouched.
- Frontend Settings panel verified manually via Interceptor (real Chrome) per LifeOS convention.

## Decisions

- 2026-08-08: SimpleFIN Bridge chosen over Plaid — purpose-built for self-hosted single-user tools (used by Actual Budget for the same pattern), flat ~$15/yr, read-only, no webhook infrastructure required, fits the pull-on-demand model better than Plaid's sales-led production/webhook-oriented setup.
- 2026-08-08: Backend runs always-on for this build rather than a scheduled-wake model. Dan wants to revisit "off unless needed" later; not blocking this build.
- 2026-08-08: Synced transactions auto-accept into the ledger (no manual review queue) — matches the goal of not touching the app daily. Corrections happen via the existing transaction-edit UI.
- 2026-08-08: Bank access token encrypted at rest with a dedicated Fernet key, separate from `JWT_SECRET` — a bank credential is a materially higher-stakes secret than the app's own auth, even under OfflineBudget's home-LAN threat model.
- 2026-08-08: Weekly digest email (to Dan and his wife) confirmed already built; out of scope for this design beyond noting the SMTP/`DIGEST_RECIPIENTS` config prerequisite.

## Next Step

Spec awaiting Dan's review of this file. Once approved, invoke `writing-plans` to produce the step-by-step implementation plan. `SECURITY.md` should get a new section documenting the bank-connection threat model as part of that implementation (scheduled outbound calls to SimpleFIN, encrypted-token storage) — captured here so it isn't dropped.
