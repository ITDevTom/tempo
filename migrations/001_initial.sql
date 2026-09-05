CREATE TABLE IF NOT EXISTS sync_runs (
  id bigserial PRIMARY KEY, started_at timestamptz NOT NULL, finished_at timestamptz,
  status text NOT NULL, error text
);
CREATE TABLE IF NOT EXISTS sync_state (key text PRIMARY KEY, value text NOT NULL);

CREATE TABLE IF NOT EXISTS accounts (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS customers (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jira_issues (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jira_issue_details (issue_id text PRIMARY KEY, issue_key text, project_key text, organisation text, payload jsonb NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS jira_issue_organisations (issue_id text NOT NULL, organisation text NOT NULL, PRIMARY KEY (issue_id, organisation));
CREATE INDEX IF NOT EXISTS jira_issue_organisations_org_idx ON jira_issue_organisations(organisation);
CREATE TABLE IF NOT EXISTS projects (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS users (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS worklogs (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS labor_actuals (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS expense_actuals (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS rates (tempo_id text PRIMARY KEY, project_id text, rate_category text, effective_date date, value numeric, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS deletions (tempo_id text PRIMARY KEY, payload jsonb NOT NULL, source text NOT NULL, fetched_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS worklog_facts (
  tempo_id text PRIMARY KEY, worklog_date date, seconds bigint NOT NULL DEFAULT 0,
  billable_seconds bigint NOT NULL DEFAULT 0, author_id text, issue_id text, project_id text, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS worklog_facts_date_idx ON worklog_facts(worklog_date);
CREATE TABLE IF NOT EXISTS labor_facts (
  tempo_id text PRIMARY KEY, project_id text, worklog_id bigint, user_id text, fact_date date,
  seconds bigint NOT NULL DEFAULT 0, cost numeric, revenue numeric, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS labor_facts_date_idx ON labor_facts(fact_date);
ALTER TABLE labor_facts ADD COLUMN IF NOT EXISTS user_id text;
ALTER TABLE worklog_facts ADD COLUMN IF NOT EXISTS issue_id text;
CREATE TABLE IF NOT EXISTS expense_facts (
  tempo_id text PRIMARY KEY, project_id text, fact_date date, amount numeric, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS expense_facts_date_idx ON expense_facts(fact_date);
CREATE TABLE IF NOT EXISTS deleted_worklogs (
  tempo_id text PRIMARY KEY, deleted_at timestamptz, payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS support_member_salaries (
  user_id text NOT NULL, effective_from date NOT NULL, annual_salary numeric(14,2) NOT NULL CHECK (annual_salary >= 0),
  currency char(3) NOT NULL DEFAULT 'GBP', annual_working_hours numeric(8,2) NOT NULL DEFAULT 2080 CHECK (annual_working_hours > 0),
  display_name text NOT NULL, notes text, PRIMARY KEY (user_id, effective_from)
);
CREATE INDEX IF NOT EXISTS support_member_salaries_lookup_idx ON support_member_salaries(user_id, effective_from DESC);
INSERT INTO support_member_salaries (user_id, effective_from, annual_salary, currency, annual_working_hours, display_name, notes)
VALUES
  ('5f3e91cf6db35e0039630ee8', '2022-08-01', 38000.00, 'GBP', 2080, 'Tom Dootson', 'Initial salary seed'),
  ('5f3e91cf6db35e0039630ee8', '2023-12-15', 39200.00, 'GBP', 2080, 'Tom Dootson', 'Salary change'),
  ('5f3e91cf6db35e0039630ee8', '2024-07-01', 50000.00, 'GBP', 2080, 'Tom Dootson', 'Salary change')
ON CONFLICT (user_id, effective_from) DO UPDATE
SET annual_salary=EXCLUDED.annual_salary, currency=EXCLUDED.currency,
    annual_working_hours=EXCLUDED.annual_working_hours, display_name=EXCLUDED.display_name,
    notes=EXCLUDED.notes;

CREATE OR REPLACE VIEW grafana_support_worklog AS
SELECT w.tempo_id, w.worklog_date, w.seconds, w.billable_seconds, w.author_id, w.project_id,
       w.payload->'issue'->>'key' AS issue_key,
       p.payload->>'name' AS project_name,
       a.payload->>'key' AS account_key, a.payload->>'name' AS account_name,
       a.payload->>'key' AS customer_key, a.payload->>'name' AS customer_name
FROM worklog_facts w
LEFT JOIN projects p ON p.tempo_id = w.project_id
LEFT JOIN accounts a ON a.tempo_id = COALESCE(p.payload->'account'->>'id', p.payload->'account'->>'key')
                     OR a.payload->>'key' = p.payload->'account'->>'key'
;

CREATE OR REPLACE VIEW grafana_cost_to_serve_monthly AS
WITH labor AS (
  SELECT date_trunc('month', l.fact_date)::date month_start, l.project_id,
         SUM(l.seconds) effort_seconds, SUM(COALESCE(l.cost,0)) labor_cost,
         SUM(COALESCE(l.revenue,0)) revenue
  FROM labor_facts l
  GROUP BY 1,2
), expenses AS (
  SELECT date_trunc('month', e.fact_date)::date month_start, e.project_id, SUM(COALESCE(e.amount,0)) expense_cost
  FROM expense_facts e GROUP BY 1,2
)
SELECT COALESCE(l.month_start,e.month_start) month_start, COALESCE(l.project_id,e.project_id) project_id,
       p.payload->>'name' project_name,
       COALESCE(p.payload->'account'->>'key', p.payload->'account'->>'id', 'unattributed') account_key,
       COALESCE(a.payload->>'name','Unattributed') account_name,
       COALESCE(a.payload->>'key','unattributed') customer_key,
       COALESCE(a.payload->>'name','Unattributed') customer_name,
       COALESCE(l.effort_seconds,0) effort_seconds, COALESCE(l.labor_cost,0) labor_cost,
       COALESCE(e.expense_cost,0) expense_cost, COALESCE(l.labor_cost,0)+COALESCE(e.expense_cost,0) cost_to_serve,
       COALESCE(l.revenue,0) revenue
FROM labor l FULL OUTER JOIN expenses e ON e.month_start=l.month_start AND e.project_id=l.project_id
LEFT JOIN projects p ON p.tempo_id=COALESCE(l.project_id,e.project_id)
LEFT JOIN accounts a ON a.tempo_id=COALESCE(p.payload->'account'->>'id',p.payload->'account'->>'key')
                     OR a.payload->>'key'=p.payload->'account'->>'key'
;

CREATE OR REPLACE VIEW grafana_support_salary_costs AS
SELECT date_trunc('month', w.worklog_date)::date month_start, w.author_id user_id,
       s.display_name, s.currency, s.annual_salary, s.annual_working_hours,
       SUM(w.seconds) effort_seconds,
       SUM(w.seconds) / 3600.0 * s.annual_salary / s.annual_working_hours AS salary_cost
FROM worklog_facts w
JOIN LATERAL (SELECT * FROM support_member_salaries s0
              WHERE s0.user_id=w.author_id AND s0.effective_from <= w.worklog_date
              ORDER BY s0.effective_from DESC LIMIT 1) s ON true
GROUP BY 1,2,3,4,5,6;

CREATE OR REPLACE VIEW grafana_support_hours_by_user_account AS
SELECT date_trunc('month', w.worklog_date)::date month_start,
       w.author_id atlassian_user_id,
       COALESCE(a.payload->>'key', 'unattributed') account_key,
       COALESCE(a.payload->>'name', 'Unattributed') account_name,
       SUM(w.seconds) / 3600.0 AS hours,
       SUM(w.billable_seconds) / 3600.0 AS billable_hours,
       SUM(w.seconds) AS effort_seconds,
       SUM(w.billable_seconds) AS billable_seconds
FROM worklog_facts w
LEFT JOIN projects p ON p.tempo_id = w.project_id
LEFT JOIN accounts a ON a.tempo_id = COALESCE(p.payload->'account'->>'id', p.payload->'account'->>'key')
                     OR a.payload->>'key' = p.payload->'account'->>'key'
GROUP BY 1,2,3,4;

CREATE OR REPLACE VIEW grafana_support_hours_by_jira_organisation AS
SELECT date_trunc('month', w.worklog_date)::date month_start,
       w.author_id atlassian_user_id,
       COALESCE(j.organisation, 'Unassigned') organisation,
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
       COALESCE(j.organisation, 'Unassigned') AS organisation,
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

CREATE OR REPLACE VIEW grafana_sync_health AS
SELECT r.id, r.started_at, r.finished_at, r.status, r.error,
       (SELECT max(fetched_at) FROM worklogs) AS latest_worklog_fetch,
       (SELECT count(*) FROM worklog_facts) AS worklog_count,
       (SELECT count(*) FROM labor_facts) AS labor_fact_count
FROM sync_runs r;
