WITH approved_runs AS (
    SELECT *
    FROM omniq.qa_agg_test_fact
    WHERE "Custom field (Automation Test Run Approved)" = 'Yes'
),
test_cases as (
	SELECT NULLIF(COUNT(qat."Issue key"), 0) as Total_Test
	FROM omniq.qa_test_created qat
)
SELECT
	/* Automations Columns */
	TRUNC("Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Created"), 5) as START_TIME,
	"Updated" as Updated,
	"Custom field (Job Name)" As Test_Job_Name,
	"Custom field (Job Stack Prefix)" As Env_Name,
	"Custom field (Job Stack Version)" As Env_Version,
	Sprint,
	"Test Group",
	"Test Group Feature",
	"Test Scenario",
	"Auto Test Run Status",
	/* Defects Columns */
	Bugs,
	Status,
	Priority,
	Assignee,
	"Fix Version/s",
	"Component/s",
	Labels,
	"Bug Category",
	"Bug Origin",
	"Customer/s Name",
	"Detected Version",
	"Scrum Team",
	"Scope Change",
	/* Test Execution */
	"Executed Test",
	'Automation' As QA_Report,
	NULL as "Sprint Status",
	NULL as "Bug Resolved",
	/* Scenario Execution */
	SUM("No of Test Scenario") AS total_scenarios,
	/* Pass / Fail */
	SUM("Pass Test Scenario") AS passed_scenarios,
	SUM("Failed Test Scenario") AS failed_scenarios,
	/* Defects */
	SUM("Open Bugs") AS "Open Bugs",
	SUM("Closed Bugs") AS "Closed Bugs",
	/* Resolution */
	SUM("Resolution Days") AS "Resolution Days",
	/* Execution Time */
	ROUND(SUM("Executed Test Duration (Minutes)"), 2) AS total_execution_duration_min,
	/* Executive Quality Score */
	
    TO_NUMBER(NULL) AS total_bugs,
	TO_NUMBER(NULL) AS regression_bugs,
	TO_NUMBER(NULL) AS critical_regression_bugs,
	TO_NUMBER(NULL) AS open_regression_bugs,
	TO_NUMBER(NULL) AS closed_regression_bugs,
	TO_NUMBER(NULL) AS customer_regression_bugs
FROM
	approved_runs qaaut
Group BY
	TRUNC("Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Created"), 5),
	"Updated",
	"Custom field (Job Name)",
	"Custom field (Job Stack Prefix)",
	"Custom field (Job Stack Version)",
	Sprint,
	"Test Group",
	"Test Group Feature",
	"Test Scenario",
	"Auto Test Run Status",
	Bugs,
	Status,
	Priority,
	Assignee,
	"Fix Version/s",
	"Component/s",
	Labels,
	"Bug Category",
	"Bug Origin",
	"Customer/s Name",
	"Detected Version",
	"Scrum Team",
	"Scope Change",
	"Executed Test"
	
UNION

SELECT
	TRUNC("Bug Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Bug Created"), 5) as START_TIME,
	"Bug Updated" as "Bug Updated",
	NULL AS Test_Job_Name,
	NULL AS Env_Name,
	NULL AS Env_Version,
	Sprint,
	NULL AS "Test Group",
	NULL AS "Test Group Feature",
	NULL AS "Test Scenario",
	NULL AS "Auto Test Run Status",
	Bugs,
	Status,
	Priority,
	Assignee,
	"Fix Version/s",
	"Component/s",
	Labels,
	"Bug Category",
	"Bug Origin",
	"Customer/s Name",
	"Detected Version",
	"Scrum Team",
	"Scope Change",
	NULL AS "Executed Test",
	'Defects' As QA_Report,
	"Sprint Status",
	"Bug Resolved",
	TO_NUMBER(NULL) AS total_scenarios,
	TO_NUMBER(NULL) AS passed_scenarios,
	TO_NUMBER(NULL) AS failed_scenarios,
	TO_NUMBER(NULL) AS "Open Bugs",
	TO_NUMBER(NULL) AS "Closed Bugs",
	TO_NUMBER(NULL) AS "Resolution Days",
	TO_NUMBER(NULL) AS total_execution_duration_min,
	COUNT(*) AS total_bugs,
	COUNT(CASE WHEN "Bug Category" = 'Regression' THEN Bugs END) AS regression_bugs,
	COUNT(CASE WHEN "Bug Category" = 'Regression' AND Priority IN ('Blocker','Critical') THEN Bugs END) AS critical_regression_bugs,
	COUNT(CASE WHEN "Bug Category" = 'Regression' AND Status NOT IN ('Closed','Integrated', 'Rejected') THEN Bugs END) AS open_regression_bugs,
	COUNT(CASE WHEN "Bug Category" = 'Regression' AND Status IN ('Closed','Integrated', 'Rejected') THEN Bugs END) AS closed_regression_bugs,
	COUNT(CASE WHEN "Bug Category" = 'Regression' AND "Bug Origin" IN ('Customer','PSO', 'POC') THEN Bugs END) AS customer_regression_bugs
FROM
	omniq.qa_defect_dim
Group By
	TRUNC("Bug Created", 'MI') - INTERVAL '1 minute' * MOD(EXTRACT(MINUTE FROM "Bug Created"), 5),
	"Bug Updated",
	Sprint,
	Bugs,
	Status,
	Priority,
	Assignee,
	"Fix Version/s",
	"Component/s",
	Labels,
	"Bug Category",
	"Bug Origin",
	"Customer/s Name",
	"Detected Version",
	"Scrum Team",
	"Scope Change",
	"Sprint Status",
	"Bug Resolved"