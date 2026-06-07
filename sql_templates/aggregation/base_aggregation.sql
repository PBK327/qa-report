-- Base aggregation template
-- generated_at_utc=${generated_at_utc}

SELECT
  source_type,
  DATE_TRUNC('week', created_at) AS period,
  COUNT(*) AS total,
  SUM(CASE WHEN outcome = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
  SUM(CASE WHEN outcome = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
  ROUND(
    100.0 * SUM(CASE WHEN outcome = 'PASS' THEN 1 ELSE 0 END)
    / NULLIF(COUNT(*), 0),
    2
  ) AS pass_rate_pct
FROM ${table}
WHERE created_at >= DATE '${period_start}'
  AND created_at < DATE '${period_end}'
GROUP BY 1, 2
ORDER BY 2, 1;
