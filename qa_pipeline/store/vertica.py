"""
qa_pipeline.store.vertica
==========================
Vertica push layer – reads staged data from SQLite and bulk-loads it to
three Vertica tables via COPY FROM STDIN + MERGE.

Tables pushed
-------------
* ``qa_agg_test_fact``  – from ``agg_test_fact`` SQLite table
* ``qa_defect_dim``     – from ``defect_dim``    SQLite table
* ``qa_test_created``   – from ``test_created``  SQLite table

Design
------
* All columns are VARCHAR(2048) in Vertica (matches TEXT origin from SQLite).
* Primary keys are declared but Vertica does not enforce them; they drive the
  MERGE ON clause for idempotent upserts.
* The module has an optional dependency on ``vertica-python``.  If absent,
  calling any push function raises ``RuntimeError`` with an install hint.
* SQLite is the source of truth; this module only reads from it.

Usage
-----
    from qa_pipeline.store.sqlite import SqliteStore
    from qa_pipeline.store.vertica import VerticaStore
    from qa_pipeline.config import VerticaConfig

    cfg = VerticaConfig(host="...", port=5433, database="vdb",
                        user="dbadmin", password="...")

    with SqliteStore.open(db_path) as store:
        vs = VerticaStore(cfg)
        dim_rows  = vs.push_defect_dim(store)
        fact_rows = vs.push_agg_fact(store)
        test_rows = vs.push_test_created(store)
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

import pandas as pd

try:
    import vertica_python
except Exception:   # pragma: no cover – optional at runtime
    vertica_python = None  # type: ignore[assignment]

from qa_pipeline.config import VerticaConfig
from qa_pipeline.store.sqlite import SqliteStore

logger = logging.getLogger(__name__)

_VARCHAR = "VARCHAR(2048)"
_TS_COL = "last_updated_at"


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _full(schema: str, table: str) -> str:
    return f"{_q(schema)}.{_q(table)}"


def _candidate_hosts(host: str) -> List[str]:
    h = (host or "").strip()
    if not h:
        return ["localhost"]
    if h in {"localhost", "127.0.0.1", "::1"}:
        return [h, "host.docker.internal", "127.0.0.1"]
    return [h]


def _connect(cfg: VerticaConfig):
    if vertica_python is None:
        raise RuntimeError(
            "vertica-python is not installed. Run: pip install vertica-python"
        )
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
                connection_timeout=10,
            )
        except Exception as exc:   # pragma: no cover
            errors.append(f"{host}:{cfg.port} → {exc}")
    raise RuntimeError(
        "Failed to connect to Vertica. Details: " + "; ".join(errors)
    )


# ---------------------------------------------------------------------------
# DDL + upsert helpers
# ---------------------------------------------------------------------------

def _staging_name(base: str) -> str:
    uid = uuid.uuid4().hex[:8]
    safe = base.lower().replace('"', "")[:32]
    return f"_stg_{safe}_{uid}"



_TIMESTAMP_SUFFIXES = (
    "created", "updated", "resolved", "closed", "opened",
    "start", "end", "date", "time",
)


def _is_timestamp_col(col_name: str) -> bool:
    """Return True when a column name looks like a datetime field.

    Uses suffix matching so "Bug Created", "Sprint End", "Created" all match,
    but "Closed Bugs" or "Open Bugs" do not.
    """
    lower = col_name.lower().strip()
    return any(lower == s or lower.endswith(" " + s) for s in _TIMESTAMP_SUFFIXES)


def _create_flex_table(cur, full_name: str, columns: List[str], pk_cols: List[str]) -> None:
    """CREATE TABLE IF NOT EXISTS with all VARCHAR columns."""
    col_defs_list = []
    for c in columns:
        if _is_timestamp_col(c):
            col_defs_list.append(f"    {_q(c)} TIMESTAMP")
        else:
            col_defs_list.append(f"    {_q(c)} {_VARCHAR} DEFAULT ''")
    col_defs = ",\n".join(col_defs_list)
    ts_def = f"    {_q(_TS_COL)} TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    pk_expr = ", ".join(_q(c) for c in pk_cols)
    ddl = (
        f"CREATE TABLE IF NOT EXISTS {full_name} (\n"
        f"{col_defs},\n"
        f"{ts_def},\n"
        f"    PRIMARY KEY ({pk_expr})\n"
        f");"
    )
    cur.execute(ddl)


def _create_staging(cur, staging: str, columns: List[str]) -> None:
    """Create staging table with all VARCHAR columns for CSV loading.
    
    Staging is always VARCHAR since we load from CSV strings.
    The target table has proper types; MERGE converts as needed.
    """
    col_defs = ",\n".join(
        f"    {_q(c)} VARCHAR(2048)" for c in columns
    )
    ts_def = f"    {_q(_TS_COL)} VARCHAR(2048)"
    cur.execute(
        f"CREATE LOCAL TEMP TABLE {staging} (\n"
        f"{col_defs},\n{ts_def}\n"
        f") ON COMMIT PRESERVE ROWS"
    )


def _csv_buffer(df: pd.DataFrame, columns: List[str]) -> str:
    """Generate CSV with proper quoting for all string fields.

    Uses QUOTE_NONNUMERIC so all text values are enclosed in quotes,
    preventing pipe-delimited values (like Sub-Tasks) from breaking row parsing.
    """
    buf = io.StringIO()
    df[columns].to_csv(
        buf,
        index=False,
        header=False,
        na_rep="\\N",
        quoting=csv.QUOTE_NONNUMERIC,
        doublequote=True,
    )
    return buf.getvalue()


def _copy_to_staging(cur, staging: str, df: pd.DataFrame, columns: List[str]) -> None:
    col_expr = ", ".join(_q(c) for c in columns)
    # ENCLOSED BY '"' tells Vertica fields are quoted
    # DIRECT mode bypasses slow parser; allows bulk insert optimization
    cur.copy(
        f"COPY {staging} ({col_expr}) FROM STDIN DELIMITER ',' ENCLOSED BY '\"' NULL '\\N' DIRECT",
        _csv_buffer(df, columns),
    )


def _merge_into_target(
    cur, full_name: str, staging: str, pk_cols: List[str], measure_cols: List[str]
) -> None:
    def _src_expr(c: str) -> str:
        """SQL expression to read column c from the staging alias s."""
        if _is_timestamp_col(c):
            return f"NULLIF(s.{_q(c)}, '')::TIMESTAMP"
        return f"s.{_q(c)}"

    join_pred = " AND ".join(f"t.{_q(k)} = s.{_q(k)}" for k in pk_cols)
    update_set = ",\n            ".join(
        f"{_q(m)} = {_src_expr(m)}" for m in measure_cols
    )
    all_cols = pk_cols + measure_cols
    insert_cols = ", ".join(_q(c) for c in all_cols + [_TS_COL])
    insert_vals = ", ".join([*(_src_expr(c) for c in all_cols), f"s.{_q(_TS_COL)}::TIMESTAMP"])
    cur.execute(
        f"""
        MERGE INTO {full_name} AS t
        USING {staging} AS s
        ON {join_pred}
        WHEN MATCHED THEN
            UPDATE SET {update_set},
                       {_q(_TS_COL)} = s.{_q(_TS_COL)}::TIMESTAMP
        WHEN NOT MATCHED THEN
            INSERT ({insert_cols}) VALUES ({insert_vals})
        """
    )


def _add_missing_vertica_cols(cur, full_name: str, columns: List[str]) -> None:
    cur.execute(f"SELECT column_name FROM columns WHERE table_name = ?", (full_name,))
    existing = {row[0] for row in cur.fetchall()}
    for col in columns:
        if col not in existing:
            cur.execute(f"ALTER TABLE {full_name} ADD COLUMN {_q(col)} {_VARCHAR} DEFAULT ''")
            logger.debug("Added column %r to Vertica table %r", col, full_name)


def _push_dataframe(
    cfg: VerticaConfig,
    df: pd.DataFrame,
    target_table: str,
    pk_cols: List[str],
) -> int:
    """Upsert *df* into Vertica using COPY + MERGE pattern.
    
    Preserves numeric and timestamp types during conversion.
    String columns are properly quoted in CSV output.
    """
    if df.empty:
        return 0

    frame = df.copy()
    all_cols = list(frame.columns)
    measure_cols = [c for c in all_cols if c not in pk_cols]

    # Keep all columns as strings for CSV output
    # Type conversion happens in MERGE via TRY_TO_* functions
    for col in all_cols:
        frame[col] = frame[col].fillna("").astype(str)

    # Add last_updated_at with UTC timestamp
    frame[_TS_COL] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    full_name = _full(cfg.schema, target_table)
    staging = _staging_name(target_table)
    copy_cols = all_cols + [_TS_COL]

    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        _create_flex_table(cur, full_name, all_cols, pk_cols)
        _create_staging(cur, staging, all_cols)
        _copy_to_staging(cur, staging, frame, copy_cols)
        _merge_into_target(cur, full_name, staging, pk_cols, measure_cols)
        conn.commit()
        logger.info("Pushed %d rows to Vertica table %r", len(frame), full_name)
        return len(frame)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class VerticaStore:
    """Pushes staged data from SQLite to Vertica.

    Parameters
    ----------
    cfg:
        ``VerticaConfig`` with connection details and target table names.
    """

    def __init__(self, cfg: VerticaConfig) -> None:
        self.cfg = cfg

    def push_defect_dim(self, store: SqliteStore) -> int:
        """Read defect_dim from SQLite, push to Vertica ``cfg.defect_dim_table``.

        Primary key: ``Bugs`` (Jira issue key of the bug).

        Returns
        -------
        int
            Number of rows pushed.
        """
        df = store.read_defect_dim()
        if df.empty:
            logger.warning("defect_dim table is empty – nothing to push to Vertica")
            return 0
        return _push_dataframe(
            cfg=self.cfg,
            df=df,
            target_table=self.cfg.defect_dim_table,
            pk_cols=["Bugs"],
        )

    def push_agg_fact(self, store: SqliteStore) -> int:
        """Read agg_test_fact from SQLite, push to Vertica ``cfg.agg_fact_table``.

        Primary key: ``(Issue key, Block_Number, Bugs, bug_idx)`` if available,
        else ``(Issue key, Block_Number)``.

        Returns
        -------
        int
            Number of rows pushed.
        """
        df = store.read_agg_fact()
        if df.empty:
            logger.warning("agg_test_fact table is empty – nothing to push to Vertica")
            return 0

        if "Bugs" in df.columns and "bug_idx" in df.columns:
            pk = ["Issue key", "Block_Number", "Bugs", "bug_idx"]
        else:
            pk = ["Issue key", "Block_Number"]

        available_pk = [c for c in pk if c in df.columns]
        return _push_dataframe(
            cfg=self.cfg,
            df=df,
            target_table=self.cfg.agg_fact_table,
            pk_cols=available_pk,
        )

    def push_test_created(self, store: SqliteStore) -> int:
        """Read test_created from SQLite, push to Vertica ``cfg.test_created_table``.

        Primary key: ``Issue key``.

        Returns
        -------
        int
            Number of rows pushed.
        """
        df = store.read_test_created()
        if df.empty:
            logger.warning("test_created table is empty – nothing to push to Vertica")
            return 0

        pk = ["Issue key"] if "Issue key" in df.columns else [df.columns[0]]
        return _push_dataframe(
            cfg=self.cfg,
            df=df,
            target_table=self.cfg.test_created_table,
            pk_cols=pk,
        )

    def push_all(self, store: SqliteStore) -> Tuple[int, int, int]:
        """Push all staging tables.

        Returns
        -------
        tuple[int, int, int]
            ``(agg_fact_rows, defect_dim_rows, test_created_rows)``
        """
        fact_rows = self.push_agg_fact(store)
        dim_rows = self.push_defect_dim(store)
        test_created_rows = self.push_test_created(store)
        return fact_rows, dim_rows, test_created_rows
