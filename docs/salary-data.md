# Support member salaries

Add one row per salary change. `effective_from` controls which salary applies to work logged on or after that date; older facts remain unchanged.

```sql
INSERT INTO support_member_salaries
  (user_id, effective_from, annual_salary, currency, annual_working_hours, display_name)
VALUES
  ('5f3e91cf6db35e0039630ee8', '2026-01-01', 50000.00, 'GBP', 2080, 'Tom Dootson');
```

Salary view: `grafana_support_salary_costs`.

Tempo Account is treated as customer dimension. Account key/name populate customer fields in Grafana views; Tempo Customer records are not required.

Migration seeds Tom Dootson's Atlassian account `5f3e91cf6db35e0039630ee8`:

- 2022-08-01: £38,000
- 2023-12-15: £39,200
- 2024-07-01: £50,000
