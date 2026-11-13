# GitHub, branch protection and Vercel setup

This project is three deployable parts. They are hosted differently:

| Part | Location | Where it runs | Notes |
| --- | --- | --- | --- |
| React frontend | `frontend/` | **Vercel** | Static Vite build. Vercel root directory = `frontend`. |
| FastAPI backend | `backend/` | **Render** (`render.yaml`) | Needs a long-running process, PostgreSQL and the migrations on start. Not suited to Vercel's serverless functions in this setup. |
| Nodemailer service | `email-service/` | **Render**, private | Reachable only inside Render's network. Not exposed to the browser. |

The repository is a monorepo. The frontend root for Vercel is `frontend/`. The `frontend/vercel.json` file sets the
build command (`npm run build`), the output folder (`dist`) and the single-page-app rewrite.

## 1. Connect the repository to GitHub

The local repository has no remote yet. Create an empty repository on GitHub, then from the project root run:

```bash
git remote add origin <YOUR_GITHUB_REPOSITORY_URL>
git push -u origin main
git push -u origin feature/github-vercel-setup
```

Use the URL GitHub shows for your new repository. Do not force-push. If the repository already has commits, reconcile
them with `git pull --rebase origin main` before pushing, and ask before overwriting anything on GitHub.

## 2. Rotate exposed keys (required)

The earlier `.env.example` contained a real Anthropic API key and a real Google Places API key. Those values have been
removed from the file, but they were in a file that is not git-ignored and may have been shared. Rotate both:

1. Anthropic: https://console.anthropic.com/ → API keys → create a new key, then revoke the old one. Put the new key in your local `.env`.
2. Google Cloud: https://console.cloud.google.com/apis/credentials → regenerate or delete the old Places key, and restrict the new key to the Places API.

## 3. Branch protection for `main`

If the GitHub CLI is installed and authenticated (`gh auth status`), the repository owner can apply the rules below from the
terminal. Otherwise use the GitHub UI:

**GitHub → repository → Settings → Branches → Add branch ruleset (or Add classic branch protection rule)**

- Branch name pattern: `main`
- [x] Require a pull request before merging
  - Required approvals: 1
  - [x] Dismiss stale approvals when new commits are pushed
- [x] Require status checks to pass before merging
  - [x] Require branches to be up to date before merging
  - Add these required checks (they appear after the first CI run): `secret-scan`, `backend`, `frontend`, `frontend-e2e`, `email-service`
- [x] Require conversation resolution before merging
- [x] Do not allow bypassing the above settings (include administrators)
- [x] Block force pushes
- [x] Do not allow deletions

Do not enable auto-merge.

## 4. Vercel project

1. Vercel dashboard → **Add New… → Project** → import the GitHub repository.
2. Set these values:
   - **Framework Preset:** Vite
   - **Root Directory:** `frontend`
   - **Build Command:** `npm run build` (already in `frontend/vercel.json`)
   - **Output Directory:** `dist`
   - **Install Command:** `npm ci`
3. Settings → Git → **Production Branch:** `main`. Pushes to `main` deploy to production. Every other branch and every pull request gets a Preview Deployment automatically.
4. Settings → Environment Variables (see section 5). Do not put backend or email-service secrets in Vercel.
5. Do not deploy until the owner approves. Creating the project and linking the repository does not publish anything by itself, but review the first production deployment before merging.

## 5. Environment variables

Never paste values into the repository, a pull request, a screenshot or a chat.

### Vercel (frontend)

| Name | Production | Preview | Purpose |
| --- | --- | --- | --- |
| `VITE_API_ORIGIN` | `https://<your-render-backend>.onrender.com` | a staging backend URL (recommended), or the production URL only if you accept that previews read production data | Public backend address the browser calls. Build-time value. No trailing slash, no `/api`. |

### Render backend (`ro-backend` in `render.yaml`)

Set in the Render dashboard (variables marked `sync: false` in `render.yaml`):

| Name | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | AI drafts and lead scoring |
| `GOOGLE_PLACES_API_KEY` | Live discovery. Leave `DEMO_MODE=true` until live search is wanted. |
| `SESSION_SECRET` | Signs sign-in tokens. 32+ characters. |
| `UNSUBSCRIBE_SECRET` | Signs unsubscribe links. 16+ characters, 32+ recommended. |
| `PUBLIC_BASE_URL` | The public address of the deployed backend, used in unsubscribe links. Never localhost for live sending. |
| `CORS_ORIGINS` | Comma-separated frontend origins allowed to call the API, for example `https://<your-vercel-project>.vercel.app`. |
| `SENDER_ADDRESS` | Business name and postal address printed in every live email. Required before live sending. |
| `DEMO_MODE`, `MOCK_EMAIL_MODE` | Keep both `true` until you intentionally go live. |

`DATABASE_URL` is supplied by Render from the `ro-db` PostgreSQL database.

Preview deployments on Vercel use random URLs. The backend `CORS_ORIGINS` list must include each origin that should
call it. Either add the stable branch alias for the frontend, or point previews at a staging backend that allows them.

### Render email service (`ro-email`, private)

Set `EMAIL_SERVICE_SECRET` (16+ characters) and the mail-provider settings in the Render dashboard. The backend holds
the same secret as `EMAIL_SERVICE_SECRET`. Keep `EMAIL_PROVIDER=mock` until real sending is approved.

### Local development

Copy `.env.example` to `.env` (in the project root or in `backend/`) and fill in your own values. Copy
`frontend/.env.example` to `frontend/.env` only when you need to point the local build at a remote backend.

## 6. Deployment order and approval

1. Merge the pull request into `main` (owner approval required).
2. Render deploys the backend and runs `alembic upgrade head` on start.
3. Vercel deploys the frontend from `main`.
4. Check the production site, sign in, and run one discovery search in Demo Mode before enabling live features.

Nothing in this document deploys or publishes anything. Each deployment is started by merging into `main` or by an explicit
action in the Vercel or Render dashboard.
