from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class SourceRule:
    source_type: str
    filename_tokens: List[str]
    expected_issue_type: str | None = None


SOURCE_RULES: List[SourceRule] = [
    SourceRule("automation_job", ["automation", "job"], "Auto Process"),
    SourceRule("executed_test", ["executed", "test", "bi"], "Auto Test"),
    SourceRule("monthly_executed_snapshot", ["test", "executed", "nam"], "Auto Test"),
    SourceRule("defect", ["defects"], "Bug"),
    SourceRule("test_created", ["test", "create"], "Test"),
]

CANONICAL_FIELDS: Dict[str, List[str]] = {
    "issue_key": ["Issue key"],
    "issue_type": ["Issue Type"],
    "status_raw": ["Status", "Custom field (Auto Test Run Status)"],
    "created_at_raw": ["Created", "Custom field (Event Timestamp)"],
    "updated_at_raw": ["Updated"],
    "priority": ["Priority"],
    "severity": ["Custom field (Severity)", "Severity"],
    "bug_category": ["Custom field (Bug Category)"],
    "run_status_raw": [
        "Custom field (Auto Test Run Status)",
        "Custom field (AAuto Test Run Status_1)",
        "Status",
    ],
    "project_key": ["Project key"],
    "sprint_raw": ["Sprint"],
    "scrum_team_raw": ["Custom field (Scrum Team)", "Custom field (Team)", "Team"],
    "component_raw": ["Component/s", "Custom field (Component)"],
    "sub_tasks_raw": ["Sub-Tasks"],
    "executed_test_ref_raw": ["Custom field (Executed Test)"],
    "related_bugs_raw": [
        "Related Bugs",
        "Inward issue link (Related Bugs)",
        "Outward issue link (Related Bugs)",
        "Outward issue link (Defect)",
    ],
    "defect_link_raw": [
        "Outward issue link (Defect)",
        "Inward issue link (Defect)",
    ],
    "blockers_raw": ["Custom field (Blockers)", "Blockers On Execution"],
    "automation_approved_raw": ["Custom field (Automation Test Run Approved)"],
    "job_name_raw": ["Custom field (Job Name)"],
    "job_run_by_raw": ["Custom field (Job Run By User)"],
    "job_stack_prefix_raw": ["Custom field (Job Stack Prefix)"],
    "job_stack_version_raw": ["Custom field (Job Stack Version)"],
    "fix_version_raw": ["Fix Version/s"],
    "detected_version_raw": ["Custom field (Detected Version)"],
    "verified_in_raw": ["Custom field (Verified in)"],
    "story_points_raw": ["Custom field (Story Points)"],
    "bug_origin_raw": ["Custom field (Bug Origin)"],
}

SCHEMA_REQUIRED_COLUMNS = {
    "report_name": "Report Name",
    "relevant_column": "Relevant Column",
    "must_have_value": "Must Have Value",
    "hierarchy_join_key": "HIERERCHY JOIN KEY",
    "notes": "Notes",
}

# Report names are aligned to values in Report Schema sh.csv.
SCHEMA_REPORT_NAME_BY_SOURCE: Dict[str, str] = {
    "automation_job": "Automation Job",
    "executed_test": "Executed Test",
    "monthly_executed_snapshot": "Executed Test",
    "defect": "Defects",
    "test_created": "Test Created",
}


def classify_source_type(file_path: Path) -> str:
    name = file_path.name.lower()
    for rule in SOURCE_RULES:
        if all(token in name for token in rule.filename_tokens):
            return rule.source_type
    return "unknown"
