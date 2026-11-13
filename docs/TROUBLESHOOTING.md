# Troubleshooting

Find the message you see, then follow the fix. Messages are quoted as the app shows them.

## Searching for restaurants

| Message or symptom | Cause | Fix |
|---|---|---|
| Results are all named `[DEMO] …` | Demo mode is on. This is intended until live mode is approved. | Keep demo mode for practice. For live results set `DEMO_MODE=false` and `GOOGLE_PLACES_API_KEY` on the backend, then restart it. |
| "Live mode needs GOOGLE_PLACES_API_KEY" (HTTP 503) | Live mode is on but the key is missing. | Add the key on the backend and restart. Or set `DEMO_MODE=true`. |
| Search returns HTTP 429 | The Google quota is used up, or too many searches in a minute. | Wait, then search again. Check the quota in the Google console. |
| Search returns HTTP 503 with a permission or key message | The key is invalid, or the Places API is not enabled for it. | Check the key, enable Places API (New) on it, and check any key restrictions. |
| A restaurant reads "Google listing expired" | Stored Google details are older than 30 days and were cleared on purpose. | Search again to refresh the listing before you email it. |
| City is not accepted | The city name has characters other than letters, spaces, hyphens, apostrophes and periods. | Use the city list or a plain city name. |

## Websites and emails

| Message or symptom | Cause | Fix |
|---|---|---|
| "Blocked: destination resolves to a private/internal address" | The website's address (or a redirect target) is on a private network. The app will not contact it. | Check the restaurant's website. It may be wrong. |
| "Crawling disallowed by robots.txt" | The site's `robots.txt` forbids the checker. | Respect it. Do not work around it. Find the restaurant's address another way. |
| "Only standard web ports (80 and 443) are checked." | The website URL uses another port. | Correct the website address. |
| "Request timed out" or "Too many redirects" | The site was slow or redirected in a loop. | Check the site in a browser, then check it again later. |
| No email found, but the site has one | Only addresses shown in plain text on the homepage or contact/about pages are read. Addresses inside images or scripts are not. | Add the address by hand only if you verify it from the restaurant itself, and note the source. |

## Drafts and selection

| Message | Cause | Fix |
|---|---|---|
| "Demo or sample records cannot receive outreach drafts." | The restaurant is demo data. | This is intended. Use a live search to get real restaurants. |
| "Restaurant has opted out of outreach." | The restaurant was opted out. | This is intended. Do not contact them. |
| "No contact email on file." / "Contact email is not a valid business address." | No usable address, or the address is a placeholder domain such as `example.com`. | Run **Find emails** again, or check the website. Placeholder domains are excluded automatically. Personal mail domains such as gmail.com are **not** excluded automatically, so check that the address belongs to the business before approving. |
| "Only drafts with status 'draft' can be edited." | The draft is approved or rejected. | Create a new draft (regenerate) if the text needs to change. |
| "Campaign name needs at least 2 characters." | Name too short. | Use a descriptive name, such as "Lahore cafes March". |
| "None of the selected restaurants are eligible" | Every selected restaurant has a reason to be skipped. | Read the reasons in the preview and fix or deselect them. |

## Sending and campaigns

| Message or status | Cause | Fix |
|---|---|---|
| "Approve sending for N draft(s) first." | Some drafts are not approved for this campaign. | Approve them, then approve sending again. |
| "Some drafts are not approved for this campaign. Refresh the page and try again." | A draft changed after you selected it. | Refresh and select the approved drafts again. |
| "Set UNSUBSCRIBE_SECRET and PUBLIC_BASE_URL in .env before sending." | Unsubscribe links cannot be built, so sending is refused. | Set both values (see DEPLOYMENT.md) and restart the backend. |
| "Set SENDER_ADDRESS (your business name and postal address) in .env before live sending." | Live sending is on, but no postal address is set. Live emails must show one. | Set `SENDER_ADDRESS` on the backend and restart. Mock sending does not need it. |
| "Draft is not approved" (skipped) | The draft was rejected or changed after its approval. | Approve the current draft again if you still want to send. |
| "Recipient email changed after the draft was created" (skipped) | The restaurant's address was edited after the draft was written. | Review the draft against the new address. Create a new draft if needed. |
| "This address already received an outreach email" (skipped) | The same address was already emailed in this campaign. | This is intended. Do not send again. |
| "Daily sending limit of N reached." (paused) | `EMAIL_DAILY_LIMIT` was reached. | Resume tomorrow, or raise the limit after you have reviewed the volume. |
| "Sending stopped unexpectedly" (paused) | The background sender hit an error. | Read the backend log for the cause. Fix it, then resume. Nothing is resent automatically. |
| "Nodemailer is selected but EMAIL_SERVICE_URL or EMAIL_SERVICE_SECRET … is not set." | The email provider is configured without its address or secret. | Set both on the backend, using the email service's secret. |
| "Email service is not reachable; nothing was sent." | The email service is down, or its address is wrong. | Start it. Check `/livez` on the email service. Then resume. |
| "Send outcome unknown … Check the provider before retrying." / "Delivered but not recorded" (status **interrupted**) | The provider did not confirm delivery, or the app restarted mid-send. | Check the provider's sent folder before doing anything. Interrupted messages are never resent automatically. |
| Status **failed** with a provider refusal | The provider rejected the address or message. | Correct the address (or drop it), then use **Retry failed**. |

## Accounts and access

| Symptom | Cause | Fix |
|---|---|---|
| The sign-in screen says "Could not reach the server." | The API address is wrong or the backend is down. | Check `VITE_API_ORIGIN` and the backend health page. |
| "Incorrect email or password." | Wrong email or password, or the account is deactivated. | Check the email and password. An admin can reset the password or reactivate the account on the Users page. |
| Too many failed sign-ins (HTTP 429) | Ten attempts from one address in 15 minutes. | Wait 15 minutes. |
| "Sign in required." (HTTP 401) | Session expired (12 hours) or you signed out. | Sign in again. |
| "Missing X-Requested-With header." (HTTP 403) | An outside tool is calling the API without the header. | Use the app's own page, or add the header. |
| "Request body is too large." (HTTP 413) | The request is larger than `MAX_REQUEST_BYTES`. | Send less data at once. |

## Unsubscribe

| Symptom | Cause | Fix |
|---|---|---|
| "This unsubscribe link is invalid." | The link was altered, truncated, or built with a different secret. | Ask the sender to resend. Do not edit the link. |
| The recipient still receives emails | The address was never suppressed, or it is a different address. | Check the suppression list for that exact address (it is stored in lower case). |

## Where to look

- **Backend log:** each line is JSON in production. Look for `request_id` to find all lines for one request. The error page also shows the request ID.
- **Campaign log:** the sending log on each campaign lists every recipient event.
- **Health:** `/health` (process is up) and `/health/ready` (database reachable).
- **Email service:** `/livez` is public. `/health` needs the service secret.
