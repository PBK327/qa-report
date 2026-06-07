"""
Schema utility commands for QA pipeline.

Provides CLI commands to:
- Show schema definitions
- Export data with proper types
- Verify data types in stored tables
"""

import logging
from pathlib import Path

import pandas as pd

from qa_pipeline.config import load_pipeline_config
from qa_pipeline.schema import (
    AGG_TEST_FACT_SCHEMA,
    DEFECT_DIM_SCHEMA,
    describe_schema,
    get_sql_create_from_schema,
)
from qa_pipeline.store.sqlite import SqliteStore

logger = logging.getLogger(__name__)


def cmd_show_schema_agg_fact() -> None:
    """Show AGG_TEST_FACT table schema with data types."""
    print("\n" + "=" * 80)
    print("AGG_TEST_FACT Schema (Aggregation Fact Table)")
    print("=" * 80)
    print("\nColumns and their data types:")
    print(describe_schema(AGG_TEST_FACT_SCHEMA))
    print("\n\nSQL CREATE TABLE statement:")
    sql = get_sql_create_from_schema(
        "agg_test_fact",
        AGG_TEST_FACT_SCHEMA,
        pk_cols=["Issue key", "Block_Number", "Bugs", "bug_idx"],
    )
    print(sql)
    print()


def cmd_show_schema_defect_dim() -> None:
    """Show DEFECT_DIM table schema with data types."""
    print("\n" + "=" * 80)
    print("DEFECT_DIM Schema (Defect Dimension Table)")
    print("=" * 80)
    print("\nColumns and their data types:")
    print(describe_schema(DEFECT_DIM_SCHEMA))
    print("\n\nSQL CREATE TABLE statement:")
    sql = get_sql_create_from_schema(
        "defect_dim",
        DEFECT_DIM_SCHEMA,
        pk_cols=["Bugs"],
    )
    print(sql)
    print()


def cmd_verify_types() -> None:
    """Verify and display current data types in SQLite tables."""
    cfg = load_pipeline_config()
    db_path = cfg.sqlite_db_path

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Run 'make process' to generate data first.")
        return

    print("\n" + "=" * 80)
    print("Current Data Types in SQLite Tables")
    print("=" * 80)

    with SqliteStore.open(db_path) as store:
        counts = store.table_counts()
        print(f"\nTable Counts: {counts}")

        # Read typed data
        print("\n--- Reading with TYPED conversion ---")
        print("\nDefect Dimension (typed):")
        defect_typed = store.read_defect_dim_typed()
        print(f"  Shape: {defect_typed.shape}")
        print(f"  Data types:\n{defect_typed.dtypes}")

        print("\n\nAggregation Fact (typed):")
        fact_typed = store.read_agg_fact_typed()
        print(f"  Shape: {fact_typed.shape}")
        print(f"  Data types:\n{fact_typed.dtypes}")

        # Show sample values with types
        print("\n\n--- Sample Data (Defect Dimension) ---")
        if not defect_typed.empty:
            sample_cols = [
                col for col in ["Bugs", "Bug Created", "Story Points", "Priority"]
                if col in defect_typed.columns
            ]
            if sample_cols:
                print(defect_typed[sample_cols].head(3))

        print("\n\n--- Sample Data (Fact Table) ---")
        if not fact_typed.empty:
            sample_cols = [
                col for col in ["Issue key", "Created", "No of Test Scenario", "Test Pass %"]
                if col in fact_typed.columns
            ]
            if sample_cols:
                print(fact_typed[sample_cols].head(3))


def cmd_export_typed_csv(output_dir: str = "typed_exports") -> None:
    """Export typed data to CSV files for external analysis.
    
    Parameters
    ----------
    output_dir:
        Directory to save exported CSVs (will be created if missing).
    """
    cfg = load_pipeline_config()
    db_path = cfg.sqlite_db_path
    out_path = Path(output_dir)
    out_path.mkdir(exist_ok=True)

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    print(f"\nExporting typed data to {out_path}/")

    with SqliteStore.open(db_path) as store:
        # Export defect dimension
        defect_typed = store.read_defect_dim_typed()
        defect_file = out_path / "defect_dim_typed.csv"
        defect_typed.to_csv(defect_file, index=False)
        print(f"  ✓ {defect_file} ({len(defect_typed)} rows)")

        # Export fact table
        fact_typed = store.read_agg_fact_typed()
        fact_file = out_path / "agg_test_fact_typed.csv"
        fact_typed.to_csv(fact_file, index=False)
        print(f"  ✓ {fact_file} ({len(fact_typed)} rows)")

    print(f"\nExport complete. Files can be opened in Excel or analyzed with tools like:")
    print("  - pandas.read_csv() (Python)")
    print("  - read.csv() (R)")
    print("  - Excel (with automatic type detection)")
