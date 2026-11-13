# Deploying to Render

This guide deploys the Restaurant Outreach System to Render using the `render.yaml` Blueprint at the repository root.

The default configuration runs in **demo mode with mock email**. It needs no Google, SMTP or other live credentials, and it cannot send real email. Turn on live discovery or real sending only as a separate, deliberate step (see [Going live](#going-live-later)).

## What gets created

| Resource | Type | Folder | Purpose |
|---|---|---|---|
| `ro-db` | PostgreSQL | — | Application data (restaurants, drafts, campaigns, suppression list, send logs) |
| `ro-backend` | Web service (Python) | `backend/` | FastAPI API. Runs database migrations before it starts. Public, behind a sign-in. |
| `ro-email` | Private service (Node.js) | `email-service/` | Nodemailer sender. Reachable only from `ro-backend` inside Render's private network. |
| `ro-frontend` | Static site | `frontend/` | React interface. Calls `ro-backend` directly. |

Only `ro-frontend` and `ro-backend` have public URLs. `ro-email` has no public address and rejects any request without `EMAIL_SERVICE_SECRET`.

## Before you start

- A Render account and a GitHub (or GitLab) repository containing this project. Render deploys from a Git repository, so push the code first. **Do not push `.env` files.** The `.gitignore` already excludes them.
- Your own email address and a password of at least 12 characters for the first admin account, chosen by you. Keep it in a password manager.
- Node.js 20 or newer and Python 3.13 on your computer if you want to run the checks locally.

### Create the first admin account

There is no shared password. Each person signs in with their own email and password. The first admin is created once, after the database is migrated, from the `backend` folder:

```powershell
python scripts\create_admin.py
```

Enter your name and email, then type the password at the hidden prompt (twice). The command refuses to run if an active admin already exists. Later accounts are created on the Users page by an admin.

If you are migrating from the old shared admin password, run `python scripts\create_admin.py --from-legacy-hash` while `ADMIN_PASSWORD_HASH` is still set. Your existing password keeps working for the new admin account, and the plain `ADMIN_PASSWORD` is never read. Then remove `ADMIN_PASSWORD` and `ADMIN_PASSWORD_HASH` from the environment.

For local checks, set up the Python environment from the pinned file, not from whatever is installed:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Do not put real secrets in `render.yaml`, in a commit, or in a chat.

## Step 1 — Run the local checks

From the project root, in PowerShell:

```powershell
cd backend
python -m pytest -q
cd ..\email-service
cmd /c "npm test"
cd ..\frontend
cmd /c "npm ci"
cmd /c "npm run build"
```

All three must pass before you deploy.

## Step 2 — Create the Blueprint

1. Push the repository to GitHub.
2. In the Render dashboard choose **New → Blueprint** and select the repository.
3. Render reads `render.yaml` and shows the four resources. Review them, then choose **Apply**.
4. Render asks for the values marked as "sync: false" (see the table below). Enter these now or later in each service's **Environment** page:
   - `ro-backend`: `SESSION_SECRET`, `CORS_ORIGINS`, `PUBLIC_BASE_URL`
   - `ro-frontend`: `VITE_API_ORIGIN`

   You do not know the public URLs until the services exist. You can leave `CORS_ORIGINS`, `PUBLIC_BASE_URL` and `VITE_API_ORIGIN` blank at first and fill them in during Step 4.

Render generates `SESSION_SECRET`, `UNSUBSCRIBE_SECRET` and `EMAIL_SERVICE_SECRET` automatically. You never need to see them.

## Step 3 — Confirm the service addresses

After the first deploy, note the public URLs:

- Backend: `https://ro-backend.onrender.com` (your URL may differ; Render adds a suffix if the name is taken)
- Frontend: `https://ro-frontend.onrender.com`

## Step 4 — Connect the three public values

1. On **ro-backend** → Environment, set:
   - `CORS_ORIGINS` = the frontend URL, for example `https://ro-frontend.onrender.com`. No trailing slash.
   - `PUBLIC_BASE_URL` = the backend URL, for example `https://ro-backend.onrender.com`. The unsubscribe links point here.
2. On **ro-frontend** → Environment, set `VITE_API_ORIGIN` = the backend URL, for example `https://ro-backend.onrender.com`. Vite reads this at build time, so trigger **Manual Deploy → Clear build cache & deploy** on the static site after changing it.
3. Save. Render redeploys the backend. The static site redeploys after step 2.

## Step 5 — Check health

- `https://ro-backend.onrender.com/health` should return `{"status":"ok", ...}`.
- `https://ro-backend.onrender.com/health/ready` should return success (it checks the database).
- Open `https://ro-frontend.onrender.com`. You should see the sign-in screen. Sign in with the email and password of the admin account you created with `scripts/create_admin.py`.
- Check the **Logs** tab of `ro-backend`. Each line is JSON. The startup should show the demo-mode warning and no errors.

If the backend fails at startup, the log names the missing or invalid setting (for example "SESSION_SECRET must be at least 32 characters"). Fix it in the dashboard and redeploy.

## Step 6 — Move local data (optional)

Skip this step if you want to start with an empty production database.

To copy your local SQLite data into the new PostgreSQL database:

1. Stop the local backend so the SQLite file is not changing.
2. Make a backup copy of the SQLite file first (see [Backups](#backups)).
3. In the Render dashboard open **ro-db** and copy the **External Database URL**. Render shows it only on the database page. Change its prefix to `postgresql+psycopg://`. Keep the database credentials out of chat and out of files you commit.
4. Make sure the target is empty. The migration refuses to write into a database that already contains rows. A fresh deployment only has empty tables, but if anyone has already used the production app, start over with a new database.
5. From the `backend` folder run:

   ```powershell
   python scripts\migrate_sqlite_to_postgres.py --source "..\restaurant_outreach.db" --target "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME"
   ```

   Replace the placeholder with the URL you copied. The script prints the row count for each table. It never changes the SQLite file.
6. Sign in to the production app and check that your restaurants, drafts and campaigns are there.

## Environment variables

Set these on the service shown. "Blueprint" means `render.yaml` sets the value.

| Variable | Service | Source | Purpose |
|---|---|---|---|
| `APP_ENV` | backend | Blueprint (`production`) | Enables production checks, disables API docs, enables HSTS |
| `DATABASE_URL` | backend | Blueprint (from `ro-db`) | PostgreSQL connection |
| `SESSION_SECRET` | backend | Blueprint (generated, 32+ characters) | Signs session cookies. Sessions are also stored on the server and deleted on sign-out. |
| `TRUST_PROXY_HEADERS` | backend | Blueprint (`true`) | Count login attempts by the address Render's proxy saw, not by a client-supplied header |
| `MAX_REQUEST_BYTES` | backend | Blueprint (`65536`) | Largest accepted request body. Larger bodies get HTTP 413. |
| `UNSUBSCRIBE_SECRET` | backend | Blueprint (generated) | Signs unsubscribe links |
| `CORS_ORIGINS` | backend | **You** (frontend URL) | Which browser origin may call the API |
| `PUBLIC_BASE_URL` | backend | **You** (backend URL) | Base of unsubscribe links in emails |
| `DEMO_MODE` | backend | Blueprint (`true`) | Sample Google results. Keep `true` until live discovery is approved. |
| `MOCK_EMAIL_MODE` | backend | Blueprint (`true`) | Forces the mock sender. Keep `true` until real sending is approved. |
| `EMAIL_PROVIDER` | backend | Blueprint (`mock`) | `mock`, `nodemailer` or `smtp` |
| `EMAIL_SERVICE_URL` | backend | Blueprint (from `ro-email` hostport) | Address of the private email service |
| `EMAIL_SERVICE_SECRET` | backend and ro-email | Blueprint (`ro-backend` reads it from `ro-email`) | Shared secret for the private email service (16+ characters) |
| `RATE_LIMIT_ENABLED` | backend | Blueprint (`true`) | Limits login and expensive requests per IP |
| `LOG_JSON` / `LOG_LEVEL` | backend | Blueprint | Structured logs |
| `VITE_API_ORIGIN` | frontend | **You** (backend URL) | Where the browser sends API calls (build time) |
| `MAIL_MODE` | ro-email | Blueprint (`mock`) | `mock` records messages; `smtp` sends through SMTP |
| `EMAIL_SERVICE_HOST` / `EMAIL_SERVICE_PORT` | ro-email | Blueprint (`0.0.0.0` / `10000`) | Where the private service listens |
| `GOOGLE_PLACES_API_KEY` | backend | Add later, only for live discovery | Not needed for demo mode |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` | ro-email | Add later, only for SMTP | Not needed for mock mode |

Never give the frontend any key. Only `VITE_API_ORIGIN` is set there, and it is a public address.

## Service configuration

| Setting | ro-backend | ro-email | ro-frontend |
|---|---|---|---|
| Type | Web service, Python | Private service, Node | Static site |
| Root directory | `backend` | `email-service` | `frontend` |
| Build command | `pip install -r requirements.txt` | `npm ci` | `npm ci && npm run build` |
| Start command | `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT` | `npm start` | — |
| Publish directory | — | — | `dist` |
| Health check | `/health` | `/livez` | — |
| Plan | Starter | Starter | Free or Starter |

Note on `ro-email` health checks: `/livez` is public and returns only `{"status":"ok"}`, so Render can probe it without the secret. The `/health` route needs the secret and is used only by the backend.

## Backups

**PostgreSQL (production):**

- Paid Render PostgreSQL plans include automatic daily backups and point-in-time recovery. Check the plan you chose on the **ro-db** page.
- For an extra copy you control, run from a computer that has PostgreSQL client tools installed:

  ```bash
  pg_dump --format=custom --no-owner --file ro_outreach_YYYY-MM-DD.dump "postgresql://USER:PASSWORD@HOST:5432/DBNAME"
  ```

  Use the External Database URL from the **ro-db** page without the `+psycopg` part. Store the dump somewhere private. It contains your data.
- Restore with `pg_restore --clean --no-owner -d <target-url> ro_outreach_YYYY-MM-DD.dump`. Practice this on a scratch database before you need it.

**Logical backup and restore (works without `pg_dump`):** `backend/scripts/logical_backup.py` exports every table to JSON Lines, with a manifest holding row counts and SHA-256 checksums. Sessions are not exported. Restore checks every checksum first and refuses to write into a database that already has data.

```powershell
cd backend
python scripts\logical_backup.py export --database-url "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME" --out "..\backups\2026-11-04"
python scripts\logical_backup.py restore --from "..\backups\2026-11-04" --database-url "postgresql+psycopg://USER:PASSWORD@HOST:5432/SCRATCH_DBNAME"
```

Always restore into a new, empty database first and check it before using it. Keep backup folders private: they contain contact details and the suppression list.

**Local SQLite (before migration):** copy `restaurant_outreach.db` to a dated file while the backend is stopped. Keep the copy until you have confirmed the migrated data.

**Suppression list:** this table records people who opted out. Back it up with everything else. Losing it could mean emailing someone who asked to be removed.

## Email service storage

**Sending decisions are made in the application database.** Each campaign recipient has one row in `email_send_ledger` (unique per campaign and recipient). The row is reserved in a transaction before the provider is called, and its outcome is recorded in the same transaction as the recipient. The database survives restarts, so sent history is kept and a sent recipient is never sent again. A send whose outcome is unknown is marked `uncertain` and is never retried automatically.

`ro-email` still keeps its own idempotency file (`data/send-ledger.json`) on the container's disk. Render erases that disk on each deploy or restart. It is now only a secondary check: the decision is made in the application database, so losing this file cannot cause a repeat send by itself.

## Going live later

Each of these needs your explicit approval and is not part of this deployment:

1. **Live Google discovery:** add `GOOGLE_PLACES_API_KEY` to `ro-backend` and set `DEMO_MODE=false`. Follow [docs/GOOGLE_PLACES_SETUP.md](GOOGLE_PLACES_SETUP.md). Storage rules still apply: stored listings older than 30 days are purged automatically.
2. **Real email:** configure SMTP or a provider on `ro-email`, set `MAIL_MODE=smtp` there and `EMAIL_PROVIDER=nodemailer` on `ro-backend`, set `MOCK_EMAIL_MODE=false`, and first solve the ledger storage issue above. Send only to test addresses you own before any campaign.

## Remaining blockers and limits

- **Not yet validated against live services.** Google Places and SMTP have only been tested with mocked responses. The first real run needs your own keys and a supervised test.
- **Single instance only.** The campaign sender runs as a background worker inside `ro-backend`, and the rate limiter counts requests in memory. Keep `ro-backend` at one instance. Running several would duplicate background work and weaken rate limits.
- **Single admin password.** There is one shared password and no user accounts, roles or password reset.
- **Email ledger on ephemeral disk** (see above).
- **Render plan costs.** The Starter plans and the PostgreSQL plan cost money. Free web services sleep after inactivity, which delays the first request. Check the current plan options before you choose.
- **Blueprint details to confirm on first sync.** The Blueprint uses the `hostport` property and an `envVarKey` reference to share `EMAIL_SERVICE_SECRET` between services. Confirm both on the dashboard after the first sync. If Render rejects either, set `EMAIL_SERVICE_URL` and `EMAIL_SERVICE_SECRET` on `ro-backend` by hand, using the private address and the secret from `ro-email`.
- **Rotating secrets.** Changing `SESSION_SECRET` signs everyone out. Changing `EMAIL_SERVICE_SECRET` requires updating both services at the same time.
- **Node and Python versions.** `render.yaml` pins Python 3.13.0 and Node 24.20.0. Confirm Render still offers these versions when you deploy.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Sign-in page says "Could not reach the server" | `VITE_API_ORIGIN` is empty or wrong. Set it and rebuild the static site. |
| Login returns HTTP 429 | Too many sign-in attempts from one address. Wait 15 minutes. |
| An upload returns HTTP 413 | The request body is larger than `MAX_REQUEST_BYTES`. |
| Browser shows a CORS error | `CORS_ORIGINS` does not match the frontend URL exactly (scheme, no trailing slash). |
| Signed in but every request returns 401 | Browser blocks third-party cookies. Both sites must use `https`. |
| Backend exits at startup | Read the log line. Usually `SESSION_SECRET` or `DATABASE_URL` is missing or too short. |
| Health check fails on `ro-email` | Health check path should be `/livez`, not `/health`. |
| Migration script says the target has rows | You are not using an empty database. Create a new one and retry. |
