# Security audit, monitoring and production testing (Phase 11)

Date: 2026-11-04. Scope: backend (FastAPI), email service (Node.js), frontend (React), database (SQLite and PostgreSQL), dependencies, and deployment configuration. Everything was tested with DEMO_MODE and MOCK_EMAIL_MODE on. No real email was sent, no campaign was launched, no Google Places request was made, and nothing was deployed. The Google Places integration was not modified.

---

## 1. Vulnerabilities found and fixed

| # | Severity | Finding | Fix | Verified by |
|---|---|---|---|---|
| 1 | High | **SSRF through redirects.** The website checker let the HTTP client follow redirects and checked the target only after the request had reached it, so a redirect to `127.0.0.1` or a private address was contacted. | Redirects are followed manually. Each hop is validated before any request is sent to it. | `test_redirect_to_loopback_is_refused_before_any_request`, `test_redirect_loop_is_bounded` |
| 2 | High | **DNS rebinding.** The host was resolved for the check and resolved again for the connection, so a DNS answer could change in between. | Each hop resolves once, rejects any internal address, and connects to the validated IP. The original Host header and TLS server name are kept. | `test_requests_are_pinned_to_the_validated_address`, `test_dns_rebinding_cannot_swap_the_address_after_validation` |
| 3 | High | **Login throttle bypass.** The rate limiter trusted the first `X-Forwarded-For` value, which the client controls, so each attempt could appear to come from a new address. | `X-Forwarded-For` is read only when `TRUST_PROXY_HEADERS` is on (production default), and only the rightmost hop is used. | `test_login_throttle_cannot_be_reset_by_changing_forwarded_for`, `test_trusted_proxy_uses_the_rightmost_hop...` |
| 4 | Medium | **Internal addresses in IPv6 form were not blocked.** `::ffff:127.0.0.1`, NAT64 (`64:ff9b::`) and 6to4 (`2002::/16`) forms bypassed the IPv4 block list. | Mapped addresses are unwrapped before checking, the block list was extended, and the standard `is_private`/`is_loopback`/`is_link_local` checks are applied as well. | `test_internal_addresses_are_blocked` (17 cases) |
| 5 | Medium | **Non-web ports and embedded credentials were allowed** (for example `:22`, `:8080`, `user:pass@host`). | Only ports 80 and 443 are used, and URLs with login details are refused before any lookup. | `test_unsafe_url_syntax_is_refused_without_a_lookup` |
| 6 | Medium | **Proxy settings in the environment could route website checks** outside the address checks. | The website client ignores environment proxies (`trust_env=False`). | `test_website_client_ignores_proxy_environment` |
| 7 | Medium | **An unsafe `robots.txt` was treated as "allowed"** (fail open). | An unsafe robots address now stops the check. An unreachable robots file still counts as allowed, as before. | `test_robots_txt_on_an_internal_address_stops_the_check`, `test_contact_discovery_does_not_fetch_internal_pages` |
| 8 | Medium | **No request size limit.** Any size of JSON body was read into memory. | 64 KB default (`MAX_REQUEST_BYTES`, up to 1 MB). Declared lengths are refused immediately with 413; chunked bodies are counted as they arrive. | `test_declared_oversized_body_is_refused_before_it_is_read`, `test_chunked_body_over_the_limit_is_refused` |
| 9 | Medium | **Sign-out did not end the session.** A copied cookie stayed valid for 12 hours. | Sessions are stored on the server (table `auth_sessions`, migration `0002`). Sign-out deletes the row. | `test_a_copied_cookie_stops_working_after_logout` |
| 10 | Medium | **The admin password was stored as plain text** in the environment. | `ADMIN_PASSWORD_HASH` accepts a salted scrypt hash, created by `scripts/hash_admin_password.py`. Plain `ADMIN_PASSWORD` still works. | `test_password_hash_is_checked_and_never_stored_in_plain_text`, `test_production_accepts_a_valid_hash...` |
| 11 | Medium | **Send-time approval was not rechecked per recipient.** Each row is now checked against the campaign's approved drafts. | Per-row check, under the send lock. | `test_each_send_checks_that_its_draft_was_approved_for_this_campaign` |
| 12 | Medium | **Send-time race.** The daily limit was checked outside the claim step, so two workers could exceed it. Duplicate addresses inside one campaign were not rechecked at send time. | Limit check, claim, eligibility check, send and record now run under one lock. The address check covers the same campaign. Follow-up campaigns to the same address are still allowed, as before, and still need approval. | `test_address_changed_after_approval_is_not_sent_twice_in_one_campaign`, `test_a_later_approved_campaign_may_follow_up_the_same_address` |
| 13 | Medium | **Known dependency vulnerabilities.** `starlette 0.41.3` (10 advisories), `python-dotenv 1.0.1` and `pytest 8.3.5` were pinned. `requirements.txt` also did not match the environment the tests ran in. | Pins updated to fixed versions: fastapi 0.143.2 with starlette 1.8.0, python-dotenv 1.2.4, pytest 9.1.1, pytest-asyncio 1.4.0, uvicorn 0.54.0. Verified in a clean environment. | `pip-audit`: no known vulnerabilities |
| 14 | Low | **Unvalidated unsubscribe token** was echoed into the form action. | Tokens must be 64 lowercase hex characters. Anything else gets a plain 400 page. | `test_malformed_unsubscribe_tokens_are_rejected` |
| 15 | Low | **Recipient update helper accepted any column name** (only internal callers use it today). | Allowlist of five columns. | `test_recipient_updates_accept_only_known_columns` |
| 16 | Low | **List endpoints had no bounds.** | `limit` (1–1000) and `offset` on `/restaurants` and `/outreach/drafts`. Defaults are unchanged. | `test_list_endpoints_reject_unbounded_pages`, `test_pages_are_sliced_by_limit_and_offset` |

Also verified, with no change needed: all secrets come from environment variables; the frontend contains no keys (only the public `VITE_API_ORIGIN`); no SQL is built from user input (the few f-string SQL sites only join generated placeholders or fixed column names); no `dangerouslySetInnerHTML`, `innerHTML` or `eval` in the frontend; the email service uses a constant-time secret comparison, a 64 KB body limit, an allowlist of fields, and header-injection checks; and access logs record paths without query strings.

## 2. Performance fix

| # | Finding | Fix | Result |
|---|---|---|---|
| P1 | `/campaigns` loaded every recipient row for every campaign to count them (N+1 pattern). | One grouped SQL query returns all campaign counters. The result is checked against the detail counts. | 1,767 ms → 52 ms (50 campaigns, 20,000 recipients) |

## 3. Remaining security risks

| Risk | Severity | Notes and action |
|---|---|---|
| One shared admin account, no MFA, no per-account lockout | Medium | Login is throttled per address (10 attempts per 15 minutes). A distributed attacker can keep trying. Use a long random password (or a hash of one) and keep the service private where possible. |
| Login throttle and rate limits are in memory | Medium | Correct only with **one** instance. Keep `ro-backend` at one instance (already documented). |
| Session cookie is `SameSite=None` in production | Low | Required for the cross-site frontend. CSRF protection relies on the custom `X-Requested-With` header plus CORS. |
| Email ledger is on an ephemeral disk | High before real sending | Cannot prevent a duplicate after a restart. Must move to persistent storage before `MAIL_MODE=smtp`. Unchanged from Phase 10. |
| Website text reaches the language model | Medium | Scraped page text is sent to the model when drafts are written. A malicious page could try to steer the draft. Drafts still require human approval before any send. |
| Legal compliance of outreach emails | Medium (business) | The footer contains an unsubscribe link. `SENDER_ADDRESS` is blank by default, so the footer carries no postal address. Set it, and check the rules that apply to you (CAN-SPAM, PECA, GDPR or similar) before any real campaign. |
| Live Google Places and SMTP have never been run against live services | Medium | Tested only with mocks. The first live run needs your own keys and a supervised test. |
| Local `restaurant_outreach.db` at the project root contains real-looking restaurant contact data | Low | Keep it out of shared folders and out of commits (already git-ignored). |
| Relative `DATABASE_URL` depends on the working directory | Low | Two different SQLite files can be used, depending on where the server starts. Set an absolute path in local `.env` files. |
| Frontend dependencies are behind major versions (React 18 → 19, Vite 6 → 8) | Low | No advisories reported. Upgrade as a separate task, not as part of security work. |
| Sign-in screen not exercised in a browser | Low | Built and type-checked, and the API it uses is tested. Click through it once before deploying. |

## 4. Test results

| Check | Result |
|---|---|
| Backend, SQLite (`pytest`) | 288 passed |
| Backend, PostgreSQL 18.6 (`TEST_POSTGRES_URL`) | 288 passed |
| Security and hardening (`test_hardening.py`, 57 tests; `test_security.py`, 21 tests) | Passed |
| Logical backup and restore (5 tests, on SQLite and PostgreSQL sources) | Passed |
| End-to-end workflow (`test_e2e_workflow.py`, demo data to campaign sending) | Passed |
| Email service (`npm test`) | 18 passed |
| Frontend production build | Succeeded (JavaScript 229.5 KB, 69.5 KB gzipped; CSS 23.0 KB, 5.0 KB gzipped) |
| `pip-audit` on the pinned environment | No known vulnerabilities |
| `npm audit` (frontend, email service) | 0 vulnerabilities |

## 5. Deployment health (connectivity)

| Link | Check | Result |
|---|---|---|
| Browser → Vite dev server → FastAPI | Dashboard loads through the `/api` proxy and shows live data | Pass |
| Vite proxy → backend | `GET /api/auth/session` returns JSON | Pass |
| Backend CORS | Dev origin allowed with credentials; untrusted origin gets no allow-origin header | Pass |
| Backend security headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP, request ID | Pass |
| Backend body limit | 200 KB declared body → HTTP 413 | Pass |
| Backend → PostgreSQL | `/health/ready` on a PostgreSQL database; full PostgreSQL test run | Pass |
| Backend → email service (mock) | Health with secret, send, idempotent replay, wrong secret refused, public `/livez` | Pass (`email_link_check`) |
| Render configuration | `render.yaml` parses; Blueprint features not yet confirmed on Render | **Not verified on Render** (no deployment performed) |

## 6. Backup and recovery results

Two drills were run. The first used a **copy** of the local development database. Only its `restaurants` table had data (23 rows); the other six tables were empty. The original file was read but not modified (its checksum was unchanged). The second used a **synthetic** PostgreSQL dataset that fills every table, so it tests the restore at realistic volume.

Drill 1: copy of the local development database

| Step | Result |
|---|---|
| Migrate the copy to the current schema (`0002` adds `auth_sessions`) | All 23 rows kept; `auth_sessions` created |
| Export every table (`scripts/logical_backup.py export`) | Row counts match the database; SHA-256 manifest written |
| Restore into a new, empty PostgreSQL database | All seven tables restored |
| Export the restored database again | Row counts and file checksums identical to the backup for all seven tables |
| Integrity checks on the restored database | 0 orphan drafts, 0 orphan recipients, 0 duplicate active drafts, sequences ahead of IDs, `auth_sessions` present, revision `0002_auth_sessions` |
| Tampered backup | Refused before anything is written (checksum mismatch) |
| Restore into a database that already has data | Refused |

Drill 2: synthetic PostgreSQL dataset (no real data)

| Table | Rows backed up and restored | Exported again: files identical |
|---|---|---|
| restaurants | 20,000 | Yes |
| leads | 0 | Yes |
| email_drafts | 5,000 | Yes |
| campaigns | 50 | Yes |
| campaign_recipients | 20,000 | Yes |
| suppression_list | 500 | Yes |
| campaign_send_logs | 50,000 | Yes |

Export took 6.7 s and restore 18.5 s for 95,550 rows on the local PostgreSQL test server.

Not tested: `pg_dump` and `pg_restore`. The PostgreSQL client tools are not installed on this machine, so the logical backup tool was used instead. Run `pg_dump` once on a computer that has the tools, and restore it into a scratch database, before relying on it (see [DEPLOYMENT.md](DEPLOYMENT.md#backups)).

## 7. Production readiness

**Verdict: ready for a controlled deployment in demo and mock mode, after approval. Not ready for real sending or live Google discovery.**

Before the first deployment:

1. Create `ADMIN_PASSWORD_HASH` with `scripts/hash_admin_password.py`, and set `CORS_ORIGINS`, `PUBLIC_BASE_URL` and `VITE_API_ORIGIN`.
2. Confirm the Render Blueprint behaviour on first sync (`hostport`, and the `envVarKey` shared secret).
3. Sign in once in a browser.

Before any real email:

1. Move the email ledger to persistent storage (remaining risk above).
2. Set `SENDER_ADDRESS` and review the legal requirements for your recipients.
3. Send only to test addresses you own.

Before live Google discovery: add `GOOGLE_PLACES_API_KEY` and set `DEMO_MODE=false`, following [GOOGLE_PLACES_SETUP.md](GOOGLE_PLACES_SETUP.md). Storage limits still apply.

## 8. Local environment findings

- `backend/.venv` is stale: it has FastAPI 0.115.5 and pytest 8.3.5 from the old pins, and it lacks SQLAlchemy, Alembic and psycopg, so the app cannot run from it. Recreate it from `requirements.txt` (see [DEPLOYMENT.md](DEPLOYMENT.md)).
- The running development server (`uvicorn main:app --reload`) started from the project root. Its startup applied migration `0002` to the root `restaurant_outreach.db`, which is the intended behaviour.
- The Python environment used by the earlier test runs was a conda installation with unrelated packages. It is no longer used for testing.

## 9. Not changed

- The Google Places integration (`services/discovery.py`) and its storage rules.
- Outreach content generation and the approval workflow.
- The frontend features (only the earlier Phase 10 changes exist).
- No deployment, no commits, no real email, no live campaign.
