from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class AppConfig:
    workspace_root: Path
    jira_sync_config: Path
    output_dir: Path
    sql_template_dir: Path
    default_list_delimiter: str = " | "


def _parse_env_file(env_file: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not env_file.exists() or not env_file.is_file():
        return values

    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        key_value = line.split("=", 1)
        if len(key_value) != 2:
            continue

        key = key_value[0].strip()
        value = key_value[1].strip().strip('"').strip("'")
        if not key:
            continue
        values[key] = value

    return values


def load_env_file(env_file: Path) -> Dict[str, str]:
    parsed = _parse_env_file(env_file)
    for key, value in parsed.items():
        os.environ.setdefault(key, value)
    return parsed


def _load_json_or_empty(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _as_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path)


def load_app_config(
    workspace_root: Path,
    app_config_path: Path | None = None,
    env_file: Path | None = None,
) -> AppConfig:
    root = workspace_root.resolve()
    config_path = (app_config_path or (root / "app_config.json")).resolve()
    config_data = _load_json_or_empty(config_path)

    configured_env_file = str(config_data.get("env_file", ".env"))
    effective_env_file = (env_file or _as_path(root, configured_env_file)).resolve()
    load_env_file(effective_env_file)

    jira_sync_config = os.environ.get("APP_JIRA_SYNC_CONFIG") or str(
        config_data.get("jira_sync_config", "jira_sync_config.json")
    )
    output_dir = os.environ.get("APP_OUTPUT_DIR") or str(
        config_data.get("output_dir", "Report CSV")
    )
    sql_template_dir = os.environ.get("APP_SQL_TEMPLATE_DIR") or str(
        config_data.get("sql_template_dir", "sql_templates")
    )
    default_list_delimiter = os.environ.get("APP_LIST_DELIMITER") or str(
        config_data.get("default_list_delimiter", " | ")
    )

    return AppConfig(
        workspace_root=root,
        jira_sync_config=_as_path(root, jira_sync_config).resolve(),
        output_dir=_as_path(root, output_dir).resolve(),
        sql_template_dir=_as_path(root, sql_template_dir).resolve(),
        default_list_delimiter=default_list_delimiter,
    )
