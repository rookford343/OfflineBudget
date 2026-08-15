# Privacy

What this app stores, what leaves your machine, and how to delete it.

Written against the code, not against intentions — every claim below is
something you can verify by grepping the source, and the relevant files are
named so you can check.

---

## The short version

Your ledger lives in one SQLite file on your own machine. The app makes
**exactly three** outbound network calls in the entire codebase, all of them
optional and all off by default:

| Destination | When | What it carries |
|---|---|---|
| SimpleFIN Bridge | Only if you connect a bank | Your access token; returns accounts + transactions |
| SimpleFIN Bridge | Only if you connect a bank | One-time setup-token claim |
| Your SMTP server | Only if you configure email | The daily summary email |

There is no telemetry, no analytics, no crash reporting, and no CDN. The
frontend loads no external fonts, scripts, or stylesheets. If you never
enable bank sync and never configure SMTP, the app makes **no outbound
requests at all** — import your transactions by CSV or OFX and nothing ever
leaves your network.

Verify it yourself:

```bash
grep -rn "httpx\.\|requests\.\|smtplib\|urlopen" backend --include="*.py" | grep -v tests
```

That should return three lines, in `simplefin_client.py` and
`email_service.py`.

---

## What's stored, and where

Everything lives in `data/budget.db` (SQLite). That includes accounts and
balances, transactions and merchants, credit cards, recurring items, budgets,
forecasts, and your user record.

**Encrypted at rest** (Fernet, keyed by `APP_ENCRYPTION_KEY`):

- Your SimpleFIN access URL — the credential that can read your bank data
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

Bank sync uses [SimpleFIN Bridge](https://www.simplefin.org/), a third-party
aggregation service. This is the one place where a party other than you can
see your financial data, so it's worth being precise:

- SimpleFIN holds read-only credentials to the accounts you link and can see
  the transactions and balances on them.
- You give the app a one-time setup token; it exchanges it for an access URL,
  encrypts that, and stores it locally. The token is spent in the exchange.
- Sync is **pull-only**. Nothing is written back to your bank, and the app
  never sees or stores your online-banking password.
- Your budget data, categories, forecasts, and everything you enter in the
  app are never sent to SimpleFIN. The traffic is one-directional: you ask
  for transactions, they answer.

**You never have to use it.** Import CSV or OFX files from your bank instead
and no third party is involved at any point.

To disconnect: **Settings → Accounts & Bank Sync → Disconnect**. That
deletes the stored credential. Revoke access on SimpleFIN's side too if you
want it fully severed.

---

## If you enable email

The daily summary is sent through whatever SMTP server you configure — your
own, or a provider like Gmail. That provider sees the email, which contains
your checking balances, upcoming bills, month-to-date spending, credit-card
balances and utilization, and on digest days your top spending categories and
merchants.

That is real financial detail leaving your machine. It goes only to the
recipients you list, through the server you chose. Leave SMTP unconfigured
and no email is ever sent — `send_email` returns immediately when no host is
set.

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
