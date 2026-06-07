"""
qa_pipeline.pipeline.defects
==============================
Stage 3 – Enrich defect records with sprint analytics, then join the
full fact table with defect dimension data.

Returns two DataFrames:
  * ``defect_dim``    – enriched defect dimension (``closebugs_df``)
  * ``agg_test_fact`` – AGG_TEST_WITH_DEFECTS fact table

Public API
----------
    result = run_defects(report_csv_dir, auto_df=auto_df, exec_df=exec_df)
    result.defect_dim      # → qa_defect_dim table
    result.agg_test_fact   # → qa_agg_test_fact table
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column rename map (Jira CSV → warehouse names)
# ---------------------------------------------------------------------------

_DEFECT_RENAME: dict[str, str] = {
    "Issue key": "Bugs",
    "Created": "Bug Created",
    "Updated": "Bug Updated",
    "Resolved": "Bug Resolved",
    "Custom field (Bug Category)": "Bug Category",
    "Custom field (Bug Origin)": "Bug Origin",
    "Custom field (Customer Name (epic))": "Customer Name (epic)",
    "Custom field (Customer/s Name)": "Customer/s Name",
    "Custom field (Detected Version)": "Detected Version",
    "Custom field (Scrum Team)": "Scrum Team",
    "Custom field (Story Points)": "Story Points",
    "Custom field (Verified in)": "Verified in",
}

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Holds both outputs of Stage 3."""
    defect_dim: pd.DataFrame
    """Enriched defect dimension – one row per Jira bug."""
    agg_test_fact: pd.DataFrame
    """Full fact table – test runs enriched with defect data."""


# ---------------------------------------------------------------------------
# Sprint enrichment helpers
# ---------------------------------------------------------------------------

def _enrich_sprint_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add Sprint Number, Sprint Start/End, Sprint Status, Scope Change."""
    out = df.copy()

    out["Sprint Number"] = out["Sprint"].str.extract(r"SPR#(\d+)").astype(str)

    out["Sprint Start"] = pd.to_datetime(
        out["Sprint"].str.extract(r"(\d+/\d+/\d+)-")[0],
        format="%m/%d/%y",
        utc=True,
        errors="coerce",
    )

    last_sprint = out["Sprint"].str.split("|").str[-1]
    out["Sprint End"] = pd.to_datetime(
        last_sprint.str.extract(r"-(\d+/\d+/\d+)")[0],
        format="%m/%d/%y",
        utc=True,
        errors="coerce",
    )

    today = pd.Timestamp.today().normalize().tz_localize("UTC")
    out["Sprint Status"] = np.select(
        [today < out["Sprint Start"], today > out["Sprint End"]],
        ["Upcoming", "Completed"],
        default="Active",
    )

    # Parse timestamps for date arithmetic
    for col in ("Created", "Resolved"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    if "Resolved" in out.columns and "Created" in out.columns:
        out["Resolution Days"] = np.where(
            out["Status"].eq("Closed"),
            (out["Resolved"] - out["Created"]).dt.days,
            np.nan,
        )
    else:
        out["Resolution Days"] = np.nan
        logger.warning("Stage 3 – 'Resolved' column not found; Resolution Days will be NaN")

    out["Scope Change"] = np.select(
        [out["Sprint Start"].isna(), out["Created"] > out["Sprint Start"]],
        ["Unplanned", "Added During Sprint"],
        default="Planned",
    )

    return out


def _compute_per_sprint_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Add Open Bugs and Closed Bugs counts per sprint."""
    open_bugs = (
        df.loc[df["Status"] == "Open"]
        .groupby("Sprint Number")["Issue key"]
        .nunique()
        .reset_index(name="Open Bugs")
    )

    closed_bugs = (
        df.loc[df["Status"] == "Closed"]
        .groupby("Sprint Number")["Issue key"]
        .nunique()
        .reset_index(name="Closed Bugs")
    )

    out = df.merge(open_bugs, on="Sprint Number", how="left")
    out = out.merge(closed_bugs, on="Sprint Number", how="left")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_defects(
    report_csv_dir: Path,
    glob_pattern: str = "Defects *.csv",
    auto_df: pd.DataFrame | None = None,
    exec_df: pd.DataFrame | None = None,
) -> PipelineResult:
    """Stage 3: build defect dimension and full fact table.

    Parameters
    ----------
    report_csv_dir:
        Directory containing Jira CSV exports.
    glob_pattern:
        Glob to match Defects CSV files. Latest file is used if multiple match.
    auto_df:
        Output of Stage 1 (``run_auto_process``).
    exec_df:
        Output of Stage 2 (``run_executed_test``). If provided, uses this as
        the master auto-test base for the fact join. Falls back to ``auto_df``.

    Returns
    -------
    PipelineResult
        Contains ``defect_dim`` and ``agg_test_fact`` DataFrames.
    """
    matches = sorted(Path(report_csv_dir).glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No Defects CSVs found in {report_csv_dir!r} matching '{glob_pattern}'"
        )

    # Use the most recent file if multiple snapshots exist
    defects_path = matches[-1]
    logger.info("Stage 3 – defects: reading %s", defects_path.name)
    defcase = pd.read_csv(defects_path, dtype=str).fillna("")

    # --- Sprint enrichment ---
    defcase = _enrich_sprint_columns(defcase)
    defcase = _compute_per_sprint_counts(defcase)

    # --- Build defect dimension (closebugs_df) ---
    defect_dim = defcase.copy()
    defect_dim["bug_idx"] = "1"
    defect_dim = defect_dim.rename(columns=_DEFECT_RENAME)

    logger.info(
        "Stage 3 – defect_dim: %d rows, %d columns", *defect_dim.shape
    )

    # --- Build fact table (AGG_TEST_WITH_DEFECTS) ---
    # The master test base is exec_df (Stage 2 joined output) or auto_df (Stage 1).
    master_df = exec_df if exec_df is not None else auto_df
    if master_df is None:
        logger.warning(
            "Stage 3 – no master_df supplied; fact table will only contain defect dimension"
        )
        return PipelineResult(defect_dim=defect_dim, agg_test_fact=defect_dim.copy())

    # Normalise bug_idx dtype before merge to avoid Int64 vs str mismatch.
    master_df = master_df.copy()
    defect_dim = defect_dim.copy()
    if "bug_idx" in master_df.columns:
        master_df["bug_idx"] = master_df["bug_idx"].astype(str)
    defect_dim["bug_idx"] = defect_dim["bug_idx"].astype(str)

    master_cols = set(master_df.columns)
    key_cols = ["Bugs", "bug_idx"]
    # Exclude key cols AND any master cols from the extra-column list to avoid duplicates.
    exclude = master_cols | set(key_cols)
    extra_cols = [col for col in defect_dim.columns if col not in exclude]
    dim_fact_cols = key_cols + extra_cols
    # Keep only columns that actually exist in defect_dim, preserving order, no dupes.
    seen: set[str] = set()
    available_dim_cols = []
    for c in dim_fact_cols:
        if c in defect_dim.columns and c not in seen:
            available_dim_cols.append(c)
            seen.add(c)

    agg_test_fact = pd.merge(
        master_df,
        defect_dim[available_dim_cols],
        on=["Bugs", "bug_idx"],
        how="left",
    )

    logger.info(
        "Stage 3 – agg_test_fact: %d rows, %d columns", *agg_test_fact.shape
    )
    return PipelineResult(defect_dim=defect_dim, agg_test_fact=agg_test_fact)
