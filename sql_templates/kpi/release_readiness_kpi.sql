-- Release readiness KPI template
-- generated_at_utc=${generated_at_utc}

WITH agg AS (
  SELECT
    DATE_TRUNC('week', created_at) AS period,
    COUNT(*) AS total_tests,
    SUM(CASE WHEN outcome = 'PASS' THEN 1 ELSE 0 END) AS passed_tests,
    SUM(CASE WHEN source_type = 'defect' AND status = 'Open' THEN 1 ELSE 0 END) AS open_defects,
    SUM(CASE WHEN source_type = 'defect' AND severity = 'Critical' THEN 1 ELSE 0 END) AS critical_defects
  FROM ${table}
  WHERE created_at >= DATE '${period_start}'
    AND created_at < DATE '${period_end}'
  GROUP BY 1
)
SELECT
  period,
  total_tests,
  passed_tests,
  ROUND(100.0 * passed_tests / NULLIF(total_tests, 0), 2) AS pass_rate_pct,
  open_defects,
  critical_defects,
  CASE
    WHEN critical_defects = 0 AND open_defects <= 5 AND passed_tests >= total_tests * 0.95 THEN 'GO'
    WHEN critical_defects <= 1 AND open_defects <= 15 THEN 'CONDITIONAL_GO'
    ELSE 'NO_GO'
  END AS release_recommendation
FROM agg
ORDER BY period;
