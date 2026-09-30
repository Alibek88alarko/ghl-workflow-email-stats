# GoHighLevel workflow email stats → Google Sheets, one click

Every email that goes out from a GoHighLevel **workflow** has its own statistics, but GHL only shows them
one step at a time, inside the workflow editor. Agencies with dozens of workflows copy those numbers by hand
every month. This tool pulls all of them into one Google Sheet with a menu click, through the official
HighLevel Email API v3.

One row per email step:

| Workflow | Step | Subject | From | Sent | Delivered | Opened | Clicked | Replied | Unsubscribed | Complained | Hard bounces | Soft bounces | Open rate % | Click rate % | ... |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

Demo output (fake data): [`demo/report-demo.csv`](demo/report-demo.csv).

## Status

Version 0.1. Built from the official HighLevel API v3 spec and tested against an imitation of that API.
It has not been run on a live agency account yet. I'm looking for 3 to 5 agencies to try it for free on one
sub-account and tell me what breaks. Open an issue or write to me, and I'll help with setup.

## What you get

- `apps-script/Code.gs`: the Google Sheets version. Menu **GHL Report → Refresh report**. Optional monthly
  auto-refresh on the 1st. Token is stored in your Google account's script properties, never in a cell.
- `python/ghl_report.py`: the same logic as a command line tool that writes a CSV, for people who prefer that.
- `tests/`: 9 pytest checks against an in-memory imitation of the API (pagination, id fallback, rate maths,
  bad token). `apps-script/test_code.mjs` runs the Sheets logic under Node with the same fake API.

## Install (Google Sheets, about 10 minutes)

1. Create a blank Google Sheet. **Extensions → Apps Script**. Delete the sample code, paste the contents of
   `apps-script/Code.gs`, click **Save**. Reload the sheet: a **GHL Report** menu appears.
2. In GoHighLevel, open the **sub-account** (not the agency view): **Settings → Private Integrations → New**.
   Name it anything, tick two scopes: **emails/campaigns.readonly** and **emails/stats.readonly**. Copy the token.
3. Sheet menu **GHL Report → Set API token**, paste it.
4. **Settings → Business Profile** in the same sub-account, copy the **Location ID**. Menu **GHL Report → Set Location ID**.
5. **GHL Report → Refresh report**. The first run shows Google's permission screen: *This app isn't verified*
   → **Advanced** → **Go to (unsafe)** → **Allow**. That screen is Google's standard warning for any script you
   paste yourself; it asks for permission to call an external service (GoHighLevel) and to edit this sheet.
6. Optional: **GHL Report → Schedule monthly refresh**.

Two sheets appear: **Report** (the rows) and **Info** (last refreshed, counts, and any errors).

## Command line version

```
pip install httpx
python python/ghl_report.py --token pit-xxxx --location XXXXXXXX --out report.csv
python python/ghl_report.py --token pit-xxxx --location XXXXXXXX --include-email-campaigns
```

## How it works

Three calls, all under `https://services.leadconnectorhq.com` with header `Version: v3`:

1. `GET /emails/locations/{locationId}/campaigns/workflows?status=published&limit=20&offset=N` lists workflows.
2. `GET /emails/locations/{locationId}/campaigns/workflows/{campaignId}` returns the email steps (`subSources`).
3. `GET /emails/locations/{locationId}/campaigns/stats/workflow-campaigns/{sourceId}?subSourceId={stepId}`
   returns sent, accepted, delivered, opened, clicked, replied, unsubscribed, complained, permanentFail,
   temporaryFail, rejected, failed and the rates.

The spec is not explicit about whether the stats call wants the workflow's `sourceId` or its `id`, so the tool
tries `sourceId` first and falls back to `id`, and records which one worked. Rates missing from the API are
computed from the counts. Calls are spaced 120 ms apart to stay under the 100 requests per 10 seconds limit.

## Limits and notes

- Only **published** workflows are listed. Draft workflows have no sends anyway.
- The token must come from the sub-account whose data you want. One sheet = one sub-account. For several
  clients, copy the sheet per client.
- The Google "unverified app" screen appears once per sheet. Publishing as a verified add-on would remove it
  and is a later step.
- Sub-account data never leaves your Google account: the script runs in your Sheet and talks to GHL directly.

## Tests

```
pip install httpx pytest
python -m pytest -q          # 9 passed
node apps-script/test_code.mjs
```

## Licence

MIT. Built by Alibek Kozhatayev, September 2026. Questions: open an issue.
