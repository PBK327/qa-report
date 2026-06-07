"""
qa_pipeline.pipeline.executed_test
====================================
Stage 2 – Merge multi-region Executed Test CSVs, compute job duration,
then join with Stage 1 output.

Public API
----------
    df = run_executed_test(report_csv_dir, auto_df)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DROP_COLUMNS = {"Issue Type", "Created", "Updated", "Custom field (Job Start Time)", "Custom field (Job End Time)"}
_RENAME_MAP = {
    "Issue key": "Auto Test",
    "Custom field (Auto Test Run Status)": "Auto Test Run Status",
    "Custom field (Executed Test)": "Executed Test",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_executed_test(
    report_csv_dir: Path,
    glob_pattern: str = "* Executed Test *.csv",
    auto_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Stage 2: merge all Executed Test CSVs, compute duration, join with auto_df.

    Parameters
    ----------
    report_csv_dir:
        Directory containing Jira CSV exports.
    glob_pattern:
        Glob to match per-region Executed Test CSV files.
    auto_df:
        Output of Stage 1 (``run_auto_process``).  If None, returns the
        merged executed-test DataFrame without further joining.

    Returns
    -------
    pd.DataFrame
        Merged fact DataFrame with duration computed and optional Stage 1 join.
    """
    matches = sorted(Path(report_csv_dir).glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No Executed Test CSVs found in {report_csv_dir!r} matching '{glob_pattern}'"
        )

    frames = []
    for p in matches:
        try:
            frame = pd.read_csv(p, dtype=str).fillna("")
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            logger.warning("Skipping %s: %s", p.name, exc)

    if not frames:
        raise FileNotFoundError(
            f"All Executed Test CSVs in {report_csv_dir!r} were empty or unreadable"
        )
    df = pd.concat(frames, ignore_index=True)

    logger.info(
        "Stage 2 – executed_test: loaded %d rows from %d file(s)", len(df), len(matches)
    )

    # Compute duration
    for col in ("Custom field (Job Start Time)", "Custom field (Job End Time)"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    start_col = "Custom field (Job Start Time)"
    end_col = "Custom field (Job End Time)"
    if start_col in df.columns and end_col in df.columns:
        df["Executed Test Duration (Minutes)"] = (
            (df[end_col] - df[start_col])
            .dt.total_seconds()
            .floordiv(60)
            .astype("Int64")
        )
    else:
        logger.warning("Stage 2 – Job Start/End Time columns not found; duration skipped")
        df["Executed Test Duration (Minutes)"] = pd.NA

    drop_present = list(_DROP_COLUMNS & set(df.columns))
    df = df.drop(columns=drop_present).rename(columns=_RENAME_MAP).drop_duplicates()

    if auto_df is None:
        logger.info("Stage 2 – executed_test: no auto_df provided, returning merged test rows only")
        return df

    merged = pd.merge(auto_df, df, on="Auto Test", how="left")
    logger.info("Stage 2 – executed_test: output %d rows, %d columns", *merged.shape)
    return merged
