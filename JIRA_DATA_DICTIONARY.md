# Jira Data Dictionary

This document describes the structure and relationships of Jira issues used by the QA automation pipeline.

## Data Model Overview

The pipeline integrates data from 4 interconnected Jira issue types:

```
Automation Job (Auto Process)
    ├── Sub-Tasks → Executed Test (Auto Test)
    │                   └── Executed Test field → Test (Test)
    │                                                └── Related Bugs → Defects (Bug)
    └── Blockers → Defects (Bug)
```

---

## Issue Type 1: Automation Job

**Type:** Auto Process  
**Purpose:** Top-level weekly test run that aggregates multiple test executions

### Required Fields

| Field | Must Have Value | Notes |
|-------|-----------------|-------|
| Issue Type | `Auto Process` | |
| Issue key | — | Auto-generated issue key |
| Created | — | Date issue was created |
| Updated | — | Date issue was last modified |
| Sprint | — | Which sprint this job was executed in |

### Custom Fields

| Field | Must Have Value | Join Key | Notes |
|-------|-----------------|----------|-------|
| Blockers | Issue key of "Bug" type | Relates to Defects | Bug IDs blocking this automation job |
| Automation Test Run Approved | Yes | — | Indicates if job was reviewed by automation engineer |
| Job Name | — | — | Name of job (e.g., BI-Sanity); format: `<Team>-<TestType>` |
| Job Run By User | — | — | User who triggered the job |
| Job Stack Prefix | — | — | Software version deployed on stack |
| Job Stack Version | — | — | Stack name where automation was run |
| Sub-Tasks | Issue key of "Auto Test" type | **HIERARCHY** | Test executions related to this job |

---

## Issue Type 2: Executed Test

**Type:** Auto Test  
**Purpose:** Individual test execution within an Automation Job

### Required Fields

| Field | Must Have Value | Notes |
|-------|-----------------|-------|
| Issue Type | `Auto Test` | Related to Automation Job sub-tasks |
| Issue key | — | Auto-generated issue key |
| Created | — | Date execution record was created |
| Updated | — | Date execution record was last modified |

### Custom Fields

| Field | Must Have Value | Join Key | Notes |
|-------|-----------------|----------|-------|
| Auto Test Run Status | — | — | Pass/Fail status of this test execution |
| Job Start Time | — | — | Timestamp when execution started |
| Job End Time | — | — | Timestamp when execution ended |
| Executed Test | Issue key of "Test" type | **HIERARCHY** | Test case(s) included in this execution |

---

## Issue Type 3: Test Created

**Type:** Test  
**Purpose:** Test case definition (what was tested)

### Required Fields

| Field | Must Have Value | Notes |
|-------|-----------------|-------|
| Issue Type | `Test` | |
| Issue key | — | Auto-generated issue key |
| Project key | — | Project this test belongs to |
| Creator | — | User who created the test |
| Created | — | Date test was created |
| Updated | — | Date test was last modified/run |

### Custom Fields

| Field | Must Have Value | Join Key | Notes |
|-------|-----------------|----------|-------|
| Epic Link | — | — | Epic under which test was written |
| TestRunStatus | — | — | Current test execution status |
| Related Bugs (Inward) | Issue key of "Bug" type | **JOIN** | Bugs related to this test |
| Defect (Outward) | Issue key of "Bug" type | **JOIN** | Bugs this test helps verify |
| Automated | "Done" | — | Indicates test is covered by automation |
| Customer Name (epic) | — | — | Customer for which test was created |
| Test Sets association with a Test | — | — | Test sets this test belongs to |
| Related Stories/Tasks | — | — | Associated stories or tasks |

---

## Issue Type 4: Defects

**Type:** Bug  
**Purpose:** Bug/defect tracking and management

### Required Fields

| Field | Must Have Value | Notes |
|-------|-----------------|-------|
| Issue Type | `Bug` | |
| Issue key | — | Auto-generated issue key |
| Status | — | Open, Closed, In Progress, etc. |
| Priority | — | Critical, Blocker, Major, Minor, etc. |
| Assignee | — | Developer assigned to fix |
| Creator | — | Who reported the bug |
| Created | — | Date bug was reported |
| Updated | — | Date bug was last modified |

### Custom Fields

| Field | Must Have Value | Notes |
|-------|-----------------|-------|
| Fix Version/s | — | Planned version where bug will be fixed |
| Component/s | — | Code component affected by bug |
| Labels | — | Tags for organization |
| Bug Category | — | Category (e.g., UI, Backend, Data) |
| Bug Origin | — | Who raised this bug |
| Clones | — | Clone ID of bugs (for tracking variants) |
| Customer Name (epic) | — | Customer affected by bug |
| Customer/s Name | — | Additional customer names |
| Detected Version | — | Version in which bug was detected |
| Scrum Team | — | Team responsible for fixing |
| Sprint | — | Sprint where bug is planned (blank = not scheduled) |
| Story Points | — | Effort estimation |
| Verified in | — | Version where fix was verified |

---

## Data Relationships & Joins

### Primary Hierarchy (Parent-Child)
```
Automation Job (parent)
    └── Sub-Tasks (custom field)
        └── Executed Test (child issue type)
```

### Secondary Relationships (References)
```
Automation Job --Blockers--> Defects
                             ↑
Executed Test --Executed Test--> Test --Related Bugs--> Defects
```

### Key Join Fields for Pipeline

| From | To | Join Field | Purpose |
|------|----|-----------| ---------|
| Automation Job | Defects | Blockers | Find bugs blocking this job |
| Automation Job | Executed Test | Sub-Tasks | Get all test runs for this job |
| Executed Test | Test | Executed Test field | Get actual test cases executed |
| Test | Defects | Related Bugs / Defect | Connect tests to bugs they cover |

---

## Notes for Pipeline Implementation

1. **Multi-Region Execution:** Executed Test data comes from multiple regional CSVs (ADM, ADP, BI, NAM, PAM, SAM)
2. **Sprint Enrichment:** Defects are enriched with sprint analytics (Open count, Closed count per sprint)
3. **Duration Calculation:** Job duration is computed from Job Start Time and Job End Time
4. **Bug Explosion:** Blockers field may contain multiple bug IDs separated by delimiters
5. **Null Handling:** Some fields may be empty (e.g., Sprint for unscheduled defects)
6. **Schema Evolution:** Pipeline automatically handles new columns from Jira custom fields

---

## CSV Export Mapping

When reports are exported to CSV, the mapping follows this pattern:

- **Automation Job Report** → `Automation Job*.csv`
- **Executed Test Report** → `Executed Test*.csv`  
- **Test Created Report** → `Test Created*.csv`
- **Defects Report** → `Defects*.csv`

See `jira_sync_config.json` for specific JQL queries and column mappings used to fetch these reports.
