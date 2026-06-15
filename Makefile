.PHONY: help setup install download process process-cleaned push-vertica run clean list-sql render-sql check-jira test-connection docs rollup-vertica dashboard-ui-install dashboard-ui-build dashboard-serve dashboard-health dashboard-test

VENV_DIR ?= $(shell pwd)/../Dashboard/.venv
PYTHON := "$(VENV_DIR)/bin/python"
PIP := "$(VENV_DIR)/bin/pip"

help:
	@echo "QA Pipeline – Makefile targets"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make install           Install Python dependencies"
	@echo "  make setup             One-time setup (create .env, etc.)"
	@echo ""
	@echo "Core Pipeline:"
	@echo "  make download          Fetch Jira CSVs (Report CSV/)"
	@echo "  make process           Run 3-stage pipeline → SQLite"
	@echo "  make process-cleaned   Run pipeline from Report CSV/cleaned only"
	@echo "  make push-vertica      Push SQLite → Vertica"
	@echo "  make run               Full pipeline: download → process → push-vertica"
	@echo ""
	@echo "Aggregations (requires Vertica in app_config.json):"
	@echo "  make rollup-vertica    Build AGG_QA_REPORT_5_MIN/HOUR/DAY (all-time)"
	@echo "                         Custom: make rollup-vertica PERIOD_START='2026-06-01 00:00:00' PERIOD_END='2026-07-01 00:00:00'"
	@echo ""
	@echo "Utilities:"
	@echo "  make check-jira        Test Jira API connectivity"
	@echo "  make list-sql          List available SQL templates"
	@echo "  make render-sql TEMPLATE=<path> [VAR1=val1] [VAR2=val2]"
	@echo "                         Render a SQL template"
	@echo ""
	@echo "Executive Dashboard:"
	@echo "  make dashboard-ui-install   Install npm packages for React UI"
	@echo "  make dashboard-ui-build     Build React UI (Vite dist/)"
	@echo "  make dashboard-serve        Start Python server for dashboard UI + API"
	@echo "  make dashboard-health       Check dashboard API health endpoint"
	@echo "  make dashboard-test         Run dashboard smoke checks"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean             Remove SQLite DB and generated CSVs"
	@echo "  make clean-all         clean + remove all data"
	@echo ""
	@echo "Examples:"
	@echo "  make run"
	@echo "  make process"
	@echo "  make push-vertica"
	@echo "  make rollup-vertica"
	@echo "  make rollup-vertica PERIOD_START='2026-06-01 00:00:00' PERIOD_END='2026-07-01 00:00:00'"
	@echo "  make list-sql"
	@echo "  make render-sql TEMPLATE=aggregation/base_aggregation.sql"
	@echo "  make check-jira"

# ───────────────────────────────────────────────────────────────────────────
# Setup & Installation
# ───────────────────────────────────────────────────────────────────────────

setup: install create-env-file
	@echo "✓ Setup complete. Review .env file and run: make run"

install:
	@echo "Installing Python dependencies..."
	$(PIP) install -q -r requirements.txt
	@echo "✓ Dependencies installed"

create-env-file:
	@if [ ! -f .env ]; then \
		echo "Creating .env template..."; \
		cp .env.example .env 2>/dev/null || echo "JIRA_PAT=your_token_here" > .env; \
		echo "⚠ .env created. Edit with your JIRA_PAT:"; \
		echo "    nano .env"; \
	else \
		echo "✓ .env already exists"; \
	fi

# ───────────────────────────────────────────────────────────────────────────
# Core Pipeline
# ───────────────────────────────────────────────────────────────────────────

download:
	@echo "Downloading Jira reports..."
	$(PYTHON) -m qa_pipeline.cli download

process:
	@echo "Running 3-stage pipeline (auto_process → executed_test → defects)..."
	$(PYTHON) -m qa_pipeline.cli process

process-cleaned:
	@echo "Running 3-stage pipeline from cleaned CSVs..."
	$(PYTHON) -m qa_pipeline.cli process --use-cleaned

push-vertica:
	@echo "Pushing SQLite tables to Vertica..."
	$(PYTHON) -m qa_pipeline.cli push-vertica

run: download process push-vertica
	@echo "✓ Full pipeline complete"

# ───────────────────────────────────────────────────────────────────────────
# Aggregations (Vertica)
# ───────────────────────────────────────────────────────────────────────────

PERIOD_START ?= 1900-01-01 00:00:00
PERIOD_END ?= 2100-01-01 00:00:00
TARGET_TABLE_5MIN ?= AGG_QA_REPORT_5_MIN
TARGET_TABLE_HOUR ?= AGG_QA_REPORT_HOUR
TARGET_TABLE_DAY ?= AGG_QA_REPORT_DAY
DASHBOARD_TABLE ?= AGG_QA_REPORT_DAY

rollup-vertica:
	@echo "Building 5-minute, hourly, and daily aggregations in Vertica..."
	@echo "  Period: $(PERIOD_START) to $(PERIOD_END)"
	$(PYTHON) -m qa_pipeline.cli run-rollup-sql \
		--period-start "$(PERIOD_START)" \
		--period-end "$(PERIOD_END)" \
		--target-table-5min "$(TARGET_TABLE_5MIN)" \
		--target-table-hour "$(TARGET_TABLE_HOUR)" \
		--target-table-day "$(TARGET_TABLE_DAY)" \
		--output generated/rollup_vertica.sql
	@echo "✓ Aggregation complete. Output: generated/rollup_vertica.sql"

# ───────────────────────────────────────────────────────────────────────────
# Utilities & Diagnostics
# ───────────────────────────────────────────────────────────────────────────

check-jira: check-jira-auth
	@echo "Jira connectivity check complete (see above)"

check-jira-auth:
	@echo "Testing Jira API connectivity..."
	$(PYTHON) -m qa_pipeline.cli check-jira

list-sql:
	@echo "Available SQL templates:"
	$(PYTHON) -m qa_pipeline.cli list-sql

render-sql:
	@if [ -z "$(TEMPLATE)" ]; then \
		echo "Error: TEMPLATE is required"; \
		echo "Usage: make render-sql TEMPLATE=aggregation/base_aggregation.sql [VAR1=val1] ..."; \
		exit 1; \
	fi
	@echo "Rendering SQL template: $(TEMPLATE)"
	@vars_str=""; \
	for var in $(filter-out $@,$(MAKECMDGOALS)); do \
		vars_str="$$vars_str --sql-var $$var"; \
	done; \
	$(PYTHON) -m qa_pipeline.cli render-sql "$(TEMPLATE)" $$vars_str --output generated/rendered.sql
	@echo "✓ Output: generated/rendered.sql"

# ───────────────────────────────────────────────────────────────────────────
# Cleanup
# ───────────────────────────────────────────────────────────────────────────

clean:
	@echo "Removing SQLite staging database and generated CSVs..."
	rm -f qa_pipeline.db
	rm -f Report CSV/*.csv
	rm -rf generated/
	@echo "✓ Cleaned"

clean-all: clean
	@echo "Removing all data including Report CSV/ and Report Schema sh.csv..."
	rm -rf "Report CSV/"
	@echo "⚠ Kept Report Schema sh.csv (schema definition)"
	@echo "✓ Full cleanup complete"

# ───────────────────────────────────────────────────────────────────────────
# Development
# ───────────────────────────────────────────────────────────────────────────

lint:
	@echo "Checking Python syntax..."
	$(PYTHON) -m py_compile qa_pipeline/*.py qa_dashboard/*.py

test: lint check-jira
	@echo "✓ Basic checks passed"

docs:
	@echo "Opening README..."
	@cat README.md | head -100
	@echo "..."
	@echo "Run: less README.md"

# ───────────────────────────────────────────────────────────────────────────
# Executive Dashboard (React + Python server)
# ───────────────────────────────────────────────────────────────────────────

dashboard-ui-install:
	@echo "Installing dashboard UI dependencies..."
	cd exec_dashboard_ui && npm install
	@echo "✓ Dashboard UI dependencies installed"

dashboard-ui-build:
	@echo "Building dashboard UI..."
	cd exec_dashboard_ui && npm run build
	@echo "✓ Dashboard UI build complete (exec_dashboard_ui/dist)"

dashboard-serve:
	@echo "Starting dashboard server on http://$${EXEC_DASH_HOST:-0.0.0.0}:$${EXEC_DASH_PORT:-8000}"
	@echo "Dashboard table lock: AGG_QA_REPORT_DAY"
	bash exec_dashboard_server/run.sh

dashboard-health:
	@echo "Checking dashboard health endpoint..."
	curl -fsS "http://127.0.0.1:$${EXEC_DASH_PORT:-8000}/api/health"
	@echo ""
	@echo "✓ Dashboard health endpoint is reachable"

dashboard-test: dashboard-ui-build
	@echo "Running dashboard smoke checks..."
	python3 -m py_compile exec_dashboard_server/server.py
	@echo "✓ Python server syntax is valid"

# ───────────────────────────────────────────────────────────────────────────
# .env file handling for render-sql target
# ───────────────────────────────────────────────────────────────────────────

%:
	@:
