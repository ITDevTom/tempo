import json
import logging
import random
import time
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


class TempoError(RuntimeError):
    pass


class TempoClient:
    def __init__(self, base_url: str, token: str, *, retries: int = 5, timeout: int = 60):
        self.base_url, self.token, self.retries, self.timeout = base_url.rstrip("/"), token, retries, timeout

    def request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        # Repeated array query parameters are required by Tempo.
        encoded = urlencode(query, doseq=True)
        url = f"{self.base_url}{path}" + (f"?{encoded}" if encoded else "")
        for attempt in range(self.retries + 1):
            try:
                req = Request(url, headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
                with urlopen(req, timeout=self.timeout) as response:
                    body = response.read()
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise TempoError(f"Tempo returned non-object JSON for {path}")
                return data
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise TempoError(f"Tempo authentication/permission failure: HTTP {exc.code}") from exc
                if exc.code == 429 or exc.code >= 500:
                    if attempt < self.retries:
                        retry_after = exc.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after else min(60, 2 ** attempt) + random.random()
                        log.warning("Tempo HTTP %s; retrying in %.1fs", exc.code, delay)
                        time.sleep(delay)
                        continue
                raise TempoError(f"Tempo request failed: HTTP {exc.code} {path}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.retries:
                    time.sleep(min(60, 2 ** attempt) + random.random())
                    continue
                raise TempoError(f"Tempo request failed: {path}: {exc}") from exc
        raise AssertionError("retry loop exhausted")

    def pages(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("limit", 50)
        offset = int(params.pop("offset", 0))
        next_token = params.pop("nextPageToken", None)
        while True:
            current = dict(params)
            if next_token:
                current["nextPageToken"] = next_token
            else:
                current["offset"] = offset
            payload = self.request(path, current)
            for item in payload.get("results", []):
                if isinstance(item, dict):
                    yield item
            meta = payload.get("metadata", {}) or {}
            next_url = meta.get("nextPageUrl")
            next_token = meta.get("nextPageToken")
            if next_token:
                continue
            if next_url:
                # Preserve host/auth safety; extract query only.
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(next_url)
                params = {k: v[-1] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
                offset = 0
                continue
            count = int(meta.get("count", 0))
            limit = int(meta.get("limit", params.get("limit", 50)))
            if count == 0 or count < limit:
                return
            offset += limit
