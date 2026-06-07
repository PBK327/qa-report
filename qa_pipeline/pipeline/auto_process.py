"""
qa_pipeline.pipeline.auto_process
===================================
Stage 1 – Parse Automation Reporting (AR) blocks from Jira issue descriptions
and explode Sub-Task subtask lists into row-per-test rows.

Public API
----------
    df = run_auto_process(report_csv_dir)   # returns enriched DataFrame
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_START_MARKER = "================ Automation_Reporting ================"
_END_MARKER = "================ End_Automation_Reporting ================"

_AR_BLOCK_RE = re.compile(
    re.escape(_START_MARKER) + r"(.*?)" + re.escape(_END_MARKER),
    flags=re.DOTALL,
)
_AR_FIELD_RE = re.compile(
    r"(AR_[A-Za-z0-9_]+)=(.*?)(?=\s+AR_[A-Za-z0-9_]+=|$)",
    flags=re.DOTALL,
)

_AR_COLUMN_MAP: Dict[str, str] = {
    "AR_Application": "Test Group",
    "AR_Duration": "Test Duration",
    "AR_Executed": "No of Test Scenario",
    "AR_Failed": "Failed Test Scenario",
    "AR_FailedDimensions": "Failed Test Scenario Reason",
    "AR_Feature": "Test Group Feature",
    "AR_JiraID": "Executed Test",
    "AR_PassPercentage": "Test Pass %",
    "AR_Passed": "Pass Test Scenario",
    "AR_Scenario": "Test Scenario",
    "AR_Status": "Auto Test Run Status",
}

_AR_DROP_COLUMNS = {"Executed Test", "Auto Test Run Status"}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _extract_ar_blocks(description: Any) -> List[str]:
    if pd.isna(description):
        return []
    return _AR_BLOCK_RE.findall(str(description))


def _parse_ar_block(block: str) -> Dict[str, str]:
    return {key: value.strip() for key, value in _AR_FIELD_RE.findall(block.strip())}


# ---------------------------------------------------------------------------
# Stage transformations
# ---------------------------------------------------------------------------

def _build_auto_test_df(df: pd.DataFrame) -> pd.DataFrame:
    """Explode Sub-Tasks pipe-delimited column → one row per auto-test."""
    exploded = df.copy()
    exploded["Auto Test"] = exploded["Sub-Tasks"].str.split("|")
    exploded = exploded.explode("Auto Test", ignore_index=True)
    exploded["Block_Number"] = exploded.groupby("Issue key").cumcount().add(1)

    return pd.merge(
        df,
        exploded[["Issue key", "Auto Test", "Block_Number"]],
        on="Issue key",
        how="right",
    )


def _build_ar_description_df(df: pd.DataFrame) -> Tuple[pd.DataFrame, Set[str]]:
    """Parse AR blocks from Description column, one row per block."""
    output_rows: List[Dict[str, Any]] = []
    all_ar_fields: Set[str] = set()

    for _, row in df.iterrows():
        blocks = _extract_ar_blocks(row.get("Description"))
        for block_num, block in enumerate(blocks, start=1):
            ar_data = _parse_ar_block(block)
            output_row = row.to_dict()
            output_row["Block_Number"] = block_num
            output_row.update(ar_data)
            output_rows.append(output_row)
            all_ar_fields.update(ar_data.keys())

    if not output_rows:
        return pd.DataFrame(), all_ar_fields

    result = pd.DataFrame(output_rows)
    cols = ["Issue key", "Block_Number"] + sorted(all_ar_fields)
    available = [c for c in cols if c in result.columns]
    return result[available], all_ar_fields


def _build_bugs_df(df: pd.DataFrame) -> pd.DataFrame:
    """Explode Blockers column → one row per Bug link, keyed by Issue key + Block_Number."""
    exploded = df.copy()
    exploded["Bugs"] = exploded["Custom field (Blockers)"].str.split("|")
    exploded = exploded.explode("Bugs", ignore_index=True)
    exploded["Block_Number"] = exploded.groupby("Issue key").cumcount().add(1)
    return exploded[["Issue key", "Block_Number", "Bugs"]]


def _forward_fill_by_issue(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill metadata columns within each Issue key group."""
    out = df.replace("", np.nan)
    fill_cols = out.columns.difference(["Issue key", "Auto Test", "Bugs"])
    out[fill_cols] = out.groupby("Issue key")[fill_cols].ffill()
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_auto_process(report_csv_dir: Path, glob_pattern: str = "Automation Job *.csv") -> pd.DataFrame:
    """Stage 1: load, parse, and explode automation job CSV data.

    Parameters
    ----------
    report_csv_dir:
        Directory containing Jira CSV exports.
    glob_pattern:
        Glob to match Automation Job CSV files.

    Returns
    -------
    pd.DataFrame
        Enriched DataFrame ready to merge with Stage 2 output.
    """
    matches = sorted(Path(report_csv_dir).glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No Automation Job CSVs found in {report_csv_dir!r} matching '{glob_pattern}'"
        )

    # Concatenate all matching files (allows multiple job CSVs)
    frames = []
    for path in matches:
        frames.append(pd.read_csv(path, dtype=str).fillna(""))
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Issue key"])

    logger.info("Stage 1 – auto_process: loaded %d rows from %d file(s)", len(df), len(matches))

    auto_test_df = _build_auto_test_df(df)
    ar_df, ar_fields = _build_ar_description_df(df)

    if ar_df.empty:
        logger.warning("Stage 1 – no AR blocks found in Description column")
        return auto_test_df

    ar_df = ar_df.rename(columns=_AR_COLUMN_MAP)
    drop_present = list(_AR_DROP_COLUMNS & set(ar_df.columns))
    ar_df = ar_df.drop(columns=drop_present)

    merged = pd.merge(
        auto_test_df,
        ar_df,
        on=["Issue key", "Block_Number"],
        how="outer",
    )

    bugs_df = _build_bugs_df(df)
    final = pd.merge(
        merged,
        bugs_df,
        on=["Issue key", "Block_Number"],
        how="outer",
    )
    final = _forward_fill_by_issue(final)

    # Stable bug index per bug key
    final["bug_idx"] = (
        final.groupby("Bugs").cumcount().add(1).astype("Int64")
    )

    logger.info("Stage 1 – auto_process: output %d rows, %d columns", *final.shape)
    return final
