# Phase 26 — End-to-End UAT Report

Date: 2026-11-06. Scope: whole project as it stands (Phases 1–22 built; Phases 23, 24 and 25 not built).

Test conditions: Demo mode, mock email provider, scratch SQLite database (`scratchpad/uat/uat_scratch.db`), no real emails, no campaigns against real recipients, production database and `.env` not read or changed, nothing deployed. Outbound email went to the in-memory `MockSender`. DNS MX checks were stubbed for the email-validation step. Draft text came from a stub generator, so the live Claude call was not exercised.

## 1. Feature-by-feature status

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Registration | Public sign-up | **Missing** | Phase 23 not built. `POST /auth/register` returns 404. |
| Registration | Bootstrap first admin | Working | `POST /auth/setup` returns 409 once accounts exist. |
| Login | Email/password login, Argon2 | Working | Login works; tests cover Argon2 and legacy-hash upgrade. |
| Login | Generic refusal (no enumeration) | Working | Unknown email and wrong password give identical 401 bodies. |
| Login | Session cookie | Working | `ro_session` is HttpOnly and SameSite. Token not in localStorage. |
| Login | Login rate limiting | Partial | 429 after 5 failed attempts with limiter on. Counts successful logins too (see B-3). Off by default outside production. |
| Verification | Email verification | **Missing** | Phase 24 not built. |
| Recovery | Password reset / recovery | **Missing** | Phase 24 not built. Authenticated password change exists. |
| Profile | Profile page, avatar, name, email change, preferences | **Missing** | Phase 25 not built. |
| Profile | Password change, password policy | Working | Policy rejects a 5-character password. |
| Workspaces | Create, rename, switch, membership | Working | Backend tests and Vitest/Playwright cover these. |
| Workspaces | Invitations (7-day, single use, revocable, hashed) | Working | Backend and frontend tests. |
| Roles | Viewer / operator / admin enforcement | Working | Viewer cannot discover, read audit, or cancel. Operator cannot manage users. |
| Isolation | Records scoped to workspace | Working | Isolation tests pass; each record type is scoped in the store layer. |
| Discovery | Pakistani city search (Demo) | Working | Lahore returns 5 demo rows. 19 cities and 20 cuisine profiles. |
| Discovery | Live Google Places | **Not verified** | No API key in this environment. Refuses with a clear 503 when the key is missing. |
| Discovery | Free-text city | Partial | "Atlantis" is accepted and returns demo rows. Validation is missing (B-7). |
| Website | Website detection | Working | Public site returns `present`, ordering checked. Localhost and private addresses refused by design. |
| Email | Public contact discovery | Partial | Runs on a real site. Example.com has no address to find, so extraction is not proven. |
| Email | Email verification (MX) | Working | Placeholder, malformed and business addresses classified correctly. MX check stubbed. |
| Leads | Qualify, opt-out, lead list | Working | Qualify and opt-out work. Lead filter is in the list endpoint. |
| Selection | Select restaurants, preview eligibility | Working | Preview reports eligible count and reasons. |
| Drafts | Generate, edit, approve, reject | Working | Generation uses a stub. Real Claude call not tested. |
| Demo safety | Demo records cannot receive drafts | Working | 422. Consequence: a full demo-to-send run is impossible without live data. |
| Delivery | Send via mock provider | Working | 3 messages delivered, campaign completed. |
| Delivery | Nodemailer service | Working offline | 18/18 Node tests pass. Live SMTP not run (no real emails allowed). |
| Ledger | Send ledger, repeat-send block | Working | Repeat send returns 409 and delivers nothing. Ledger rows match sent messages. |
| Duplicates | Same campaign name | Working | Alpha blocked with a clear reason. |
| Duplicates | Across different campaigns | **Failed** | Alpha, already emailed by "UAT Launch", was emailed again by "UAT Second Wave" (B-1). |
| Safeguards | Daily sending limit | Working | At limit: campaign paused, recipient stays queued, 0 delivered. |
| Suppression | Manual suppression | Working | Suppressed address excluded from new previews. |
| Suppression | Unsubscribe link | Working | Valid link confirms, forged token gets 400, address suppressed. |
| Bounces | Signed provider webhook | Working | Unsigned request 401. Signed hard bounce recorded as `bounced_hard`. |
| Bounces | Suppression after hard bounce | Not verified | Not checked in this UAT. |
| Replies | Reply tracking (IMAP) | **Not run** | Needs a live mailbox. |
| Analytics | Reporting / dashboard endpoint | **Missing** | No analytics route and no analytics page. Overview shows counts only. |
| Audit | Audit log | Working | 27 entries including discovery and campaign actions. Viewers refused. |
| Persistence | Data after reconnect | Working | Campaign, recipients and ledger present after reconnect. |
| Migrations | Upgrade and downgrade round trip | Working | Downgrade to 0003 and upgrade to head succeed. |
| Migrations | Foreign keys | Working | `PRAGMA foreign_key_check` clean. |
| Deployment | Health and readiness | Working | `/health` and `/health/ready` return ok. |
| Deployment | Live deployment | **Not run** | Not deployed, as instructed. |

## 2. Automated test results

| Suite | Result |
|---|---|
| Backend pytest (full, Phase 22 code) | **496 passed** (11 min). Ran before the test-hygiene fix in B-4. |
| Backend `test_workspaces.py` (after fix) | **26 passed** |
| Frontend Vitest | **181 passed** (15 files) |
| Frontend Playwright (desktop, tablet, mobile) | **29 passed** |
| Frontend production build | **Passes** |
| Node email service (`npm test`) | **18 passed** |
| Phase 26 UAT script (scratch DB) | **48 passed, 2 failed, 3 not run** (53 checks) |

UAT failures: the cross-campaign re-send (B-1) and the missing analytics endpoint (Missing, not a regression).

## 3. Bugs

| ID | Severity | Bug | Evidence | Status |
|---|---|---|---|---|
| B-1 | **High** | Duplicate prevention is per campaign. A restaurant emailed by one campaign can be emailed again by a campaign with a different name. Preview blocks only the same campaign name, and send-time checks use `sent_addresses(campaign_id)`. | UAT: Alpha received 2 messages across two campaigns. Preview said eligible. | Open. Needs a product decision (block globally, or allow with a cooldown). |
| B-2 | Medium | Analytics does not exist. | No route or page. | Open. Missing feature. |
| B-3 | Medium | Login rate limit counts successful logins too. Ten sign-ins in 15 minutes from one IP return 429, which can lock out an office behind one NAT address. | UAT hit 429 after several successful logins. Code counts every request in `services/rate_limit.py`. | Open. Recommend counting failed attempts only. |
| B-4 | Low | Backend test hygiene: `test_workspaces.py` created campaigns that started a real background draft thread, which outlived its test and raised `no such column: workspace_id`. | Warnings in `pytest-p22-final.log`. | **Fixed**: the `world` fixture stubs `_spawn`. Re-run 26/26, no thread warnings. |
| B-5 | Low | Downgrade and re-upgrade drops delivery and reply data on the affected tables. | Downgrade to 0003 removes `delivery_status`; re-upgrade returns it as NULL. | Open. Document: back up before any downgrade. |
| B-6 | Low | Unknown city returns demo rows without a warning. | "Atlantis" returns 200. | Open. |
| B-7 | Low | `api.js` joins validation messages with a double period (`..`). | Known from Phase 22. | Open. |
| B-8 | Low | Regenerate button wording does not match behaviour in the drafts UI. | Known from Phase 22. | Open. |

## 4. Bugs fixed in this phase

- **B-4**: test isolation fix in `backend/tests/test_workspaces.py` (stub `_spawn` in the `world` fixture). No product code changed.

No product behaviour was changed in Phase 26. B-1 is confirmed but not fixed because it needs a product decision on what "duplicate" means.

## 5. Production blockers

1. **B-1 (duplicate outreach across campaigns)**: must be decided and fixed before real sending.
2. **Phases 23–25 not built**: no public sign-up, no email verification, no password recovery, no profile or email change. Acceptable only if the launch is operator-only with accounts created by an admin.
3. **Live verification not done**: live Google Places discovery, live SMTP delivery, and reply tracking through a real mailbox all need credentials and a controlled test. None were run.
4. **Demo mode cannot run an outreach flow end to end**, so the full path can only be proven with live data.

## 6. Prioritised recommendations

1. Decide and fix B-1 (global contact block, or a per-restaurant cooldown). Add a test that a second campaign cannot email the same address.
2. Limit login rate limiting to failed attempts and make it on by default outside development.
3. Run a controlled live test: Google Places with a key, Nodemailer to a test inbox you own, and a reply through the real mailbox.
4. Build Phase 23 (sign-up), then Phase 24 (verification and recovery). Phase 25 can follow.
5. Add a basic analytics endpoint (sent, bounced, replied, opted out per campaign) and a page for it.
6. Validate city input against the catalogue or flag free text.
7. Add a backup step to the deployment runbook before any downgrade.
8. Fix B-7 and B-8.

## 7. Launch-readiness assessment

**Not ready for production sending.** The core workflow (discovery in Demo, qualification, drafts, approval, mock delivery, ledger, suppression, unsubscribe, signed bounces, persistence, migrations) works in the scratch environment. Three things block launch: cross-campaign duplicate outreach (B-1), missing public account flows (Phases 23–25), and no live verification of Google discovery, SMTP delivery, or reply tracking.

Evidence files: `scratchpad/uat/uat_p26.py` (script) and `scratchpad/uat/uat_results.json` (results).
