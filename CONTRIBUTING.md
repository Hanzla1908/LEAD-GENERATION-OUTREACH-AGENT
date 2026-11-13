# Contributing

`main` is the stable production branch. Every change reaches it through a feature branch and a pull request. Nothing is
committed or pushed directly to `main`.

## Rules

- Never develop on `main`. Create `feature/<name>` from an up-to-date `main`.
- Never commit `.env`, API keys, passwords, database credentials or private keys. Only `.env.example` (placeholders) is tracked.
- Never force-push `main` or any shared branch. Never delete `main`.
- Every pull request targets `main` and uses the template in `.github/PULL_REQUEST_TEMPLATE.md`.
- Merge only after the repository owner approves and every required check passes. Nothing is merged automatically.
- Keep Demo Mode and Mock Email Mode on for development and tests. Tests never send real email and never call Google.
- If a database migration is part of the change, say so in the pull request, and test both upgrade and downgrade.

## Workflow

1. Update your local `main`:

   ```bash
   git checkout main
   git pull --ff-only origin main
   ```

2. Create a feature branch from `main`:

   ```bash
   git checkout -b feature/feature-name
   ```

3. Implement the change and run the checks locally (see "Checks" below).

4. Commit and push the feature branch:

   ```bash
   git add <files>
   git commit -m "Short summary of the change"
   git push -u origin feature/feature-name
   ```

5. Open a pull request into `main`:

   ```bash
   gh pr create --base main --head feature/feature-name --fill
   ```

   Or open it on GitHub. Fill in every section of the template, including screenshots for visible changes.

6. Wait for CI (`backend`, `frontend`, `frontend-e2e`, `email-service`, `secret-scan`) to pass. Open the Vercel
   Preview Deployment linked from the pull request and test the change there.

7. Check for merge conflicts. If there are any, merge the latest `main` into the feature branch and resolve them. Do not
   merge with unresolved conflicts or unresolved review conversations.

8. Merge only after the repository owner's approval and all required checks pass.

9. Vercel deploys the merged `main` to production automatically. The backend is deployed separately on Render (see
   `docs/GITHUB_AND_VERCEL.md`).

## Checks to run before opening a pull request

```bash
# Backend (from backend/)
python -m pytest -q

# Frontend (from frontend/)
npm test
npm run build
npx playwright test            # end-to-end, uses the mocked backend

# Email service (from email-service/)
npm test
```

## Creating a new feature branch quickly

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feature/my-change
```

## Database migrations

- Add a new revision in `backend/migrations/versions/` with a new id (for example `0015_...`). Never edit an applied one.
- Test on an existing SQLite file and, when relevant, on PostgreSQL (`TEST_POSTGRES_URL`).
- Describe the migration in the pull request template, including how existing records are kept.
