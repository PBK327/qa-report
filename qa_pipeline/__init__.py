"""
qa_pipeline
===========
Production application package for Jira CSV ingestion, pipeline processing,
and dual-store staging (SQLite → Vertica).

Entry points
------------
CLI:
    python -m qa_pipeline.cli --help

Programmatic:
    from qa_pipeline.config import load_pipeline_config
    from qa_pipeline.pipeline import run_pipeline
    from qa_pipeline.store.sqlite import SqliteStore
"""

__all__ = ["config", "pipeline", "store"]
