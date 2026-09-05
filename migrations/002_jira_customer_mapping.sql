ALTER TABLE jira_issue_details ADD COLUMN IF NOT EXISTS customer text;

CREATE TABLE IF NOT EXISTS jira_issue_customers (
  issue_id text NOT NULL,
  customer text NOT NULL,
  PRIMARY KEY (issue_id, customer)
);
CREATE INDEX IF NOT EXISTS jira_issue_customers_customer_idx
  ON jira_issue_customers(customer);

CREATE OR REPLACE VIEW grafana_support_hours_by_jira_organisation AS
SELECT date_trunc('month', w.worklog_date)::date month_start,
       w.author_id atlassian_user_id,
       CASE WHEN j.project_key = 'CO'
            THEN COALESCE(j.customer, 'Unassigned')
            ELSE COALESCE(j.organisation, 'Unassigned')
       END organisation,
       SUM(w.seconds) / 3600.0 AS hours,
       SUM(w.billable_seconds) / 3600.0 AS billable_hours,
       SUM(w.seconds) AS effort_seconds,
       SUM(w.billable_seconds) AS billable_seconds
FROM worklog_facts w
LEFT JOIN jira_issue_details j ON j.issue_id = w.issue_id
GROUP BY 1,2,3;

CREATE OR REPLACE VIEW grafana_cost_by_jira_ticket AS
SELECT w.tempo_id AS tempo_worklog_id,
       w.issue_id AS jira_issue_id,
       j.issue_key AS jira_ticket,
       CASE WHEN j.project_key = 'CO'
            THEN COALESCE(j.customer, 'Unassigned')
            ELSE COALESCE(j.organisation, 'Unassigned')
       END AS organisation,
       w.author_id AS atlassian_user_id,
       COALESCE(s.display_name, w.author_id) AS support_member,
       w.worklog_date,
       w.seconds / 3600.0 AS hours,
       w.billable_seconds / 3600.0 AS billable_hours,
       s.currency,
       s.annual_salary,
       w.seconds / 3600.0 * s.annual_salary / s.annual_working_hours AS salary_cost
FROM worklog_facts w
LEFT JOIN jira_issue_details j ON j.issue_id = w.issue_id
LEFT JOIN LATERAL (SELECT * FROM support_member_salaries s0
                   WHERE s0.user_id=w.author_id AND s0.effective_from <= w.worklog_date
                   ORDER BY s0.effective_from DESC LIMIT 1) s ON true;
