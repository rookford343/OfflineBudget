# Privacy

What this app stores, what leaves your machine, and how to delete it.

Written against the code, not against intentions — every claim below is
something you can verify by grepping the source, and the relevant files are
named so you can check.

---

## The short version

Your ledger lives in one SQLite file on your own machine. The app makes
**four** outbound network call sites in the entire codebase, all of them
optional and all off by default:

| Destination | When | What it carries |
|---|---|---|
| SimpleFIN Bridge | Only if you connect a bank via SimpleFIN | Your access token; returns accounts, posted transactions, and pending card charges |
| SimpleFIN Bridge | Only if you connect a bank via SimpleFIN | One-time setup-token claim |
| Plaid | Only if you connect a bank via Plaid | Your access token; returns accounts, balances, transactions, and card statement data. The same function also creates and exchanges a Link token (connecting or reconnecting) and removes the item (Disconnect) |
| Your SMTP server | Only if you configure email | The daily summary email |

There is no telemetry, no analytics, and no crash reporting. The frontend
loads no external fonts, scripts, or stylesheets by default — the one
exception is Plaid's own Link script, from `cdn.plaid.com`, which loads only
if and when you click **Connect with Plaid** or **Reconnect**. If you never
connect a bank and never configure SMTP, the app makes **no outbound
requests at all** — import your transactions by CSV or OFX and nothing ever
leaves your network.

Verify it yourself:

```bash
grep -rn "httpx\.\|requests\.\|smtplib\|urlopen" backend --include="*.py" | grep -v tests
```

The network calls are `httpx.post` (setup-token claim) and `httpx.get`
(sync) in `simplefin_client.py`, one shared `httpx.Client(...).post()` for
every Plaid operation in `plaid_client.py`, and `smtplib.SMTP` in
`email_service.py`. The other matching lines are their error handlers, type
hints, and imports.

---

## What's stored, and where

Everything lives in `data/budget.db` (SQLite). That includes accounts and
balances, transactions and merchants, credit cards, recurring items, budgets,
forecasts, and your user record.

**Adventures:** trips, checklist items, loyalty-program balances and transfer partners you enter. Stored only in the local database; nothing is looked up online.

**Wish List:** wishes, prices, trade-in values and payment options you enter. Stored only in the local database.

**Pending card charges:** if you connect a bank, the charges your card issuer
currently lists as pending (date, merchant, amount). Each sync replaces the
whole list, so a charge is deleted from it as soon as it posts; nothing about
pending charges is kept as history.

**Encrypted at rest** (Fernet, keyed by `APP_ENCRYPTION_KEY`):

- Your bank access credential — the SimpleFIN access URL, or the Plaid
  access token, whichever provider(s) you connect
- Your SMTP password

Both are decrypted only in memory, at the moment they're used. Neither is
ever returned by the API: the Settings page receives a boolean saying whether
a password is set, never the value. Without an encryption key configured, the
app **refuses to store** the SMTP password rather than falling back to
plaintext.

**Hashed:** your login password (bcrypt, 12 rounds). It is not recoverable,
including by you.

**Plaintext in the database:** everything else — balances, transaction
descriptions, merchants, amounts. Anyone with the `budget.db` file can read
your finances. Treat it like the sensitive file it is; see Backups below.

**Session tokens:** a JWT in browser `localStorage`, valid 7 days by default
(`JWT_EXPIRE_DAYS`).

---

## If you connect a bank

Bank sync has two providers, SimpleFIN and Plaid. This is the one place
where a party other than you can see your financial data, so it's worth
being precise about each.

**You never have to use either.** Import CSV or OFX files from your bank
instead and no third party is involved at any point.

### SimpleFIN

[SimpleFIN Bridge](https://www.simplefin.org/) is a third-party aggregation
service.

- SimpleFIN holds read-only credentials to the accounts you link and can see
  the transactions and balances on them.
- You give the app a one-time setup token; it exchanges it for an access URL,
  encrypts that, and stores it locally. The token is spent in the exchange.
- Sync is **pull-only**. Nothing is written back to your bank, and the app
  never sees or stores your online-banking password.
- The app asks SimpleFIN once a day, at 7am, plus whenever you press
  **Sync Now**.
- Your budget data, categories, forecasts, and everything you enter in the
  app are never sent to SimpleFIN. The traffic is one-directional: you ask
  for transactions, they answer.

### Plaid

[Plaid](https://plaid.com/) is a larger, bank-grade aggregation service.

- Plaid stores your linked accounts' balance and transaction history on its
  own servers — that's how it can answer the app's requests without going
  back to your bank every time. What the app actually asks Plaid for is
  transactions and liabilities (card statement data); it doesn't request
  identity, assets or investment data, and the Settings → Link customization
  step in the setup guide turns those off at the source too.
- You connect through Plaid Link, a window Plaid itself controls — your
  online-banking login goes to Plaid (or, for banks that support it, straight
  to your bank via OAuth), never to this app. What the app receives back is
  an access token, which it encrypts (Fernet, the same `APP_ENCRYPTION_KEY`
  as SimpleFIN) and stores locally.
- Sync is **pull-only**, same as SimpleFIN. Nothing is written back to your
  bank.
- The app asks Plaid four times a day — 7am, 11am, 3pm and 7pm — plus
  whenever you press **Sync Now**.
- Your budget data, categories, forecasts, and everything you enter in the
  app are never sent to Plaid.
- **Revoking access:** either disconnect the connection in the app
  (**Settings → Accounts & Bank Sync → Disconnect**, which calls Plaid's
  item-removal API and deletes the stored token), or revoke it directly at
  [my.plaid.com](https://my.plaid.com/), Plaid's own consumer portal. Either
  one is enough on its own; doing both is fine too.

To disconnect either provider: **Settings → Accounts & Bank Sync →
Disconnect**. That deletes the stored credential. For SimpleFIN, you can
also revoke access on SimpleFIN's side if you want it fully severed.

---

## If you enable email

The daily summary is sent through whatever SMTP server you configure — your
own, or a provider like Gmail. That provider sees the email, which contains
your checking balances, upcoming bills, this month's spending by category and
your top merchants, and credit-card balances. On digest days it adds the past
week's spending. Password-reset emails go through the same server.

That is real financial detail leaving your machine. It goes only to the
recipients you list, through the server you chose. Leave SMTP unconfigured
and no email is ever sent: every send checks for an SMTP host first and stops
when there isn't one.

---

## Deleting your data

**Everything at once:** stop the app and delete `data/budget.db` (plus any
`-wal` / `-shm` files alongside it). That is the whole dataset. Also clear
`data/backups/` if you've been taking backups.

**Selectively, in the app:** Settings → Danger Zone can clear checking
transactions, clear credit-card transactions, or delete your account.

**Raw bank payloads:** if you turned on "Capture Raw Bank Data" for
debugging, those live in the `bank_sync_raw_snapshots` table. Turn the
setting off and drop the table to clear them:

```bash
sqlite3 data/budget.db "DELETE FROM bank_sync_raw_snapshots;"
```

---

## Backups

`data/budget.db` is unencrypted. If you copy it to another disk, a NAS, or
cloud storage, your full financial history goes with it in readable form.

The repository's `.gitignore` blocks `data/**` by file type — `.db`, `.csv`,
`.xlsx`, `.ofx` and friends — anywhere under `data/`, and a `pre-commit` hook
in `.githooks/` blocks them even if force-added. Enable the hook on a fresh
clone with:

```bash
git config core.hooksPath .githooks
```

---

## Reporting a problem

Security issues: see [SECURITY.md](../SECURITY.md).
