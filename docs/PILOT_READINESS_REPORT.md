# Pilot readiness report (Phase 13)

Date: 2026-11-04.

## Pilot readiness status

**NOT READY. The pilot has not started, and no contact has been emailed.**

The pilot needs three things that do not exist yet:

1. **Real restaurants.** The Google Places key is empty, so the database holds only the 23 demo records. There are zero real restaurants and zero real contact emails.
2. **A delivery channel.** No SMTP account or email provider is configured, and the email service has no credentials. Delivery to your own address has therefore not been tested.
3. **Required settings.** `UNSUBSCRIBE_SECRET`, `PUBLIC_BASE_URL` and `SENDER_ADDRESS` are not set. The app refuses to send until the first two are set.

I did not invent contacts, did not send anything, and did not start a campaign.

## Integrations

| Integration | Status | Evidence |
|---|---|---|
| Google Places (live) | **Not working.** No key. | Mocked tests only. `GOOGLE_PLACES_API_KEY` is empty. |
| Website checking | **Working on the live internet.** | `example.com` and `iana.org` return `present`. The internal address `127.0.0.1` is refused. |
| Email discovery | **Partly verified live.** | Live fetch of `example.com` succeeded (1 page checked). The addresses found were not recorded, so this is not evidence of extraction accuracy. Extraction is covered by mocked tests only. |
| Lead qualification | Works (deterministic rules, tested). | No real data to judge quality. |
| Bulk selection and campaign management | Works (tested end to end on mock sender). | Campaign, preview, approval and sending tests. |
| Nodemailer email service | Works in mock mode. | Backend to service: health, send, idempotent replay and wrong-secret refusal all verified in Phase 11. |
| SMTP | **Not configured.** | Code path tested with mocks. No server or credentials exist. |
| Delivery to your own address | **Not tested.** | Requires a provider, your approval, and the `send_test_email.py --confirm` step. |

## Test results

| Check | Result |
|---|---|
| Backend, SQLite | 297 passed |
| Backend, PostgreSQL | 297 passed |
| Batch concurrency test (new) | Passed. Checks run in parallel, capped at 5, results keep request order. |
| Live website check against public sites | Passed (see Integrations) |
| Email service (Node) | 18 passed (unchanged this phase) |

## Changes made in this phase

1. **Batch website checks and batch email searches now run up to 5 at a time** (previously one at a time). Results and database writes keep the request order. A batch of 50 no longer waits for 50 sequential network round trips.
2. **Index migration `0003_list_indexes`.** Measured on a synthetic 20,000-restaurant PostgreSQL dataset: first page of restaurants 10.7 ms → 1.7 ms; deep page (offset 15,000) 51 ms → 5.3 ms. Campaign recipient lookups gained a `(campaign_id, status)` index.

No functional bugs were confirmed in this phase. The bugs found in Phase 12 were already fixed.

## Campaign performance

**No real campaign performance can be reported.** No real campaign has run and none has been sent. Delivery, bounce, reply and open rates are unknown.

The only numbers available are the synthetic measurements (not campaign results):

| Operation (synthetic data, 20,000 restaurants, 20,000 recipients) | Median time |
|---|---|
| Health check | 6.7 ms |
| Restaurant list, first page | 36.8 ms through the API (1.7 ms in the query after the index) |
| Campaign list (50 campaigns) | 51.9 ms (was 1,767 ms before the Phase 11 fix) |
| Campaign detail | 95 ms |
| Eligibility for all restaurants (5,000 cap) | 356 ms |

## Lead quality and email relevance

**Cannot be evaluated.** Every restaurant in the database is demo data, so there is nothing to judge.

Two points are already visible from the code:

- A found email adds 25 points to a lead's score even though the email is unverified. A lead can qualify on that alone.
- Outreach drafts are written from website evidence and the qualification facts only. Their relevance needs a human review of real drafts before any pilot.

## Bottlenecks and recommendations

| Bottleneck | Impact | Recommendation |
|---|---|---|
| Email sending is rate-limited on purpose | Defaults are 5 emails a minute and 100 a day, which the daily cap makes the real limit. Intentional, and it protects sender reputation. | Keep the limits. Raise them only after a clean pilot. |
| Eligibility check reads up to 5,000 restaurants | 356 ms now, grows with the database | Page it or compute it in SQL once the database grows past 5,000. |
| Each send re-reads the suppression list and sent addresses | Fine for hundreds of recipients; grows with the list | Cache per campaign run if campaigns grow past a few thousand. |
| Qualification list capped at 200 | Leads beyond 200 are not shown | Add paging before scale (not needed for a 5-to-10-contact pilot). |
| No bounce or reply processing | Failures are known only at send time; replies are invisible in the app | Add provider bounce webhooks or inbound parsing before a larger campaign. |
| Email ledger on temporary disk | A restart could allow a duplicate send | Move to persistent storage before real sending. This is a blocker. |
| Unverified addresses | Wasted sends and higher bounce risk | Verify each pilot address by hand, and add a domain check before scaling. |

## Blockers, in order

1. `GOOGLE_PLACES_API_KEY` (or an agreed plan to pilot from a manual list you verify yourself, which would need a feature that does not exist).
2. A delivery provider, with credentials stored only on the email service.
3. `UNSUBSCRIBE_SECRET`, `PUBLIC_BASE_URL` and `SENDER_ADDRESS` set on the backend.
4. Persistent storage for the email ledger.
5. Your approval, at each step below.

## Approval gates (nothing happens without these)

1. **Your own address:** approve one `[TEST]` message to your address. Then run `python scripts/send_test_email.py --to <your address> --confirm` with the provider configured and `MOCK_EMAIL_MODE=false`.
2. **Pilot contact list:** approve the list of 5 to 10 named restaurants with verified emails and their source pages.
3. **Pilot drafts:** approve each draft's text. Approval is per draft.
4. **Pilot campaign:** approve sending for the named drafts only, at a low rate.

## Pilot checklist (when the blockers are cleared)

- [ ] Live discovery in one city and one restaurant type. Check each result on Google Maps by hand.
- [ ] Website checks and email searches on the sample. Open each source page and confirm the address belongs to the business.
- [ ] Remove duplicates and any address on a personal mail domain you cannot confirm belongs to the business.
- [ ] Confirm `UNSUBSCRIBE_SECRET`, `PUBLIC_BASE_URL` and `SENDER_ADDRESS` are set.
- [ ] Test message to your own address, delivered and read.
- [ ] Pilot of 5 to 10 emails. Watch the sending log. Pause on any unexpected result.
- [ ] Check bounces and replies in your own mailbox, and record them. The app does not record them.
- [ ] Confirm every opt-out is in the suppression list and absent from drafts.
- [ ] Review the results with you before any larger campaign.

## Remaining approvals needed from you

1. The Google Places key, or a decision to stay in demo mode.
2. A delivery provider, or a decision to wait.
3. Your business name, postal address and legal basis for contacting each business.
4. Approval for the test message to your own address.
5. Approval of the pilot contact list.
