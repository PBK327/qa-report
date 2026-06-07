"""
qa_pipeline.store
=================
Dual-store staging layer: SQLite (local, fast) → Vertica (analytical warehouse).

Tables
------
``agg_test_fact``   – AGG_TEST_WITH_DEFECTS fact table (test runs enriched with defects).
``defect_dim``      – Defect dimension (closebugs_df: sprint-annotated defect records).

Usage
-----
    from qa_pipeline.store.sqlite import SqliteStore
    from qa_pipeline.store.vertica import VerticaStore

    with SqliteStore.open(db_path) as store:
        store.upsert_defect_dim(defect_df)
        store.upsert_agg_fact(fact_df)

    vs = VerticaStore(vertica_cfg)
    vs.push_from_sqlite(store)
"""
