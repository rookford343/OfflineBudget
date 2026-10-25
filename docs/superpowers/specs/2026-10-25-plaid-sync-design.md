# Plaid bank sync (Chase), with SimpleFIN kept for Apple Card

Date: 2026-10-25 · Status: approved in conversation, awaiting spec review

## Why

SimpleFIN Bridge refreshes about once a day, and no paid tier changes that. On the day this
spec was written, SimpleFIN was two days behind on checking: it had not yet seen a bill
payment that Plaid already reported, and its card pending total was short.
Statement balances and due dates are typed in by hand, and they go stale.

A probe run against the user's real Plaid Trial account (outside the app) showed:

- **One Chase login covers three accounts:** checking, savings and the Sapphire card. Chase
  connects through OAuth, so Plaid never sees the password.
- **Balances were current.** Pending card charges were reported, and their total matched the
  user's spreadsheet.
- **Liabilities returns the card statement:** `last_statement_balance`,
  `last_statement_issue_date`, `next_payment_due_date`, `minimum_payment_amount` and
  `last_payment_amount`/`last_payment_date`.
- **90 days of transactions**, with `merchant_name` on about 88% of rows, a
  `personal_finance_category` on each, and an `authorized_date` (the purchase date) that
  differs from the posted date on most card rows.
- **Recurring streams** (`/transactions/recurring/get`) were detected on their own: 18 active
  outflows, several of which differ from the app's recurring items.

Plaid doesn't list Apple Card, so Apple stays on SimpleFIN.

## Scope

**In (v1):**

1. Plaid becomes a second sync provider, alongside SimpleFIN.
2. The app links a Plaid connection with Plaid Link and maps each Plaid account to a local
   account or card.
3. Plaid syncs four times a day: transactions, balances, card pending charges, and card
   statement fields.
4. A one-time cutover for the three Chase accounts, effective 2026-10-25.
5. Reconnect handling for when Chase requires the user to log in again.

**Out (phase 2, separate specs):**

- Recurring streams feeding the existing amount-drift prompt.
- Using `authorized_date` for spending-by-day reports.
- Re-enabling statement auto-clear. `AUTO_CLEAR_STATEMENTS_IN_SYNC` stays `False`.
- Webhooks. The app stays pull-only, with no inbound listener.

## Configuration and secrets

- **Plaid keys:** `PLAID_CLIENT_ID`, `PLAID_SECRET` and `PLAID_ENV` live in the backend
  `.env`, which is gitignored. They are never stored in the database or returned by any
  endpoint.
- **Environment:** `PLAID_ENV` must be `sandbox` or `production`, and anything else fails at
  startup. The base URL is built from a constant map (`https://{env}.plaid.com`), never from
  input. The Trial plan uses `production`.
- **Access tokens:** each Plaid access token is stored with `crypto.encrypt` (Fernet), the
  same as the SimpleFIN access URL. It is never logged, and never included in an API
  response or an error message.
- **HTTP client:** no Plaid SDK. A thin `plaid_client.py` built on `httpx` (already pinned)
  POSTs JSON with `client_id`/`secret` in the body, as Plaid requires. This avoids a new
  supply-chain dependency.

## Data model

All columns below are added in `database.py`'s ALTER list.

**`bank_connections`**
- `provider`: `simplefin` | `plaid`, default `simplefin`.
- `access_url_encrypted`: kept as the encrypted credential for both providers (the SimpleFIN
  access URL, or the Plaid access token). Its docstring is updated to say so.
- `plaid_item_id`: Plaid's item id, plain text. It isn't a secret.
- `sync_cursor`: the `/transactions/sync` cursor.
- `cutover_date` (date, nullable): set on the Plaid connection. See Cutover.

**`bank_connection_account_links`**
- `simplefin_account_id`: holds the provider's account id. It is not renamed; the docstring
  says so.
- `is_active`: bool, default true. Sync skips inactive links. The cutover deactivates the
  Chase SimpleFIN links instead of deleting them, so a rollback just flips them back.

**`credit_cards`**
- `last_statement_issue_date` (date, nullable).
- `minimum_payment_amount` (numeric, nullable).

## Sync behaviour (Plaid)

Each run covers each active Plaid connection:

1. **Transactions.** Call `/transactions/sync` with the stored cursor, in pages of up to 500,
   until `has_more` is false, with `options.include_original_description = true`.
   - **Description:** use `original_description`, falling back to `name`. This keeps
     descriptions close to the bank text that SimpleFIN and CSV imports carry.
   - **Sign:** Plaid's positive amount means money out. Flip it to the app's convention
     (negative = charge) in one place in the client.
   - **Pending:** `added` rows with `pending: true` never import. On card links they replace
     the card's `CardPendingTransaction` snapshot and `pending_charges`, reusing
     `_replace_pending_snapshot`.
   - **Posted:** posted rows go through `build_preview` / `run_import` exactly as SimpleFIN
     rows do, so rules, categorization and bill matching are unchanged.
   - **Modified and removed:** `modified` and `removed` rows update or delete the matching
     `external_id`. A removed row the user has edited by hand (category or notes) is logged
     and kept, not deleted.
   - **External id:** stored as `plaid:<transaction_id>`, so ids from the two providers can
     never collide.
   - **Cursor:** saved only after every page commits.
2. **Balances.** Call `/accounts/get`.
   - **Checking and savings:** `current_balance` comes from `balances.current`. The
     checking-day auto anchor and late-transaction folding work exactly as in `_sync_link`.
   - **Cards:** `current_balance` comes from `balances.current`, with no sign flip, because
     Plaid reports credit as a positive amount owed. The existing `balance_as_of` staleness
     guard applies, using the item's `last_successful_update` as the balance date.
3. **Statements.** Call `/liabilities/get`, only for card links.
   - **New statement:** when `last_statement_issue_date` is newer than the stored one, set
     `balance_due`, `last_statement_issue_date`, `next_payment_date`,
     `minimum_payment_amount` and `balance_due_updated_at`.
   - **Same statement:** when the issue date is unchanged, leave `balance_due` alone. The
     user's `record_payment` reductions and the posting-lag rule stay authoritative.
4. **Refresh.** Call `/transactions/refresh` last. Plaid fetches from the bank in the
   background, so the next run's `/transactions/sync` picks the result up. This needs no
   webhook and no waiting inside a run.

**Schedule:** Plaid runs at 07:00, 11:00, 15:00 and 19:00. Every run holds the existing
`_bank_sync_lock`, and the 07:15 email still waits for the 07:00 run.
- **SimpleFIN:** now Apple only, so it runs only at 07:00 inside the same job. The 15:17
  cards-only SimpleFIN refresh is removed, because SimpleFIN data only changes about daily.
- **Request budget:** one run makes about 4–6 Plaid calls, so 4 runs a day are far under the
  per-item limits (`/transactions/refresh` 2/min and 120/hr; `/accounts/get` and
  `/liabilities/get` well above that). A 429 is logged and skipped. It never retries in a
  loop.

## Errors and reconnect

- **Login required:** `ITEM_LOGIN_REQUIRED` (and other `ITEM_ERROR` codes) set the
  connection to `error` with a plain-language `last_error`. Settings then shows a
  **Reconnect** button, which opens Plaid Link in update mode with a link token for that
  item.
- **Isolation:** failures stay isolated per connection and per link, as in `sync_all`.
- **Error text:** Plaid's `error_code` and `error_message` are shown. Request bodies and
  tokens never are.

## Linking flow (Settings → Accounts → Bank sync)

1. **Start.** "Connect with Plaid" calls `POST /bank-sync/plaid/link-token`. It requires
   login and the admin role, so a viewer can't link. The backend creates a link token with
   `products: ["transactions"]`, `optional_products: ["liabilities"]`,
   `transactions.days_requested: 90`, and `user.client_user_id` set to the user's id.
2. **Link.** The frontend loads `https://cdn.plaid.com/link/v2/stable/link-initialize.js`
   only on this page, and only when the button is clicked. On success it POSTs the
   `public_token` to `POST /bank-sync/plaid/exchange` (admin only). The backend exchanges
   it, encrypts the access token, and stores `plaid_item_id`.
3. **Map accounts.** The mapping screen lists the Plaid accounts by name, mask and type. Each
   one maps to an existing local account or card, or is skipped, reusing the SimpleFIN
   mapping UI. A local account or card can have only one active link across both providers.
   Mapping one that already has an active SimpleFIN link offers "Switch to Plaid", which
   runs the cutover for that link.
4. **Dashboard setting.** Plaid's Link consent also listed assets, identity and signal. Turn
   those off in the Plaid dashboard's Link customization. This is documented in
   `docs/SETUP.md` and not enforced in code.

## Cutover (2026-10-25, Chase checking, savings and Sapphire)

The user's rule: existing transactions stay; Plaid supplies everything new, without
duplicates.

1. **Back up first** with `backup_database()`. A raw `cp` of `budget.db` misses the WAL.
2. **Switch the links.** Deactivate the three Chase SimpleFIN links (`is_active = false`),
   then activate the matching Plaid links. Set `cutover_date = 2026-10-25` on the Plaid
   connection.
3. **Import window:**
   - **Older rows:** Plaid's first sync ignores posted rows dated before
     `cutover_date − 10 days`. Older history is already covered by SimpleFIN or CSV imports.
   - **Overlap rows:** for posted rows dated from `cutover_date − 10` through
     `cutover_date + 3`, **cross-provider matching** runs before import. It looks for an
     existing row on the same local account or card where:
     - the amount is equal (with the card sign convention applied),
     - the date is within ±3 days of either Plaid's `date` or its `authorized_date`,
     - and the description matches: either the normalized descriptions are equal, or they
       share at least one significant token (reusing `_evidence_tokens`), or Plaid's
       `merchant_name` appears in the stored description.

     Matching is 1:1 via `consumed`, closest date first. A match is kept as it is. The
     existing row is **not** rewritten, and the Plaid id is recorded on it in a new
     `alt_external_id` column, so later `modified` or `removed` events still find it. No
     match means the row is imported.
   - **Later rows:** rows dated after `cutover_date + 3` use normal `external_id` dedup only.
4. **Pending charges** dated in the days before the cutover post after it, and fall inside the
   matching window, so they are neither lost nor doubled.
5. **Dry run first.** The cutover runs once in dry-run mode. It prints counts of matched,
   imported and ignored rows, plus each imported row's date, amount and description, and
   the user reviews that output. Only then does the real run apply.
6. **Rollback:** deactivate the Plaid links, reactivate the SimpleFIN links, and restore the
   backup if any rows need to come out.

## Testing

All tests use invented figures, never the user's real amounts. The repo is public.

- **`plaid_client`:** tested with `httpx.MockTransport` for sign flip, pagination, cursor
  handling, `original_description` fallback, error mapping and the 429 path.
- **Sync:** pending rows go to the snapshot and are never imported; modified and removed rows
  are handled; card balance has no sign flip; a liabilities update only happens on a new
  issue date; a `record_payment` reduction survives a same-statement sync.
- **Cross-provider matching:**
  - Same amount within ±3 days, with a token match, is matched. A different amount is not.
  - Two identical same-day charges match 1:1, not 2:1.
  - A Plaid row dated before the window is ignored.
  - The authorized-date-only match case works.
  - A dry run writes nothing.
- **Security regressions** in `test_security_regressions.py`:
  - No API response or log line contains an access token or the Plaid secret.
  - Link-token and exchange endpoints refuse unauthenticated and viewer users.
  - A `PLAID_ENV` outside the allowlist fails at startup.
  - A crafted `public_token` error doesn't echo request contents.
- **Scheduler:** four Plaid runs a day; SimpleFIN only at 07:00; every run holds the lock.
- **Gates:** each new test is shown to fail against broken code first, and the coverage floor
  holds.

## Rollout notes

- **Live database:** the live backend runs `uvicorn --reload` and migrates on file change.
  Take a `backup_database()` copy before the first implementer commit that touches
  `models.py` or `database.py`. The live cutover (step 3 onward) waits for the user's
  explicit go-ahead after the dry run.
- **Docs:** update `docs/SETUP.md` (Plaid keys and Link customization),
  `docs/USER_GUIDE.md` (connecting, reconnecting, switching a link) and `docs/PRIVACY.md`.
  PRIVACY must say Plaid stores the user's transaction history on its servers, and that
  my.plaid.com can revoke access.
