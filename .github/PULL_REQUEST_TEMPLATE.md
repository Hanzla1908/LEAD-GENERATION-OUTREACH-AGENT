## Summary
<!-- One or two sentences: what changes and why. -->

## Feature description
<!-- What a user or operator sees differently after this change. -->

## Modified files
<!-- Main files and folders changed, and why. -->

## Screenshots
<!-- Required for any visible change: before and after, desktop and phone width. Write "Not applicable" otherwise. -->

## Test results
- [ ] Backend: `python -m pytest -q` in `backend/` passes
- [ ] Frontend: `npm test` in `frontend/` passes
- [ ] Frontend: `npm run build` in `frontend/` passes
- [ ] End-to-end: `npx playwright test` in `frontend/` passes (or not affected)
- [ ] Email service: `npm test` in `email-service/` passes (or not affected)
- [ ] Manual check on the Vercel Preview Deployment (link below)

Preview deployment: <!-- paste the Vercel preview URL -->

## Database migrations
- [ ] No migration in this change
- [ ] Migration added: <!-- revision id, for example 0015_something -->
  - Upgrade tested on an existing database: <!-- yes / no -->
  - Downgrade tested: <!-- yes / no -->
  - Existing records preserved: <!-- how it was checked -->

## Configuration and environment variables
<!-- New or changed variables, in .env.example and in the Render and Vercel dashboards. Never paste values. -->

## Deployment risks
<!-- What could go wrong in production, how it would be noticed, and how to roll back. Write "None" only if true. -->

## Safety checklist
- [ ] No `.env` file, API key, password or database credential is in this change
- [ ] Mock Email Mode is still the default; no test sends real email
- [ ] Email limits, duplicate-send protection and unsubscribe handling are unchanged, or the change is described above
- [ ] This branch is up to date with `main` and has no merge conflicts
- [ ] Every review conversation is resolved

---
Merging into `main` needs the repository owner's approval. Do not merge until every required check passes and the owner has approved.
