"""
qa_pipeline.pipeline.test_created
=================================
Load and normalize Test Created Jira CSV exports.

Public API
----------
    df = run_test_created(report_csv_dir)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .preprocess import load_deduped_report_csvs, read_cleaned_csv, write_cleaned_csv

logger = logging.getLogger(__name__)


def run_test_created(
    report_csv_dir: Path,
    glob_pattern: str = "Test Created *.csv",
    use_cleaned: bool = False,
) -> pd.DataFrame:
    """Load Test Created CSV snapshots and return a deduplicated DataFrame."""
    if use_cleaned:
        df = read_cleaned_csv(report_csv_dir, "test_created_cleaned.csv")
        matches = [Path(report_csv_dir) / "cleaned" / "test_created_cleaned.csv"]
    else:
        df, matches = load_deduped_report_csvs(
            report_csv_dir,
            glob_pattern,
            key_column="Issue key",
            updated_col="Updated",
            created_col="Created",
        )
        write_cleaned_csv(report_csv_dir, "test_created_cleaned.csv", df)
    logger.info(
        "Stage TC – test_created: loaded %d rows from %d file(s)",
        len(df),
        len(matches),
    )
    return df
