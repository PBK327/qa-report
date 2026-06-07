from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd


CLOSED_STATUSES = {"CLOSED", "FIXED", "DONE", "RESOLVED", "REJECTED"}
CRITICAL_VALUES = {"CRITICAL", "BLOCKER"}
LINK_PATHS = {
    "automation_job_to_executed_test": {
        "source_types": ["automation_job"],
        "key_col": "sub_task_keys",
        "target_types": ["executed_test", "monthly_executed_snapshot"],
    },
    "executed_test_to_test_created": {
        "source_types": ["executed_test", "monthly_executed_snapshot"],
        "key_col": "executed_test_ref_keys",
        "target_types": ["test_created"],
    },
    "test_created_to_defects": {
        "source_types": ["test_created"],
        "key_col": "all_defect_ref_keys",
        "target_types": ["defect"],
    },
    "automation_job_blockers_to_defects": {
        "source_types": ["automation_job"],
        "key_col": "blocker_bug_keys",
        "target_types": ["defect"],
    },
}


@dataclass
class DashboardKpis:
    total_tests_executed: int
    pass_rate: float
    open_defects: int
    critical_defects: int
    open_risk_load: int
    test_execution_rate_daily: float
    release_readiness_signal: str


def _coverage_ratio(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    series = df[column]
    if series.dtype == "object":
        non_empty = series.fillna("").astype(str).str.strip().ne("")
    else:
        non_empty = series.notna()
    return float(non_empty.mean()) if len(series) else 0.0


def _confidence_from_ratio(ratio: float) -> str:
    if ratio >= 0.85:
        return "HIGH"
    if ratio >= 0.6:
        return "MEDIUM"
    return "LOW"


def _build_link_bridges(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    bridges: Dict[str, pd.DataFrame] = {}
    if df.empty:
        for path_name in LINK_PATHS:
            bridges[path_name] = pd.DataFrame(
                columns=["path", "source_issue_key", "target_issue_key", "matched", "source_file"]
            )
        return bridges

    prepared = df.copy()
    if "all_defect_ref_keys" not in prepared.columns:
        prepared["all_defect_ref_keys"] = prepared.apply(
            lambda row: (row.get("related_bug_keys") or []) + (row.get("defect_link_keys") or []),
            axis=1,
        )

    for path_name, path in LINK_PATHS.items():
        source = prepared[prepared["source_type"].isin(path["source_types"])].copy()
        target = prepared[prepared["source_type"].isin(path["target_types"])].copy()
        target_keys = set(target["issue_key"].dropna().astype(str))

        rows: List[dict] = []
        key_col = path["key_col"]
        for _, row in source.iterrows():
            source_key = str(row.get("issue_key", ""))
            source_file = str(row.get("source_file", ""))
            links = row.get(key_col)
            link_keys = links if isinstance(links, list) else []
            for target_key in link_keys:
                rows.append(
                    {
                        "path": path_name,
                        "source_issue_key": source_key,
                        "target_issue_key": target_key,
                        "matched": bool(target_key in target_keys),
                        "source_file": source_file,
                    }
                )

        bridges[path_name] = pd.DataFrame(rows)
        if bridges[path_name].empty:
            bridges[path_name] = pd.DataFrame(
                columns=["path", "source_issue_key", "target_issue_key", "matched", "source_file"]
            )

    return bridges


def build_bridge_table_view(df: pd.DataFrame, path_name: str) -> pd.DataFrame:
    bridges = _build_link_bridges(df)
    table = bridges.get(path_name)
    if table is None:
        return pd.DataFrame(
            columns=["path", "source_issue_key", "target_issue_key", "matched", "source_file"]
        )
    return table.sort_values(["matched", "source_issue_key"], ascending=[True, True])


def build_unmatched_key_drilldown(df: pd.DataFrame, path_name: str, limit: int = 200) -> pd.DataFrame:
    bridge = build_bridge_table_view(df, path_name)
    if bridge.empty:
        return pd.DataFrame(columns=["target_issue_key", "attempts", "sample_source_issue_keys"])

    unmatched = bridge[~bridge["matched"]].copy()
    if unmatched.empty:
        return pd.DataFrame(columns=["target_issue_key", "attempts", "sample_source_issue_keys"])

    grouped = (
        unmatched.groupby("target_issue_key", as_index=False)
        .agg(
            attempts=("source_issue_key", "count"),
            sample_source_issue_keys=(
                "source_issue_key",
                lambda s: ", ".join(list(dict.fromkeys(s.astype(str).tolist()))[:5]),
            ),
        )
        .sort_values("attempts", ascending=False)
    )
    return grouped.head(limit)


def build_kpi_confidence_table(df: pd.DataFrame) -> pd.DataFrame:
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])]
    defects = df[df["source_type"] == "defect"]
    bridges = _build_link_bridges(df)

    pass_rate_cov = _coverage_ratio(tests, "run_status_norm")
    open_defect_cov = _coverage_ratio(defects, "status_norm")
    severity_cov = _coverage_ratio(defects, "severity")
    priority_cov = _coverage_ratio(defects, "priority")
    critical_cov = max(severity_cov, priority_cov)
    project_cov = _coverage_ratio(tests, "project_key")
    sprint_cov = _coverage_ratio(defects, "sprint_id")
    component_cov = _coverage_ratio(defects, "component_raw")

    def _match_cov(path: str) -> float:
        table = bridges.get(path)
        if table is None or table.empty:
            return 0.0
        return float(table["matched"].mean())

    leakage_cov = _match_cov("test_created_to_defects")

    metrics = [
        ("Pass Rate", pass_rate_cov, "run_status_norm coverage"),
        ("Open Defects", open_defect_cov, "status_norm coverage"),
        ("Critical Defects", critical_cov, "severity/priority coverage"),
        ("Pass Rate by Project", project_cov, "project_key coverage"),
        ("Planning by Sprint", sprint_cov, "sprint_id coverage"),
        ("Planning by Component", component_cov, "component coverage"),
        (
            "Regression Leakage Proxy",
            leakage_cov,
            "test_created_to_defects link match rate",
        ),
    ]

    rows = []
    for metric, ratio, rule in metrics:
        rows.append(
            {
                "kpi": metric,
                "coverage_pct": round(ratio * 100.0, 1),
                "confidence": _confidence_from_ratio(ratio),
                "rule": rule,
            }
        )

    return pd.DataFrame(rows)


def build_automation_coverage(df: pd.DataFrame) -> float:
    tests = df[df["source_type"] == "test_created"].copy()
    if tests.empty:
        return 0.0
    automated = (tests["automation_approved_raw"].astype(str).str.upper().eq("YES")).sum()
    total = len(tests)
    return round((100.0 * automated / total), 1) if total else 0.0


def build_defect_leakage(df: pd.DataFrame) -> float:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return 0.0
    # Use "Verified in" as proxy for production/verified defects
    verified = defects["verified_in_raw"].astype(str).str.strip().ne("").sum()
    total = len(defects)
    return round((100.0 * verified / total), 1) if total else 0.0


def build_reopened_defect_rate(df: pd.DataFrame) -> float:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return 0.0
    closed_mask = defects["status_norm"].isin(CLOSED_STATUSES)
    closed = closed_mask.sum()
    if closed == 0:
        return 0.0
    # Proxy for reopened: defects updated > 5 days after creation
    reopened_proxy = ((defects["fix_cycle_days"] > 5) & closed_mask).sum()
    return round((100.0 * reopened_proxy / closed), 1)


def build_automation_stability(df: pd.DataFrame) -> float:
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])].copy()
    if tests.empty:
        return 0.0
    # Automation stability = pass rate of automated tests
    pass_count = (tests["run_status_norm"] == "PASS").sum()
    total = len(tests)
    return round((100.0 * pass_count / total), 1) if total else 0.0


def build_sprint_completion(df: pd.DataFrame) -> float:
    tests = df[df["source_type"] == "test_created"].copy()
    if tests.empty:
        return 0.0
    # Sprint completion proxy: tests with sprint assigned and status = done
    with_sprint = (tests["sprint_id"].astype(str).str.strip().ne("")).sum()
    if with_sprint == 0:
        return 0.0
    completed = (
        (tests["sprint_id"].astype(str).str.strip().ne("")) & (tests["status_norm"].eq("CLOSED"))
    ).sum()
    return round((100.0 * completed / with_sprint), 1)


def build_defect_density_by_story_points(df: pd.DataFrame) -> float:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return 0.0
    total_defects = len(defects)
    story_points = pd.to_numeric(defects["story_points_raw"], errors="coerce").sum()
    if story_points <= 0:
        return 0.0
    return round(total_defects / story_points, 2)


def build_flaky_test_rate(df: pd.DataFrame) -> float:
    # Flaky tests: tests that appear multiple times with mixed pass/fail outcomes in same week
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])].copy()
    if tests.empty:
        return 0.0

    # Group by week and test key; count pass/fail per test per week
    tests["week_start"] = tests["created_at"].dt.to_period("W-MON").dt.start_time
    grouped = (
        tests.groupby(["week_start", "issue_key"])
        .agg(
            pass_count=("run_status_norm", lambda s: (s == "PASS").sum()),
            fail_count=("run_status_norm", lambda s: (s == "FAIL").sum()),
        )
        .reset_index()
    )

    # Flaky = both pass and fail counts > 0 in same week
    flaky = ((grouped["pass_count"] > 0) & (grouped["fail_count"] > 0)).sum()
    unique_test_weeks = len(grouped)
    return round((100.0 * flaky / unique_test_weeks), 1) if unique_test_weeks else 0.0


def build_failed_test_count(df: pd.DataFrame) -> int:
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])].copy()
    return int((tests["run_status_norm"] == "FAIL").sum())


def build_mttr_proxy(df: pd.DataFrame) -> float:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return 0.0
    closed = defects[defects["status_norm"].isin(CLOSED_STATUSES)].copy()
    if closed.empty:
        return 0.0
    # MTTR proxy: average fix_cycle_days for closed defects
    avg_days = closed["fix_cycle_days"].dropna().mean()
    return round(avg_days * 24.0, 1) if pd.notna(avg_days) else 0.0  # Convert to hours


def build_automation_success_rate(df: pd.DataFrame) -> float:
    jobs = df[df["source_type"] == "automation_job"].copy()
    if jobs.empty:
        return 0.0
    approved = (jobs["automation_approved_raw"].astype(str).str.upper().eq("YES")).sum()
    total = len(jobs)
    return round((100.0 * approved / total), 1) if total else 0.0


def build_bug_trend_by_severity(df: pd.DataFrame) -> pd.DataFrame:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return pd.DataFrame(columns=["week_start", "critical", "high", "medium", "low"])

    defects["week_start"] = defects["created_at"].dt.to_period("W-MON").dt.start_time
    defects["severity_bucket"] = defects["severity_norm"].map(
        lambda s: "critical"
        if s in CRITICAL_VALUES
        else "high" if s in {"HIGH"} else "medium" if s in {"MEDIUM"} else "low"
    )

    grouped = defects.groupby(["week_start", "severity_bucket"]).size().unstack(fill_value=0)
    grouped = grouped.reset_index()
    grouped = grouped.sort_values("week_start")
    return grouped


def build_release_readiness_score(df: pd.DataFrame) -> Dict[str, float]:
    kpis = compute_kpis(df)
    automation_stab = build_automation_stability(df)

    # Weights: Critical Bugs 30%, Pass Rate 20%, Automation Stability 15%, Security 20%, Performance 15%

    # Critical bugs score (0-100): inverse of critical count ratio
    defects = df[df["source_type"] == "defect"]
    total_defects = len(defects) if not defects.empty else 1
    critical_ratio = (kpis.critical_defects / total_defects) * 100 if total_defects else 0.0
    critical_score = max(0.0, 100.0 - critical_ratio)  # Higher is better

    # Pass rate score (already 0-100)
    pass_score = kpis.pass_rate

    # Automation stability score (already 0-100)
    automation_score = automation_stab

    # Security proxy: use defect density (lower is better)
    security_score = max(0.0, 100.0 - build_defect_density_by_story_points(df) * 10.0)
    security_score = min(100.0, security_score)

    # Performance proxy: inverse of failed tests ratio
    failed = build_failed_test_count(df)
    total_tests = len(df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])])
    perf_score = max(0.0, 100.0 - (100.0 * failed / total_tests)) if total_tests else 100.0

    # Compute weighted score
    overall_score = (
        critical_score * 0.30
        + pass_score * 0.20
        + automation_score * 0.15
        + security_score * 0.20
        + perf_score * 0.15
    )

    return {
        "overall_score": round(overall_score, 1),
        "critical_score": round(critical_score, 1),
        "pass_score": round(pass_score, 1),
        "automation_score": round(automation_score, 1),
        "security_score": round(security_score, 1),
        "performance_score": round(perf_score, 1),
    }


def build_release_recommendation(df: pd.DataFrame) -> Dict[str, Any]:
    kpis = compute_kpis(df)
    scores = build_release_readiness_score(df)
    automation_cov = build_automation_coverage(df)

    overall = scores["overall_score"]
    reasons: List[str] = []
    blockers: List[str] = []

    # Check blockers
    if kpis.critical_defects > 0:
        blockers.append(f"{kpis.critical_defects} Critical Defects Open")
    if kpis.pass_rate < 95.0:
        blockers.append(f"Pass Rate {kpis.pass_rate}% (< 95% threshold)")
    if automation_cov < 40.0:
        blockers.append(f"Automation Coverage {automation_cov}% (< 40% threshold)")

    # Build reasons
    if kpis.critical_defects == 0:
        reasons.append("✓ 0 Critical Defects")
    if kpis.pass_rate >= 95.0:
        reasons.append(f"✓ Pass Rate = {kpis.pass_rate}%")
    if automation_cov >= 70.0:
        reasons.append(f"✓ Automation Coverage = {automation_cov}%")
    if kpis.open_defects < 100:
        reasons.append(f"✓ Open Defects = {kpis.open_defects}")

    if overall > 85 and len(blockers) == 0:
        status = "GO"
    elif overall >= 70 and len(blockers) <= 1:
        status = "CONDITIONAL GO"
    else:
        status = "NO GO"

    return {
        "status": status,
        "score": overall,
        "reasons": reasons,
        "blockers": blockers,
    }


def compute_kpis(df: pd.DataFrame) -> DashboardKpis:
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])]

    pass_count = int((tests["run_status_norm"] == "PASS").sum())
    fail_count = int((tests["run_status_norm"] == "FAIL").sum())
    pass_rate = (100.0 * pass_count / (pass_count + fail_count)) if (pass_count + fail_count) else 0.0

    defects = df[df["source_type"] == "defect"].copy()
    defects["is_open"] = ~defects["status_norm"].isin(CLOSED_STATUSES)

    critical_mask = defects["severity"].str.upper().isin(CRITICAL_VALUES) | defects[
        "priority"
    ].str.upper().isin(CRITICAL_VALUES)

    if tests["created_at"].notna().any():
        day_span = max((tests["created_at"].max() - tests["created_at"].min()).days + 1, 1)
        execution_rate_daily = float(len(tests) / day_span)
    else:
        execution_rate_daily = 0.0

    trend = build_weekly_trend(df)
    if len(trend) >= 2:
        prev = trend.iloc[-2]
        curr = trend.iloc[-1]
        pass_dir = curr["pass_rate"] - prev["pass_rate"]

        open_critical_weekly = (
            defects[defects["created_at"].notna()]
            .assign(week_start=lambda d: d["created_at"].dt.to_period("W-MON").dt.start_time)
            .assign(is_critical=critical_mask)
            .groupby("week_start", as_index=False)
            .agg(open_critical=("is_critical", "sum"))
            .sort_values("week_start")
        )
        risk_dir = 0.0
        if len(open_critical_weekly) >= 2:
            risk_dir = (
                open_critical_weekly.iloc[-1]["open_critical"]
                - open_critical_weekly.iloc[-2]["open_critical"]
            )

        if pass_dir >= 0 and risk_dir <= 0:
            release_signal = "ON_TRACK"
        elif pass_dir < 0 and risk_dir > 0:
            release_signal = "AT_RISK"
        else:
            release_signal = "WATCH"
    else:
        release_signal = "INSUFFICIENT_TREND"

    return DashboardKpis(
        total_tests_executed=int(len(tests)),
        pass_rate=round(pass_rate, 1),
        open_defects=int(defects["is_open"].sum()),
        critical_defects=int((defects["is_open"] & critical_mask).sum()),
        open_risk_load=int((defects["is_open"] & critical_mask).sum()),
        test_execution_rate_daily=round(execution_rate_daily, 2),
        release_readiness_signal=release_signal,
    )


def build_weekly_trend(df: pd.DataFrame) -> pd.DataFrame:
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])].copy()
    tests = tests[tests["week_start"].notna()]

    if tests.empty:
        return pd.DataFrame(columns=["week_start", "executed", "pass", "fail", "pass_rate"])

    grouped = (
        tests.groupby("week_start", as_index=False)
        .agg(
            executed=("issue_key", "count"),
            pass_count=("run_status_norm", lambda s: (s == "PASS").sum()),
            fail_count=("run_status_norm", lambda s: (s == "FAIL").sum()),
        )
        .sort_values("week_start")
    )

    grouped["pass_rate"] = grouped.apply(
        lambda row: (100.0 * row["pass_count"] / (row["pass_count"] + row["fail_count"]))
        if (row["pass_count"] + row["fail_count"])
        else 0.0,
        axis=1,
    )

    grouped = grouped.rename(columns={"pass_count": "pass", "fail_count": "fail"})
    return grouped


def build_defect_category_table(df: pd.DataFrame) -> pd.DataFrame:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return pd.DataFrame(columns=["bug_category", "open_defects", "critical_open_defects"])

    defects["is_open"] = ~defects["status_norm"].isin(CLOSED_STATUSES)
    defects["is_critical"] = defects["severity"].str.upper().isin(CRITICAL_VALUES) | defects[
        "priority"
    ].str.upper().isin(CRITICAL_VALUES)
    defects["bug_category"] = defects["bug_category"].replace("", "Uncategorized")

    return (
        defects.groupby("bug_category", as_index=False)
        .agg(
            open_defects=("is_open", "sum"),
            critical_open_defects=("is_critical", "sum"),
        )
        .sort_values(["open_defects", "critical_open_defects"], ascending=False)
    )


def build_weekly_outcome_table(trend_df: pd.DataFrame) -> pd.DataFrame:
    if trend_df.empty:
        return pd.DataFrame(columns=["week_start", "executed", "pass", "fail", "pass_rate"])

    table = trend_df.copy()
    table["week_start"] = table["week_start"].dt.strftime("%Y-%m-%d")
    table["pass_rate"] = table["pass_rate"].round(1)
    return table[["week_start", "executed", "pass", "fail", "pass_rate"]]


def build_pass_rate_by_project(df: pd.DataFrame) -> pd.DataFrame:
    tests = df[df["source_type"].isin(["executed_test", "monthly_executed_snapshot"])].copy()
    if tests.empty:
        return pd.DataFrame(columns=["project_key", "executed", "pass", "fail", "pass_rate"])

    tests["project_key"] = tests["project_key"].replace("", "UNKNOWN")
    grouped = (
        tests.groupby("project_key", as_index=False)
        .agg(
            executed=("issue_key", "count"),
            pass_count=("run_status_norm", lambda s: (s == "PASS").sum()),
            fail_count=("run_status_norm", lambda s: (s == "FAIL").sum()),
        )
        .sort_values("executed", ascending=False)
    )
    grouped["pass_rate"] = grouped.apply(
        lambda row: (100.0 * row["pass_count"] / (row["pass_count"] + row["fail_count"]))
        if (row["pass_count"] + row["fail_count"]) > 0
        else 0.0,
        axis=1,
    )
    grouped = grouped.rename(columns={"pass_count": "pass", "fail_count": "fail"})
    grouped["pass_rate"] = grouped["pass_rate"].round(1)
    return grouped


def build_defect_inflow_outflow(df: pd.DataFrame) -> pd.DataFrame:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return pd.DataFrame(columns=["week_start", "inflow", "outflow"])

    created = defects[defects["created_at"].notna()].copy()
    created["week_start"] = created["created_at"].dt.to_period("W-MON").dt.start_time
    inflow = created.groupby("week_start", as_index=False).agg(inflow=("issue_key", "count"))

    closed = defects[defects["updated_at"].notna() & defects["status_norm"].isin(CLOSED_STATUSES)].copy()
    closed["week_start"] = closed["updated_at"].dt.to_period("W-MON").dt.start_time
    outflow = closed.groupby("week_start", as_index=False).agg(outflow=("issue_key", "count"))

    return (
        inflow.merge(outflow, on="week_start", how="outer")
        .fillna(0)
        .sort_values("week_start")
    )


def build_critical_defect_aging(df: pd.DataFrame) -> pd.DataFrame:
    defects = df[df["source_type"] == "defect"].copy()
    if defects.empty:
        return pd.DataFrame(columns=["project_key", "open_critical", "avg_age_days"])

    is_critical = defects["severity"].str.upper().isin(CRITICAL_VALUES) | defects[
        "priority"
    ].str.upper().isin(CRITICAL_VALUES)
    subset = defects[defects["is_open_defect"] & is_critical].copy()
    if subset.empty:
        return pd.DataFrame(columns=["project_key", "open_critical", "avg_age_days"])

    subset["project_key"] = subset["project_key"].replace("", "UNKNOWN")
    out = (
        subset.groupby("project_key", as_index=False)
        .agg(
            open_critical=("issue_key", "count"),
            avg_age_days=("defect_age_days", "mean"),
        )
        .sort_values("open_critical", ascending=False)
    )
    out["avg_age_days"] = out["avg_age_days"].round(1)
    return out


def build_regression_leakage_proxy(df: pd.DataFrame) -> pd.DataFrame:
    tests = df[df["source_type"] == "test_created"].copy()
    defects = df[df["source_type"] == "defect"].copy()
    if tests.empty or defects.empty:
        return pd.DataFrame(columns=["metric", "value"])

    defect_keys = set(defects["issue_key"].dropna().astype(str))
    linked_defect_count = 0
    for _, row in tests.iterrows():
        linked = set((row.get("related_bug_keys") or []) + (row.get("defect_link_keys") or []))
        linked_defect_count += len(linked & defect_keys)

    total_defects = len(defect_keys)
    ratio = (100.0 * linked_defect_count / total_defects) if total_defects else 0.0
    return pd.DataFrame(
        [
            {"metric": "Linked defects from tests", "value": linked_defect_count},
            {"metric": "Total defects", "value": total_defects},
            {"metric": "Regression leakage proxy %", "value": round(ratio, 1)},
        ]
    )
