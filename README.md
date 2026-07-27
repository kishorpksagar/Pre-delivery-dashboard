# Shop > Pre-Delivery CS Dashboard

Static dashboard (`index.html`) reading from `data.json`. A GitHub Actions workflow
re-runs the Metabase queries every morning and updates `data.json`, which GitHub Pages
then serves automatically — no manual redeploy needed.

## 1. Create the repo

1. Go to https://github.com/new
2. Name it (e.g. `cs-shop-predelivery-dashboard`)
3. Choose **Private** if this data shouldn't be public, or **Public** if that's fine
   for your org — note: GitHub Pages on a **private** repo requires GitHub Pro,
   Team, or Enterprise. On the free plan, Pages only works on public repos.
4. Don't initialize with a README (we already have one) — or initialize and just
   overwrite files after.

## 2. Push these files

From this folder:

```bash
git init
git add .
git commit -m "Initial dashboard"
git branch -M main
git remote add origin https://github.com/<your-org>/<your-repo>.git
git push -u origin main
```

## 3. Enable GitHub Pages

1. In the repo: **Settings > Pages**
2. Under "Build and deployment", set **Source** to "Deploy from a branch"
3. Branch: `main`, folder: `/ (root)`
4. Save. GitHub will give you a URL like `https://<your-org>.github.io/<your-repo>/`
   within a minute or two.

## 4. Add Metabase secrets (for the auto-refresh job)

In the repo: **Settings > Secrets and variables > Actions > New repository secret**.
Add:

| Secret name | Value |
|---|---|
| `METABASE_URL` | Your Metabase base URL, e.g. `https://metabase.yourcompany.com` |
| `METABASE_API_KEY` | A Metabase API key — create one under **Admin settings > Authentication > API Keys** in Metabase (needs read access to the `kapture`/`pop` database, database id used below) |
| `METABASE_DATABASE_ID` | The Metabase database id (16, in this build — confirm in your Metabase admin if different) |

You do **not** need to add a GitHub token — the workflow uses the automatic
`GITHUB_TOKEN` that Actions provides to commit the refreshed `data.json` back
to the repo.

## 5. Test it

- Go to the **Actions** tab in your repo, select "Refresh dashboard data",
  click **Run workflow** to trigger it manually the first time.
- Check the run logs — it should print the cutoff date, row counts, and
  "Wrote .../data.json".
- Confirm `data.json`'s `generated_at` field updated and the commit shows up
  in the repo history.
- After that, it runs automatically every day at 2:00 AM UTC (7:30 AM IST).
  Change the cron line in `.github/workflows/refresh-data.yml` if you want a
  different time (cron is always in UTC).

## How the pieces fit together

- **`index.html`** — the dashboard itself. Loads `data.json` via `fetch()` on
  page load; no data is hardcoded in the HTML anymore.
- **`data.json`** — the current data snapshot. This file is what changes daily.
- **`scripts/fetch_data.py`** — re-runs the same Metabase SQL queries used to
  build this dashboard (ticket counts by Disposition Level 3, filtered to
  Shop > Order Related – Pre Delivery, Chat source, agent-disposed; and the
  order-count denominator, `count(distinct sub_order_number)` where
  `status != 'Discard'`, dated by `date_created` shifted to IST), aggregates
  them into daily/weekly buckets with trailing-14-day rolling sums, and
  overwrites `data.json`.
- **`.github/workflows/refresh-data.yml`** — the cron job that runs the script
  daily and commits the result. GitHub Pages then just serves whatever's on
  `main`, so no separate deploy step is needed.

## Notes / things to double check

- The script assumes `createdate` in `kapture.raw_ticket_reports` is already
  a business-local date (no timezone shift applied), matching how this
  dashboard was originally built. If that's wrong for your Metabase instance,
  adjust the `ticket_sql` date handling in `fetch_data.py`.
- The cutoff each day is "yesterday in IST" by default, so the very latest
  partial day of data is never shown as if it were complete. You can override
  this with a `CUTOFF_DATE` environment variable (`YYYY-MM-DD`) if you ever
  need to regenerate a specific historical date.
- If `scripts/fetch_data.py` fails (e.g. bad credentials, Metabase down), the
  workflow run will show a red ✗ in the Actions tab and `data.json` will
  simply not be updated that day — the dashboard keeps showing the last good
  data rather than breaking.
