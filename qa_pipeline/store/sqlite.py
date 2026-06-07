"""
qa_pipeline.store.sqlite
=========================
SQLite staging layer – the first stop for all pipeline output.

Three tables are managed:
    * ``agg_test_fact``   – AGG_TEST_WITH_DEFECTS (test runs enriched with defects)
    * ``defect_dim``      – defect dimension (sprint-annotated, one row per bug)
    * ``test_created``    – Test Created Jira export staging table

Design decisions
----------------
* Columns are stored as TEXT – matches the CSV-origin nature of the data and
  avoids silent coercion on schema changes.
* Upsert uses ``INSERT OR REPLACE`` keyed on the natural business key for each
  table, so re-running the pipeline is idempotent.
* The class is a context manager so the connection is always closed cleanly.
* Type conversion is handled by qa_pipeline.schema module for downstream consumers.

Usage
-----
    from qa_pipeline.store.sqlite import SqliteStore
    from qa_pipeline.schema import convert_df_to_schema, AGG_TEST_FACT_SCHEMA

    # Write: pipeline output is automatically stored as TEXT in SQLite
    with SqliteStore.open(db_path) as store:
        rows = store.upsert_defect_dim(defect_df)
        rows = store.upsert_agg_fact(fact_df)

    # Read back with proper types for downstream
    with SqliteStore.open(db_path) as store:
        defect_df = store.read_defect_dim_typed()  # Returns proper types
        fact_df   = store.read_agg_fact_typed()    # Returns proper types

    # Or read raw (TEXT) and convert later
    with SqliteStore.open(db_path) as store:
        fact_df_text = store.read_agg_fact()
        fact_df_typed = convert_df_to_schema(fact_df_text, AGG_TEST_FACT_SCHEMA)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import List

import pandas as pd

from qa_pipeline.schema import (
    AGG_TEST_FACT_SCHEMA,
    DEFECT_DIM_SCHEMA,
    TEST_CREATED_SCHEMA,
    convert_df_to_schema,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _col_defs(columns: List[str]) -> str:
    return ",\n    ".join(f'"{col}" TEXT' for col in columns)


def _create_table_sql(table: str, columns: List[str], pk_cols: List[str]) -> str:
    pk_expr = ", ".join(f'"{c}"' for c in pk_cols)
    return (
        f'CREATE TABLE IF NOT EXISTS "{table}" (\n'
        f"    {_col_defs(columns)},\n"
        f"    PRIMARY KEY ({pk_expr})\n"
        f");"
    )


def _align_columns(df: pd.DataFrame, existing_cols: List[str]) -> pd.DataFrame:
    """Ensure *df* has exactly *existing_cols* (add missing as empty, drop extra)."""
    for col in existing_cols:
        if col not in df.columns:
            df = df.copy()
            df[col] = ""
    return df[existing_cols]


def _add_missing_columns(cur: sqlite3.Cursor, table: str, new_columns: List[str]) -> None:
    """ALTER TABLE to add any columns that don't already exist."""
    cur.execute(f'PRAGMA table_info("{table}")')
    existing = {row[1] for row in cur.fetchall()}
    for col in new_columns:
        if col not in existing:
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT DEFAULT ""')
            logger.debug("Added column %r to table %r", col, table)


def _upsert_df(
    conn: sqlite3.Connection,
    table: str,
    df: pd.DataFrame,
    pk_cols: List[str],
) -> int:
    """Upsert *df* into *table* using INSERT OR REPLACE semantics.

    Creates the table on the first call; evolves the schema automatically
    when new columns appear in subsequent runs.
    """
    if df.empty:
        return 0

    # Convert all dtypes to object strings safely.
    # nullable integer/boolean dtypes (Int64, boolean) cannot fillna("") directly.
    frame = df.copy()
    for col in frame.columns:
        if hasattr(frame[col], "dtype") and str(frame[col].dtype) in {
            "Int8", "Int16", "Int32", "Int64",
            "UInt8", "UInt16", "UInt32", "UInt64",
            "boolean",
        }:
            frame[col] = frame[col].astype(object).where(frame[col].notna(), other="")
    frame = frame.fillna("").astype(str)
    columns = list(frame.columns)

    cur = conn.cursor()

    # Ensure table exists with current column set
    cur.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    if cur.fetchone() is None:
        cur.execute(_create_table_sql(table, columns, pk_cols))
        logger.info("Created table %r with %d columns", table, len(columns))
    else:
        _add_missing_columns(cur, table, columns)

    col_expr = ", ".join(f'"{c}"' for c in columns)
    placeholder = ", ".join("?" for _ in columns)
    sql = f'INSERT OR REPLACE INTO "{table}" ({col_expr}) VALUES ({placeholder})'

    rows = [tuple(row) for row in frame.itertuples(index=False, name=None)]
    cur.executemany(sql, rows)
    conn.commit()

    logger.info("Upserted %d rows into %r", len(rows), table)
    return len(rows)


def _create_test_created_typed_view(conn: sqlite3.Connection, table: str) -> None:
    """Create a typed SQL view over the raw test_created staging table.

    SQLite does not have a native DATETIME storage class, so the view exposes:
      - normalized datetime text columns (UTC)
      - epoch integer columns for reliable numeric filtering/sorting
    """
    view = f"{table}_typed_v"
    cur = conn.cursor()
    cur.execute(f'DROP VIEW IF EXISTS "{view}"')
    cur.execute(
        f'''
        CREATE VIEW "{view}" AS
        SELECT
            "Issue key" AS issue_key,
            "Issue Type" AS issue_type,
            "Project key" AS project_key,
            "Creator" AS creator,
            datetime(
                CASE
                    WHEN length("Created") >= 28
                    THEN substr("Created", 1, 19)
                         || substr("Created", 24, 1)
                         || substr("Created", 25, 2)
                         || ':'
                         || substr("Created", 27, 2)
                    ELSE "Created"
                END
            ) AS created_utc,
            datetime(
                CASE
                    WHEN length("Updated") >= 28
                    THEN substr("Updated", 1, 19)
                         || substr("Updated", 24, 1)
                         || substr("Updated", 25, 2)
                         || ':'
                         || substr("Updated", 27, 2)
                    ELSE "Updated"
                END
            ) AS updated_utc,
            CAST(
                strftime(
                    '%s',
                    CASE
                        WHEN length("Created") >= 28
                        THEN substr("Created", 1, 19)
                             || substr("Created", 24, 1)
                             || substr("Created", 25, 2)
                             || ':'
                             || substr("Created", 27, 2)
                        ELSE "Created"
                    END
                ) AS INTEGER
            ) AS created_epoch,
            CAST(
                strftime(
                    '%s',
                    CASE
                        WHEN length("Updated") >= 28
                        THEN substr("Updated", 1, 19)
                             || substr("Updated", 24, 1)
                             || substr("Updated", 25, 2)
                             || ':'
                             || substr("Updated", 27, 2)
                        ELSE "Updated"
                    END
                ) AS INTEGER
            ) AS updated_epoch,
            "Custom field (Epic Link)" AS epic_link,
            "Custom field (TestRunStatus)" AS test_run_status,
            "Custom field (Automated)" AS automated,
            "Related Bugs" AS related_bugs,
            "Inward issue link (Related Bugs)" AS inward_related_bugs,
            "Outward issue link (Defect)" AS outward_defect,
            "Custom field (Customer Name (epic))" AS customer_name_epic,
            "Custom field (Test Sets association with a Test)" AS test_sets,
            "Custom field (Related Stories/Tasks)" AS related_stories_tasks
        FROM "{table}"
        '''
    )
    conn.commit()
    logger.info("Created view %r", view)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class SqliteStore:
    """Manages the staging tables inside a single SQLite database.

    Parameters
    ----------
    conn:
        Open ``sqlite3.Connection``.
    agg_fact_table:
        Name of the fact table (default ``agg_test_fact``).
    defect_dim_table:
        Name of the dimension table (default ``defect_dim``).
    test_created_table:
        Name of the test-created table (default ``test_created``).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        agg_fact_table: str = "agg_test_fact",
        defect_dim_table: str = "defect_dim",
        test_created_table: str = "test_created",
    ) -> None:
        self._conn = conn
        self.agg_fact_table = agg_fact_table
        self.defect_dim_table = defect_dim_table
        self.test_created_table = test_created_table

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        db_path: Path | str,
        *,
        agg_fact_table: str = "agg_test_fact",
        defect_dim_table: str = "defect_dim",
        test_created_table: str = "test_created",
    ) -> "SqliteStore":
        """Open a SQLite connection and return a ready-to-use store."""
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent access
        conn.execute("PRAGMA foreign_keys=ON")
        logger.info("Opened SQLite store at %s", path)
        return cls(
            conn,
            agg_fact_table=agg_fact_table,
            defect_dim_table=defect_dim_table,
            test_created_table=test_created_table,
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_defect_dim(self, df: pd.DataFrame) -> int:
        """Upsert the defect dimension.

        Natural key: ``Bugs`` (Jira issue key of the bug).

        Returns number of rows written.
        """
        pk = ["Bugs"]
        if "Bugs" not in df.columns:
            raise ValueError("defect_dim DataFrame must have a 'Bugs' column")
        return _upsert_df(self._conn, self.defect_dim_table, df, pk_cols=pk)

    def upsert_agg_fact(self, df: pd.DataFrame) -> int:
        """Upsert the AGG_TEST_WITH_DEFECTS fact table.

        Natural key: ``(Issue key, Block_Number, Bugs, bug_idx)``.
        Falls back to ``(Issue key, Block_Number)`` if Bugs columns are absent.

        Returns number of rows written.
        """
        if "Bugs" in df.columns and "bug_idx" in df.columns:
            pk = ["Issue key", "Block_Number", "Bugs", "bug_idx"]
        else:
            pk = ["Issue key", "Block_Number"]

        available_pk = [c for c in pk if c in df.columns]
        if not available_pk:
            raise ValueError(
                "agg_test_fact DataFrame must have at least 'Issue key' column"
            )
        return _upsert_df(self._conn, self.agg_fact_table, df, pk_cols=available_pk)

    def upsert_test_created(self, df: pd.DataFrame) -> int:
        """Upsert Test Created staging rows.

        Natural key: ``Issue key`` if present; otherwise first available column.
        """
        if df.empty:
            return 0

        if "Issue key" in df.columns:
            pk = ["Issue key"]
        else:
            pk = [df.columns[0]]

        rows = _upsert_df(self._conn, self.test_created_table, df, pk_cols=pk)
        _create_test_created_typed_view(self._conn, self.test_created_table)
        return rows

    # ------------------------------------------------------------------
    # Read operations (used by Vertica push)
    # ------------------------------------------------------------------

    def read_defect_dim(self) -> pd.DataFrame:
        """Load the full defect dimension table (as TEXT, no type conversion).
        
        Use ``read_defect_dim_typed()`` to get proper types for downstream consumers.
        """
        return pd.read_sql_query(
            f'SELECT * FROM "{self.defect_dim_table}"', self._conn
        )

    def read_defect_dim_typed(self) -> pd.DataFrame:
        """Load defect dimension with proper data types applied.
        
        Converts all columns to their appropriate types (datetime, int, float, bool, str)
        according to DEFECT_DIM_SCHEMA. Safe for downstream analytics, Vertica, or BI tools.
        
        Returns
        -------
        pd.DataFrame
            Defect dimension with typed columns.
        
        Example
        -------
        >>> with SqliteStore.open(db_path) as store:
        ...     df = store.read_defect_dim_typed()
        ...     df['Bug Created'].dtype  # datetime64[ns, UTC]
        ...     df['Story Points'].dtype  # float64
        """
        df = self.read_defect_dim()
        return convert_df_to_schema(df, DEFECT_DIM_SCHEMA, strict=False)

    def read_agg_fact(self) -> pd.DataFrame:
        """Load the full fact table (as TEXT, no type conversion).
        
        Use ``read_agg_fact_typed()`` to get proper types for downstream consumers.
        """
        return pd.read_sql_query(
            f'SELECT * FROM "{self.agg_fact_table}"', self._conn
        )

    def read_test_created(self) -> pd.DataFrame:
        """Load the full Test Created staging table (as TEXT)."""
        return pd.read_sql_query(
            f'SELECT * FROM "{self.test_created_table}"', self._conn
        )

    def read_test_created_typed(self) -> pd.DataFrame:
        """Load Test Created table with proper data types applied."""
        df = self.read_test_created()
        return convert_df_to_schema(df, TEST_CREATED_SCHEMA, strict=False)

    def read_agg_fact_typed(self) -> pd.DataFrame:
        """Load fact table with proper data types applied.
        
        Converts all columns to their appropriate types (datetime, int, float, bool, str)
        according to AGG_TEST_FACT_SCHEMA. Safe for downstream analytics, Vertica, or BI tools.
        
        Returns
        -------
        pd.DataFrame
            Aggregation fact table with typed columns.
        
        Example
        -------
        >>> with SqliteStore.open(db_path) as store:
        ...     df = store.read_agg_fact_typed()
        ...     df['Created'].dtype  # datetime64[ns, UTC]
        ...     df['No of Test Scenario'].dtype  # int64
        ...     df['Test Pass %'].dtype  # float64
        """
        df = self.read_agg_fact()
        return convert_df_to_schema(df, AGG_TEST_FACT_SCHEMA, strict=False)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def table_counts(self) -> dict[str, int]:
        """Return row counts for managed tables."""
        counts: dict[str, int] = {}
        cur = self._conn.cursor()
        for table in (
            self.agg_fact_table,
            self.defect_dim_table,
            self.test_created_table,
        ):
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = -1
        return counts
