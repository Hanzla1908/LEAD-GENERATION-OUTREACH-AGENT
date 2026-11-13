# Frontend testing

The frontend has two test layers. Neither one calls a live API, a database, Google Places, Claude,
a mailbox or an email server.

- **Vitest + React Testing Library + MSW** (`tests/unit`, `tests/integration`): components, pages,
  the API client and helpers. MSW answers every request from the in-memory fake backend. Any request
  it does not answer fails the test.
- **Playwright** (`tests/e2e`): the real app in a browser, served by Vite on port 4173. The same fake
  backend answers `/api` through `page.route`. Every other external request is aborted.

The fake backend (`tests/support/fakeBackend.js`) mirrors the response shapes the pages read and the
eligibility rules in `backend/services/campaigns.py`. It does not change the backend or its contracts.

## Commands (Windows)

Run these from the `frontend` folder. On Windows, PowerShell blocks `npm.ps1` under the default
execution policy, so run npm through `cmd /c`:

```bash
cmd /c "npm test"
```

| Command | What it does |
|---|---|
| `cmd /c "npm test"` | Vitest: unit and integration tests, once |
| `cmd /c "npm run test:watch"` | Vitest in watch mode |
| `cmd /c "npm run test:e2e:install"` | One-time: download the Chromium browser for Playwright |
| `cmd /c "npm run test:e2e"` | Playwright: E2E tests on desktop, tablet and mobile |
| `cmd /c "npm run test:all"` | Vitest, then Playwright |
| `cmd /c "npm run build"` | Production build (unchanged) |

Playwright starts its own dev server on `127.0.0.1:4173`. Port 4173 is used so that a developer's
dev server on 5173 is not reused. Set `CI=1` to disable server reuse and enable one retry.

Test reports: `frontend/playwright-report/` (HTML) and `frontend/test-results/` (screenshots and
traces, kept only for failures). Both are git-ignored.

## Layout

```
frontend/
  vitest.config.js            Vitest: jsdom, setup file, include patterns
  playwright.config.js        Playwright: webServer on 4173, desktop / tablet / mobile projects
  .env.test                   VITE_API_ORIGIN=http://api.test (test mode only, no secrets)
  tests/
    setup/vitest.setup.js     jest-dom, MSW lifecycle, fresh fake backend per test
    support/
      fakeBackend.js          in-memory API fake, shared by Vitest and Playwright
      mswServer.js            MSW server wired to the fake
      scenarios.js            deterministic seed data (11 restaurants covering every eligibility case)
      render.jsx              renderAppAt / waitForWorkspace helpers
    unit/                     helpers and the API client
    integration/              pages and components (dashboard, filters, selection, drafts, campaigns, a11y)
    e2e/
      support/mockApi.js      page.route wiring for the fake backend; blocks external requests
      support/app.js          opens the app and waits for it to load
      restaurant-to-campaign.spec.js   the main workflow (desktop)
      responsive.spec.js      no sideways scrolling and reachable navigation (all projects)
```

## Safety

- Every test uses Demo Mode and Mock Email Mode data. Nothing is sent.
- `tests/support` never reads `.env` or any production setting. `.env.test` contains only the
  test API origin.
- Campaign sending in the fake only moves records to "sent" inside the in-memory state. The
  E2E workflow asserts `live_sending` is false.

## Known findings (open)

These are real behaviours the tests expose or that were found while writing them. Finding 1 was fixed
after Phase 20 (see the integration test "Drafts list freshness"):

1. (Fixed) **Outreach Drafts list was stale after a campaign was created.** The drafts list is now
   reloaded each time the Outreach Drafts page is opened.
2. **Regenerate is enabled only for drafts awaiting approval**, but its confirmation text says
   "This draft is rejected". The text and the enabled state disagree.
3. **Validation messages can end in `..`.** `api.js` joins messages with `". "`. A message that already
   ends in a period gives `"required.."`. The unit test documents this and checks that both messages arrive.
4. **The "generating" campaign state is not exercised.** The fake writes drafts synchronously, so the
   progress bar for drafts being written is not tested.
