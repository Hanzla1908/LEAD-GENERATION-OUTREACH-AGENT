# Launch acceptance report (Phase 12)

Date: 2026-11-04.

## Verdict

**NOT READY FOR LAUNCH.** The software is tested and its safety rules hold in every test that runs here. But the launch cannot proceed yet. The critical requirements that need real data, real credentials and a real deployment are not met, so production readiness cannot be claimed.

What was done in this phase:

- Nothing was sent. No email left the machine, no campaign was started, and no Google Places request was made.
- No pilot campaign was prepared. A pilot needs verified, eligible business contacts from live Google data and a real delivery channel. Neither exists here, and no contact was invented.
- Nothing was deployed. The Render services have not been created.

## 1. Workflow audit

| Stage | Status | Evidence |
|---|---|---|
| Restaurant discovery (demo) | Works | Demo records, `[DEMO]` names, 14 Pakistan city and cuisine tests pass |
| Restaurant discovery (live Google Places) | **Not verified live** | Tested with mocked Places responses only. `GOOGLE_PLACES_API_KEY` is empty. |
| Website checking | Works (tested with mocks) | SSRF, redirect, pinning, robots and port tests (Phase 11) |
| Email discovery | Works (tested with mocks) | Contact discovery tests. Addresses come only from public pages and are marked `unverified`. |
| Lead qualification | Works | Deterministic scoring tests; the language model only writes the explanation |
| Selection (individual and bulk) | Works. **One bug fixed:** lists were cut at 200 restaurants and 200 drafts. | Client now pages through all results |
| Personalised drafts | Works (not exercised live: Claude calls were mocked) | Draft tests; demo records now blocked |
| Draft approval | Works. **Fixed:** demo drafts could be approved or regenerated. | `test_launch_safety.py` |
| Bulk campaigns and preview | Works | Campaign tests; mixed selections send only real restaurants |
| Sending limits | Works | Per-minute and daily limit tests (mock sender) |
| Duplicate prevention | Works | Same-address and duplicate-draft tests |
| Unsubscribe and opt-outs | Works | Confirm-then-post flow, forged-token refusal, opt-out blocks drafts and campaigns |
| Email tracking (delivery status) | Partial | Provider acceptance, failures and retries are recorded. Opens, clicks and replies are not tracked (see gaps). |

## 2. Safety rules checked

| Rule | Result |
|---|---|
| Demo records never enter real campaigns | Enforced at four points: campaign creation, queue check, send-time check, and the draft endpoints (added this phase). Tested. |
| No unapproved email is sent | Approval is required per draft and again for sending. Tested. |
| Invalid, placeholder, duplicate or opted-out contacts are not emailed | Placeholder domains, suppression, opt-out, same-address and changed-address checks. Tested. |
| Mock email is the default | Yes. Real delivery needs `MOCK_EMAIL_MODE=false` and a provider. |
| Credentials stay out of the frontend and logs | Verified in Phase 11. No change in this phase. |

## 3. Test results

| Check | Result |
|---|---|
| Backend, SQLite (`pytest`) | 296 passed |
| Backend, PostgreSQL 18.6 | 296 passed |
| Launch-safety tests (new, `test_launch_safety.py`) | 8 passed |
| Pakistan city, cuisine and demo-mode tests | 14 passed |
| Email service (Node) | 18 passed |
| Frontend production build | Succeeds (229.7 KB JavaScript, 69.6 KB gzipped) |
| Test-send script (dry run, invalid address, mock send) | Behaves as designed; nothing delivered |

Tests run with mocked Google Places, mocked Claude and the mock email provider. They do not prove live behaviour.

## 4. Bugs fixed in this phase

1. **Demo drafts could be generated, approved or regenerated** through the single-draft endpoints. Campaign paths were already protected. Now blocked with HTTP 422.
2. **Selection lists were silently truncated** at 200 restaurants and 200 drafts. The client now reads every page (up to 50,000 restaurants).

## 5. Remaining bugs and gaps

| # | Item | Severity | Notes |
|---|---|---|---|
| G1 | No reply tracking. Replies arrive in the sender's mailbox and the app never sees them. | High for analytics | Needs inbound mail integration, which needs credentials. |
| G2 | No bounce handling. Bounce notices are not read; failures are known only at send time. | High | Provider bounce webhooks or inbound parsing are needed. |
| G3 | No open or click tracking. | Low (deliberate) | Tracking pixels and link tracking are intentionally not added. |
| G4 | Qualification list (`/restaurants/leads`) returns at most 200 leads. | Medium | Fine at current volume; add paging before scale. |
| G5 | The eligibility check reads at most 5,000 restaurants. | Low | Raise or page when the database grows. |
| G6 | Suppression list has an API but no screen. | Low | Use the API for manual removals. |
| G7 | Email addresses are not verified (no deliverability or mailbox check). | Medium | Addresses stay `unverified`. Check each one manually before a pilot. |
| G8 | Personal mail domains (for example gmail.com) are not excluded automatically. | Medium | Check each address belongs to the business. |
| G9 | Email ledger is on the email service's temporary disk. | High before real sending | A restart could allow a duplicate. Move it to persistent storage first. |
| G10 | Single instance only (background sender and login throttle live in memory). | Medium | Keep one backend instance. |
| G11 | The local `.env` is missing `UNSUBSCRIBE_SECRET` and `PUBLIC_BASE_URL`. Sending is refused until they are set. | Blocker for sending | The app refuses to send, which is the correct behaviour. |
| G12 | `backend/.venv` is stale and cannot run the app (Phase 11 finding). | Low | Recreate from `requirements.txt`. |

## 6. Missing credentials and integrations

| Item | Status | Needed for |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | **Empty** | Real restaurant discovery |
| `ANTHROPIC_API_KEY` | Set | Draft and explanation text (not exercised live in this phase) |
| `UNSUBSCRIBE_SECRET`, `PUBLIC_BASE_URL` | **Not set** | Any sending at all |
| `SENDER_ADDRESS` | Not set | Your business name and postal address in every email (legal requirement, see the user guide) |
| Email provider: SMTP account or a Nodemailer-backed provider, with `EMAIL_SERVICE_SECRET` | **Not set** | Any real delivery, including your own test address |
| Deployed backend, frontend, database and email service on Render | **Not created** | Hosted use |

## 7. Connectivity and deployment status

| Link | Status |
|---|---|
| Browser → Vite dev server → FastAPI | Verified earlier in Phase 11 (dashboard loads with live local data) |
| Backend → PostgreSQL | Verified (full test run on PostgreSQL) |
| Backend → Node email service (mock) | Verified earlier in Phase 11 |
| Node email service → real provider | **Not verified** (no provider) |
| Render (frontend, backend, database, email service) | **Not deployed** |
| Blueprint features (`hostport`, `envVarKey`) | Not confirmed on Render |

## 8. Production blockers

These must be resolved before any real email is sent:

1. **No live restaurant data.** Live Google discovery needs your Google Places key. Without it, every restaurant is a demo record.
2. **No delivery channel.** No SMTP account or email provider credentials exist, so delivery to your own address cannot be tested.
3. **Email ledger on a temporary disk** (G9).
4. **Sending settings not configured** (G11), and no sender identity or postal address (`SENDER_ADDRESS`).
5. **Not deployed.** The hosted system has not been verified.
6. **Reply and bounce handling absent** (G1, G2). Campaign results are incomplete without them.
7. **Legal review.** Confirm the rules that apply to your recipients (for example CAN-SPAM, PECA, GDPR), your lawful basis for contacting each business, and the wording of your unsubscribe and footer text. This is your decision, not something the software can determine.
8. **Address verification** (G7, G8): each pilot address must be checked by you.

## 9. Controlled launch checklist

Work through these in order. Each step that sends mail needs your explicit approval first.

**A. Configuration (no mail sent)**

- [ ] Set `UNSUBSCRIBE_SECRET` (32+ random characters) and `PUBLIC_BASE_URL` in the backend environment.
- [ ] Set `SENDER_ADDRESS` to your business name and postal address.
- [ ] Decide on live discovery. If yes: set `GOOGLE_PLACES_API_KEY`, `DEMO_MODE=false`. Check the key's quota and restrictions in the Google console.
- [ ] Move the email ledger to persistent storage (G9) before any real sending.
- [ ] Set `ADMIN_PASSWORD_HASH` and the production CORS and public URLs.

**B. Deployment (no mail sent)**

- [ ] Create the Render Blueprint and confirm the private email service link.
- [ ] Check `/health`, `/health/ready`, `/livez`, and the sign-in screen.
- [ ] Take a logical backup, restore it into a scratch database, and check the counts (see the deployment guide).

**C. Data quality (no mail sent)**

- [ ] Run a live discovery in one city and one restaurant type. Check each result against Google Maps by hand.
- [ ] Run website checks and email discovery on a small sample. Open each source page and confirm the address is the business's.
- [ ] Review qualification scores for the sample. Remove any restaurant whose evidence does not hold.

**D. Delivery test to your own address (requires your approval)**

- [ ] Configure a provider and set `MOCK_EMAIL_MODE=false`.
- [ ] Run `python scripts/send_test_email.py --to <your address> --confirm`. This sends one `[TEST]` message to you only.
- [ ] Confirm the message arrives, shows your sender name, and that the unsubscribe link works.
- [ ] Reply to nothing. Note any spam-folder placement.

**E. Pilot campaign (requires your explicit approval of the named contacts)**

- [ ] Choose 5 to 10 restaurants with verified public emails. Write the list down, with source page for each address.
- [ ] Generate drafts. Read every draft in full. Approve only the drafts you would send to a friend.
- [ ] Create the campaign. Check the preview shows no demo or duplicate entries.
- [ ] Approve sending for the named drafts only, then start the campaign at `EMAIL_PER_MINUTE=1` for the pilot.
- [ ] Watch the sending log. Pause at the first unexpected result.

**F. Review after the pilot (no mail sent)**

- [ ] Check bounces and replies in your mailbox. Record them in your own tracker, because the app does not record them.
- [ ] Check every opt-out was honoured: the address should be in the suppression list and absent from drafts.
- [ ] Decide, based on results and your legal review, whether to continue. Any larger campaign needs a new explicit approval.

## 10. Remaining approvals needed from you

1. Provide the Google Places key (or confirm you will stay in demo mode).
2. Provide a delivery provider, or confirm the pilot waits until one is configured.
3. Confirm your business name, postal address and the legal basis you rely on.
4. Approve Render deployment.
5. Approve the one-message delivery test to your own address.
6. Approve the pilot contact list, once it exists.
