"""
qa_pipeline.cli
===============
Unified command-line interface for the QA pipeline application.

Commands
--------
download        Fetch all Jira reports into Report CSV/ using jira_sync_config.json.
process         Run the 3-stage pipeline and stage results to SQLite.
push-vertica    Push both SQLite tables to Vertica (requires vertica config in app_config.json).
run             download → process → push-vertica in one shot.
list-sql        List available SQL templates.
render-sql      Render a SQL template with variable substitution.
check-jira      Diagnose Jira API connectivity.

Usage
-----
    python -m qa_pipeline.cli --help
    python -m qa_pipeline.cli download
    python -m qa_pipeline.cli process
    python -m qa_pipeline.cli push-vertica
    python -m qa_pipeline.cli run
    python -m qa_pipeline.cli list-sql
    python -m qa_pipeline.cli render-sql aggregation/base_aggregation.sql \
        --var table=qa_agg_test_fact --var period_start=2026-01-01 \
        --output generated/aggregation.sql
    python -m qa_pipeline.cli check-jira
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Dict, List, Optional

logger = logging.getLogger("qa_pipeline")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s – %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_vars(raw: List[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in raw:
        parts = item.split("=", 1)
        if len(parts) != 2 or not parts[0].strip():
            raise SystemExit(f"Invalid --var '{item}'. Expected key=value")
        result[parts[0].strip()] = parts[1].strip()
    return result


def _load_config(args: argparse.Namespace):
    from qa_pipeline.config import load_pipeline_config
    return load_pipeline_config(
        app_config_path=Path(args.app_config).resolve() if args.app_config else None,
        env_file=Path(args.env_file).resolve() if args.env_file else None,
    )


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_download(args: argparse.Namespace) -> None:
    """Fetch Jira reports via the Jira API and write CSVs to output_dir."""
    cfg = _load_config(args)

    from qa_dashboard.jira_sync import (
        load_sync_config,
        run_sync,
        set_list_value_delimiter,
    )

    if not cfg.jira_sync_config.exists():
        raise SystemExit(f"Jira sync config not found: {cfg.jira_sync_config}")

    if args.jira_pat:
        os.environ["JIRA_PAT"] = args.jira_pat

    set_list_value_delimiter(cfg.default_list_delimiter)

    logger.info("Downloading Jira reports → %s", cfg.output_dir)
    result = run_sync(
        config_path=cfg.jira_sync_config,
        workspace_root=cfg.workspace_root,
        jira_pat=args.jira_pat,
        since_date=args.since_date,
        vertica_config=None,
        prefer_cached_csv=False,
    )
    logger.info("Download complete. Output dir: %s", result.output_dir)
    for item in result.results:
        print(
            f"  ✓ {item.report_name}: fetched={item.issues_fetched} rows={item.rows_written}"
        )


def cmd_process(args: argparse.Namespace) -> None:
    """Run the 3-stage pipeline and upsert results to SQLite."""
    cfg = _load_config(args)

    from qa_pipeline.pipeline import run_pipeline
    from qa_pipeline.store.sqlite import SqliteStore

    logger.info("Running pipeline on %s", cfg.output_dir)
    result = run_pipeline(cfg.output_dir)

    logger.info(
        "Pipeline complete: fact=%d rows, defect_dim=%d rows",
        len(result.agg_test_fact),
        len(result.defect_dim),
    )

    with SqliteStore.open(
        cfg.sqlite_db_path,
        agg_fact_table=cfg.agg_fact_table,
        defect_dim_table=cfg.defect_dim_table,
    ) as store:
        dim_rows = store.upsert_defect_dim(result.defect_dim)
        fact_rows = store.upsert_agg_fact(result.agg_test_fact)

    counts = _read_table_counts(cfg)
    print(f"  ✓ SQLite staging complete: {cfg.sqlite_db_path}")
    print(f"    {cfg.agg_fact_table}: {fact_rows} rows upserted (total={counts.get(cfg.agg_fact_table, '?')})")
    print(f"    {cfg.defect_dim_table}: {dim_rows} rows upserted (total={counts.get(cfg.defect_dim_table, '?')})")


def _read_table_counts(cfg) -> dict:
    from qa_pipeline.store.sqlite import SqliteStore
    try:
        with SqliteStore.open(
            cfg.sqlite_db_path,
            agg_fact_table=cfg.agg_fact_table,
            defect_dim_table=cfg.defect_dim_table,
        ) as store:
            return store.table_counts()
    except Exception:
        return {}


def cmd_push_vertica(args: argparse.Namespace) -> None:
    """Push both SQLite tables to Vertica."""
    cfg = _load_config(args)

    if cfg.vertica is None:
        raise SystemExit(
            "Vertica config not found in app_config.json.\n"
            "Add a 'vertica' block with host, port, database, user, password."
        )

    from qa_pipeline.store.sqlite import SqliteStore
    from qa_pipeline.store.vertica import VerticaStore

    with SqliteStore.open(
        cfg.sqlite_db_path,
        agg_fact_table=cfg.agg_fact_table,
        defect_dim_table=cfg.defect_dim_table,
    ) as store:
        counts = store.table_counts()
        if all(v <= 0 for v in counts.values()):
            raise SystemExit("SQLite store is empty. Run 'process' first.")

        vs = VerticaStore(cfg.vertica)
        logger.info("Pushing to Vertica at %s:%s/%s", cfg.vertica.host, cfg.vertica.port, cfg.vertica.database)
        fact_rows, dim_rows = vs.push_all(store)

    schema = cfg.vertica.schema
    print(f"  ✓ Vertica push complete")
    print(f"    {schema}.{cfg.vertica.agg_fact_table}: {fact_rows} rows")
    print(f"    {schema}.{cfg.vertica.defect_dim_table}: {dim_rows} rows")


def cmd_run(args: argparse.Namespace) -> None:
    """Full pipeline: download → process → push-vertica."""
    cmd_download(args)
    cmd_process(args)
    if _load_config(args).vertica is not None:
        cmd_push_vertica(args)
    else:
        logger.info("Skipping Vertica push (no vertica config in app_config.json)")


def cmd_list_sql(args: argparse.Namespace) -> None:
    """List available SQL templates."""
    cfg = _load_config(args)
    sql_dir = cfg.sql_template_dir

    if not sql_dir.exists():
        print(f"SQL template directory not found: {sql_dir}")
        return

    templates = sorted(sql_dir.rglob("*.sql"))
    if not templates:
        print(f"No SQL templates found under: {sql_dir}")
        return

    print(f"SQL templates in: {sql_dir}")
    for t in templates:
        print(f"  {t.relative_to(sql_dir)}")


def cmd_render_sql(args: argparse.Namespace) -> None:
    """Render a SQL template with variable substitution."""
    cfg = _load_config(args)
    template_path = (cfg.sql_template_dir / args.template).resolve()

    if not template_path.exists():
        raise SystemExit(f"Template not found: {template_path}")
    if cfg.sql_template_dir.resolve() not in template_path.parents:
        raise SystemExit("Template path is outside the configured sql_template_dir")

    sql_vars = _parse_vars(args.var or [])
    default_vars = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "table": cfg.agg_fact_table,
        "period_start": "2026-01-01",
        "period_end": "2027-01-01",
    }
    default_vars.update(sql_vars)

    rendered = Template(template_path.read_text(encoding="utf-8")).safe_substitute(default_vars)

    if args.output:
        out = Path(args.output).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"Rendered SQL written to: {out}")
    else:
        print(rendered)


def cmd_check_jira(args: argparse.Namespace) -> None:
    """Diagnose Jira API connectivity."""
    cfg = _load_config(args)
    from qa_dashboard.jira_sync import diagnose_connection

    result = diagnose_connection(config_path=cfg.jira_sync_config)
    print("Jira connectivity diagnostic")
    print(f"  base_url:       {result.get('base_url')}")
    print(f"  api_version:    {result.get('api_version')}")
    print(f"  auth_type:      {result.get('auth_type')}")
    print(f"  serverInfo_ok:  {result.get('serverInfo_ok')}")
    if not result.get("serverInfo_ok"):
        print(f"  error:          {result.get('serverInfo_error')}")
    else:
        print(f"  deploymentType: {result.get('deploymentType', '')}")
    print(f"  myself_ok:      {result.get('myself_ok')}")
    if not result.get("myself_ok"):
        print(f"  error:          {result.get('myself_error')}")
    else:
        print(f"  user:           {result.get('user', '')}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qa_pipeline.cli",
        description="QA Pipeline – config-driven Jira CSV ingestion and staging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--app-config", default="app_config.json",
                        help="Path to app_config.json (default: app_config.json)")
    parser.add_argument("--env-file", default=None,
                        help="Optional .env file path")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # download
    dl = sub.add_parser("download", help="Fetch Jira reports → Report CSV/")
    dl.add_argument("--mode", choices=["download", "append"], default="download")
    dl.add_argument("--since-date", default=None)
    dl.add_argument("--jira-pat", default=None)

    # process
    proc = sub.add_parser("process", help="Run pipeline → SQLite")
    proc.add_argument("--auto-process-glob", default="Automation Job *.csv")
    proc.add_argument("--executed-test-glob", default="* Executed Test *.csv")
    proc.add_argument("--defects-glob", default="Defects *.csv")

    # push-vertica
    push = sub.add_parser("push-vertica", help="Push SQLite → Vertica")

    # run
    run = sub.add_parser("run", help="download + process + push-vertica")
    run.add_argument("--since-date", default=None)
    run.add_argument("--jira-pat", default=None)
    run.add_argument("--mode", choices=["download", "append"], default="download")

    # list-sql
    sub.add_parser("list-sql", help="List SQL templates")

    # render-sql
    rs = sub.add_parser("render-sql", help="Render a SQL template")
    rs.add_argument("template", help="Relative path under sql_template_dir")
    rs.add_argument("--var", action="append", default=[],
                    help="Variable override in key=value format. Repeatable.")
    rs.add_argument("--output", "-o", default=None,
                    help="Output SQL file. If omitted, prints to stdout.")

    # check-jira
    cj = sub.add_parser("check-jira", help="Diagnose Jira API connectivity")
    cj.add_argument("--jira-pat", default=None)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    dispatch = {
        "download": cmd_download,
        "process": cmd_process,
        "push-vertica": cmd_push_vertica,
        "run": cmd_run,
        "list-sql": cmd_list_sql,
        "render-sql": cmd_render_sql,
        "check-jira": cmd_check_jira,
    }

    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("%s", exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
