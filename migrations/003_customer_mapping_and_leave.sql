ALTER TABLE jira_issue_details ADD COLUMN IF NOT EXISTS canonical_customer text;
ALTER TABLE jira_issue_details ADD COLUMN IF NOT EXISTS work_category text NOT NULL DEFAULT 'support';

CREATE TABLE IF NOT EXISTS jira_customer_mappings (
  source_value text PRIMARY KEY,
  canonical_customer text NOT NULL,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS jira_leave_issues (
  issue_key text PRIMARY KEY,
  description text,
  active boolean NOT NULL DEFAULT true
);

INSERT INTO jira_customer_mappings (source_value, canonical_customer) VALUES
  ('Marks and Spencer', 'Marks and Spencer'), ('M&S', 'Marks and Spencer'),
  ('Marks and Spencer MM', 'Marks and Spencer'), ('MANDS', 'Marks and Spencer'),
  ('Wincanton', 'Wincanton'), ('WincantonCityPlumbing', 'Wincanton'),
  ('WincantonDobbies', 'Wincanton'), ('WincantonHomebase', 'Wincanton'),
  ('WincantonSnug', 'Wincanton'), ('Cygnia', 'Wincanton'), ('Clipper', 'Wincanton')
ON CONFLICT (source_value) DO UPDATE SET canonical_customer=EXCLUDED.canonical_customer, active=true;

INSERT INTO jira_leave_issues (issue_key, description) VALUES
  ('CS-259', 'Support team holiday/leave tracking')
ON CONFLICT (issue_key) DO UPDATE SET description=EXCLUDED.description, active=true;

CREATE OR REPLACE VIEW grafana_support_hours_by_jira_organisation AS
SELECT date_trunc('month', w.worklog_date)::date month_start,
       w.author_id atlassian_user_id,
       CASE WHEN j.work_category = 'leave' THEN 'Leave'
            WHEN j.canonical_customer IS NOT NULL THEN j.canonical_customer
            WHEN j.project_key = 'CO' THEN COALESCE(j.customer, 'Unassigned')
            ELSE COALESCE(j.organisation, 'Unassigned') END organisation,
       SUM(w.seconds) / 3600.0 AS hours,
       SUM(w.billable_seconds) / 3600.0 AS billable_hours,
       SUM(w.seconds) AS effort_seconds,
       SUM(w.billable_seconds) AS billable_seconds
FROM worklog_facts w
LEFT JOIN jira_issue_details j ON j.issue_id = w.issue_id
GROUP BY 1,2,3;

CREATE OR REPLACE VIEW grafana_cost_by_jira_ticket AS
SELECT w.tempo_id AS tempo_worklog_id, w.issue_id AS jira_issue_id,
       j.issue_key AS jira_ticket,
       CASE WHEN j.work_category = 'leave' THEN 'Leave'
            WHEN j.canonical_customer IS NOT NULL THEN j.canonical_customer
            WHEN j.project_key = 'CO' THEN COALESCE(j.customer, 'Unassigned')
            ELSE COALESCE(j.organisation, 'Unassigned') END AS organisation,
       COALESCE(j.work_category, 'unassigned') AS work_category,
       j.customer AS raw_customer, j.organisation AS raw_organisation,
       w.author_id AS atlassian_user_id,
       COALESCE(s.display_name, w.author_id) AS support_member,
       w.worklog_date, w.seconds / 3600.0 AS hours,
       w.billable_seconds / 3600.0 AS billable_hours,
       s.currency, s.annual_salary,
       CASE WHEN j.work_category = 'leave' THEN 0
            ELSE w.seconds / 3600.0 * s.annual_salary / s.annual_working_hours END AS salary_cost
FROM worklog_facts w
LEFT JOIN jira_issue_details j ON j.issue_id = w.issue_id
LEFT JOIN LATERAL (SELECT * FROM support_member_salaries s0
                   WHERE s0.user_id=w.author_id AND s0.effective_from <= w.worklog_date
                   ORDER BY s0.effective_from DESC LIMIT 1) s ON true;

CREATE OR REPLACE VIEW grafana_support_leave AS
SELECT * FROM grafana_cost_by_jira_ticket WHERE work_category = 'leave';
