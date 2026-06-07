"""
aggregator.py
=============
Flexible aggregation engine for the QA dashboard.

Provides a catalogue of time grains, dimensions, and measures, plus
`build_agg_cube()` which groups the unified DataFrame by any combination
of (time period, dimensions) and returns every measure as a column.  The
cube is intentionally "tidy" (one row per group) so any charting library
can consume it directly.

Usage
-----
    from qa_dashboard.aggregator import (
        TIME_GRAINS, DIMENSIONS, MEASURES, build_agg_cube
    )

    cube = build_agg_cube(
        df,
        time_grain="Month",
        groupby_dims=["project_key", "severity_norm"],
        source_types=["defect"],
        date_col="created_at",
    )
    # cube columns: period, project_key, severity_norm,
    #               total, pass_count, fail_count, open_count,
    #               closed_count, critical_count, pass_rate_pct,
    #               avg_fix_cycle_days, avg_defect_age_days
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

# ── Closed/critical vocabulary (must match kpi.py) ──────────────────────────
_CLOSED_STATUSES = {"CLOSED", "FIXED", "DONE", "RESOLVED", "REJECTED"}
_CRITICAL_VALUES = {"CRITICAL", "BLOCKER"}

# ── Time grains ──────────────────────────────────────────────────────────────
# Maps user-facing label → pandas period/resample alias.
TIME_GRAINS: dict[str, str] = {
    "Day": "D",
    "Week": "W-MON",
    "Month": "M",
    "Quarter": "Q",
    "Year": "Y",
}

# ── Dimensions ───────────────────────────────────────────────────────────────
# Maps DataFrame column name → display label shown in the UI.
DIMENSIONS: dict[str, str] = {
    "source_type": "Source Type",
    "project_key": "Project",
    "component_raw": "Component",
    "sprint_id": "Sprint ID",
    "scrum_team_raw": "Team",
    "priority_norm": "Priority",
    "severity_norm": "Severity",
    "bug_category": "Bug Category",
    "bug_origin_raw": "Bug Origin",
    "status_norm": "Status",
    "fix_version_raw": "Fix Version",
    "issue_type": "Issue Type",
}

# ── Measures ─────────────────────────────────────────────────────────────────
# Maps internal measure column name → display label.
MEASURES: dict[str, str] = {
    "total": "Total Issues",
    "pass_count": "Passed",
    "fail_count": "Failed",
    "open_count": "Open",
    "closed_count": "Closed",
    "critical_count": "Critical / Blocker",
    "pass_rate_pct": "Pass Rate (%)",
    "avg_fix_cycle_days": "Avg Fix Cycle (days)",
    "avg_defect_age_days": "Avg Defect Age (days)",
}

# Source type labels for the filter UI
SOURCE_TYPE_LABELS: dict[str, str] = {
    "automation_job": "Automation Job",
    "executed_test": "Executed Test",
    "monthly_executed_snapshot": "Monthly Executed Snapshot",
    "defect": "Defect",
    "test_created": "Test Created",
}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _add_indicator_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add integer indicator columns that can be summed in groupby.agg."""
    out = df.copy()

    def _get_str_col(name: str) -> pd.Series:
        if name in out.columns:
            return out[name].fillna("").astype(str).str.upper().str.strip()
        return pd.Series("", index=out.index)

    status = _get_str_col("status_norm")
    severity = _get_str_col("severity_norm")
    priority = _get_str_col("priority_norm")

    is_open_defect: pd.Series
    if "is_open_defect" in out.columns:
        is_open_defect = out["is_open_defect"].fillna(False).astype(bool)
    else:
        is_open_defect = pd.Series(False, index=out.index)

    out["_is_pass"] = (status == "PASS").astype(int)
    out["_is_fail"] = (status == "FAIL").astype(int)
    out["_is_open"] = ((status == "OPEN") | is_open_defect).astype(int)
    out["_is_closed"] = status.isin(_CLOSED_STATUSES).astype(int)
    out["_is_critical"] = (
        severity.isin(_CRITICAL_VALUES) | priority.isin(_CRITICAL_VALUES)
    ).astype(int)

    return out


def _period_start(series: pd.Series, grain_alias: str) -> pd.Series:
    """Convert a datetime series to period-start timestamps for the given grain."""
    dt = pd.to_datetime(series, errors="coerce", utc=False)
    return dt.dt.to_period(grain_alias).dt.start_time


# ── Public API ────────────────────────────────────────────────────────────────

def build_agg_cube(
    df: pd.DataFrame,
    time_grain: str = "Month",
    groupby_dims: Optional[List[str]] = None,
    source_types: Optional[List[str]] = None,
    date_col: str = "created_at",
) -> pd.DataFrame:
    """Aggregate the unified DataFrame into a tidy KPI cube.

    Parameters
    ----------
    df:
        Normalized unified DataFrame produced by ``load_all_csvs()``.
    time_grain:
        Label from ``TIME_GRAINS`` (e.g. ``"Month"``).
    groupby_dims:
        Additional dimension column names (from ``DIMENSIONS``) to group by.
        The period column is always the first key.
    source_types:
        Restrict rows to these source_type values; ``None`` means all.
    date_col:
        Column to derive the time period from. Typically ``"created_at"``
        or ``"updated_at"``.

    Returns
    -------
    pd.DataFrame
        Columns: ``period``, *groupby_dims*, then all ``MEASURES`` keys.
        Sorted by ``period`` ascending.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    groupby_dims = list(groupby_dims or [])

    # ── Source type filter ────────────────────────────────────────────────────
    if source_types:
        df = df[df["source_type"].isin(source_types)].copy()
    else:
        df = df.copy()

    if df.empty:
        return pd.DataFrame()

    # ── Build period column ───────────────────────────────────────────────────
    grain_alias = TIME_GRAINS.get(time_grain, "ME")
    ts_col = df[date_col] if date_col in df.columns else df.get("created_at", pd.Series(dtype="datetime64[us]"))
    df["period"] = _period_start(ts_col, grain_alias)
    df = df.dropna(subset=["period"])

    if df.empty:
        return pd.DataFrame()

    # ── Add indicator columns ─────────────────────────────────────────────────
    df = _add_indicator_columns(df)

    # ── Normalise dimension columns (fill blanks) ─────────────────────────────
    for dim in groupby_dims:
        if dim in df.columns:
            df[dim] = (
                df[dim]
                .fillna("(blank)")
                .astype(str)
                .str.strip()
                .replace({"": "(blank)"})
            )

    # ── Groupby keys ──────────────────────────────────────────────────────────
    valid_dims = [d for d in groupby_dims if d in df.columns]
    group_keys = ["period"] + valid_dims

    # ── Aggregation spec ──────────────────────────────────────────────────────
    agg_spec: dict = {
        "_is_pass": "sum",
        "_is_fail": "sum",
        "_is_open": "sum",
        "_is_closed": "sum",
        "_is_critical": "sum",
    }
    numeric_extras: list[tuple[str, str]] = []  # (df_col, measure_name)
    if "fix_cycle_days" in df.columns:
        agg_spec["fix_cycle_days"] = "mean"
        numeric_extras.append(("fix_cycle_days", "avg_fix_cycle_days"))
    if "defect_age_days" in df.columns:
        agg_spec["defect_age_days"] = "mean"
        numeric_extras.append(("defect_age_days", "avg_defect_age_days"))

    grouped = df.groupby(group_keys, observed=True)

    counts = grouped.size().reset_index(name="total")
    agg_result = grouped.agg(agg_spec).reset_index()

    cube = counts.merge(agg_result, on=group_keys, how="left")

    # ── Rename indicator → measure names ──────────────────────────────────────
    rename_map: dict[str, str] = {
        "_is_pass": "pass_count",
        "_is_fail": "fail_count",
        "_is_open": "open_count",
        "_is_closed": "closed_count",
        "_is_critical": "critical_count",
    }
    for df_col, measure_name in numeric_extras:
        rename_map[df_col] = measure_name

    cube = cube.rename(columns=rename_map)

    # ── Derived measures ──────────────────────────────────────────────────────
    cube["pass_rate_pct"] = (
        cube["pass_count"] / cube["total"].replace(0, pd.NA) * 100
    ).round(1)

    # Ensure every MEASURES key exists (pad with NA if not computed)
    for measure in MEASURES:
        if measure not in cube.columns:
            cube[measure] = pd.NA

    return cube.sort_values("period").reset_index(drop=True)


def available_source_types(df: pd.DataFrame) -> List[str]:
    """Return sorted list of source_type values present in *df*."""
    if df.empty or "source_type" not in df.columns:
        return []
    return sorted(df["source_type"].dropna().unique().tolist())
