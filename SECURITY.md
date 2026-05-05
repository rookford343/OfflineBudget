# Security Model

## Threat Model

OfflineBudget is designed for **offline / home LAN use**. The threat model is:

- **Protected against:** Unauthorized access from other devices on your LAN, data theft if the laptop is stolen, accidental exposure of financial data
- **Not designed for:** Public internet exposure without additional hardening (see Cloud Hardening below)
- **Assumed environment:** Single-family home network, trusted users, no adversarial insiders

---

## What Is Protected

### Passwords
- Stored as **bcrypt hashes** (cost factor 12) — never in plaintext
- Even if `budget.db` is stolen, passwords cannot be recovered without brute-force
- Change your password: log out, re-register (or add a `/auth/change-password` endpoint in a future release)

### Authentication Tokens (JWT)
- Signed with **HS256** using a secret from `.env`
- Default expiry: **7 days** (configurable via `JWT_EXPIRE_DAYS`)
- Tokens are stored in `localStorage` on the browser — cleared on sign-out
- If a token is stolen, it's valid until it expires — for LAN use this is acceptable

### Data at Rest
- SQLite file at `data/budget.db` — protected by macOS file system permissions
- Recommended: `chmod 600 data/budget.db` so only your user can read it
- The `.gitignore` excludes `data/` so your financial data is never committed to git

### Data in Transit
- **Default (local dev / LAN):** HTTP — unencrypted on the local network
- **Acceptable for home LAN use** where you trust the network
- For HTTPS, see [Enabling HTTPS on LAN](#enabling-https-on-lan) below

---

## What Is NOT Protected (and Why It's OK for Home Use)

| Risk | Status | Mitigation |
|------|--------|-----------|
| HTTP (no TLS) on LAN | Unencrypted | Home LAN is trusted; use HTTPS if concerned (see below) |
| JWT in localStorage | Accessible to JS | No XSS vectors in a Vite build served locally |
| Single `JWT_SECRET` | Shared | Fine for single-machine use; rotate if secret is ever exposed |
| No rate limiting | Unlimited login attempts | Behind home router — no public exposure |
| SQLite not encrypted | Plain file | Protected by macOS filesystem permissions |

---

## Enabling HTTPS on LAN

For encrypted LAN connections (recommended if other devices on your LAN access the app):

```bash
# Install mkcert
brew install mkcert
mkcert -install

# Generate a cert for your local IP
mkcert localhost 192.168.1.42   # replace with your actual LAN IP

# You'll get: localhost+1.pem and localhost+1-key.pem
```

Then update `scripts/start.sh` to pass the cert to uvicorn:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
  --ssl-keyfile localhost+1-key.pem \
  --ssl-certfile localhost+1.pem
```

And update Vite's `server.https` in `frontend/vite.config.ts`:
```ts
server: {
  https: { key: '../localhost+1-key.pem', cert: '../localhost+1.pem' },
  host: true,
}
```

---

## Cloud Hardening Checklist

If you move OfflineBudget to the public internet:

- [ ] Generate a new `JWT_SECRET` (at least 64 random hex characters)
- [ ] Set `JWT_EXPIRE_DAYS=1` (shorter-lived tokens)
- [ ] Use PostgreSQL (not SQLite)
- [ ] Enable TLS on the load balancer or reverse proxy (Caddy / Nginx)
- [ ] Set `ALLOWED_ORIGINS` to your exact production domain only
- [ ] Add rate limiting to `/auth/login` (e.g., slowapi)
- [ ] Store `JWT_SECRET` and `DATABASE_URL` in environment secrets (not in `.env` files)
- [ ] Run the backend as a non-root user inside Docker
- [ ] Enable PostgreSQL SSL (`?sslmode=require` in the connection string)
- [ ] Review and restrict CORS to the frontend's exact origin

---

## Backup Strategy

Your entire financial history lives in one file:

```bash
# Manual backup
cp data/budget.db data/budget_$(date +%Y%m%d).db

# Automated daily backup via cron
crontab -e
# Add:
# 0 2 * * * cp /path/to/OfflineBudgetv2/data/budget.db /path/to/backups/budget_$(date +\%Y\%m\%d).db
```

Recommended: store backups in iCloud Drive, an external drive, or a separate machine.

---

## Reporting Security Issues

This is a private project. If you find a security issue, note it in the project's issue tracker or fix it directly in the codebase.
