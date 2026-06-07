from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd

try:
    import vertica_python
except Exception:  # pragma: no cover - optional dependency at runtime
    vertica_python = None


@dataclass
class VerticaConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str = "public"
    table: str = "qa_kpi_agg"


JDBC_RE = re.compile(r"^jdbc:vertica://([^:/]+)(?::(\d+))?/([^/?#]+)$", re.IGNORECASE)


def parse_jdbc_url(jdbc_url: str) -> Dict[str, str | int]:
    m = JDBC_RE.match((jdbc_url or "").strip())
    if not m:
        raise ValueError("Invalid JDBC URL. Expected format: jdbc:vertica://host:port/database")

    host = m.group(1)
    port = int(m.group(2) or "5433")
    database = m.group(3)
    return {"host": host, "port": port, "database": database}


def _quoted(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _full_table_name(schema: str, table: str) -> str:
    return f"{_quoted(schema)}.{_quoted(table)}"


def _candidate_hosts(host: str) -> List[str]:
    h = (host or "").strip()
    if not h:
        return ["localhost"]

    if h in {"localhost", "127.0.0.1", "::1"}:
        # In WSL/containers, localhost may not map to the host's forwarded ports.
        return [h, "host.docker.internal", "127.0.0.1"]

    return [h]


def _connect_vertica(cfg: VerticaConfig):
    errors: List[str] = []
    for host in _candidate_hosts(cfg.host):
        try:
            return vertica_python.connect(
                host=host,
                port=cfg.port,
                database=cfg.database,
                user=cfg.user,
                password=cfg.password,
                autocommit=False,
                connection_timeout=8,
            )
        except Exception as exc:  # pragma: no cover - network/runtime specific
            errors.append(f"{host}:{cfg.port} -> {exc}")

    attempted = "; ".join(errors)
    raise RuntimeError(
        "Failed to connect to Vertica. Tried hosts: "
        f"{', '.join(_candidate_hosts(cfg.host))}. Details: {attempted}"
    )


def _ensure_table(cur, full_table_name: str, dimensions: List[str]) -> None:
    dim_defs = ",\n".join(f"{_quoted(dim)} VARCHAR(256) NOT NULL DEFAULT ''" for dim in dimensions)
    key_cols = ["time_grain", "period"] + dimensions
    key_expr = ", ".join(_quoted(k) for k in key_cols)

    ddl = f"""
    CREATE TABLE IF NOT EXISTS {full_table_name} (
        { _quoted('time_grain') } VARCHAR(16) NOT NULL,
        { _quoted('period') } DATE NOT NULL,
        {dim_defs},
        { _quoted('total') } INT,
        { _quoted('pass_count') } INT,
        { _quoted('fail_count') } INT,
        { _quoted('open_count') } INT,
        { _quoted('closed_count') } INT,
        { _quoted('critical_count') } INT,
        { _quoted('pass_rate_pct') } FLOAT,
        { _quoted('avg_fix_cycle_days') } FLOAT,
        { _quoted('avg_defect_age_days') } FLOAT,
        { _quoted('last_updated_at') } TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY ({key_expr})
    )
    """
    cur.execute(ddl)


def _normalize_df(df: pd.DataFrame, dimensions: List[str]) -> pd.DataFrame:
    out = df.copy()
    out["period"] = pd.to_datetime(out["period"], errors="coerce").dt.date
    out = out.dropna(subset=["period"]) 

    out["time_grain"] = out["time_grain"].fillna("").astype(str)
    for dim in dimensions:
        if dim not in out.columns:
            out[dim] = ""
        out[dim] = out[dim].fillna("").astype(str)

    int_cols = ["total", "pass_count", "fail_count", "open_count", "closed_count", "critical_count"]
    for col in int_cols:
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)

    float_cols = ["pass_rate_pct", "avg_fix_cycle_days", "avg_defect_age_days"]
    for col in float_cols:
        if col not in out.columns:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")

    ordered = [
        "time_grain",
        "period",
        *dimensions,
        "total",
        "pass_count",
        "fail_count",
        "open_count",
        "closed_count",
        "critical_count",
        "pass_rate_pct",
        "avg_fix_cycle_days",
        "avg_defect_age_days",
    ]
    return out[ordered].reset_index(drop=True)


def test_vertica_connection(cfg: VerticaConfig) -> str:
    """Open a connection and run a trivial query. Returns server version text."""
    if vertica_python is None:
        raise RuntimeError("vertica-python is not installed. Add it to requirements and install dependencies.")

    conn = _connect_vertica(cfg)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT version()")
        row = cur.fetchone()
        if row and len(row) > 0:
            return str(row[0])
        return "Connected"
    finally:
        conn.close()


def _staging_table_name(base_table: str) -> str:
    """Return a unique temp staging table name for this load."""
    uid = uuid.uuid4().hex[:8]
    safe = re.sub(r"[^a-z0-9_]", "_", base_table.lower())
    return f"_stg_{safe}_{uid}"


def _create_staging_table(cur, staging: str, full_table: str, dimensions: List[str]) -> None:
    """Create a LOCAL TEMP table with the same measure columns as the target (no PK/FK)."""
    dim_defs = ",\n            ".join(
        f"{_quoted(dim)} VARCHAR(256)" for dim in dimensions
    )
    dim_block = f",\n            {dim_defs}" if dim_defs else ""
    ddl = f"""
        CREATE LOCAL TEMP TABLE {staging} (
            {_quoted('time_grain')} VARCHAR(16),
            {_quoted('period')} DATE{dim_block},
            {_quoted('total')} INT,
            {_quoted('pass_count')} INT,
            {_quoted('fail_count')} INT,
            {_quoted('open_count')} INT,
            {_quoted('closed_count')} INT,
            {_quoted('critical_count')} INT,
            {_quoted('pass_rate_pct')} FLOAT,
            {_quoted('avg_fix_cycle_days')} FLOAT,
            {_quoted('avg_defect_age_days')} FLOAT,
            {_quoted('last_updated_at')} TIMESTAMP
        ) ON COMMIT PRESERVE ROWS
    """
    cur.execute(ddl)


def _csv_buffer(df: pd.DataFrame, columns: List[str]) -> str:
    """Serialise *df* to a CSV string for COPY FROM STDIN. NaN → \\N (Vertica NULL)."""
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="\\N")
    return buf.getvalue()


def _copy_into_staging(cur, staging: str, df: pd.DataFrame, columns: List[str]) -> None:
    """Bulk-load *df* into the staging table using Vertica COPY FROM STDIN."""
    col_expr = ", ".join(_quoted(c) for c in columns)
    copy_sql = (
        f"COPY {staging} ({col_expr}) "
        "FROM STDIN "
        "DELIMITER ',' "
        "NULL '\\N' "
        "DIRECT "        # write straight to ROS, bypass WOS for large loads
        "ABORT ON ERROR"
    )
    cur.copy(copy_sql, _csv_buffer(df, columns))


def _merge_staging_to_target(
    cur, full_table: str, staging: str, dimensions: List[str]
) -> None:
    """MERGE rows from staging into the permanent target table."""
    key_cols = ["time_grain", "period"] + dimensions
    measure_cols = [
        "total", "pass_count", "fail_count", "open_count",
        "closed_count", "critical_count", "pass_rate_pct",
        "avg_fix_cycle_days", "avg_defect_age_days",
    ]
    all_cols = key_cols + measure_cols

    join_pred = " AND ".join(
        f"t.{_quoted(k)} = s.{_quoted(k)}" for k in key_cols
    )
    # Vertica MERGE does not accept target-table aliases in UPDATE SET.
    update_set = ",\n            ".join(
        f"{_quoted(m)} = s.{_quoted(m)}" for m in measure_cols
    ) + f",\n            {_quoted('last_updated_at')} = s.{_quoted('last_updated_at')}"

    insert_cols_expr = ", ".join(_quoted(c) for c in all_cols + ["last_updated_at"])
    insert_vals_expr = ", ".join(
        f"s.{_quoted(c)}" for c in all_cols + ["last_updated_at"]
    )

    merge_sql = f"""
        MERGE INTO {full_table} AS t
        USING {staging} AS s
        ON {join_pred}
        WHEN MATCHED THEN
            UPDATE SET
                {update_set}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols_expr})
            VALUES ({insert_vals_expr})
    """
    cur.execute(merge_sql)


def _create_staging_table_generic(
    cur,
    staging: str,
    column_defs: List[tuple[str, str]],
) -> None:
    cols_sql = ",\n            ".join(
        f"{_quoted(col)} {col_type}" for col, col_type in column_defs
    )
    ddl = f"""
        CREATE LOCAL TEMP TABLE {staging} (
            {cols_sql}
        ) ON COMMIT PRESERVE ROWS
    """
    cur.execute(ddl)


def _merge_staging_generic(
    cur,
    full_table: str,
    staging: str,
    key_cols: List[str],
    insert_cols: List[str],
    update_cols: List[str],
) -> None:
    join_pred = " AND ".join(
        f"t.{_quoted(k)} = s.{_quoted(k)}" for k in key_cols
    )
    update_set = ",\n            ".join(
        f"{_quoted(c)} = s.{_quoted(c)}" for c in update_cols
    )
    insert_cols_expr = ", ".join(_quoted(c) for c in insert_cols)
    insert_vals_expr = ", ".join(f"s.{_quoted(c)}" for c in insert_cols)

    merge_sql = f"""
        MERGE INTO {full_table} AS t
        USING {staging} AS s
        ON {join_pred}
        WHEN MATCHED THEN
            UPDATE SET
                {update_set}
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols_expr})
            VALUES ({insert_vals_expr})
    """
    cur.execute(merge_sql)


def upsert_aggregation_to_vertica(df: pd.DataFrame, cfg: VerticaConfig, dimensions: List[str]) -> int:
    """Bulk-load aggregated KPI data into Vertica using COPY + MERGE.

    Strategy
    --------
    1. Ensure the permanent target table exists.
    2. Create a LOCAL TEMP staging table (dropped automatically at session end).
    3. Stream the entire DataFrame into the staging table via ``COPY FROM STDIN``
       (Vertica's fastest ingest path — no per-row overhead).
    4. MERGE staging → target: UPDATE matched rows, INSERT new ones.
    5. Commit.  On any failure, roll back.

    Returns the number of rows upserted.
    """
    if vertica_python is None:
        raise RuntimeError(
            "vertica-python is not installed. Add it to requirements and install dependencies."
        )

    if df.empty:
        return 0

    normalized = _normalize_df(df, dimensions)
    if normalized.empty:
        return 0

    # Force UTC write-time for Vertica regardless of DB/session timezone.
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    normalized["last_updated_at"] = utc_now

    staging_cols = [
        "time_grain", "period", *dimensions,
        "total", "pass_count", "fail_count", "open_count",
        "closed_count", "critical_count", "pass_rate_pct",
        "avg_fix_cycle_days", "avg_defect_age_days", "last_updated_at",
    ]

    full_table = _full_table_name(cfg.schema, cfg.table)
    staging = _staging_table_name(cfg.table)

    conn = _connect_vertica(cfg)
    try:
        cur = conn.cursor()

        # 1. Ensure permanent target table
        _ensure_table(cur, full_table, dimensions)

        # 2. Create temp staging table
        _create_staging_table(cur, staging, full_table, dimensions)

        # 3. COPY FROM STDIN → staging (bulk fast path)
        _copy_into_staging(cur, staging, normalized, staging_cols)

        # 4. MERGE staging → target
        _merge_staging_to_target(cur, full_table, staging, dimensions)

        conn.commit()
        return len(normalized)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_denorm_table(cur, full_table_name: str, dimensions: List[str]) -> None:
    dim_defs = ",\n".join(f"{_quoted(dim)} VARCHAR(256) NOT NULL DEFAULT ''" for dim in dimensions)
    dim_block = f"{dim_defs},\n" if dim_defs else ""
    key_cols = ["time_grain", "period"] + dimensions
    key_expr = ", ".join(_quoted(k) for k in key_cols)

    ddl = f"""
    CREATE TABLE IF NOT EXISTS {full_table_name} (
        {_quoted('time_grain')} VARCHAR(16) NOT NULL,
        {_quoted('period')} DATE NOT NULL,
        {_quoted('period_start')} TIMESTAMP,
        {_quoted('period_end')} TIMESTAMP,
        {_quoted('period_label')} VARCHAR(64),
        {_quoted('period_year')} INT,
        {_quoted('period_quarter')} INT,
        {_quoted('period_month')} INT,
        {_quoted('period_week')} INT,
        {_quoted('period_day')} INT,
        {dim_block}
        {_quoted('source_type_label')} VARCHAR(64),
        {_quoted('total')} INT,
        {_quoted('pass_count')} INT,
        {_quoted('fail_count')} INT,
        {_quoted('open_count')} INT,
        {_quoted('closed_count')} INT,
        {_quoted('critical_count')} INT,
        {_quoted('pass_rate_pct')} FLOAT,
        {_quoted('avg_fix_cycle_days')} FLOAT,
        {_quoted('avg_defect_age_days')} FLOAT,
        {_quoted('last_updated_at')} TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY ({key_expr})
    )
    """
    cur.execute(ddl)


def _normalize_denorm_df(df: pd.DataFrame, dimensions: List[str]) -> pd.DataFrame:
    out = df.copy()

    out["period"] = pd.to_datetime(out["period"], errors="coerce").dt.date
    out["period_start"] = pd.to_datetime(out.get("period_start"), errors="coerce")
    out["period_end"] = pd.to_datetime(out.get("period_end"), errors="coerce")
    out = out.dropna(subset=["period"])

    if "time_grain" not in out.columns:
        out["time_grain"] = ""
    if "period_label" not in out.columns:
        out["period_label"] = ""
    if "source_type_label" not in out.columns:
        out["source_type_label"] = ""
    out["time_grain"] = out["time_grain"].fillna("").astype(str)
    out["period_label"] = out["period_label"].fillna("").astype(str)
    out["source_type_label"] = out["source_type_label"].fillna("").astype(str)

    for dim in dimensions:
        if dim not in out.columns:
            out[dim] = ""
        out[dim] = out[dim].fillna("").astype(str)

    int_cols = [
        "period_year",
        "period_quarter",
        "period_month",
        "period_week",
        "period_day",
        "total",
        "pass_count",
        "fail_count",
        "open_count",
        "closed_count",
        "critical_count",
    ]
    for col in int_cols:
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)

    float_cols = ["pass_rate_pct", "avg_fix_cycle_days", "avg_defect_age_days"]
    for col in float_cols:
        if col not in out.columns:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")

    ordered = [
        "time_grain",
        "period",
        "period_start",
        "period_end",
        "period_label",
        "period_year",
        "period_quarter",
        "period_month",
        "period_week",
        "period_day",
        *dimensions,
        "source_type_label",
        "total",
        "pass_count",
        "fail_count",
        "open_count",
        "closed_count",
        "critical_count",
        "pass_rate_pct",
        "avg_fix_cycle_days",
        "avg_defect_age_days",
    ]
    return out[ordered].reset_index(drop=True)


def upsert_denorm_aggregation_to_vertica(
    df: pd.DataFrame,
    cfg: VerticaConfig,
    dimensions: List[str],
    table_suffix: str = "_denorm",
) -> int:
    """Bulk-load denormalized multi-grain aggregation data into Vertica."""
    if vertica_python is None:
        raise RuntimeError(
            "vertica-python is not installed. Add it to requirements and install dependencies."
        )

    if df.empty:
        return 0

    normalized = _normalize_denorm_df(df, dimensions)
    if normalized.empty:
        return 0

    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    normalized["last_updated_at"] = utc_now

    target_table = f"{cfg.table}{table_suffix}"
    full_table = _full_table_name(cfg.schema, target_table)
    staging = _staging_table_name(target_table)

    key_cols = ["time_grain", "period", *dimensions]
    insert_cols = [
        "time_grain",
        "period",
        "period_start",
        "period_end",
        "period_label",
        "period_year",
        "period_quarter",
        "period_month",
        "period_week",
        "period_day",
        *dimensions,
        "source_type_label",
        "total",
        "pass_count",
        "fail_count",
        "open_count",
        "closed_count",
        "critical_count",
        "pass_rate_pct",
        "avg_fix_cycle_days",
        "avg_defect_age_days",
        "last_updated_at",
    ]
    update_cols = [c for c in insert_cols if c not in key_cols]

    column_defs: List[tuple[str, str]] = [
        ("time_grain", "VARCHAR(16)"),
        ("period", "DATE"),
        ("period_start", "TIMESTAMP"),
        ("period_end", "TIMESTAMP"),
        ("period_label", "VARCHAR(64)"),
        ("period_year", "INT"),
        ("period_quarter", "INT"),
        ("period_month", "INT"),
        ("period_week", "INT"),
        ("period_day", "INT"),
    ]
    column_defs.extend((d, "VARCHAR(256)") for d in dimensions)
    column_defs.extend(
        [
            ("source_type_label", "VARCHAR(64)"),
            ("total", "INT"),
            ("pass_count", "INT"),
            ("fail_count", "INT"),
            ("open_count", "INT"),
            ("closed_count", "INT"),
            ("critical_count", "INT"),
            ("pass_rate_pct", "FLOAT"),
            ("avg_fix_cycle_days", "FLOAT"),
            ("avg_defect_age_days", "FLOAT"),
            ("last_updated_at", "TIMESTAMP"),
        ]
    )

    conn = _connect_vertica(cfg)
    try:
        cur = conn.cursor()
        _ensure_denorm_table(cur, full_table, dimensions)
        _create_staging_table_generic(cur, staging, column_defs)
        _copy_into_staging(cur, staging, normalized, insert_cols)
        _merge_staging_generic(
            cur=cur,
            full_table=full_table,
            staging=staging,
            key_cols=key_cols,
            insert_cols=insert_cols,
            update_cols=update_cols,
        )
        conn.commit()
        return len(normalized)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()