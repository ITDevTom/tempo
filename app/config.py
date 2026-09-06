from dataclasses import dataclass
from datetime import date
import os


@dataclass(frozen=True)
class Settings:
    tempo_token: str
    tempo_base_url: str
    team_id: str
    database_url: str
    initial_from: date
    initial_to: date | None
    interval_seconds: int
    overlap_seconds: int
    redact_descriptions: bool
    jira_domain: str
    jira_email: str
    jira_token: str
    jira_project: str
    jira_organisation_field: str
    jira_customer_field: str
    jira_cab_organisation: str
    jira_leave_issues: tuple[str, ...]
    jira_internal_issues: tuple[str, ...]
    jira_training_issues: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("TEMPO_TOKEN", "").strip()
        team_id = os.environ.get("TEMPO_TEAM_ID", "").strip()
        if not token or not team_id:
            raise ValueError("TEMPO_TOKEN and TEMPO_TEAM_ID are required")
        end = os.environ.get("INITIAL_TO", "").strip()
        jira_token = os.environ.get("JIRA_API_TOKEN", "").strip()
        jira_email = os.environ.get("JIRA_USER_EMAIL", "").strip()
        jira_domain = os.environ.get("JIRA_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
        if not jira_token or not jira_email or not jira_domain:
            raise ValueError("JIRA_DOMAIN, JIRA_USER_EMAIL, and JIRA_API_TOKEN are required")
        return cls(
            token, os.environ.get("TEMPO_BASE_URL", "https://api.tempo.io").rstrip("/"),
            team_id, os.environ.get("DATABASE_URL", "postgresql://tempo:tempo@postgres:5432/tempo"),
            date.fromisoformat(os.environ.get("INITIAL_FROM", "2000-01-01")),
            date.fromisoformat(end) if end else None,
            int(os.environ.get("SYNC_INTERVAL_SECONDS", "3600")),
            int(os.environ.get("SYNC_OVERLAP_SECONDS", "300")),
            os.environ.get("REDACT_DESCRIPTIONS", "true").lower() not in {"0", "false", "no"},
            jira_domain, jira_email, jira_token,
            os.environ.get("JIRA_JQL_PROJECT", ""),
            os.environ.get("JIRA_ORGANISATION_FIELD", "customfield_10002"),
            os.environ.get("JIRA_CUSTOMER_FIELD", "customfield_10070"),
            os.environ.get("JIRA_CAB_ORGANISATION", "Sorted Group"),
            tuple(x.strip() for x in os.environ.get("JIRA_LEAVE_ISSUES", "CS-259").split(",") if x.strip()),
            tuple(x.strip() for x in os.environ.get("JIRA_INTERNAL_ISSUES", "CS-35").split(",") if x.strip()),
            tuple(x.strip() for x in os.environ.get("JIRA_TRAINING_ISSUES", "CS-670").split(",") if x.strip()),
        )
