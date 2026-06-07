# QA Release Readiness Pipeline

Production-grade Jira data pipeline for quality analytics.

## Quick Start (with Makefile)

### One-time setup

```bash
cd /mnt/d/Test\ Automation\ Report/tester_pro
make setup           # Installs deps, creates .env template
nano .env            # Edit: add your JIRA_PAT
```

### Run the full pipeline

```bash
make run             # download → process → push-vertica
```

### Individual commands

```bash
make download        # Fetch Jira reports
make process         # Run 3-stage pipeline → SQLite
make push-vertica    # Push to Vertica (if configured)
make check-jira      # Test Jira connectivity
make list-sql        # Show available SQL templates
make clean           # Remove SQLite DB and generated files
```

See all targets: `make help`

---

## Features

This pipeline provides:
- 3-stage ETL: auto_process (AR parsing) → executed_test (merge) → defects (enrichment)
- SQLite staging with dual tables: agg_test_fact and defect_dim
- Optional Vertica push for analytical warehouse
- Jira API sync with configuration-driven approach
- SQL template rendering for custom aggregations

## 1) What This Dashboard Uses

### Data inputs
- `Report CSV/` folder with exported Jira CSV files
- `Report Schema sh.csv` for report metadata, required columns, and hierarchy joins

### Main source types
- Automation Job
- Executed Test
- Test Created
- Defects
- Monthly executed test snapshots

### Relationship model
The dashboard follows schema-based report links:
- Automation Job -> Executed Test (Sub-Tasks)
- Executed Test -> Test Created (Executed Test reference)
- Test Created -> Defects (Related Bugs / Defect links)
- Automation Job -> Defects (Blockers)

## 2) Features Included

### Executive section
- Release Readiness Score (weighted)
- Release recommendation with reasons and blockers
- Top KPI cards:
  - Total Tests
  - Pass Rate
  - Open Defects
  - Critical Bugs
  - Automation Coverage
  - Failed Tests

### Trends and analysis
- Bug trend by severity
- Weekly pass-rate trend
- Automation quality metrics
- Project-level pass-rate split (project used as scrum proxy)

### Planning and stability
- Sprint quality metrics
- Critical defect aging
- Defect inflow vs outflow
- Defect category mix
- MTTR proxy
- Flaky test rate

### Deep drilldowns
- Bridge-table view per join path
- Unmatched-key drilldown
- KPI confidence table (HIGH, MEDIUM, LOW)
- Ingestion and link-quality diagnostics

## Prerequisites
- Python 3.10+
- Virtual environment at `../Dashboard/.venv` (shared with other tools)

### One-time setup

```bash
make setup
# Or manually:
# pip install -r requirements.txt
# cp .env.example .env && nano .env  (add your JIRA_PAT)
```

## 4) Jira API Sync

### What you need
- Jira base URL (for example `https://your-domain.atlassian.net`)
- Jira user email
- Jira API token
- Correct Jira custom field IDs for your instance

### Credentials
Set credentials as environment variables (do not hardcode secrets in files):

```bash
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your_api_token"
```

If you use Jira Personal Access Token (PAT) only (recommended for your setup):

```bash
export JIRA_PAT="your_personal_access_token"
```

And in `jira_sync_config.json`:
- set `jira.auth_type` to `bearer`
- set `jira.pat_env` to `JIRA_PAT`

### Config file
Use `jira_sync_config.json` (already created from the example template).

Files:
- `jira_sync_config.example.json` (reference template)
- `jira_sync_config.json` (active config used by app and CLI)

Update these fields carefully:
- `jira.base_url`
- each report `jql`
- each report `columns[].path` for your Jira custom field IDs

### Application config (production-style)

Use `app_config.json` to centralize runtime locations and defaults:

- `env_file`
- `jira_sync_config`
- `output_dir`
- `sql_template_dir`
- `default_list_delimiter`

Files:
- `app_config.example.json`
- `app_config.json`
- `.env.example`

Secrets remain in environment variables (for example `JIRA_PAT`) and are not stored in JSON.

### Config schema design
Top-level keys:
- `jira`
  - `base_url`
  - `email_env`
  - `token_env`
  - `verify_ssl`
  - `timeout_seconds`
- `output_dir`
- `reports[]`
  - `key`
  - `name`
  - `jql`
  - `filename_template`
  - `page_size`
  - `max_results`
  - `columns[]` with:
    - `csv` (output CSV header)
    - `path` (Jira issue path such as `fields.status.name`)
    - `default` (optional fallback)

### Run sync

Option A: from dashboard sidebar
- Open app and click `Run Jira Sync` in `Jira API Sync` section.

Option B: from CLI

```bash
source .venv/bin/activate
python sync_jira.py
```

### CSV-only sync application (single command)

If you only want CSV files in `Report CSV/` (without Vertica upsert), use:

```bash
source ../Dashboard/.venv/bin/activate
python sync_jira_csv.py --mode download
```

This command is now config-driven and reads:
- `app_config.json`
- `jira_sync_config.json`
- `.env` (if present)

Append mode merges new Jira rows into one stable CSV per report in `Report CSV/`:

```bash
source ../Dashboard/.venv/bin/activate
python sync_jira_csv.py --mode append
```

Optional date filter for both modes:

```bash
python sync_jira_csv.py --mode append --since-date 2026-01-01
```

Optional list delimiter override for flattened list fields (for example Sub-Tasks):

```bash
python sync_jira_csv.py --mode download --list-delimiter " | "
```

Optional app config path override:

```bash
python sync_jira_csv.py --mode download --app-config app_config.json
```

List available SQL templates:

```bash
python sync_jira_csv.py --action list-sql
```

Render a SQL template for aggregation/KPI pipelines:

```bash
python sync_jira_csv.py --action render-sql \
  --sql-template aggregation/base_aggregation.sql \
  --sql-var table=qa_kpi_agg \
  --sql-var period_start=2026-01-01 \
  --sql-var period_end=2027-01-01 \
  --sql-output generated/aggregation.sql
```

Append behavior:
- Target file naming: `<Report Name>.csv`
- Merge strategy: existing + incoming rows
- De-duplication: by `Issue key` (keep latest row)

Legacy ad-hoc scripts are now isolated under `legacy/`:
- `legacy/auto_process.py`
- `legacy/executed_test.py`
- `legacy/defects_analysis.py`

### Auto-resolve placeholder field paths from Jira metadata
After setting credentials, resolve `REPLACE_*` placeholders using Jira `/rest/api/3/field`:

```bash
source .venv/bin/activate
python resolve_jira_fields.py
```

This updates `jira_sync_config.json` in place and prints unresolved placeholders.

### Auto-generate starter config from schema
If your schema changed, regenerate a starter config and unresolved mapping list:

```bash
source .venv/bin/activate
python generate_jira_sync_config.py
```

Generated files:
- `jira_sync_config.json`
- `jira_sync_field_todo.csv`

Then replace placeholder paths in `jira_sync_config.json` based on `jira_sync_field_todo.csv`.

### How it works
- Calls Jira Search API with pagination per report config.
- Extracts configured columns from each issue object.
- Writes per-report CSV files to `Report CSV/`.
- Dashboard reload can then use fresh synced data.

### Vertica dual-table aggregation (BI-ready)

The sync pipeline now writes **two separate aggregation tables** to Vertica.

This is intentional:
- one table keeps the compact KPI cube used by the app
- one table is denormalized for direct BI consumption (Power BI, Tableau, Looker, etc.)

#### Table 1: compact cube
- table name: `<schema>.<table>`
- default example: `public.qa_kpi_agg`
- purpose: lightweight KPI cube for app/API use
- grain: `(time_grain, period, dimensions...)`
- measures:
  - `total`
  - `pass_count`
  - `fail_count`
  - `open_count`
  - `closed_count`
  - `critical_count`
  - `pass_rate_pct`
  - `avg_fix_cycle_days`
  - `avg_defect_age_days`

#### Table 2: denormalized BI cube
- table name: `<schema>.<table>_denorm`
- default example: `public.qa_kpi_agg_denorm`
- purpose: BI-ready model with rich period attributes and label columns
- key columns:
  - `time_grain`
  - `period`
  - all dimension columns from `qa_dashboard/aggregator.py` (`DIMENSIONS`)
- extra denormalized columns:
  - `period_start`
  - `period_end`
  - `period_label`
  - `period_year`
  - `period_quarter`
  - `period_month`
  - `period_week`
  - `period_day`
  - `source_type_label`
- measures: same KPI measures as compact cube

#### Why this helps BI teams
- Decoupled from application logic.
- BI tools can query pre-aggregated rows directly.
- Standardized table structure for semantic models.
- Stable table naming for scheduled reports and dashboards.

#### Upsert behavior
- Load method: bulk `COPY FROM STDIN` into a temporary staging table, then `MERGE` into target.
- Existing keys are updated; new keys are inserted.
- Both tables are upserted in the same sync run.
- `last_updated_at` is written in UTC for auditability.

#### Data flow diagram

The pipeline flows data from Jira API through 3-stage processing to SQLite, with optional Vertica push.

#### How to run

```bash
make run              # Full pipeline: download → process → push-vertica
# Or run stages individually:
make download         # Fetch Jira CSVs
make process          # 3-stage pipeline → SQLite
make push-vertica     # Push to Vertica (if configured)
```

#### BI query starter examples

Monthly pass rate by project:

```sql
SELECT
  period,
  project_key,
  pass_rate_pct,
  total,
  pass_count,
  fail_count
FROM public.qa_kpi_agg_denorm
WHERE time_grain = 'month'
ORDER BY period, project_key;
```

Open and critical defects trend by sprint:

```sql
SELECT
  period,
  sprint_id,
  open_count,
  critical_count
FROM public.qa_kpi_agg_denorm
WHERE time_grain = 'week'
  AND source_type = 'defect'
ORDER BY period, sprint_id;
```

#### Notes and caveats
- `time_grain` values are lower-case (`day`, `week`, `month`, `quarter`, `year`).
- `period` is the period start date.
- Blank dimensions are normalized to empty string in Vertica.
- If aggregation is empty, sync reports that zero rows were upserted.

### Important note about field IDs
`customfield_XXXXX` IDs differ per Jira instance. You must replace placeholders in `jira_sync_config.json` with your real IDs.

### Recommended rollout
1. Start with one report (for example `Defects`) and validate output.
2. Add remaining reports one by one.
3. Compare synced CSV headers with your schema expectations.
4. Enable scheduled sync later via cron/CI if needed.

## 5) How To Use The Pipeline

### Step-by-step
1. Run `make setup` (one-time).
2. Edit `.env` with your Jira PAT.
3. Run `make run` to execute the full pipeline.
4. Check output in `Report CSV/` and `qa_pipeline.db`.
5. (Optional) Configure Vertica in `app_config.json` and re-run `make push-vertica`.
   - Sprint ID
   - Component
5. Review top score and recommendation first.
6. Drill into trends and mismatch diagnostics if score is low.

### Release decision flow
1. Check Release Readiness Score.
2. Review blockers listed in recommendation panel.
3. Verify critical defects, pass rate, and automation metrics.
4. Use link-quality and unmatched-key drilldown to inspect data trust.
5. Decide GO / CONDITIONAL GO / NO GO.

## 6) Configuration Guide

### A) Update schema-driven behavior
File: `Report Schema sh.csv`

Important columns used:
- `Report Name`
- `Relevant Column`
- `Must Have Value`
- `HIERERCHY JOIN KEY`
- `Notes`

Use this file to:
- define mandatory columns per report
- define expected values (such as Issue Type)
- document/report join keys

### B) Update source classification and aliases
File: `qa_dashboard/schema_config.py`

Use this file to:
- add new source filename rules
- add new canonical aliases for Jira columns
- expand field mapping when Jira export headers change

### C) Update KPI formulas and thresholds
File: `qa_dashboard/kpi.py`

Use this file to tune:
- readiness score weights
- release gating thresholds (for example pass rate or critical bugs)
- confidence levels for KPI badges
- proxy logic for missing enterprise fields

### D) Update dashboard layout
File: `app.py`

Use this file to:
- reorder sections
- add/remove charts and tables
- adjust filter behavior
- expose more diagnostic panels

### E) Update Jira sync behavior
Files:
- `qa_dashboard/jira_sync.py`
- `jira_sync_config.json`
- `sync_jira.py`

Use these to:
- adjust API pagination and limits
- refine extraction paths and defaults
- add/remove synced report definitions
- run sync from CLI jobs or scheduler

## 7) KPI Notes (Important)

Some metrics are computed as proxies because not all enterprise fields exist directly in CSV exports.

Examples:
- MTTR is computed as a fix-cycle proxy from timestamps
- Reopened rate may use heuristic logic depending on available fields
- Project key is used as scrum/team proxy where scrum team is incomplete

Always use confidence badges and link-quality tables before making critical decisions.

## 8) Troubleshooting

### No data shown
- Confirm CSV files are in `Report CSV/`
- Check schema file exists and has correct headers
- Validate source-type filters are not overly restrictive

### Wrong KPI values
- Check `Report Schema sh.csv` for changed column names
- Verify aliases in `qa_dashboard/schema_config.py`
- Inspect confidence table and link-quality stats

### Many unmatched links
- Open unmatched-key drilldown panel
- Check issue key formatting in source CSV fields
- Verify relation columns contain Jira keys consistently

### Import/package errors
- Activate venv and reinstall dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Jira sync fails with auth error
- If using PAT mode: verify `JIRA_PAT` is exported and `jira.auth_type` is `bearer`
- If using basic mode: verify `JIRA_EMAIL` and `JIRA_API_TOKEN`
- Confirm `jira.base_url` is correct

### Jira sync writes empty CSV
- Validate report `jql` directly in Jira UI
- Verify `max_results` is high enough
- Ensure selected project/issue type actually has matching data

### Missing columns after sync
- Check `columns[].path` mapping in `jira_sync_config.json`
- Replace placeholder `customfield_XXXXX` with actual field IDs

## 9) Recommended Operating Practice

- Refresh reports weekly (or per release cycle)
- Prefer API sync before each release review instead of manual file drops
- Keep schema metadata updated with every Jira export change
- Review data quality warnings before stakeholder sharing
- Use score + blockers + confidence together, not score alone

## 10) Project Structure

```text
Dashboard/
  app.py
  sync_jira.py
  resolve_jira_fields.py
  jira_sync_config.json
  jira_sync_config.example.json
  requirements.txt
  Report Schema sh.csv
  Report CSV/
  qa_dashboard/
    schema_config.py
    data_loader.py
    kpi.py
    jira_sync.py
```
## 11) Next Enhancements (Optional)

- Add CSV export for drilldown tables
- Add role-based views (Executive, QA Lead, Team Lead)
- Add historical score snapshots per release
- Add alerting for threshold violations
