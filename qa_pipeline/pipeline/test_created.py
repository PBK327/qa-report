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

logger = logging.getLogger(__name__)


def run_test_created(
    report_csv_dir: Path,
    glob_pattern: str = "Test Created *.csv",
) -> pd.DataFrame:
    """Load Test Created CSV snapshots and return a deduplicated DataFrame."""
    matches = sorted(Path(report_csv_dir).glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No Test Created CSVs found in {report_csv_dir!r} matching '{glob_pattern}'"
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
            f"All Test Created CSVs in {report_csv_dir!r} were empty or unreadable"
        )

    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    logger.info(
        "Stage TC – test_created: loaded %d rows from %d file(s)",
        len(df),
        len(matches),
    )
    return df
