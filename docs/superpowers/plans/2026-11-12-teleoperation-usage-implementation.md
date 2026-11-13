# Teleoperation Usage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Datalego query pipeline and static HTML dashboard for daily and weekly teleoperation customer usage.

**Architecture:** Python scripts under `scripts/` read the customer workbook, submit Hive SQL to Datalego, normalize SKU rows, and write CSV plus `usage/dashboard.json`. A dependency-free static page under `index.html`, `styles.css`, and `app.js` reads that JSON and renders filters, KPIs, SVG trend lines, ranking, detail rows, and CSV download.

**Tech Stack:** Python 3 standard library, `openpyxl` for customer workbook reads, Datalego HTTP API, static HTML/CSS/JavaScript, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-12-teleoperation-usage-design.md`

## Global Constraints

- Datalego client logic is reimplemented locally and does not import `beauty-analytics`.
- HTML remains a static page with no build step or backend.
- `ods.sku.value` is passed through and summed without unit conversion.
- Customer source columns are `NAME`, `CID`, `VID`, `SALE`.
- Git repository root is `teleoperation-usage`.

### Task 1: Move Git ownership into the project folder

**Files:**
- Create: `teleoperation-usage/.git/` through Git initialization
- Modify: parent Git metadata only as needed to stop the parent directory being the active repository

**Interfaces:**
- Produces a repository rooted at `teleoperation-usage` with `origin=https://github.com/SwordOfSpring/teleoperation-usage.git`.

- [ ] **Step 1: Verify parent repository has no commits and inspect remote.**

Run: `git -C .. status --short --branch; git -C .. log -1 --oneline; git -C .. remote -v`

Expected: no project commits and the existing remote points to the requested repository.

- [ ] **Step 2: Preserve parent metadata and initialize the child repository.**

Rename the parent `.git` directory to a timestamped backup, run `git init -b main` inside `teleoperation-usage`, and add the requested `origin`.

- [ ] **Step 3: Verify repository root and remote.**

Run: `git -C teleoperation-usage rev-parse --show-toplevel; git -C teleoperation-usage remote -v`

Expected: the root is the `teleoperation-usage` folder and `origin` is the GitHub URL.

### Task 2: Implement Datalego client

**Files:**
- Create: `scripts/datalego_client.py`
- Create: `scripts/__init__.py`
- Test: `tests/test_datalego_client.py`

**Interfaces:**
- `AuthContext.init()`, `AuthContext.refresh()`.
- `submit_query(sql: str, engine: str = "hive", queue: str = "share") -> tuple[str, str, dict]`.
- `get_job_status(job_id: str) -> dict`.
- `wait_for_job(job_id: str, label: str = "Query", engine: str = "hive") -> dict | None`.
- `result_to_csv(result: dict, output_path: Path) -> int`.

- [ ] **Step 1: Write tests for schema/data CSV conversion and API payload construction.**
- [ ] **Step 2: Run `python -m unittest tests/test_datalego_client.py -v` and verify the new tests fail.**
- [ ] **Step 3: Implement token loading, JWT payload parsing, 401 refresh, submit, poll, timeout, and BOM CSV output.**
- [ ] **Step 4: Run the focused tests and verify they pass.**

### Task 3: Implement usage pipeline and daily/weekly entry points

**Files:**
- Create: `scripts/usage_pipeline.py`
- Create: `scripts/daily_usage.py`
- Create: `scripts/weekly_usage.py`
- Create: `sql/daily_usage.sql`
- Create: `sql/weekly_usage.sql`
- Create: `requirements.txt`
- Test: `tests/test_usage_pipeline.py`

**Interfaces:**
- `load_customers(path: Path) -> list[dict]`.
- `build_usage_sql(start: str, end: str, vids: list[str]) -> str`.
- `aggregate_rows(rows: list[dict], customers: dict[str, dict], period_key: str = "date") -> list[dict]`.
- `write_dashboard_data(...) -> Path`.
- CLI: `python scripts/daily_usage.py [--start YYYYMMDD --end YYYYMMDD] [--dry-run]`.
- CLI: `python scripts/weekly_usage.py [--start YYYYMMDD --end YYYYMMDD] [--dry-run]`.

- [ ] **Step 1: Write failing tests for Excel mapping, date defaults, safe VID SQL, SKU totals, and dashboard JSON.**
- [ ] **Step 2: Run `python -m unittest tests/test_usage_pipeline.py -v` and verify failures.**
- [ ] **Step 3: Implement customer loading, SQL template rendering, daily/weekly date selection, raw result normalization, SKU aggregation, and output writes.**
- [ ] **Step 4: Add wrappers that call the common pipeline and choose yesterday or the previous complete ISO week by default.**
- [ ] **Step 5: Run focused tests, then run both wrappers with `--dry-run`.**

### Task 4: Build the static dashboard

**Files:**
- Create: `index.html`
- Create: `styles.css`
- Create: `app.js`
- Create: `usage/dashboard.json` fixture with representative rows

**Interfaces:**
- Browser reads `usage/dashboard.json` with a same-origin fetch; when opened directly from `file://`, the page shows a clear local-server hint instead of crashing.
- `app.js` renders normalized records with no external chart dependency.

- [ ] **Step 1: Implement semantic static HTML shell and dashboard-design token structure.**
- [ ] **Step 2: Implement responsive CSS for calm light/dark surfaces, KPI cards, controls, table, and chart panels.**
- [ ] **Step 3: Implement JSON loading, filters, KPI calculations, SVG trend chart, ranking bars, table rendering, empty/error/stale states, and CSV download.**
- [ ] **Step 4: Open via a local static server and verify desktop and narrow layouts manually.**

### Task 5: Documentation and final verification

**Files:**
- Create: `README.md`
- Modify: `.gitignore`
- Modify: `tests/` only if verification reveals a defect

- [ ] **Step 1: Document Datalego login/token prerequisites, Excel VID updates, daily/weekly commands, output files, and static page serving.**
- [ ] **Step 2: Add safe ignores for local secrets, Python caches, and temporary raw files while keeping dashboard data trackable.**
- [ ] **Step 3: Run all tests, `py_compile`, both dry runs, and a static-server smoke check.**
- [ ] **Step 4: Inspect `git diff --stat` and repository status, then commit the project changes.**
