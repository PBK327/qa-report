from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from qa_dashboard.schema_config import (
    CANONICAL_FIELDS,
    SCHEMA_REPORT_NAME_BY_SOURCE,
    SCHEMA_REQUIRED_COLUMNS,
    SOURCE_RULES,
    classify_source_type,
)

HTML_TAG_RE = re.compile(r"<[^>]+>")
ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
SPRINT_ID_RE = re.compile(r"SPR#(\d+)", re.IGNORECASE)
NULL_TOKENS = {"", "-", "'-", "null", "none", "nan"}


@dataclass
class IngestionReport:
    files_processed: int
    rows_total: int
    rows_normalized: int
    source_counts: Dict[str, int]
    link_stats: Dict[str, Dict[str, int]]
    warnings: List[str]


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in NULL_TOKENS:
        return ""
    text = HTML_TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_status(value: object) -> str:
    text = _clean_text(value).upper()
    if "PASS" in text:
        return "PASS"
    if "FAIL" in text:
        return "FAIL"
    if text in {"FIXED", "DONE", "CLOSED", "RESOLVED", "REJECTED"}:
        return "CLOSED"
    if text in {"IN PROGRESS", "OPEN", "RUN", "TO DO", "TODO"}:
        return "OPEN"
    return text or "UNKNOWN"


def _parse_jira_datetime(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    # Parse everything as UTC first to avoid mixed timezone errors, then return tz-naive timestamps.
    parsed = pd.to_datetime(values, format="%d/%b/%y %H:%M:%S", errors="coerce", utc=True)

    missing_mask = parsed.isna() & values.ne("")
    if missing_mask.any():
        parsed_alt = pd.to_datetime(values[missing_mask], errors="coerce", utc=True)
        parsed.loc[missing_mask] = parsed_alt

    return parsed.dt.tz_localize(None)


def _extract_issue_keys(value: object) -> List[str]:
    text = _clean_text(value)
    if not text:
        return []
    return list(dict.fromkeys(ISSUE_KEY_RE.findall(text.upper())))


def _parse_sprint_id(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    match = SPRINT_ID_RE.search(text)
    return match.group(1) if match else ""


def _find_first_available_column(df: pd.DataFrame, aliases: List[str]) -> str | None:
    # Jira exports can include duplicated headers. Use first matching base alias or alias with .N suffix.
    for alias in aliases:
        exact = [c for c in df.columns if c == alias]
        if exact:
            return exact[0]
        prefixed = [c for c in df.columns if c.startswith(f"{alias}.")]
        if prefixed:
            return prefixed[0]
    return None


def _normalize_frame(df: pd.DataFrame, source_type: str, file_name: str) -> Tuple[pd.DataFrame, List[str]]:
    warnings: List[str] = []
    out = pd.DataFrame(index=df.index)

    for canonical, aliases in CANONICAL_FIELDS.items():
        col = _find_first_available_column(df, aliases)
        out[canonical] = df[col] if col else ""
        if col is None:
            warnings.append(f"{file_name}: missing expected column for {canonical}")

    out["source_file"] = file_name
    out["source_type"] = source_type

    out["issue_key"] = out["issue_key"].map(_clean_text)
    out["issue_type"] = out["issue_type"].map(_clean_text)
    out["project_key"] = out["project_key"].map(_clean_text)
    out["priority"] = out["priority"].map(_clean_text)
    out["severity"] = out["severity"].map(_clean_text)
    out["bug_category"] = out["bug_category"].map(_clean_text)
    out["component_raw"] = out["component_raw"].map(_clean_text)
    out["scrum_team_raw"] = out["scrum_team_raw"].map(_clean_text)
    out["sprint_raw"] = out["sprint_raw"].map(_clean_text)
    out["bug_origin_raw"] = out["bug_origin_raw"].map(_clean_text)

    out["status_norm"] = out["status_raw"].map(_normalize_status)
    out["run_status_norm"] = out["run_status_raw"].map(_normalize_status)

    out["created_at"] = _parse_jira_datetime(out["created_at_raw"])
    out["updated_at"] = _parse_jira_datetime(out["updated_at_raw"])
    out["week_start"] = out["created_at"].dt.to_period("W-MON").dt.start_time
    out["sprint_id"] = out["sprint_raw"].map(_parse_sprint_id)

    out["severity_norm"] = out["severity"].str.upper()
    out["priority_norm"] = out["priority"].str.upper()
    out["scrum_proxy"] = out["project_key"].map(_clean_text)

    is_defect = out["source_type"].eq("defect")
    out["is_open_defect"] = is_defect & (~out["status_norm"].isin({"CLOSED", "FIXED", "DONE", "RESOLVED", "REJECTED"}))
    out["fix_cycle_days"] = (out["updated_at"] - out["created_at"]).dt.total_seconds() / 86400.0
    out.loc[~is_defect, "fix_cycle_days"] = pd.NA
    out.loc[out["fix_cycle_days"] < 0, "fix_cycle_days"] = pd.NA
    now_ts = pd.Timestamp.now()
    out["defect_age_days"] = (now_ts - out["created_at"]).dt.total_seconds() / 86400.0
    out.loc[~(is_defect & out["is_open_defect"]), "defect_age_days"] = pd.NA

    # Join key extraction used by linked KPI model.
    out["sub_task_keys"] = out["sub_tasks_raw"].map(_extract_issue_keys)
    out["executed_test_ref_keys"] = out["executed_test_ref_raw"].map(_extract_issue_keys)
    out["related_bug_keys"] = out["related_bugs_raw"].map(_extract_issue_keys)
    out["defect_link_keys"] = out["defect_link_raw"].map(_extract_issue_keys)
    out["blocker_bug_keys"] = out["blockers_raw"].map(_extract_issue_keys)

    expected_issue_type = None
    for rule in SOURCE_RULES:
        if rule.source_type == source_type:
            expected_issue_type = rule.expected_issue_type
            break

    if expected_issue_type:
        before = len(out)
        out = out[out["issue_type"].str.casefold() == expected_issue_type.casefold()]
        dropped = before - len(out)
        if dropped > 0:
            warnings.append(
                f"{file_name}: dropped {dropped} rows where Issue Type != {expected_issue_type}"
            )

    out = out.reset_index(drop=True)
    return out, warnings


def load_schema_requirements(schema_file: Path) -> Dict[str, List[Tuple[str, str]]]:
    if not schema_file.exists():
        return {}

    schema_df = pd.read_csv(schema_file)
    requirements: Dict[str, List[Tuple[str, str]]] = {}

    for _, row in schema_df.iterrows():
        report_name = str(row.get(SCHEMA_REQUIRED_COLUMNS["report_name"], "")).strip()
        column = str(row.get(SCHEMA_REQUIRED_COLUMNS["relevant_column"], "")).strip()
        must_value = str(row.get(SCHEMA_REQUIRED_COLUMNS["must_have_value"], "")).strip()
        if not report_name or not column:
            continue
        requirements.setdefault(report_name, []).append((column, must_value))

    return requirements


def _build_link_stats(unified: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    if unified.empty:
        return {}

    link_stats: Dict[str, Dict[str, int]] = {}

    auto_jobs = unified[unified["source_type"] == "automation_job"]
    executed = unified[unified["source_type"].isin(["executed_test", "monthly_executed_snapshot"])]
    tests = unified[unified["source_type"] == "test_created"]
    defects = unified[unified["source_type"] == "defect"]

    executed_keys = set(executed["issue_key"].dropna().astype(str))
    test_keys = set(tests["issue_key"].dropna().astype(str))
    defect_keys = set(defects["issue_key"].dropna().astype(str))

    def _count_links(rows: pd.Series, target_keys: set[str]) -> Dict[str, int]:
        matched = 0
        unresolved = 0
        total_links = 0
        for keys in rows:
            key_list = keys if isinstance(keys, list) else []
            total_links += len(key_list)
            for key in key_list:
                if key in target_keys:
                    matched += 1
                else:
                    unresolved += 1
        return {
            "links_total": total_links,
            "matched": matched,
            "unresolved": unresolved,
        }

    link_stats["automation_job_to_executed_test"] = _count_links(
        auto_jobs["sub_task_keys"], executed_keys
    )
    link_stats["executed_test_to_test_created"] = _count_links(
        executed["executed_test_ref_keys"], test_keys
    )

    merged_bug_refs = tests.apply(
        lambda row: (row["related_bug_keys"] or []) + (row["defect_link_keys"] or []), axis=1
    )
    link_stats["test_created_to_defects"] = _count_links(merged_bug_refs, defect_keys)
    link_stats["automation_job_blockers_to_defects"] = _count_links(
        auto_jobs["blocker_bug_keys"], defect_keys
    )

    return link_stats


def load_all_csvs(base_dir: Path, schema_file: Path) -> Tuple[pd.DataFrame, IngestionReport]:
    csv_files = sorted(base_dir.glob("*.csv"))
    all_rows: List[pd.DataFrame] = []
    warnings: List[str] = []
    source_counts: Dict[str, int] = {}

    schema_requirements = load_schema_requirements(schema_file)

    for csv_file in csv_files:
        source_type = classify_source_type(csv_file)
        source_counts[source_type] = source_counts.get(source_type, 0) + 1

        try:
            df = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
        except Exception as exc:
            warnings.append(f"{csv_file.name}: read error: {exc}")
            continue

        report_name = SCHEMA_REPORT_NAME_BY_SOURCE.get(source_type)
        if report_name and report_name in schema_requirements:
            for required_col, must_value in schema_requirements[report_name]:
                if required_col not in df.columns:
                    warnings.append(
                        f"{csv_file.name}: schema-required column missing: {required_col}"
                    )
                elif must_value not in {"", "-"}:
                    if not (df[required_col].astype(str).str.strip() == must_value).any():
                        warnings.append(
                            f"{csv_file.name}: no rows matched {required_col}={must_value}"
                        )

        normalized, frame_warnings = _normalize_frame(df, source_type, csv_file.name)
        all_rows.append(normalized)
        warnings.extend(frame_warnings)

    if all_rows:
        unified = pd.concat(all_rows, ignore_index=True)
    else:
        unified = pd.DataFrame(
            columns=[
                "issue_key",
                "issue_type",
                "status_raw",
                "status_norm",
                "created_at_raw",
                "updated_at_raw",
                "priority",
                "severity",
                "bug_category",
                "run_status_raw",
                "run_status_norm",
                "project_key",
                "sprint_raw",
                "sprint_id",
                "scrum_team_raw",
                "scrum_proxy",
                "component_raw",
                "created_at",
                "updated_at",
                "week_start",
                "is_open_defect",
                "fix_cycle_days",
                "defect_age_days",
                "sub_task_keys",
                "executed_test_ref_keys",
                "related_bug_keys",
                "defect_link_keys",
                "blocker_bug_keys",
                "source_file",
                "source_type",
            ]
        )

    link_stats = _build_link_stats(unified)

    report = IngestionReport(
        files_processed=len(csv_files),
        rows_total=int(sum(len(df) for df in all_rows)) if all_rows else 0,
        rows_normalized=int(len(unified)),
        source_counts=source_counts,
        link_stats=link_stats,
        warnings=warnings,
    )
    return unified, report
