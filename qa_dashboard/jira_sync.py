from __future__ import annotations

import base64
import json
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, request

import pandas as pd

from qa_dashboard.aggregator import (
    DIMENSIONS,
    SOURCE_TYPE_LABELS,
    TIME_GRAINS,
    build_agg_cube,
)
from qa_dashboard.data_loader import load_all_csvs
from qa_dashboard.vertica_loader import (
    VerticaConfig,
    upsert_aggregation_to_vertica,
    upsert_denorm_aggregation_to_vertica,
)


SPRINT_NAME_RE = re.compile(r"name=([^,\]]+)")
LIST_VALUE_DELIMITER = " | "
HTML_TAG_RE = re.compile(r"<[^>]+>")
TEST_RUN_STATUS_LABELS: Dict[int, str] = {
    0: "TODO",
    1: "EXECUTING",
    2: "FAIL",
    3: "PASS",
    4: "ABORTED",
    # Common custom IDs seen in this Jira/Xray instance
    1001: "BLOCKED",
    1002: "ABORTED",
}


def set_list_value_delimiter(delimiter: str) -> None:
    global LIST_VALUE_DELIMITER
    cleaned = str(delimiter or "").strip()
    LIST_VALUE_DELIMITER = cleaned if cleaned else " | "


@dataclass
class JiraAuthConfig:
    base_url: str
    api_version: str = "2"
    auth_type: str = "bearer"
    pat_env: str = "JIRA_PAT"
    email_env: str = "JIRA_EMAIL"
    token_env: str = "JIRA_API_TOKEN"
    verify_ssl: bool = True
    timeout_seconds: int = 60


@dataclass
class ColumnMapping:
    csv: str
    path: str
    default: str = ""


@dataclass
class ReportConfig:
    key: str
    name: str
    jql: str
    columns: List[ColumnMapping]
    filename_template: str = "{report_name} {timestamp}.csv"
    page_size: int = 100
    max_results: int = 5000


@dataclass
class SyncConfig:
    jira: JiraAuthConfig
    output_dir: str
    reports: List[ReportConfig]


@dataclass
class ReportSyncResult:
    report_key: str
    report_name: str
    file_path: str
    issues_fetched: int
    rows_written: int


@dataclass
class SyncResult:
    output_dir: str
    results: List[ReportSyncResult]
    vertica_rows_upserted: int = 0
    vertica_denorm_rows_upserted: int = 0
    vertica_table: str = ""
    vertica_denorm_table: str = ""
    vertica_error: str = ""
    vertica_skipped: bool = False


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_sync_config(config_path: Path) -> SyncConfig:
    data = _load_json(config_path)

    jira_raw = data.get("jira", {})
    jira = JiraAuthConfig(
        base_url=str(jira_raw.get("base_url", "")).rstrip("/"),
        api_version=str(jira_raw.get("api_version", "2")).strip() or "2",
        auth_type=str(jira_raw.get("auth_type", "bearer")).lower(),
        pat_env=str(jira_raw.get("pat_env", "JIRA_PAT")),
        email_env=str(jira_raw.get("email_env", "JIRA_EMAIL")),
        token_env=str(jira_raw.get("token_env", "JIRA_API_TOKEN")),
        verify_ssl=bool(jira_raw.get("verify_ssl", True)),
        timeout_seconds=int(jira_raw.get("timeout_seconds", 60)),
    )

    output_dir = str(data.get("output_dir", "Report CSV"))

    reports_raw = _as_list(data.get("reports", []))
    reports: List[ReportConfig] = []
    for item in reports_raw:
        cols = [
            ColumnMapping(
                csv=str(col.get("csv", "")),
                path=str(col.get("path", "")),
                default=str(col.get("default", "")),
            )
            for col in _as_list(item.get("columns", []))
            if str(col.get("csv", "")).strip() and str(col.get("path", "")).strip()
        ]
        if not cols:
            continue

        reports.append(
            ReportConfig(
                key=str(item.get("key", "")).strip() or str(item.get("name", "")).strip(),
                name=str(item.get("name", "")).strip(),
                jql=str(item.get("jql", "")).strip(),
                columns=cols,
                filename_template=str(
                    item.get("filename_template", "{report_name} {timestamp}.csv")
                ),
                page_size=int(item.get("page_size", 100)),
                max_results=int(item.get("max_results", 5000)),
            )
        )

    if not jira.base_url:
        raise ValueError("jira.base_url is required in sync config")
    if not reports:
        raise ValueError("At least one report must be configured")

    return SyncConfig(jira=jira, output_dir=output_dir, reports=reports)


def _get_auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


def _build_auth_header(auth: JiraAuthConfig) -> str:
    mode = (auth.auth_type or "bearer").lower()
    if mode == "bearer":
        pat = os.environ.get(auth.pat_env, "") or os.environ.get(auth.token_env, "")
        if not pat:
            raise RuntimeError(
                f"Missing Jira PAT. Set env var: {auth.pat_env}"
            )
        return f"Bearer {pat}"

    if mode == "basic":
        email = os.environ.get(auth.email_env, "")
        token = os.environ.get(auth.token_env, "")
        if not email or not token:
            raise RuntimeError(
                f"Missing Jira credentials. Set env vars: {auth.email_env} and {auth.token_env}"
            )
        return _get_auth_header(email=email, token=token)

    raise RuntimeError("jira.auth_type must be one of: bearer, basic")


def _build_ssl_context(verify_ssl: bool) -> ssl.SSLContext:
    """Return an SSL context respecting the config's verify_ssl flag.

    When verify_ssl is False (common for on-premise Jira Data Center with
    self-signed certificates) we create a context that does not verify the
    server certificate.  When True we use the system CA bundle.
    """
    if verify_ssl:
        ctx = ssl.create_default_context()
        # Allow TLS 1.2 minimum so older Jira Data Center servers still work.
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_error_hint(code: int) -> str:
    if code in {401, 403}:
        return (
            " Authentication failed. For Jira Data Center PAT use"
            " auth_type=bearer and api_version=2. For Jira Cloud API token"
            " use auth_type=basic with JIRA_EMAIL + JIRA_API_TOKEN."
        )
    return ""


def _post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Jira API HTTP {exc.code}: {msg}{_http_error_hint(exc.code)}") from exc
    except OSError as exc:
        raise RuntimeError(
            f"Jira connection failed: {exc}. "
            "Check network access to the Jira server and that verify_ssl in "
            "jira_sync_config.json matches the server's certificate setup."
        ) from exc


def _get_json(
    url: str,
    headers: Dict[str, str],
    timeout: int,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Any:
    req = request.Request(url=url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Jira API HTTP {exc.code}: {msg}{_http_error_hint(exc.code)}") from exc
    except OSError as exc:
        raise RuntimeError(
            f"Jira connection failed: {exc}. "
            "Check network access to the Jira server and that verify_ssl in "
            "jira_sync_config.json matches the server's certificate setup."
        ) from exc


def _api_endpoint(base_url: str, api_version: str, suffix: str) -> str:
    ver = api_version.strip() if api_version else "2"
    return f"{base_url}/rest/api/{ver}/{suffix.lstrip('/')}"


def _sanitize_cell(value: Any) -> str:
    text = str(value)
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()


def _extract_sprint_name(text: str) -> str:
    cleaned = _sanitize_cell(text)
    if cleaned.startswith("com.atlassian.greenhopper.service.sprint.Sprint@"):
        match = SPRINT_NAME_RE.search(cleaned)
        if match:
            return _sanitize_cell(match.group(1))
    return cleaned


def _extract_test_run_status(obj: Dict[str, Any]) -> str:
    """Decode Xray-like test run status payload into readable labels.

    Expected shape:
      {"timestamp":..., "issueId":..., "statuses":[{"statusResults":[{"latestFinal":3,...}]}]}
    """
    statuses = obj.get("statuses")
    if not isinstance(statuses, list):
        return ""

    codes: List[int] = []
    for status_bucket in statuses:
        if not isinstance(status_bucket, dict):
            continue
        for result in status_bucket.get("statusResults") or []:
            if not isinstance(result, dict):
                continue
            raw_code = result.get("latestFinal", result.get("latest"))
            try:
                codes.append(int(raw_code))
            except Exception:
                continue

    if not codes:
        return ""

    labels = [TEST_RUN_STATUS_LABELS.get(code, f"STATUS_{code}") for code in codes]
    unique = list(dict.fromkeys(labels))
    return LIST_VALUE_DELIMITER.join(unique)


def _dict_to_scalar(obj: Dict[str, Any]) -> str:
    if "statuses" in obj and "issueId" in obj:
        # For Xray-like test run payloads, return decoded status text or blank.
        return _extract_test_run_status(obj)

    decoded_test_status = _extract_test_run_status(obj)
    if decoded_test_status:
        return decoded_test_status

    for key in ("value", "name", "displayName", "emailAddress", "key", "id"):
        val = obj.get(key)
        if val not in (None, ""):
            return _sanitize_cell(val)

    fields = obj.get("fields")
    if isinstance(fields, dict):
        key = obj.get("key")
        summary = fields.get("summary")
        if key and summary:
            return _sanitize_cell(f"{key}:{summary}")

    return _sanitize_cell(json.dumps(obj, ensure_ascii=True, separators=(",", ":")))


def _scalarize_value(value: Any) -> str:
    if value in (None, ""):
        return ""

    if isinstance(value, dict):
        return _dict_to_scalar(value)

    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                # Jira issue references (for example subtasks) should export as keys.
                if item.get("key"):
                    parts.append(_sanitize_cell(item.get("key")))
                else:
                    parts.append(_dict_to_scalar(item))
            else:
                parts.append(_extract_sprint_name(str(item)))

        # Keep order, remove duplicates/blanks.
        unique_parts = list(dict.fromkeys([p for p in parts if p]))
        # Use a configurable non-CSV delimiter to keep spreadsheet import stable.
        return LIST_VALUE_DELIMITER.join(unique_parts)

    return _extract_sprint_name(str(value))


def _resolve_path(item: Dict[str, Any], path: str, default: str = "") -> Any:
    # Jira CSV export often uses rendered values for plugin/custom fields.
    # Prefer rendered value for TestRunStatus so API output matches Jira CSV.
    if path == "fields.customfield_10010":
        rendered = item.get("renderedFields", {}).get("customfield_10010")
        if rendered not in (None, ""):
            rendered_text = _sanitize_cell(rendered)
            if rendered_text:
                return rendered_text

    current: Any = item
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = None
        if current is None:
            return default

    flattened = _scalarize_value(current)
    return flattened if flattened else default


def _fetch_all_issues(
    base_url: str,
    api_version: str,
    auth_header: str,
    jql: str,
    fields: List[str],
    page_size: int,
    max_results: int,
    timeout_seconds: int,
    expand: List[str] | None = None,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> List[Dict[str, Any]]:
    endpoint = _api_endpoint(base_url=base_url, api_version=api_version, suffix="search")
    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    issues: List[Dict[str, Any]] = []
    start_at = 0

    while start_at < max_results:
        payload = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": min(page_size, max_results - start_at),
            "fields": fields,
        }
        if expand:
            payload["expand"] = expand
        resp = _post_json(endpoint, payload, headers=headers, timeout=timeout_seconds, ssl_context=ssl_context)

        page = resp.get("issues", [])
        if not page:
            break

        issues.extend(page)
        start_at += len(page)

        total = int(resp.get("total", 0))
        if start_at >= total:
            break

    return issues


def _is_placeholder_path(path: str) -> bool:
    text = path.upper()
    return "REPLACE" in text


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _extract_placeholder_token(path: str) -> str:
    if "customfield_REPLACE_" in path:
        return path.split("customfield_REPLACE_", 1)[1]
    if "REPLACE_" in path:
        return path.split("REPLACE_", 1)[1]
    return ""


def _fetch_jira_fields(base_url: str, api_version: str, auth_header: str, timeout_seconds: int, ssl_context: Optional[ssl.SSLContext] = None) -> List[Dict[str, Any]]:
    endpoint = _api_endpoint(base_url=base_url, api_version=api_version, suffix="field")
    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
    }
    data = _get_json(endpoint, headers=headers, timeout=timeout_seconds, ssl_context=ssl_context)
    return data if isinstance(data, list) else []


def _best_field_match(token: str, fields: List[Dict[str, Any]], custom_only: bool) -> str | None:
    token_slug = _slug(token)
    if not token_slug:
        return None

    token_parts = [p for p in token_slug.split("_") if p]
    best_score = -1
    best_id: str | None = None

    for field in fields:
        field_id = str(field.get("id", ""))
        if not field_id:
            continue
        if custom_only and not field_id.startswith("customfield_"):
            continue

        name_slug = _slug(field.get("name", ""))
        clause_slugs = [_slug(c) for c in field.get("clauseNames", []) if c]
        candidates = [name_slug] + clause_slugs

        score = 0
        for cand in candidates:
            if not cand:
                continue
            if cand == token_slug:
                score = max(score, 100)
            elif token_slug in cand or cand in token_slug:
                score = max(score, 70)
            elif token_parts and all(part in cand for part in token_parts):
                score = max(score, 40)

        if score > best_score:
            best_score = score
            best_id = field_id

    return best_id if best_score >= 40 else None


def auto_resolve_placeholder_paths(config_path: Path, workspace_root: Path) -> Dict[str, Any]:
    cfg = load_sync_config(config_path)
    auth_header = _build_auth_header(cfg.jira)
    ssl_ctx = _build_ssl_context(cfg.jira.verify_ssl)
    fields = _fetch_jira_fields(
        base_url=cfg.jira.base_url,
        api_version=cfg.jira.api_version,
        auth_header=auth_header,
        timeout_seconds=cfg.jira.timeout_seconds,
        ssl_context=ssl_ctx,
    )

    data = _load_json(config_path)
    reports = _as_list(data.get("reports", []))
    resolved = 0
    unresolved: List[Dict[str, str]] = []

    for report in reports:
        cols = _as_list(report.get("columns", []))
        for col in cols:
            path = str(col.get("path", ""))
            if not _is_placeholder_path(path):
                continue

            token = _extract_placeholder_token(path)
            is_custom = "customfield_REPLACE_" in path
            field_id = _best_field_match(token=token, fields=fields, custom_only=is_custom)

            if field_id:
                col["path"] = f"fields.{field_id}"
                resolved += 1
            else:
                unresolved.append(
                    {
                        "report": str(report.get("name", "")),
                        "csv": str(col.get("csv", "")),
                        "placeholder": path,
                    }
                )

    with config_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    return {
        "config_path": str(config_path),
        "resolved": resolved,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }


def _safe_filename(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in {" ", "-", "_", ".", "(" , ")"}:
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip()


def _render_filename(template: str, report_name: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H_%M_%S%z")
    rendered = template.format(report_name=report_name, timestamp=ts, year=datetime.now().year)
    if not rendered.lower().endswith(".csv"):
        rendered += ".csv"
    return _safe_filename(rendered)


def _build_jql_with_since_date(jql: str, since_date: str | None) -> str:
    text = (jql or "").strip()
    if not since_date:
        return text

    date_filter = f"(created >= '{since_date}' OR updated >= '{since_date}')"
    if not text:
        return date_filter

    lowered = text.casefold()
    marker = " order by "
    idx = lowered.find(marker)
    if idx >= 0:
        base = text[:idx].strip()
        order_part = text[idx:].strip()
        return f"{base} AND {date_filter} {order_part}" if base else f"{date_filter} {order_part}"
    return f"{text} AND {date_filter}"


def _build_multi_grain_aggregation(df: pd.DataFrame) -> pd.DataFrame:
    dims = [d for d in DIMENSIONS.keys() if d in df.columns]
    frames: List[pd.DataFrame] = []

    for grain in TIME_GRAINS.keys():
        cube = build_agg_cube(
            df,
            time_grain=grain,
            groupby_dims=dims,
            source_types=None,
            date_col="created_at",
        )
        if cube.empty:
            continue
        cube = cube.copy()
        cube["time_grain"] = grain.lower()
        frames.append(cube)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _build_denormalized_multi_grain_aggregation(agg_df: pd.DataFrame) -> pd.DataFrame:
    if agg_df.empty:
        return pd.DataFrame()

    out = agg_df.copy()
    out["period_start"] = pd.to_datetime(out["period"], errors="coerce")
    out = out.dropna(subset=["period_start"]).copy()
    if out.empty:
        return pd.DataFrame()

    grain_alias_map = {k.lower(): v for k, v in TIME_GRAINS.items()}
    labels: List[str] = []
    period_end: List[pd.Timestamp] = []
    period_quarter: List[int] = []
    period_month: List[int] = []
    period_week: List[int] = []

    for _, row in out.iterrows():
        grain = str(row.get("time_grain", "")).lower()
        alias = grain_alias_map.get(grain, "M")
        ts = pd.Timestamp(row["period_start"])
        p = ts.to_period(alias)

        labels.append(str(p))
        period_end.append(p.end_time.normalize())
        period_quarter.append(int(ts.quarter))
        period_month.append(int(ts.month))
        period_week.append(int(ts.isocalendar().week))

    out["period_end"] = pd.to_datetime(period_end)
    out["period_label"] = labels
    out["period_year"] = out["period_start"].dt.year.astype("Int64")
    out["period_quarter"] = pd.Series(period_quarter, index=out.index, dtype="Int64")
    out["period_month"] = pd.Series(period_month, index=out.index, dtype="Int64")
    out["period_week"] = pd.Series(period_week, index=out.index, dtype="Int64")
    out["period_day"] = out["period_start"].dt.day.astype("Int64")

    source_series = out.get("source_type", pd.Series("", index=out.index)).fillna("").astype(str)
    out["source_type_label"] = source_series.map(SOURCE_TYPE_LABELS).fillna(source_series)

    return out.reset_index(drop=True)


def _upsert_vertica_from_local_csv(
    output_dir: Path,
    workspace_root: Path,
    vertica_config: VerticaConfig,
) -> tuple[int, int, str, str]:
    unified_df, _ = load_all_csvs(output_dir, workspace_root / "Report Schema sh.csv")
    agg_df = _build_multi_grain_aggregation(unified_df)
    if agg_df.empty:
        return 0, 0, f"{vertica_config.schema}.{vertica_config.table}", f"{vertica_config.schema}.{vertica_config.table}_denorm"

    dims = [d for d in DIMENSIONS.keys() if d in agg_df.columns]
    denorm_df = _build_denormalized_multi_grain_aggregation(agg_df)

    compact_rows = upsert_aggregation_to_vertica(agg_df, vertica_config, dimensions=dims)
    denorm_rows = upsert_denorm_aggregation_to_vertica(
        denorm_df,
        vertica_config,
        dimensions=dims,
    )

    compact_table = f"{vertica_config.schema}.{vertica_config.table}"
    denorm_table = f"{vertica_config.schema}.{vertica_config.table}_denorm"
    return compact_rows, denorm_rows, compact_table, denorm_table


def run_sync(
    config_path: Path,
    workspace_root: Path,
    jira_pat: str | None = None,
    since_date: str | None = None,
    vertica_config: VerticaConfig | None = None,
    prefer_cached_csv: bool = True,
) -> SyncResult:
    cfg = load_sync_config(config_path)

    if jira_pat:
        os.environ[cfg.jira.pat_env] = jira_pat

    output_dir = (workspace_root / cfg.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if vertica_config is not None and prefer_cached_csv:
        existing_csv_files = sorted(output_dir.glob("*.csv"))
        if existing_csv_files:
            vertica_table = f"{vertica_config.schema}.{vertica_config.table}"
            try:
                rows, denorm_rows, compact_table, denorm_table = _upsert_vertica_from_local_csv(
                    output_dir, workspace_root, vertica_config
                )
            except Exception as exc:
                return SyncResult(
                    output_dir=str(output_dir),
                    results=[],
                    vertica_rows_upserted=0,
                    vertica_denorm_rows_upserted=0,
                    vertica_table=vertica_table,
                    vertica_denorm_table=f"{vertica_table}_denorm",
                    vertica_error=str(exc),
                    vertica_skipped=False,
                )

            if rows == 0 and denorm_rows == 0:
                return SyncResult(
                    output_dir=str(output_dir),
                    results=[],
                    vertica_rows_upserted=0,
                    vertica_denorm_rows_upserted=0,
                    vertica_table=compact_table,
                    vertica_denorm_table=denorm_table,
                    vertica_error="Aggregation produced 0 rows from existing CSV files — nothing to upsert.",
                    vertica_skipped=False,
                )

            return SyncResult(
                output_dir=str(output_dir),
                results=[],
                vertica_rows_upserted=rows,
                vertica_denorm_rows_upserted=denorm_rows,
                vertica_table=compact_table,
                vertica_denorm_table=denorm_table,
                vertica_error="",
                vertica_skipped=False,
            )

    auth_header = _build_auth_header(cfg.jira)
    ssl_ctx = _build_ssl_context(cfg.jira.verify_ssl)

    results: List[ReportSyncResult] = []

    for report in cfg.reports:
        field_paths = [c.path for c in report.columns]
        # Avoid requesting unresolved placeholder fields from Jira API.
        fields = sorted(
            {
                p.split(".", 1)[1]
                for p in field_paths
                if p.startswith("fields.") and not _is_placeholder_path(p)
            }
        )

        issues = _fetch_all_issues(
            base_url=cfg.jira.base_url,
            api_version=cfg.jira.api_version,
            auth_header=auth_header,
            jql=_build_jql_with_since_date(report.jql, since_date),
            fields=fields,
            page_size=report.page_size,
            max_results=report.max_results,
            timeout_seconds=cfg.jira.timeout_seconds,
            expand=["renderedFields"],
            ssl_context=ssl_ctx,
        )

        rows: List[Dict[str, Any]] = []
        for issue in issues:
            row: Dict[str, Any] = {}
            for col in report.columns:
                row[col.csv] = _resolve_path(issue, col.path, default=col.default)
            rows.append(row)

        df = pd.DataFrame(rows)
        filename = _render_filename(report.filename_template, report.name)
        full_path = output_dir / filename
        df.to_csv(full_path, index=False)

        results.append(
            ReportSyncResult(
                report_key=report.key,
                report_name=report.name,
                file_path=str(full_path),
                issues_fetched=len(issues),
                rows_written=len(df),
            )
        )

    vertica_rows_upserted = 0
    vertica_denorm_rows_upserted = 0
    vertica_table = ""
    vertica_denorm_table = ""
    vertica_error = ""
    vertica_skipped = vertica_config is None

    if vertica_config is not None:
        vertica_table = f"{vertica_config.schema}.{vertica_config.table}"
        vertica_denorm_table = f"{vertica_config.schema}.{vertica_config.table}_denorm"
        try:
            (
                vertica_rows_upserted,
                vertica_denorm_rows_upserted,
                vertica_table,
                vertica_denorm_table,
            ) = _upsert_vertica_from_local_csv(
                output_dir, workspace_root, vertica_config
            )
            if vertica_rows_upserted == 0 and vertica_denorm_rows_upserted == 0:
                vertica_error = "Aggregation produced 0 rows — nothing to upsert."
        except Exception as exc:
            vertica_error = str(exc)

    return SyncResult(
        output_dir=str(output_dir),
        results=results,
        vertica_rows_upserted=vertica_rows_upserted,
        vertica_denorm_rows_upserted=vertica_denorm_rows_upserted,
        vertica_table=vertica_table,
        vertica_denorm_table=vertica_denorm_table,
        vertica_error=vertica_error,
        vertica_skipped=vertica_skipped,
    )


def diagnose_connection(config_path: Path) -> Dict[str, Any]:
    cfg = load_sync_config(config_path)
    auth_header = _build_auth_header(cfg.jira)
    ssl_ctx = _build_ssl_context(cfg.jira.verify_ssl)

    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
    }

    server_info_url = _api_endpoint(
        base_url=cfg.jira.base_url,
        api_version=cfg.jira.api_version,
        suffix="serverInfo",
    )
    myself_url = _api_endpoint(
        base_url=cfg.jira.base_url,
        api_version=cfg.jira.api_version,
        suffix="myself",
    )

    out: Dict[str, Any] = {
        "base_url": cfg.jira.base_url,
        "api_version": cfg.jira.api_version,
        "auth_type": cfg.jira.auth_type,
        "verify_ssl": cfg.jira.verify_ssl,
    }

    try:
        info = _get_json(server_info_url, headers=headers, timeout=cfg.jira.timeout_seconds, ssl_context=ssl_ctx)
        out["serverInfo_ok"] = True
        out["deploymentType"] = info.get("deploymentType", "") if isinstance(info, dict) else ""
    except Exception as exc:
        out["serverInfo_ok"] = False
        out["serverInfo_error"] = str(exc)

    try:
        me = _get_json(myself_url, headers=headers, timeout=cfg.jira.timeout_seconds, ssl_context=ssl_ctx)
        out["myself_ok"] = True
        if isinstance(me, dict):
            out["user"] = me.get("displayName") or me.get("name") or me.get("accountId", "")
    except Exception as exc:
        out["myself_ok"] = False
        out["myself_error"] = str(exc)

    return out
