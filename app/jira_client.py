import logging
import time
from typing import Any
import requests

log = logging.getLogger(__name__)


def field_names(value: Any) -> list[str]:
    """Normalize Jira organisation/customer fields without leaking raw objects."""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    names = []
    for item in values:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("value")
            if name and str(name).strip():
                names.append(str(name).strip())
    return list(dict.fromkeys(names))


class JiraError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, domain: str, email: str, token: str, *, retries: int = 3, timeout: int = 60):
        self.base_url = f"https://{domain.rstrip('/')}"
        self.auth = (email, token)
        self.retries, self.timeout = retries, timeout

    def search_issues(self, *, since: str, project: str, organisation_field: str, customer_field: str, use_created: bool):
        date_field = "created" if use_created else "updated"
        project_clause = f"project = {project} AND " if project else ""
        params = {
            "jql": f'{project_clause}{date_field} >= "{since.replace("T", " ")[:16]}" ORDER BY updated',
            "maxResults": 100,
            "fields": ",".join(["summary", "created", "updated", "project", organisation_field, customer_field]),
            "expand": "names",
        }
        while True:
            data = self._get("/rest/api/3/search/jql", params)
            for issue in data.get("issues", []):
                yield issue
            token = data.get("nextPageToken")
            if not token:
                return
            params["nextPageToken"] = token

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.retries):
            try:
                response = requests.get(self.base_url + path, headers={"Accept": "application/json"}, auth=self.auth, params=params, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < self.retries:
                        delay = int(response.headers.get("Retry-After", 2 * (attempt + 1)))
                        log.warning("Jira HTTP %s; retrying in %ss", response.status_code, delay)
                        time.sleep(delay)
                        continue
                if response.status_code in {401, 403}:
                    raise JiraError(f"Jira authentication/permission failure: HTTP {response.status_code}")
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise JiraError(f"Jira returned non-object JSON for {path}")
                return value
            except requests.RequestException as exc:
                if attempt + 1 == self.retries:
                    raise JiraError(f"Jira request failed: {path}: {exc}") from exc
                time.sleep(2 * (attempt + 1))
        raise AssertionError("retry loop exhausted")
