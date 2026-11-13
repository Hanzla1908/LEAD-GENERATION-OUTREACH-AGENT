# Restaurant Outreach: production user guide

This guide covers the day-to-day workflow. It describes what the app does today. For setup and hosting, see [DEPLOYMENT.md](DEPLOYMENT.md). For problems, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Before you start

- **Demo mode** (`DEMO_MODE=true`, the default) shows sample restaurants named `[DEMO] …`. They are for practice only. The app never emails them, never includes them in a campaign, and never writes outreach drafts for them.
- **Live mode** searches Google Places. It needs `GOOGLE_PLACES_API_KEY` on the backend and `DEMO_MODE=false`. Until both are set, the app stays in demo mode.
- **Mock email** (`MOCK_EMAIL_MODE=true`, the default) records messages in the app and delivers nothing. Real delivery needs a configured provider and an explicit change of that setting.

## The workflow at a glance

1. **Find restaurants**: choose a city and a restaurant type, then search.
2. **Check websites**: the app checks whether each website is reachable and whether it offers online ordering.
3. **Find emails**: the app reads public pages on the restaurant's website and keeps only addresses shown there.
4. **Qualify**: each restaurant gets a score and a status (qualified, needs review, or disqualified).
5. **Select**: choose restaurants one at a time or in bulk. Ineligible ones explain why.
6. **Draft**: the app writes a personalised email for each selected restaurant. You read and edit each draft.
7. **Approve**: a draft must be approved before it can be sent. Nothing is sent without approval.
8. **Campaign**: create a campaign from the selection. Preview shows what will be sent and what is skipped.
9. **Send**: approve sending for the campaign, then start. Emails go out at a limited rate. You can pause, cancel or retry failures at any time.
10. **Review**: check the campaign counts and the sending log.

## 1. Find restaurants

1. Open **Restaurant Leads** and choose a city from the Pakistan list, or type a city name.
2. Choose a restaurant type (for example Biryani, Fast food, Cafe).
3. Choose how many results to fetch (1 to 60) and search.

Results are saved. Restaurants found by a search are kept in the local database. Google listing details are kept for at most 30 days and then cleared automatically; search again to refresh them.

## 2. Check websites

Select restaurants and choose **Check websites**, or open a restaurant and check it individually. The result shows whether the site is present, not found, or unknown, and whether online ordering was detected, with the evidence (links or button text) that led to that conclusion.

The checker never runs a site's JavaScript, obeys `robots.txt`, and refuses addresses on private networks.

## 3. Find contact emails

Select restaurants and choose **Find emails**. The app reads the homepage and up to four contact or about pages. Every address it keeps is shown with the page it came from, and is marked **unverified**. The app does not guess addresses and does not confirm that a mailbox exists.

Check the source page before you rely on an address.

## 4. Qualify leads

Qualification uses fixed rules, not the language model:

| Factor | Points |
|---|---|
| Website reachable | +30 |
| Website not reachable | −40 |
| No online ordering found (an opportunity) | +25 |
| Online ordering already in place | −20 |
| Email address found | +25 |
| Phone number available | +10 |

Score 55 or more is **qualified**. Score 20 to 54 needs **review**. Below 20 is **disqualified**. A short explanation is written for each restaurant. The language model only words that explanation.

An unverified email still adds points. Treat the score as a ranking aid, not proof that the restaurant is a good prospect.

## 5. Select restaurants

- **Individually:** tick the restaurant in the list.
- **In bulk:** select several, or use the selection controls.
- Restaurants that are not eligible show the reasons (for example "Not qualified", "No public email found", "Restaurant has opted out of outreach", "Demo or sample record").

## 6. Write and approve drafts

1. Open **Outreach Drafts**, or generate a draft from a restaurant.
2. Read the subject and body. Edit them if needed. Edits are allowed only while a draft is still a draft.
3. Choose **Approve** for drafts you are happy with, or **Reject** to discard them.

Approval is per draft and per text. If you change a draft after approval, it must be approved again. Rejected drafts never reach a campaign.

## 7. Create a campaign

1. From the selection, choose **Create campaign** and give it a name.
2. Read the preview. It shows the eligible restaurants and the reason for each skipped one.
3. Confirm. The app writes one draft per eligible restaurant. Review and approve each draft as described above.

A campaign name cannot be reused for the same address: the app will not email an address twice within one campaign name. A later campaign with a different name may contact the same address again, but each campaign still needs its own approval.

## 8. Send a campaign

1. Open the campaign and check the recipient list.
2. Choose **Approve sending** and select the approved drafts you want to send. This is the explicit approval step.
3. Choose **Send**. The app checks each recipient again immediately before sending.

While a campaign is running you can:

- **Pause**: stops after the current email. Resume later.
- **Cancel**: stops all queued emails. Emails already sent stay sent.
- **Retry failed**: resends only messages whose delivery definitely failed, never ones that might have been delivered.
- **Retry drafts**: regenerates drafts that failed to generate.

Sending limits: the app sends at most `EMAIL_PER_MINUTE` emails a minute (default 5) and `EMAIL_DAILY_LIMIT` a day (default 100). When the daily limit is reached, the campaign pauses until the next day.

Every email includes an unsubscribe link in its footer.

## 9. Campaign results and logs

- **Counts** on each campaign: selected, eligible, drafts, approved, queued, sent, failed, retryable, interrupted, skipped and cancelled.
- **Sending log**: one line per recipient event (approved, sent, failed, skipped), with the reason.

The app does not track opens or clicks, and it does not receive replies. Check your mailbox for replies. See the limits in the acceptance report.

## 10. Opt-outs and unsubscribe

- Each email has an unsubscribe link. The recipient opens it, sees a confirmation page, and confirms. The address is then added to the suppression list and is never emailed again by any campaign.
- You can also click **Opt out** on a restaurant. That blocks new drafts and campaigns for that restaurant.
- Any address on the suppression list is excluded from all campaigns, including ones that were already selected.

If someone asks to be removed by email, use the app's opt-out for their restaurant. The suppression list can also be updated through the API (no screen yet).

## 11. Data you must protect

- Restaurant names, addresses, phone numbers and contact emails are personal and commercial contact data. Keep exports and backups private.
- Keep API keys and passwords out of chat, email and screenshots.
- Use outreach only where the law allows it for your recipients. Include your real business name and postal address in each message (set `SENDER_ADDRESS`). Review the rules that apply to your region before any campaign.
