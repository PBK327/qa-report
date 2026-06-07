"""
qa_pipeline.pipeline
====================
Three-stage processing pipeline over Jira CSV exports.

Stage 1 – auto_process : parse AR description blocks + explode subtasks.
Stage 2 – executed_test: merge multi-region executed-test CSVs, compute duration.
Stage 3 – defects      : enrich defect dimension; join fact table.

Public surface
--------------
    from qa_pipeline.pipeline import run_pipeline, PipelineResult
"""

from __future__ import annotations

from .auto_process import run_auto_process
from .executed_test import run_executed_test
from .defects import run_defects, PipelineResult

__all__ = ["run_pipeline", "PipelineResult"]


def run_pipeline(
    report_csv_dir: "pathlib.Path",
    *,
    auto_process_glob: str = "Automation Job *.csv",
    executed_test_glob: str = "* Executed Test *.csv",
    defects_glob: str = "Defects *.csv",
    use_cleaned: bool = False,
) -> PipelineResult:
    """Run all three stages end-to-end and return the combined result."""
    import pathlib
    report_csv_dir = pathlib.Path(report_csv_dir)

    auto_df = run_auto_process(
        report_csv_dir,
        glob_pattern=auto_process_glob,
        use_cleaned=use_cleaned,
    )
    # Stage 2 receives auto_df so the join with executed-test data is chained.
    exec_df = run_executed_test(
        report_csv_dir,
        glob_pattern=executed_test_glob,
        auto_df=auto_df,
        use_cleaned=use_cleaned,
    )
    return run_defects(
        report_csv_dir,
        glob_pattern=defects_glob,
        auto_df=auto_df,
        exec_df=exec_df,
        use_cleaned=use_cleaned,
    )
