"""
qa_pipeline.pipeline.preprocess
================================
Shared CSV preprocessing helpers for pipeline stages.

Behavior:
* Load all snapshot CSVs matching a glob.
* Remove duplicate keys per report (default key: ``Issue key``).
* Keep the latest record per key using ``Updated`` then ``Created`` timestamps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def write_cleaned_csv(
    report_csv_dir: Path,
    cleaned_filename: str,
    df: pd.DataFrame,
) -> Path:
    """Write a cleaned de-duplicated CSV into Report CSV/cleaned/.

    The file is overwritten each run so downstream stages always read the
    latest cleaned snapshot output.
    """
    cleaned_dir = Path(report_csv_dir) / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    out_path = cleaned_dir / cleaned_filename
    df.to_csv(out_path, index=False)
    logger.info("Preprocess – wrote cleaned CSV: %s (%d rows)", out_path.name, len(df))
    return out_path


def read_cleaned_csv(report_csv_dir: Path, cleaned_filename: str) -> pd.DataFrame:
    """Read a preprocessed cleaned CSV from Report CSV/cleaned/."""
    path = Path(report_csv_dir) / "cleaned" / cleaned_filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Cleaned CSV not found: {path}. Run process once without --use-cleaned first."
        )
    df = pd.read_csv(path, dtype=str).fillna("")
    logger.info("Preprocess – loaded cleaned CSV: %s (%d rows)", path.name, len(df))
    return df


def load_deduped_report_csvs(
    report_csv_dir: Path,
    glob_pattern: str,
    *,
    key_column: str = "Issue key",
    updated_col: str = "Updated",
    created_col: str = "Created",
) -> Tuple[pd.DataFrame, List[Path]]:
    """Load matching CSV snapshots and return de-duplicated rows.

    De-duplication strategy:
    1) Prefer latest ``Updated`` timestamp per key.
    2) If Updated is missing, fall back to ``Created`` timestamp.
    3) If timestamps tie/missing, keep the row from the later snapshot file.
    """
    matches = sorted(Path(report_csv_dir).glob(glob_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No CSVs found in {report_csv_dir!r} matching '{glob_pattern}'"
        )

    frames: List[pd.DataFrame] = []
    for file_idx, path in enumerate(matches):
        try:
            frame = pd.read_csv(path, dtype=str).fillna("")
            if frame.empty:
                continue
            frame["__file_idx"] = file_idx
            frames.append(frame)
        except Exception as exc:
            logger.warning("Skipping %s: %s", path.name, exc)

    if not frames:
        raise FileNotFoundError(
            f"All CSVs in {report_csv_dir!r} matching '{glob_pattern}' were empty or unreadable"
        )

    df = pd.concat(frames, ignore_index=True)

    if key_column in df.columns:
        if updated_col in df.columns:
            df["__updated_ts"] = pd.to_datetime(df[updated_col], utc=True, errors="coerce")
        else:
            df["__updated_ts"] = pd.NaT

        if created_col in df.columns:
            df["__created_ts"] = pd.to_datetime(df[created_col], utc=True, errors="coerce")
        else:
            df["__created_ts"] = pd.NaT

        # Keep latest per key: newest updated/created timestamp and later file index.
        deduped = (
            df.sort_values(
                by=["__updated_ts", "__created_ts", "__file_idx"],
                ascending=[True, True, True],
                kind="mergesort",
            )
            .drop_duplicates(subset=[key_column], keep="last")
            .reset_index(drop=True)
        )
    else:
        deduped = df.drop_duplicates().reset_index(drop=True)

    helper_cols = ["__file_idx", "__updated_ts", "__created_ts"]
    drop_cols = [c for c in helper_cols if c in deduped.columns]
    if drop_cols:
        deduped = deduped.drop(columns=drop_cols)

    return deduped, matches
