# Tempo Support Cost-to-Serve

Docker Compose worker that imports Tempo Support-team worklogs and Jira issues into PostgreSQL for Grafana reporting.

## Data flow

```text
Tempo worklog → Jira issue ID → Jira organisation/customer
             → Atlassian user → effective-dated salary → cost
```

Jira organisations and Tempo Accounts remain separate dimensions. Tempo Account data is retained independently.

Jira mapping defaults: `CAB` tickets use organisation `Sorted Group`; `CO` tickets use Jira customer field `customfield_10070`.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in Tempo and Jira credentials. Never commit `.env`.
3. Set `TEMPO_TEAM_ID` to the Support team ID.
4. Set matching `DATABASE_URL` and `POSTGRES_PASSWORD` values.
5. Set a strong `GRAFANA_DB_PASSWORD`.
6. Start the worker and database:

```bash
docker compose up -d --build
docker compose logs -f worker
```

PostgreSQL is bound to localhost by default. Grafana on the same host connects to `localhost:5432`; Grafana in the same Compose network connects to `postgres:5432`.

## Grafana views

Use the restricted `grafana_reader` user. It has SELECT access to reporting views only.

- `grafana_cost_by_jira_ticket`
- `grafana_cost_to_serve_monthly`
- `grafana_support_hours_by_jira_organisation`
- `grafana_support_hours_by_user_account`
- `grafana_support_salary_costs`
- `grafana_support_worklog`
- `grafana_sync_health`

## Salary history

Salary rows are keyed by Atlassian account ID and effective date. Add a new row for each salary change; do not update old rows. Initial Tom Dootson salary rows are seeded by the migration. See `docs/salary-data.md`.

## Validation

```bash
pytest -q
docker compose config --quiet
```

## Security

- Tempo and Jira access is read-only.
- Credentials are environment-only.
- Grafana receives a separate SELECT-only database role.
- Keep PostgreSQL localhost-only unless a private network and firewall rule are in place.
