-- Reusable Vertica rollup template with three physical aggregation tables.
--
-- Required template vars:
--   ${agg_test_fact_relation}  e.g. omniq.qa_agg_test_fact
--   ${defect_dim_relation}     e.g. omniq.qa_defect_dim
--   ${target_schema}           e.g. omniq
--   ${target_table_5min}       e.g. AGG_QA_REPORT_5_MIN
--   ${target_table_hour}       e.g. AGG_QA_REPORT_HOUR
--   ${target_table_day}        e.g. AGG_QA_REPORT_DAY
--   ${period_start}            e.g. 2026-01-01 00:00:00
--   ${period_end}              e.g. 2027-01-01 00:00:00
--
-- Grain definitions:
--   5 MIN : TRUNC(ts, 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM ts), 5)
--   HOUR  : DATE_TRUNC('hour', start_time)
--   DAY   : DATE_TRUNC('day', start_time)

DROP TABLE IF EXISTS ${target_schema}.${target_table_5min};
DROP TABLE IF EXISTS ${target_schema}.${target_table_hour};
DROP TABLE IF EXISTS ${target_schema}.${target_table_day};

CREATE TABLE IF NOT EXISTS ${target_schema}.${target_table_5min} (
    start_time TIMESTAMP NOT NULL,
    updated_ts TIMESTAMP,

    test_job_name VARCHAR(256),
    env_name VARCHAR(128),
    env_version VARCHAR(128),
    sprint VARCHAR(128),
    test_group VARCHAR(256),
    test_group_feature VARCHAR(256),
    test_scenario VARCHAR(512),
    auto_test_run_status VARCHAR(64),

    bugs VARCHAR(64),
    status VARCHAR(64),
    priority VARCHAR(64),
    assignee VARCHAR(128),
    fix_versions VARCHAR(256),
    components VARCHAR(256),
    labels VARCHAR(512),
    bug_category VARCHAR(128),
    bug_origin VARCHAR(128),
    customer_name VARCHAR(256),
    detected_version VARCHAR(128),
    scrum_team VARCHAR(128),
    scope_change VARCHAR(128),

    executed_test VARCHAR(64),
    qa_report VARCHAR(32),
    sprint_status VARCHAR(64),
    bug_resolved TIMESTAMP,

    total_scenarios INT,
    passed_scenarios INT,
    failed_scenarios INT,
    open_bugs INT,
    closed_bugs INT,
    resolution_days NUMERIC(18, 4),
    total_execution_duration_min NUMERIC(18, 4),
    total_bugs INT,
    regression_bugs INT,
    critical_regression_bugs INT,
    open_regression_bugs INT,
    closed_regression_bugs INT,
    customer_regression_bugs INT,

    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        start_time,
        updated_ts,
        test_job_name,
        env_name,
        env_version,
        sprint,
        test_group,
        test_group_feature,
        test_scenario,
        auto_test_run_status,
        bugs,
        status,
        priority,
        assignee,
        fix_versions,
        components,
        labels,
        bug_category,
        bug_origin,
        customer_name,
        detected_version,
        scrum_team,
        scope_change,
        executed_test,
        qa_report
    )
)
PARTITION BY DATE(start_time);

CREATE TABLE IF NOT EXISTS ${target_schema}.${target_table_hour} (
    start_time TIMESTAMP NOT NULL,
    updated_ts TIMESTAMP,

    test_job_name VARCHAR(256),
    env_name VARCHAR(128),
    env_version VARCHAR(128),
    sprint VARCHAR(128),
    test_group VARCHAR(256),
    test_group_feature VARCHAR(256),
    test_scenario VARCHAR(512),
    auto_test_run_status VARCHAR(64),

    bugs VARCHAR(64),
    status VARCHAR(64),
    priority VARCHAR(64),
    assignee VARCHAR(128),
    fix_versions VARCHAR(256),
    components VARCHAR(256),
    labels VARCHAR(512),
    bug_category VARCHAR(128),
    bug_origin VARCHAR(128),
    customer_name VARCHAR(256),
    detected_version VARCHAR(128),
    scrum_team VARCHAR(128),
    scope_change VARCHAR(128),

    executed_test VARCHAR(64),
    qa_report VARCHAR(32),
    sprint_status VARCHAR(64),
    bug_resolved TIMESTAMP,

    total_scenarios INT,
    passed_scenarios INT,
    failed_scenarios INT,
    open_bugs INT,
    closed_bugs INT,
    resolution_days NUMERIC(18, 4),
    total_execution_duration_min NUMERIC(18, 4),
    total_bugs INT,
    regression_bugs INT,
    critical_regression_bugs INT,
    open_regression_bugs INT,
    closed_regression_bugs INT,
    customer_regression_bugs INT,

    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        start_time,
        updated_ts,
        test_job_name,
        env_name,
        env_version,
        sprint,
        test_group,
        test_group_feature,
        test_scenario,
        auto_test_run_status,
        bugs,
        status,
        priority,
        assignee,
        fix_versions,
        components,
        labels,
        bug_category,
        bug_origin,
        customer_name,
        detected_version,
        scrum_team,
        scope_change,
        executed_test,
        qa_report
    )
)
PARTITION BY DATE(start_time);

CREATE TABLE IF NOT EXISTS ${target_schema}.${target_table_day} (
    start_time TIMESTAMP NOT NULL,
    updated_ts TIMESTAMP,

    test_job_name VARCHAR(256),
    env_name VARCHAR(128),
    env_version VARCHAR(128),
    sprint VARCHAR(128),
    test_group VARCHAR(256),
    test_group_feature VARCHAR(256),
    test_scenario VARCHAR(512),
    auto_test_run_status VARCHAR(64),

    bugs VARCHAR(64),
    status VARCHAR(64),
    priority VARCHAR(64),
    assignee VARCHAR(128),
    fix_versions VARCHAR(256),
    components VARCHAR(256),
    labels VARCHAR(512),
    bug_category VARCHAR(128),
    bug_origin VARCHAR(128),
    customer_name VARCHAR(256),
    detected_version VARCHAR(128),
    scrum_team VARCHAR(128),
    scope_change VARCHAR(128),

    executed_test VARCHAR(64),
    qa_report VARCHAR(32),
    sprint_status VARCHAR(64),
    bug_resolved TIMESTAMP,

    total_scenarios INT,
    passed_scenarios INT,
    failed_scenarios INT,
    open_bugs INT,
    closed_bugs INT,
    resolution_days NUMERIC(18, 4),
    total_execution_duration_min NUMERIC(18, 4),
    total_bugs INT,
    regression_bugs INT,
    critical_regression_bugs INT,
    open_regression_bugs INT,
    closed_regression_bugs INT,
    customer_regression_bugs INT,

    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        start_time,
        updated_ts,
        test_job_name,
        env_name,
        env_version,
        sprint,
        test_group,
        test_group_feature,
        test_scenario,
        auto_test_run_status,
        bugs,
        status,
        priority,
        assignee,
        fix_versions,
        components,
        labels,
        bug_category,
        bug_origin,
        customer_name,
        detected_version,
        scrum_team,
        scope_change,
        executed_test,
        qa_report
    )
)
PARTITION BY DATE(start_time);

DROP TABLE IF EXISTS _stg_qa_report_5m;
DROP TABLE IF EXISTS _stg_qa_report_hour;
DROP TABLE IF EXISTS _stg_qa_report_day;

CREATE LOCAL TEMP TABLE _stg_qa_report_5m ON COMMIT PRESERVE ROWS AS
WITH approved_runs AS (
    SELECT *
    FROM ${agg_test_fact_relation}
    WHERE "Custom field (Automation Test Run Approved)" = 'Yes'
),
src_5m_auto AS (
    SELECT
        TRUNC("Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Created"), 5) AS start_time,
        CAST("Updated" AS TIMESTAMP) AS updated_ts,
        CAST("Custom field (Job Name)" AS VARCHAR(256)) AS test_job_name,
        CAST("Custom field (Job Stack Prefix)" AS VARCHAR(128)) AS env_name,
        CAST("Custom field (Job Stack Version)" AS VARCHAR(128)) AS env_version,
        CAST("Sprint" AS VARCHAR(128)) AS sprint,
        CAST("Test Group" AS VARCHAR(256)) AS test_group,
        CAST("Test Group Feature" AS VARCHAR(256)) AS test_group_feature,
        CAST("Test Scenario" AS VARCHAR(512)) AS test_scenario,
        CAST("Auto Test Run Status" AS VARCHAR(64)) AS auto_test_run_status,
        CAST("Bugs" AS VARCHAR(64)) AS bugs,
        CAST("Status" AS VARCHAR(64)) AS status,
        CAST("Priority" AS VARCHAR(64)) AS priority,
        CAST("Assignee" AS VARCHAR(128)) AS assignee,
        CAST("Fix Version/s" AS VARCHAR(256)) AS fix_versions,
        CAST("Component/s" AS VARCHAR(256)) AS components,
        CAST("Labels" AS VARCHAR(512)) AS labels,
        CAST("Bug Category" AS VARCHAR(128)) AS bug_category,
        CAST("Bug Origin" AS VARCHAR(128)) AS bug_origin,
        CAST("Customer/s Name" AS VARCHAR(256)) AS customer_name,
        CAST("Detected Version" AS VARCHAR(128)) AS detected_version,
        CAST("Scrum Team" AS VARCHAR(128)) AS scrum_team,
        CAST("Scope Change" AS VARCHAR(128)) AS scope_change,
        CAST("Executed Test" AS VARCHAR(64)) AS executed_test,
        'Automation'::VARCHAR(32) AS qa_report,
        NULL::VARCHAR(64) AS sprint_status,
        NULL::TIMESTAMP AS bug_resolved,
        COALESCE(SUM("No of Test Scenario"), 0)::INT AS total_scenarios,
        COALESCE(SUM("Pass Test Scenario"), 0)::INT AS passed_scenarios,
        COALESCE(SUM("Failed Test Scenario"), 0)::INT AS failed_scenarios,
        SUM("Open Bugs")::INT AS open_bugs,
        SUM("Closed Bugs")::INT AS closed_bugs,
        SUM("Resolution Days")::NUMERIC(18, 4) AS resolution_days,
        ROUND(SUM("Executed Test Duration (Minutes)"), 2)::NUMERIC(18, 4) AS total_execution_duration_min,
        0::INT AS total_bugs,
        0::INT AS regression_bugs,
        0::INT AS critical_regression_bugs,
        0::INT AS open_regression_bugs,
        0::INT AS closed_regression_bugs,
        0::INT AS customer_regression_bugs
    FROM approved_runs
    WHERE (
        '${period_start}' = '__ALL__'
        OR (
            "Created" >= '${period_start}'::TIMESTAMP
            AND "Created" < '${period_end}'::TIMESTAMP
        )
    )
    GROUP BY
        TRUNC("Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Created"), 5),
        CAST("Updated" AS TIMESTAMP),
        CAST("Custom field (Job Name)" AS VARCHAR(256)),
        CAST("Custom field (Job Stack Prefix)" AS VARCHAR(128)),
        CAST("Custom field (Job Stack Version)" AS VARCHAR(128)),
        CAST("Sprint" AS VARCHAR(128)),
        CAST("Test Group" AS VARCHAR(256)),
        CAST("Test Group Feature" AS VARCHAR(256)),
        CAST("Test Scenario" AS VARCHAR(512)),
        CAST("Auto Test Run Status" AS VARCHAR(64)),
        CAST("Bugs" AS VARCHAR(64)),
        CAST("Status" AS VARCHAR(64)),
        CAST("Priority" AS VARCHAR(64)),
        CAST("Assignee" AS VARCHAR(128)),
        CAST("Fix Version/s" AS VARCHAR(256)),
        CAST("Component/s" AS VARCHAR(256)),
        CAST("Labels" AS VARCHAR(512)),
        CAST("Bug Category" AS VARCHAR(128)),
        CAST("Bug Origin" AS VARCHAR(128)),
        CAST("Customer/s Name" AS VARCHAR(256)),
        CAST("Detected Version" AS VARCHAR(128)),
        CAST("Scrum Team" AS VARCHAR(128)),
        CAST("Scope Change" AS VARCHAR(128)),
        CAST("Executed Test" AS VARCHAR(64))
),
src_5m_defect AS (
    SELECT
        TRUNC("Bug Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Bug Created"), 5) AS start_time,
        CAST("Bug Updated" AS TIMESTAMP) AS updated_ts,
        NULL::VARCHAR(256) AS test_job_name,
        NULL::VARCHAR(128) AS env_name,
        NULL::VARCHAR(128) AS env_version,
        CAST("Sprint" AS VARCHAR(128)) AS sprint,
        NULL::VARCHAR(256) AS test_group,
        NULL::VARCHAR(256) AS test_group_feature,
        NULL::VARCHAR(512) AS test_scenario,
        NULL::VARCHAR(64) AS auto_test_run_status,
        CAST("Bugs" AS VARCHAR(64)) AS bugs,
        CAST("Status" AS VARCHAR(64)) AS status,
        CAST("Priority" AS VARCHAR(64)) AS priority,
        CAST("Assignee" AS VARCHAR(128)) AS assignee,
        CAST("Fix Version/s" AS VARCHAR(256)) AS fix_versions,
        CAST("Component/s" AS VARCHAR(256)) AS components,
        CAST("Labels" AS VARCHAR(512)) AS labels,
        CAST("Bug Category" AS VARCHAR(128)) AS bug_category,
        CAST("Bug Origin" AS VARCHAR(128)) AS bug_origin,
        CAST("Customer/s Name" AS VARCHAR(256)) AS customer_name,
        CAST("Detected Version" AS VARCHAR(128)) AS detected_version,
        CAST("Scrum Team" AS VARCHAR(128)) AS scrum_team,
        CAST("Scope Change" AS VARCHAR(128)) AS scope_change,
        NULL::VARCHAR(64) AS executed_test,
        'Defects'::VARCHAR(32) AS qa_report,
        CAST("Sprint Status" AS VARCHAR(64)) AS sprint_status,
        CAST("Bug Resolved" AS TIMESTAMP) AS bug_resolved,
        NULL::INT AS total_scenarios,
        NULL::INT AS passed_scenarios,
        NULL::INT AS failed_scenarios,
        NULL::INT AS open_bugs,
        NULL::INT AS closed_bugs,
        NULL::NUMERIC(18, 4) AS resolution_days,
        NULL::NUMERIC(18, 4) AS total_execution_duration_min,
        COUNT(*)::INT AS total_bugs,
        COUNT(CASE WHEN "Bug Category" = 'Regression' THEN "Bugs" END)::INT AS regression_bugs,
        COUNT(CASE WHEN "Bug Category" = 'Regression' AND "Priority" IN ('Blocker', 'Critical') THEN "Bugs" END)::INT AS critical_regression_bugs,
        COUNT(CASE WHEN "Bug Category" = 'Regression' AND "Status" NOT IN ('Closed', 'Integrated', 'Rejected') THEN "Bugs" END)::INT AS open_regression_bugs,
        COUNT(CASE WHEN "Bug Category" = 'Regression' AND "Status" IN ('Closed', 'Integrated', 'Rejected') THEN "Bugs" END)::INT AS closed_regression_bugs,
        COUNT(CASE WHEN "Bug Category" = 'Regression' AND "Bug Origin" IN ('Customer', 'PSO', 'POC') THEN "Bugs" END)::INT AS customer_regression_bugs
    FROM ${defect_dim_relation}
    WHERE (
        '${period_start}' = '__ALL__'
        OR (
            "Bug Created" >= '${period_start}'::TIMESTAMP
            AND "Bug Created" < '${period_end}'::TIMESTAMP
        )
    )
    GROUP BY
        TRUNC("Bug Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Bug Created"), 5),
        CAST("Bug Updated" AS TIMESTAMP),
        CAST("Sprint" AS VARCHAR(128)),
        CAST("Bugs" AS VARCHAR(64)),
        CAST("Status" AS VARCHAR(64)),
        CAST("Priority" AS VARCHAR(64)),
        CAST("Assignee" AS VARCHAR(128)),
        CAST("Fix Version/s" AS VARCHAR(256)),
        CAST("Component/s" AS VARCHAR(256)),
        CAST("Labels" AS VARCHAR(512)),
        CAST("Bug Category" AS VARCHAR(128)),
        CAST("Bug Origin" AS VARCHAR(128)),
        CAST("Customer/s Name" AS VARCHAR(256)),
        CAST("Detected Version" AS VARCHAR(128)),
        CAST("Scrum Team" AS VARCHAR(128)),
        CAST("Scope Change" AS VARCHAR(128)),
        CAST("Sprint Status" AS VARCHAR(64)),
        CAST("Bug Resolved" AS TIMESTAMP)
),
src_5m AS (
    SELECT * FROM src_5m_auto
    UNION ALL
    SELECT * FROM src_5m_defect
)
SELECT
    start_time,
    updated_ts,
    COALESCE(test_job_name, '') AS test_job_name,
    COALESCE(env_name, '') AS env_name,
    COALESCE(env_version, '') AS env_version,
    COALESCE(sprint, '') AS sprint,
    COALESCE(test_group, '') AS test_group,
    COALESCE(test_group_feature, '') AS test_group_feature,
    COALESCE(test_scenario, '') AS test_scenario,
    COALESCE(auto_test_run_status, '') AS auto_test_run_status,
    COALESCE(bugs, '') AS bugs,
    COALESCE(status, '') AS status,
    COALESCE(priority, '') AS priority,
    COALESCE(assignee, '') AS assignee,
    COALESCE(fix_versions, '') AS fix_versions,
    COALESCE(components, '') AS components,
    COALESCE(labels, '') AS labels,
    COALESCE(bug_category, '') AS bug_category,
    COALESCE(bug_origin, '') AS bug_origin,
    COALESCE(customer_name, '') AS customer_name,
    COALESCE(detected_version, '') AS detected_version,
    COALESCE(scrum_team, '') AS scrum_team,
    COALESCE(scope_change, '') AS scope_change,
    COALESCE(executed_test, '') AS executed_test,
    COALESCE(qa_report, '') AS qa_report,
    sprint_status,
    bug_resolved,
    total_scenarios,
    passed_scenarios,
    failed_scenarios,
    open_bugs,
    closed_bugs,
    resolution_days,
    total_execution_duration_min,
    total_bugs,
    regression_bugs,
    critical_regression_bugs,
    open_regression_bugs,
    closed_regression_bugs,
    customer_regression_bugs
FROM src_5m;

CREATE LOCAL TEMP TABLE _stg_qa_report_hour ON COMMIT PRESERVE ROWS AS
SELECT
    DATE_TRUNC('hour', start_time) AS start_time,
    DATE_TRUNC('hour', updated_ts) AS updated_ts,
    test_job_name,
    env_name,
    env_version,
    sprint,
    test_group,
    test_group_feature,
    test_scenario,
    auto_test_run_status,
    bugs,
    status,
    priority,
    assignee,
    fix_versions,
    components,
    labels,
    bug_category,
    bug_origin,
    customer_name,
    detected_version,
    scrum_team,
    scope_change,
    executed_test,
    qa_report,
    sprint_status,
    bug_resolved,
    SUM(total_scenarios) AS total_scenarios,
    SUM(passed_scenarios) AS passed_scenarios,
    SUM(failed_scenarios) AS failed_scenarios,
    SUM(open_bugs) AS open_bugs,
    SUM(closed_bugs) AS closed_bugs,
    SUM(resolution_days) AS resolution_days,
    SUM(total_execution_duration_min) AS total_execution_duration_min,
    SUM(total_bugs) AS total_bugs,
    SUM(regression_bugs) AS regression_bugs,
    SUM(critical_regression_bugs) AS critical_regression_bugs,
    SUM(open_regression_bugs) AS open_regression_bugs,
    SUM(closed_regression_bugs) AS closed_regression_bugs,
    SUM(customer_regression_bugs) AS customer_regression_bugs
FROM _stg_qa_report_5m
GROUP BY
    DATE_TRUNC('hour', start_time),
    DATE_TRUNC('hour', updated_ts),
    test_job_name,
    env_name,
    env_version,
    sprint,
    test_group,
    test_group_feature,
    test_scenario,
    auto_test_run_status,
    bugs,
    status,
    priority,
    assignee,
    fix_versions,
    components,
    labels,
    bug_category,
    bug_origin,
    customer_name,
    detected_version,
    scrum_team,
    scope_change,
    executed_test,
    qa_report,
    sprint_status,
    bug_resolved;

CREATE LOCAL TEMP TABLE _stg_qa_report_day ON COMMIT PRESERVE ROWS AS
SELECT
    DATE_TRUNC('day', start_time) AS start_time,
    DATE_TRUNC('day', updated_ts) AS updated_ts,
    test_job_name,
    env_name,
    env_version,
    sprint,
    test_group,
    test_group_feature,
    test_scenario,
    auto_test_run_status,
    bugs,
    status,
    priority,
    assignee,
    fix_versions,
    components,
    labels,
    bug_category,
    bug_origin,
    customer_name,
    detected_version,
    scrum_team,
    scope_change,
    executed_test,
    qa_report,
    sprint_status,
    bug_resolved,
    SUM(total_scenarios) AS total_scenarios,
    SUM(passed_scenarios) AS passed_scenarios,
    SUM(failed_scenarios) AS failed_scenarios,
    SUM(open_bugs) AS open_bugs,
    SUM(closed_bugs) AS closed_bugs,
    SUM(resolution_days) AS resolution_days,
    SUM(total_execution_duration_min) AS total_execution_duration_min,
    SUM(total_bugs) AS total_bugs,
    SUM(regression_bugs) AS regression_bugs,
    SUM(critical_regression_bugs) AS critical_regression_bugs,
    SUM(open_regression_bugs) AS open_regression_bugs,
    SUM(closed_regression_bugs) AS closed_regression_bugs,
    SUM(customer_regression_bugs) AS customer_regression_bugs
FROM _stg_qa_report_hour
GROUP BY
    DATE_TRUNC('day', start_time),
    DATE_TRUNC('day', updated_ts),
    test_job_name,
    env_name,
    env_version,
    sprint,
    test_group,
    test_group_feature,
    test_scenario,
    auto_test_run_status,
    bugs,
    status,
    priority,
    assignee,
    fix_versions,
    components,
    labels,
    bug_category,
    bug_origin,
    customer_name,
    detected_version,
    scrum_team,
    scope_change,
    executed_test,
    qa_report,
    sprint_status,
    bug_resolved;

DELETE FROM ${target_schema}.${target_table_5min}
WHERE '${period_start}' = '__ALL__'
     OR (
             start_time >= '${period_start}'::TIMESTAMP
             AND start_time < '${period_end}'::TIMESTAMP
     );

DELETE FROM ${target_schema}.${target_table_hour}
WHERE '${period_start}' = '__ALL__'
     OR (
             start_time >= DATE_TRUNC('hour', '${period_start}'::TIMESTAMP)
             AND start_time < DATE_TRUNC('hour', '${period_end}'::TIMESTAMP)
     );

DELETE FROM ${target_schema}.${target_table_day}
WHERE '${period_start}' = '__ALL__'
     OR (
             start_time >= DATE_TRUNC('day', '${period_start}'::TIMESTAMP)
             AND start_time < DATE_TRUNC('day', '${period_end}'::TIMESTAMP)
     );

INSERT INTO ${target_schema}.${target_table_5min} (
    start_time, updated_ts, test_job_name, env_name, env_version, sprint,
    test_group, test_group_feature, test_scenario, auto_test_run_status,
    bugs, status, priority, assignee, fix_versions, components, labels,
    bug_category, bug_origin, customer_name, detected_version, scrum_team,
    scope_change, executed_test, qa_report, sprint_status, bug_resolved,
    total_scenarios, passed_scenarios, failed_scenarios, open_bugs, closed_bugs,
    resolution_days, total_execution_duration_min, total_bugs, regression_bugs,
    critical_regression_bugs, open_regression_bugs, closed_regression_bugs,
    customer_regression_bugs, last_updated_at
)
SELECT
    start_time, updated_ts, test_job_name, env_name, env_version, sprint,
    test_group, test_group_feature, test_scenario, auto_test_run_status,
    bugs, status, priority, assignee, fix_versions, components, labels,
    bug_category, bug_origin, customer_name, detected_version, scrum_team,
    scope_change, executed_test, qa_report, sprint_status, bug_resolved,
    total_scenarios, passed_scenarios, failed_scenarios, open_bugs, closed_bugs,
    resolution_days, total_execution_duration_min, total_bugs, regression_bugs,
    critical_regression_bugs, open_regression_bugs, closed_regression_bugs,
    customer_regression_bugs, CURRENT_TIMESTAMP
FROM _stg_qa_report_5m;

INSERT INTO ${target_schema}.${target_table_hour} (
    start_time, updated_ts, test_job_name, env_name, env_version, sprint,
    test_group, test_group_feature, test_scenario, auto_test_run_status,
    bugs, status, priority, assignee, fix_versions, components, labels,
    bug_category, bug_origin, customer_name, detected_version, scrum_team,
    scope_change, executed_test, qa_report, sprint_status, bug_resolved,
    total_scenarios, passed_scenarios, failed_scenarios, open_bugs, closed_bugs,
    resolution_days, total_execution_duration_min, total_bugs, regression_bugs,
    critical_regression_bugs, open_regression_bugs, closed_regression_bugs,
    customer_regression_bugs, last_updated_at
)
SELECT
    start_time, updated_ts, test_job_name, env_name, env_version, sprint,
    test_group, test_group_feature, test_scenario, auto_test_run_status,
    bugs, status, priority, assignee, fix_versions, components, labels,
    bug_category, bug_origin, customer_name, detected_version, scrum_team,
    scope_change, executed_test, qa_report, sprint_status, bug_resolved,
    total_scenarios, passed_scenarios, failed_scenarios, open_bugs, closed_bugs,
    resolution_days, total_execution_duration_min, total_bugs, regression_bugs,
    critical_regression_bugs, open_regression_bugs, closed_regression_bugs,
    customer_regression_bugs, CURRENT_TIMESTAMP
FROM _stg_qa_report_hour;

INSERT INTO ${target_schema}.${target_table_day} (
    start_time, updated_ts, test_job_name, env_name, env_version, sprint,
    test_group, test_group_feature, test_scenario, auto_test_run_status,
    bugs, status, priority, assignee, fix_versions, components, labels,
    bug_category, bug_origin, customer_name, detected_version, scrum_team,
    scope_change, executed_test, qa_report, sprint_status, bug_resolved,
    total_scenarios, passed_scenarios, failed_scenarios, open_bugs, closed_bugs,
    resolution_days, total_execution_duration_min, total_bugs, regression_bugs,
    critical_regression_bugs, open_regression_bugs, closed_regression_bugs,
    customer_regression_bugs, last_updated_at
)
SELECT
    start_time, updated_ts, test_job_name, env_name, env_version, sprint,
    test_group, test_group_feature, test_scenario, auto_test_run_status,
    bugs, status, priority, assignee, fix_versions, components, labels,
    bug_category, bug_origin, customer_name, detected_version, scrum_team,
    scope_change, executed_test, qa_report, sprint_status, bug_resolved,
    total_scenarios, passed_scenarios, failed_scenarios, open_bugs, closed_bugs,
    resolution_days, total_execution_duration_min, total_bugs, regression_bugs,
    critical_regression_bugs, open_regression_bugs, closed_regression_bugs,
    customer_regression_bugs, CURRENT_TIMESTAMP
FROM _stg_qa_report_day;
