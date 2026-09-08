import json
import logging
import os
from pathlib import Path
import psycopg
from psycopg import sql

log = logging.getLogger(__name__)


def connect():
    return psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://tempo:tempo@postgres:5432/tempo"))


def migrate(conn):
    migration_dir = Path(__file__).parent.parent / "migrations"
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        for path in sorted(migration_dir.glob("*.sql")):
            version = path.name
            if version in applied:
                continue
            cur.execute(path.read_text())
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
    conn.commit()


def configure_grafana_reader(conn):
    user = os.environ.get("GRAFANA_DB_USER", "grafana_reader")
    password = os.environ.get("GRAFANA_DB_PASSWORD", "")
    if not password:
        log.warning("GRAFANA_DB_PASSWORD is not configured; Grafana reader role was not created")
        return
    views = [
        "grafana_support_worklog",
        "grafana_cost_to_serve_monthly",
        "grafana_support_salary_costs",
        "grafana_support_hours_by_user_account",
        "grafana_support_hours_by_jira_organisation",
        "grafana_cost_by_jira_ticket",
        "grafana_sync_health",
        "grafana_support_leave",
        "grafana_support_internal",
    ]
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DO $$ BEGIN CREATE ROLE {} LOGIN PASSWORD {}; EXCEPTION WHEN duplicate_object THEN NULL; END $$").format(sql.Identifier(user), sql.Literal(password)))
        cur.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(user), sql.Literal(password)))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {};").format(sql.Identifier(user)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {};").format(sql.Identifier("tempo"), sql.Identifier(user)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {};").format(sql.Identifier(user)))
        cur.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {};").format(sql.Identifier(user)))
        for view in views:
            cur.execute(sql.SQL("GRANT SELECT ON TABLE public.{} TO {};").format(sql.Identifier(view), sql.Identifier(user)))
    conn.commit()


def upsert_raw(conn, table: str, key: str, payload: dict, *, source: str):
    # Table names are internal constants, never user input.
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {table} (tempo_id, payload, source) VALUES (%s, %s, %s) "
                    f"ON CONFLICT (tempo_id) DO UPDATE SET payload=EXCLUDED.payload, source=EXCLUDED.source, fetched_at=now()",
                    (key, json.dumps(payload), source))
