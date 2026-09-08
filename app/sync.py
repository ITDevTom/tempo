import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from .config import Settings
from .db import upsert_raw
from .tempo_client import TempoClient
from .jira_client import JiraClient, field_names

log = logging.getLogger(__name__)


def _rewound_watermark(seconds: int) -> str:
    """Return safe replay watermark; duplicate rows are idempotent upserts."""
    value = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit_datetime(value: str) -> str:
    """Papertrail legacy endpoint rejects date-only updatedFrom values."""
    if "T" in value:
        return value.replace("+00:00", "Z")
    return f"{value}T00:00:00Z"


def _amount(obj: Any):
    return obj.get("value") if isinstance(obj, dict) else None


def sync_once(conn, client: TempoClient, settings: Settings):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sync_runs (started_at, status) VALUES (now(), 'running') RETURNING id")
        run_id = cur.fetchone()[0]
        cur.execute("SELECT value FROM sync_state WHERE key='worklogs_updated_from'")
        row = cur.fetchone()
        cur.execute("SELECT value FROM sync_state WHERE key='jira_updated_from'")
        jira_row = cur.fetchone()
        cur.execute("SELECT value FROM sync_state WHERE key='jira_scope'")
        jira_scope_row = cur.fetchone()
    updated_from = row[0] if row else settings.initial_from.isoformat()
    jira_updated_from = jira_row[0] if jira_row else settings.initial_from.isoformat()
    try:
        jira = JiraClient(settings.jira_domain, settings.jira_email, settings.jira_token)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT author_id FROM worklog_facts WHERE author_id IS NOT NULL")
            support_member_ids = {row[0] for row in cur.fetchall()}
        with conn.cursor() as cur:
            cur.execute("SELECT lower(source_value), canonical_customer FROM jira_customer_mappings WHERE active")
            customer_mappings = dict(cur.fetchall())
            cur.execute("SELECT issue_key FROM jira_leave_issues WHERE active")
            leave_issues = {row[0] for row in cur.fetchall()} | set(settings.jira_leave_issues)
            cur.execute("SELECT issue_key, work_category FROM jira_internal_issues WHERE active")
            internal_issues = dict(cur.fetchall())
            internal_issues.update({key: "internal_meeting" for key in settings.jira_internal_issues})
            internal_issues.update({key: "training" for key in settings.jira_training_issues})
        scope = f"{settings.jira_project or '*'}|cab-default-v1|co-customer-{settings.jira_customer_field}|customer-map-v1|leave-v1|internal-v1|training-v1"
        use_created = jira_row is None or not jira_scope_row or jira_scope_row[0] != scope
        for issue in jira.search_issues(since=settings.initial_from.isoformat() if use_created else jira_updated_from, project=settings.jira_project, organisation_field=settings.jira_organisation_field, customer_field=settings.jira_customer_field, use_created=use_created):
            fields = issue.get("fields", {})
            issue_id = str(issue.get("id"))
            project_key = (fields.get("project") or {}).get("key")
            org_names = field_names(fields.get(settings.jira_organisation_field))
            customer_names = field_names(fields.get(settings.jira_customer_field))
            if project_key == "CAB":
                org_names = [settings.jira_cab_organisation]
            if project_key == "CO":
                org_names = []
            issue_key = issue.get("key")
            raw_customer = customer_names[0] if customer_names else (org_names[0] if org_names else None)
            canonical_customer = customer_mappings.get((raw_customer or "").lower(), raw_customer)
            work_category = "leave" if issue_key in leave_issues else internal_issues.get(issue_key, "charged" if project_key == "CO" else "support")
            if work_category in {"leave", "internal_meeting", "training"}:
                org_names = []
                canonical_customer = None
            payload = {"id": issue_id, "key": issue.get("key"), "fields": fields}
            upsert_raw(conn, "jira_issues", issue_id, payload, source="/rest/api/3/search/jql")
            with conn.cursor() as cur:
                cur.execute("INSERT INTO jira_issue_details (issue_id, issue_key, project_key, organisation, customer, canonical_customer, work_category, payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (issue_id) DO UPDATE SET issue_key=EXCLUDED.issue_key, project_key=EXCLUDED.project_key, organisation=EXCLUDED.organisation, customer=EXCLUDED.customer, canonical_customer=EXCLUDED.canonical_customer, work_category=EXCLUDED.work_category, payload=EXCLUDED.payload, fetched_at=now()", (issue_id, issue_key, project_key, org_names[0] if org_names else None, customer_names[0] if customer_names else None, canonical_customer, work_category, json.dumps(payload)))
                cur.execute("DELETE FROM jira_issue_organisations WHERE issue_id=%s", (issue_id,))
                cur.executemany("INSERT INTO jira_issue_organisations (issue_id, organisation) VALUES (%s,%s)", [(issue_id, name) for name in org_names])
                cur.execute("DELETE FROM jira_issue_customers WHERE issue_id=%s", (issue_id,))
                cur.executemany("INSERT INTO jira_issue_customers (issue_id, customer) VALUES (%s,%s)", [(issue_id, name) for name in customer_names])
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_state(key,value) VALUES ('jira_updated_from', %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (_rewound_watermark(settings.overlap_seconds),))
            cur.execute("INSERT INTO sync_state(key,value) VALUES ('jira_scope', %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (scope,))
        # Dimensions. Legacy endpoints omit security metadata in spec, but bearer auth is still sent.
        for item in client.pages("/4/accounts"):
            upsert_raw(conn, "accounts", str(item.get("id") or item.get("key")), item, source="/4/accounts")
        for item in client.pages("/4/customers"):
            upsert_raw(conn, "customers", str(item.get("id") or item.get("key")), item, source="/4/customers")
        projects = list(client.pages("/4/projects"))
        for item in projects:
            upsert_raw(conn, "projects", str(item["id"]), item, source="/4/projects")
        for category in ("COST", "BILLING"):
            try:
                for item in client.request("/4/global-rates/by-role", {"rateCategory": category}).get("results", []):
                    for rate in item.get("rates", []):
                        rid = f"global:{category}:{item.get('roleId')}:{rate.get('effectiveDate') or 'default'}"
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO rates (tempo_id,rate_category,effective_date,value,payload,source) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (tempo_id) DO UPDATE SET effective_date=EXCLUDED.effective_date,value=EXCLUDED.value,payload=EXCLUDED.payload,fetched_at=now()", (rid,category,rate.get('effectiveDate'),rate.get('value'),json.dumps(rate), "/4/global-rates/by-role"))
            except Exception as exc:
                log.warning("global %s rate fetch failed: %s", category, exc)
        team_members = list(client.pages(f"/4/teams/{settings.team_id}/members"))
        for item in team_members:
            user = item.get("member", item)
            uid = user.get("accountId") or user.get("id") or user.get("tempoId")
            if uid:
                upsert_raw(conn, "users", str(uid), user, source="/4/teams/{id}/members")
        support_worklog_ids = set()
        for item in client.pages(f"/4/worklogs/team/{settings.team_id}", {"updatedFrom": updated_from, "orderBy": "UPDATED"}):
            if settings.redact_descriptions:
                item = dict(item); item.pop("description", None)
            wid = str(item["tempoWorklogId"])
            support_worklog_ids.add(wid)
            upsert_raw(conn, "worklogs", wid, item, source="/4/worklogs/team/{id}")
            author_id = (item.get("author") or {}).get("accountId")
            if author_id:
                support_member_ids.add(author_id)
            with conn.cursor() as cur:
                cur.execute("INSERT INTO worklog_facts (tempo_id, worklog_date, seconds, billable_seconds, author_id, issue_id, project_id, payload) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tempo_id) DO UPDATE SET worklog_date=EXCLUDED.worklog_date, seconds=EXCLUDED.seconds, billable_seconds=EXCLUDED.billable_seconds, issue_id=EXCLUDED.issue_id, project_id=EXCLUDED.project_id, payload=EXCLUDED.payload",
                            (wid, item.get("startDate"), item.get("timeSpentSeconds", 0), item.get("billableSeconds", 0),
                             author_id, (item.get("issue") or {}).get("id"), (item.get("issue") or {}).get("projectId"), json.dumps(item)))
        log.info("looking up support-member names: candidates=%d", len(support_member_ids))
        resolved_members = 0
        failed_member_lookups = 0
        for account_id in sorted(support_member_ids):
            with conn.cursor() as cur:
                cur.execute("SELECT payload->>'displayName' FROM users WHERE tempo_id=%s", (account_id,))
                row = cur.fetchone()
            if row and row[0]:
                resolved_members += 1
                continue
            try:
                user = jira.get_user(account_id)
                upsert_raw(conn, "users", account_id, user, source="/rest/api/3/user")
                if user.get("displayName"):
                    resolved_members += 1
                else:
                    failed_member_lookups += 1
            except Exception as exc:
                failed_member_lookups += 1
                log.warning("support-member lookup failed for %s: %s", account_id, exc)
        log.info("support-member names resolved: resolved=%d failed=%d", resolved_members, failed_member_lookups)
        # Financial project facts have no updatedFrom filter in this API; upsert all pages each run.
        for project in projects:
            pid = str(project["id"])
            try:
                rate_payload = client.request(f"/4/projects/{pid}/team-members/rates")
                for member_rate in rate_payload.get("rates", []):
                    member = member_rate.get("teamMember", {})
                    member_id = member.get("accountId") or member.get("id") or "unknown"
                    for category, rates in (("cost", member_rate.get("costRates", {}).get("values", [])), ("billing", member_rate.get("billingRates", {}).get("values", []))):
                        for rate in rates:
                            effective = rate.get("effectiveDate")
                            rid = f"project:{pid}:{member_id}:{category}:{effective or 'default'}"
                            with conn.cursor() as cur:
                                cur.execute("INSERT INTO rates (tempo_id,project_id,rate_category,effective_date,value,payload,source) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tempo_id) DO UPDATE SET effective_date=EXCLUDED.effective_date,value=EXCLUDED.value,payload=EXCLUDED.payload,fetched_at=now()", (rid,pid,category,effective, _amount(rate.get('rate', rate)), json.dumps(rate), "/4/projects/{id}/team-members/rates"))
            except Exception as exc:
                log.warning("rate fetch failed for project %s: %s", pid, exc)
            for item in client.pages(f"/4/projects/{pid}/actuals/labor", {"to": settings.initial_to.isoformat() if settings.initial_to else None}):
                tid = str(item.get("timeRecordId") or f"{pid}:{item.get('worklogId')}:{item.get('date')}")
                # Tempo exposes actual labor by project, not by team. Keep only
                # records belonging to Support worklogs.
                if str(item.get("worklogId")) not in support_worklog_ids:
                    continue
                upsert_raw(conn, "labor_actuals", tid, item, source="/4/projects/{id}/actuals/labor")
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO labor_facts (tempo_id, project_id, worklog_id, user_id, fact_date, seconds, cost, revenue, payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tempo_id) DO UPDATE SET user_id=EXCLUDED.user_id,seconds=EXCLUDED.seconds,cost=EXCLUDED.cost,revenue=EXCLUDED.revenue,payload=EXCLUDED.payload",
                                (tid, pid, item.get("worklogId"), (item.get("user") or {}).get("accountId"), item.get("date"), item.get("timeSpentSeconds", 0), _amount(item.get("cost")), _amount(item.get("revenue")), json.dumps(item)))
            for item in client.pages(f"/4/projects/{pid}/actuals/expenses", {"to": settings.initial_to.isoformat() if settings.initial_to else None}):
                eid = str((item.get("expense") or {}).get("id") or f"{pid}:{item.get('date')}:{item.get('cost')}")
                upsert_raw(conn, "expense_actuals", eid, item, source="/4/projects/{id}/actuals/expenses")
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO expense_facts (tempo_id, project_id, fact_date, amount, payload) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tempo_id) DO UPDATE SET amount=EXCLUDED.amount,payload=EXCLUDED.payload",
                                (eid, pid, item.get("date"), _amount(item.get("cost")), json.dumps(item)))
        audit_params = {"updatedFrom": _audit_datetime(updated_from), "limit": 50}
        while True:
            audit_page = client.request("/papertrail/1/events/deleted/types/worklog", audit_params)
            for item in audit_page.get("results", []):
                did = str(item.get("tempoWorklogId") or item.get("jiraWorklogId"))
                upsert_raw(conn, "deletions", did, item, source="/papertrail/1/events/deleted/types/worklog")
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO deleted_worklogs (tempo_id, deleted_at, payload) VALUES (%s,%s,%s) ON CONFLICT (tempo_id) DO UPDATE SET deleted_at=EXCLUDED.deleted_at,payload=EXCLUDED.payload", (did, item.get("deletedAt"), json.dumps(item)))
            audit_meta = audit_page.get("metadata", {}) or {}
            last_key = audit_meta.get("lastEvaluatedKey")
            if not last_key:
                break
            audit_params["lastEvaluatedKey"] = last_key
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_state(key,value) VALUES ('worklogs_updated_from', %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (_rewound_watermark(settings.overlap_seconds),))
            cur.execute("UPDATE sync_runs SET finished_at=now(), status='success' WHERE id=%s", (run_id,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE sync_runs SET finished_at=now(), status='failed', error=%s WHERE id=%s", (str(exc), run_id))
        conn.commit()
        raise
