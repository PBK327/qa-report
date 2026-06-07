"""
qa_pipeline.config
==================
Single source of truth for all runtime configuration.

Load order (each layer overrides the previous):
  1. Built-in defaults
  2. app_config.json
  3. .env file
  4. Process environment variables

Usage
-----
    from qa_pipeline.config import load_pipeline_config

    cfg = load_pipeline_config()
    print(cfg.sqlite_db_path)
    print(cfg.output_dir)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VerticaConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str = "public"
    agg_fact_table: str = "qa_agg_test_fact"
    defect_dim_table: str = "qa_defect_dim"
    test_created_table: str = "qa_test_created"


@dataclass
class PipelineConfig:
    workspace_root: Path
    output_dir: Path
    jira_sync_config: Path
    sqlite_db_path: Path
    sql_template_dir: Path
    default_list_delimiter: str = " | "
    agg_fact_table: str = "agg_test_fact"
    defect_dim_table: str = "defect_dim"
    test_created_table: str = "test_created"
    vertica: Optional[VerticaConfig] = None


# ---------------------------------------------------------------------------
# .env file loader
# ---------------------------------------------------------------------------

def _load_env_file(env_file: Path) -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    if not env_file.is_file():
        return loaded

    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("=", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        value = parts[1].strip().strip('"').strip("'")
        if not key:
            continue
        os.environ.setdefault(key, value)
        loaded[key] = value

    logger.debug("Loaded %d keys from %s", len(loaded), env_file)
    return loaded


# ---------------------------------------------------------------------------
# JSON config loader
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_pipeline_config(
    workspace_root: Path | None = None,
    app_config_path: Path | None = None,
    env_file: Path | None = None,
) -> PipelineConfig:
    """Load and return the merged runtime configuration.

    Parameters
    ----------
    workspace_root:
        Repository root.  Defaults to the parent of this file.
    app_config_path:
        Explicit path to ``app_config.json``.  Defaults to
        ``<workspace_root>/app_config.json``.
    env_file:
        Explicit ``.env`` file.  Defaults to value of ``env_file`` key in
        ``app_config.json``, or ``<workspace_root>/.env``.
    """
    root = (workspace_root or Path(__file__).parent.parent).resolve()
    config_path = (app_config_path or (root / "app_config.json")).resolve()
    data = _read_json(config_path)

    # Resolve and load the .env file first so env vars are set before we
    # fall back to them for any remaining settings.
    configured_env_file = str(data.get("env_file", ".env"))
    effective_env_file = (env_file or _resolve(root, configured_env_file)).resolve()
    _load_env_file(effective_env_file)

    def _env_or_json(env_key: str, json_key: str, default: str) -> str:
        return os.environ.get(env_key) or str(data.get(json_key, default))

    jira_sync_config = _resolve(
        root, _env_or_json("APP_JIRA_SYNC_CONFIG", "jira_sync_config", "jira_sync_config.json")
    ).resolve()

    output_dir = _resolve(
        root, _env_or_json("APP_OUTPUT_DIR", "output_dir", "Report CSV")
    ).resolve()

    sqlite_db_path = _resolve(
        root, _env_or_json("APP_SQLITE_DB", "sqlite_db", "qa_pipeline.db")
    ).resolve()

    sql_template_dir = _resolve(
        root, _env_or_json("APP_SQL_TEMPLATE_DIR", "sql_template_dir", "sql_templates")
    ).resolve()

    default_list_delimiter = _env_or_json(
        "APP_LIST_DELIMITER", "default_list_delimiter", " | "
    )

    agg_fact_table = _env_or_json("APP_AGG_FACT_TABLE", "agg_fact_table", "agg_test_fact")
    defect_dim_table = _env_or_json("APP_DEFECT_DIM_TABLE", "defect_dim_table", "defect_dim")
    test_created_table = _env_or_json(
        "APP_TEST_CREATED_TABLE", "test_created_table", "test_created"
    )

    vertica: Optional[VerticaConfig] = None
    vertica_data = data.get("vertica")
    if isinstance(vertica_data, dict) and vertica_data.get("host"):
        vertica = VerticaConfig(
            host=os.environ.get("VERTICA_HOST") or str(vertica_data.get("host", "localhost")),
            port=int(os.environ.get("VERTICA_PORT") or vertica_data.get("port", 5433)),
            database=os.environ.get("VERTICA_DATABASE") or str(vertica_data.get("database", "vdb")),
            user=os.environ.get("VERTICA_USER") or str(vertica_data.get("user", "dbadmin")),
            password=os.environ.get("VERTICA_PASSWORD") or str(vertica_data.get("password", "")),
            schema=os.environ.get("VERTICA_SCHEMA") or str(vertica_data.get("schema", "public")),
            agg_fact_table=str(vertica_data.get("agg_fact_table", "qa_agg_test_fact")),
            defect_dim_table=str(vertica_data.get("defect_dim_table", "qa_defect_dim")),
            test_created_table=str(vertica_data.get("test_created_table", "qa_test_created")),
        )

    return PipelineConfig(
        workspace_root=root,
        output_dir=output_dir,
        jira_sync_config=jira_sync_config,
        sqlite_db_path=sqlite_db_path,
        sql_template_dir=sql_template_dir,
        default_list_delimiter=default_list_delimiter,
        agg_fact_table=agg_fact_table,
        defect_dim_table=defect_dim_table,
        test_created_table=test_created_table,
        vertica=vertica,
    )
