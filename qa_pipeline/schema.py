"""
qa_pipeline.schema
====================
Schema definitions for agg_test_fact, defect_dim, and test_created tables.

Defines proper data types for each column to enable correct sorting, filtering,
and aggregation in downstream consumers (Vertica, analytics tools, etc.).

Design
------
SQLite stores all columns as TEXT by default. This module provides:

1. ``AGG_TEST_FACT_SCHEMA`` – Column type mappings for fact table
2. ``DEFECT_DIM_SCHEMA`` – Column type mappings for defect dimension table
3. ``TEST_CREATED_SCHEMA`` – Column type mappings for test-created table
4. ``convert_df_to_schema()`` – Function to apply schema to DataFrame
5. ``get_sql_create_from_schema()`` – Generate SQL CREATE TABLE statements

When reading from SQLite, call ``convert_df_to_schema(df, SCHEMA_NAME)`` to
restore proper types before downstream processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Type converters
# ---------------------------------------------------------------------------

def _to_datetime(val: Any) -> Optional[datetime]:
    """Convert to datetime, returning None for empty strings or NaT."""
    if pd.isna(val) or val == "":
        return None
    try:
        return pd.to_datetime(val, utc=True)
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    """Convert to int, returning None for empty strings or NaN."""
    if pd.isna(val) or val == "":
        return None
    try:
        return int(float(val))  # float first to handle "123.0"
    except (ValueError, TypeError):
        return None


def _to_float(val: Any) -> Optional[float]:
    """Convert to float, returning None for empty strings or NaN."""
    if pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_bool(val: Any) -> Optional[bool]:
    """Convert to bool. True for: Yes, True, 1, Done; False otherwise."""
    if pd.isna(val) or val == "":
        return None
    str_val = str(val).strip().lower()
    return str_val in {"yes", "true", "1", "done"}


def _to_str(val: Any) -> str:
    """Convert to string, preserving empty strings."""
    if pd.isna(val):
        return ""
    return str(val)


# ---------------------------------------------------------------------------
# Schema definition dataclass
# ---------------------------------------------------------------------------

@dataclass
class ColumnSchema:
    """Defines a column's name and conversion function."""
    name: str
    converter: Callable[[Any], Any]
    description: str = ""


# ---------------------------------------------------------------------------
# Aggregation Fact Table Schema
# ---------------------------------------------------------------------------

AGG_TEST_FACT_SCHEMA = [
    ColumnSchema("Issue key", _to_str, "Automation Job issue key"),
    ColumnSchema("Sub-Tasks", _to_str, "Pipe-delimited auto test keys"),
    ColumnSchema("Auto Test", _to_str, "Individual auto test key"),
    ColumnSchema("Block_Number", _to_int, "AR block number (1-indexed)"),
    ColumnSchema("Created", _to_datetime, "Automation Job created timestamp (UTC)"),
    ColumnSchema("Updated", _to_datetime, "Automation Job updated timestamp (UTC)"),
    ColumnSchema("Sprint", _to_str, "Sprint identifier (e.g., SPR#123)"),
    ColumnSchema("Custom field (Automation Test Run Approved)", _to_bool, "Whether run was approved"),
    ColumnSchema("Custom field (Job Name)", _to_str, "Job name (e.g., BI-Sanity)"),
    ColumnSchema("Custom field (Job Run By User)", _to_str, "User who triggered job"),
    ColumnSchema("Custom field (Job Stack Prefix)", _to_str, "Software version prefix"),
    ColumnSchema("Custom field (Job Stack Version)", _to_str, "Stack name"),
    
    # Executed Test columns
    ColumnSchema("Custom field (Auto Test Run Status)", _to_str, "Test run status (Pass/Fail)"),
    ColumnSchema("Custom field (Job Start Time)", _to_datetime, "Test execution start time (UTC)"),
    ColumnSchema("Custom field (Job End Time)", _to_datetime, "Test execution end time (UTC)"),
    ColumnSchema("Job Duration (minutes)", _to_float, "Duration in minutes"),
    ColumnSchema("Executed Test Duration (Minutes)", _to_float, "Duration of executed test in minutes"),
    
    # AR parsed columns
    ColumnSchema("Test Group", _to_str, "Application/feature group being tested"),
    ColumnSchema("Test Duration", _to_float, "Test duration in seconds or minutes"),
    ColumnSchema("No of Test Scenario", _to_int, "Total test scenarios executed"),
    ColumnSchema("Failed Test Scenario", _to_int, "Number of failed scenarios"),
    ColumnSchema("Failed Test Scenario Reason", _to_str, "Reason for failures"),
    ColumnSchema("Test Group Feature", _to_str, "Specific feature being tested"),
    ColumnSchema("Executed Test", _to_str, "Test case issue key"),
    ColumnSchema("Test Pass %", _to_float, "Pass percentage (0-100)"),
    ColumnSchema("Pass Test Scenario", _to_int, "Number of passed scenarios"),
    ColumnSchema("Test Scenario", _to_str, "Test scenario description"),
    
    # Defect join columns
    ColumnSchema("Bugs", _to_str, "Defect issue key"),
    ColumnSchema("bug_idx", _to_int, "Bug index (1-indexed)"),
    ColumnSchema("Status", _to_str, "Defect status (Open, Closed, etc.)"),
    ColumnSchema("Priority", _to_str, "Defect priority (Critical, Major, etc.)"),
    ColumnSchema("Assignee", _to_str, "Developer assigned to fix"),
    ColumnSchema("Bug Category", _to_str, "Bug category (UI, Backend, etc.)"),
    ColumnSchema("Bug Origin", _to_str, "Who reported the bug"),
    ColumnSchema("Sprint Number", _to_int, "Sprint number (e.g., 123)"),
    ColumnSchema("Sprint Start", _to_datetime, "Sprint start date (UTC)"),
    ColumnSchema("Sprint End", _to_datetime, "Sprint end date (UTC)"),
    ColumnSchema("Sprint Status", _to_str, "Sprint status (Upcoming, Active, Completed)"),
    ColumnSchema("Resolution Days", _to_float, "Days to resolve (for closed bugs)"),
    ColumnSchema("Scope Change", _to_str, "Whether bug was in scope (Planned, Added During Sprint, Unplanned)"),
    ColumnSchema("Open Bugs", _to_int, "Open bug count in sprint"),
    ColumnSchema("Closed Bugs", _to_int, "Closed bug count in sprint"),
    ColumnSchema("Story Points", _to_float, "Effort estimation"),
]


# ---------------------------------------------------------------------------
# Defect Dimension Table Schema
# ---------------------------------------------------------------------------

DEFECT_DIM_SCHEMA = [
    ColumnSchema("Bugs", _to_str, "Defect issue key"),
    ColumnSchema("bug_idx", _to_int, "Bug index (1-indexed)"),
    ColumnSchema("Issue Type", _to_str, "Always 'Bug'"),
    ColumnSchema("Status", _to_str, "Defect status (Open, Closed, In Progress, etc.)"),
    ColumnSchema("Priority", _to_str, "Defect priority (Critical, Blocker, Major, Minor)"),
    ColumnSchema("Assignee", _to_str, "Developer assigned to fix"),
    ColumnSchema("Creator", _to_str, "User who created the defect"),
    ColumnSchema("Bug Created", _to_datetime, "Defect created timestamp (UTC)"),
    ColumnSchema("Bug Updated", _to_datetime, "Defect updated timestamp (UTC)"),
    ColumnSchema("Bug Resolved", _to_datetime, "Defect resolved timestamp (UTC)"),
    ColumnSchema("Fix Version/s", _to_str, "Planned fix version"),
    ColumnSchema("Component/s", _to_str, "Affected component(s)"),
    ColumnSchema("Labels", _to_str, "Tags for organization"),
    ColumnSchema("Bug Category", _to_str, "Bug category (UI, Backend, Data, etc.)"),
    ColumnSchema("Bug Origin", _to_str, "Origin of bug report"),
    ColumnSchema("Clones", _to_str, "Clone issue key(s)"),
    ColumnSchema("Customer Name (epic)", _to_str, "Customer name"),
    ColumnSchema("Customer/s Name", _to_str, "Additional customer names"),
    ColumnSchema("Detected Version", _to_str, "Version in which bug was detected"),
    ColumnSchema("Scrum Team", _to_str, "Team responsible for fix"),
    ColumnSchema("Sprint", _to_str, "Sprint identifier (blank = unscheduled)"),
    ColumnSchema("Sprint Number", _to_int, "Sprint number (e.g., 123)"),
    ColumnSchema("Sprint Start", _to_datetime, "Sprint start date (UTC)"),
    ColumnSchema("Sprint End", _to_datetime, "Sprint end date (UTC)"),
    ColumnSchema("Sprint Status", _to_str, "Sprint status (Upcoming, Active, Completed)"),
    ColumnSchema("Story Points", _to_float, "Effort estimation"),
    ColumnSchema("Verified in", _to_str, "Version in which fix was verified"),
    ColumnSchema("Resolution Days", _to_float, "Days to resolve (for closed bugs)"),
    ColumnSchema("Scope Change", _to_str, "Whether defect was in scope (Planned, Added During Sprint, Unplanned)"),
    ColumnSchema("Open Bugs", _to_int, "Open bug count in sprint"),
    ColumnSchema("Closed Bugs", _to_int, "Closed bug count in sprint"),
]


# ---------------------------------------------------------------------------
# Test Created Table Schema
# ---------------------------------------------------------------------------

TEST_CREATED_SCHEMA = [
    ColumnSchema("Issue Type", _to_str, "Issue type, expected 'Test'"),
    ColumnSchema("Issue key", _to_str, "Test issue key"),
    ColumnSchema("Project key", _to_str, "Project key"),
    ColumnSchema("Creator", _to_str, "User who created the test"),
    ColumnSchema("Created", _to_datetime, "Test creation timestamp (UTC)"),
    ColumnSchema("Updated", _to_datetime, "Test last update timestamp (UTC)"),
    ColumnSchema("Custom field (Epic Link)", _to_str, "Linked epic"),
    ColumnSchema("Custom field (TestRunStatus)", _to_str, "Current test run status"),
    ColumnSchema("Inward issue link (Related Bugs)", _to_str, "Inbound related bug links"),
    ColumnSchema("Outward issue link (Defect)", _to_str, "Outbound defect links"),
    ColumnSchema("Custom field (Automated)", _to_str, "Automation coverage marker"),
    ColumnSchema("Custom field (Customer Name (epic))", _to_str, "Customer name from epic"),
    ColumnSchema("Custom field (Test Sets association with a Test)", _to_str, "Associated test sets"),
    ColumnSchema("Related Bugs", _to_str, "Related bug issue keys"),
    ColumnSchema("Custom field (Related Stories/Tasks)", _to_str, "Related stories/tasks"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_df_to_schema(
    df: pd.DataFrame,
    schema: List[ColumnSchema],
    strict: bool = False,
) -> pd.DataFrame:
    """Apply schema type conversions to DataFrame.
    
    Parameters
    ----------
    df:
        Input DataFrame (typically read from SQLite, where all columns are TEXT).
    schema:
        List of ColumnSchema definitions.
    strict:
        If True, drop columns not in schema. If False, preserve unknown columns as strings.
    
    Returns
    -------
    pd.DataFrame
        New DataFrame with columns converted to proper types.
    
    Example
    -------
    >>> df_from_sqlite = pd.read_sql("SELECT * FROM agg_test_fact", conn)
    >>> df_typed = convert_df_to_schema(df_from_sqlite, AGG_TEST_FACT_SCHEMA)
    >>> df_typed['Created'].dtype  # Now datetime64[ns, UTC]
    >>> df_typed['Story Points'].dtype  # Now float64
    """
    result = df.copy()
    
    # Apply conversions for columns in schema
    for col_schema in schema:
        col_name = col_schema.name
        if col_name in result.columns:
            result[col_name] = result[col_name].apply(col_schema.converter)
    
    # Optionally drop columns not in schema
    if strict:
        schema_cols = {cs.name for cs in schema}
        extra_cols = set(result.columns) - schema_cols
        if extra_cols:
            result = result.drop(columns=extra_cols)
    
    return result


def get_schema_dict(schema: List[ColumnSchema]) -> Dict[str, Callable]:
    """Convert schema list to dict mapping column name → converter."""
    return {cs.name: cs.converter for cs in schema}


def get_sql_create_from_schema(
    table_name: str,
    schema: List[ColumnSchema],
    pk_cols: List[str],
) -> str:
    """Generate SQL CREATE TABLE statement from schema.
    
    Parameters
    ----------
    table_name:
        Name of table to create.
    schema:
        List of ColumnSchema definitions.
    pk_cols:
        List of column names to use as primary key.
    
    Returns
    -------
    str
        SQL CREATE TABLE IF NOT EXISTS statement.
    
    Example
    -------
    >>> sql = get_sql_create_from_schema("agg_test_fact", AGG_TEST_FACT_SCHEMA, ["Issue key", "bug_idx"])
    """
    # Map converter functions to SQL types
    sql_type_map = {
        _to_str: "TEXT",
        _to_datetime: "TIMESTAMP WITH TIME ZONE",
        _to_int: "INTEGER",
        _to_float: "REAL",
        _to_bool: "BOOLEAN",
    }
    
    col_defs = []
    for col_schema in schema:
        sql_type = sql_type_map.get(col_schema.converter, "TEXT")
        col_defs.append(f'  "{col_schema.name}" {sql_type}')
    
    pk_expr = ", ".join(f'"{c}"' for c in pk_cols)
    
    return (
        f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n'
        f'{", ".join(col_defs)},\n'
        f'  PRIMARY KEY ({pk_expr})\n'
        f');'
    )


def describe_schema(schema: List[ColumnSchema]) -> str:
    """Return human-readable schema description."""
    lines = []
    for cs in schema:
        type_name = cs.converter.__name__.replace("_to_", "").upper()
        desc = f" – {cs.description}" if cs.description else ""
        lines.append(f"  {cs.name:<45} {type_name:<15} {desc}")
    return "\n".join(lines)
