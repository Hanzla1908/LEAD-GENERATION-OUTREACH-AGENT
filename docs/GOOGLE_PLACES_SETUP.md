# Google Places (New) setup for live restaurant discovery

The app runs in **Demo Mode** until you turn it off. Demo searches return sample records marked `[DEMO]`, never call Google, and can never be emailed.

## 1. Create the Google Cloud key

1. Open https://console.cloud.google.com and create or choose a project.
2. Enable billing for the project. Places API (New) does not run without it.
3. Go to **APIs & Services → Library**, search for **Places API (New)**, and click **Enable**.
4. Go to **APIs & Services → Credentials → Create credentials → API key**.
5. Click the key and set **API restrictions** to **Restrict key → Places API (New)**. Do not leave the key unrestricted.
6. Optional but recommended: set a daily quota under **Quotas** so a bug cannot run up the bill.

Keep the key on the server only. It goes in the backend `.env` file and is never sent to the browser.

## 2. Configure the backend

Edit the project root `.env` (copy the keys from `.env.example` if missing):

```
DEMO_MODE=false
GOOGLE_PLACES_API_KEY=paste-your-key-here
PLACES_MAX_RESULTS=60
PLACES_TIMEOUT_SECONDS=15
```

Restart the backend after any change to `.env`.

## 3. Switching modes

| Mode | Setting | Searches | Google calls |
|---|---|---|---|
| Demo (default) | `DEMO_MODE=true` | Sample `[DEMO]` records | None |
| Live | `DEMO_MODE=false` | Google Places (New) Text Search | Yes, billed |

If live mode is on and the key is missing, the app shows a warning and searches return a clear error. The Settings page shows the active mode.

## 4. Cost and policy notes

- Each search requests only the fields the app uses: place ID, name, address, phone, and website. The field mask never uses `*`.
- Each search follows `nextPageToken` only until the requested number of results is reached, so a search for 20 results needs one request.
- Google's terms limit how long listing content may be kept. The app clears name, address, phone, and website for any Google listing older than 30 days, keeps the place ID, and blocks emailing that restaurant until it is searched again.
- Website checks, email discovery, lead scores, and outreach records are the app's own data and are kept.
- Results are labelled **Powered by Google** on the Leads page.

## 5. Troubleshooting

| Message | Fix |
|---|---|
| "GOOGLE_PLACES_API_KEY was rejected" | Check the key was copied correctly, and that its API restriction includes Places API (New). |
| "Enable Places API (New)" | Enable the API in the key's project and check billing. |
| "quota or rate limit" | Wait, or raise the quota in Google Cloud. |
| "did not answer in time" | Raise `PLACES_TIMEOUT_SECONDS` or retry. |
