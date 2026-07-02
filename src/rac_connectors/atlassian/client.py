"""The thin client seam the Atlassian connector talks through.

The verify and publish paths depend only on :class:`JiraClient` and
:class:`ConfluenceClient` (Protocols), so the test-suite drives in-memory
fakes and CI never touches a live site. :class:`HttpAtlassianClient` is the
real adapter — an internal client over ``httpx`` rather than an Atlassian
SDK (ADR-010) — imported lazily so the package installs and tests run
without the ``atlassian`` extra.

Air-gap posture (rac-core ADR-086): the only host this client ever contacts
is the operator's own instance from ``ATLASSIAN_BASE_URL``.
"""

from __future__ import annotations

import os
import random
import time
from base64 import b64encode
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

BASE_URL_ENV = "ATLASSIAN_BASE_URL"
EMAIL_ENV = "ATLASSIAN_EMAIL"
TOKEN_ENV = "ATLASSIAN_API_TOKEN"
SPACE_ENV = "ATLASSIAN_CONFLUENCE_SPACE"

# The content property that binds a Confluence page to its artifact (ADR-011).
PROPERTY_KEY = "lore"
MANAGED_LABEL = "lore-managed"

_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_TIMEOUT_SECONDS = 30.0


class MissingCredentialsError(RuntimeError):
    """One or more Atlassian credentials are absent from the environment."""

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = list(missing)
        names = ", ".join(self.missing)
        super().__init__(
            f"set {names} in the environment (never hard-code credentials)"
        )


class AtlassianAuthError(RuntimeError):
    """The instance rejected the request as unauthenticated or forbidden."""


class VersionConflictError(RuntimeError):
    """A page update lost the optimistic-concurrency race (HTTP 409).

    Someone edited the page since it was read; the connector surfaces the
    conflict and never force-overwrites (ADR-011).
    """

    def __init__(self, page_id: str) -> None:
        self.page_id = page_id
        super().__init__(f"version conflict updating page {page_id}")


@dataclass(frozen=True)
class IssueState:
    """One fetched Jira issue: its key and portable status signals."""

    key: str
    status: str
    status_category: str


@dataclass(frozen=True)
class BulkFetchResult:
    """The outcome of one bulk fetch: found issues plus per-key errors."""

    issues: list[IssueState]
    errors: dict[str, str]


@dataclass(frozen=True)
class ManagedPage:
    """A Confluence page already bound to an artifact via the property."""

    page_id: str
    version: int
    title: str
    body_hash: str | None


@runtime_checkable
class JiraClient(Protocol):
    """What the verify path (and remote-link backlinks) need from Jira."""

    def bulk_fetch_issues(self, keys: Sequence[str]) -> BulkFetchResult: ...

    def upsert_remote_link(
        self, *, issue_key: str, global_id: str, url: str, title: str
    ) -> None: ...


@runtime_checkable
class ConfluenceClient(Protocol):
    """What the publish path needs from Confluence.

    Property versioning is the adapter's problem; the seam works in artifact
    ids and body hashes only, so fakes stay a dict.
    """

    def find_managed_page(
        self, *, space_key: str, artifact_id: str
    ) -> ManagedPage | None: ...

    def create_page(self, *, space_key: str, title: str, storage_body: str) -> str: ...

    def update_page(
        self, *, page_id: str, version: int, title: str, storage_body: str
    ) -> None: ...

    def set_managed_property(
        self, *, page_id: str, artifact_id: str, body_hash: str
    ) -> None: ...

    def add_label(self, *, page_id: str, label: str) -> None: ...


class HttpAtlassianClient:
    """Adapter over ``httpx`` implementing both Protocols against Cloud.

    Basic auth (``email:api_token``), Jira under ``/rest/api/3/``, Confluence
    under ``/wiki/api/v2/`` (plus the v1 CQL search and label endpoints v2
    does not cover). Requests are sequential; 429 and 5xx responses retry
    with capped, jittered exponential backoff honouring ``Retry-After``. The
    sleep function is injectable so the retry battery runs instantly.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        transport: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        env = {
            BASE_URL_ENV: base_url or os.environ.get(BASE_URL_ENV),
            EMAIL_ENV: email or os.environ.get(EMAIL_ENV),
            TOKEN_ENV: api_token or os.environ.get(TOKEN_ENV),
        }
        missing = [name for name, value in env.items() if not value]
        if missing:
            raise MissingCredentialsError(missing)
        self._base_url = str(env[BASE_URL_ENV]).rstrip("/")
        credentials = f"{env[EMAIL_ENV]}:{env[TOKEN_ENV]}".encode()
        self._auth_header = "Basic " + b64encode(credentials).decode("ascii")
        self._transport = transport
        self._sleep = sleep
        self._client: Any = None
        self._space_ids: dict[str, str] = {}

    # -- transport ---------------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - exercised via message
                raise RuntimeError(
                    "the 'httpx' package is not installed; "
                    "install the connector's 'atlassian' extra"
                ) from exc
            self._client = httpx.Client(
                base_url=self._base_url,
                headers={
                    "Authorization": self._auth_header,
                    "Accept": "application/json",
                },
                timeout=_TIMEOUT_SECONDS,
                transport=self._transport,
            )
        return self._client

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        ok_statuses: tuple[int, ...] = (200,),
    ) -> Any:
        """One request with retry; returns parsed JSON (or None on 204)."""
        client = self._ensure_client()
        attempt = 0
        while True:
            response = client.request(method, path, json=json, params=params)
            if response.status_code in ok_statuses:
                return None if response.status_code == 204 else response.json()
            if response.status_code in (401, 403):
                raise AtlassianAuthError(
                    f"{method} {path}: HTTP {response.status_code} — check the "
                    f"credentials' permissions on the instance"
                )
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < _MAX_RETRIES:
                self._sleep(self._retry_delay(attempt, response))
                attempt += 1
                continue
            raise RuntimeError(
                f"{method} {path}: HTTP {response.status_code}: {response.text[:200]}"
            )

    @staticmethod
    def _retry_delay(attempt: int, response: Any) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(float(retry_after), _BACKOFF_CAP_SECONDS)
            except ValueError:
                pass
        delay = min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_CAP_SECONDS)
        return delay + random.uniform(0, delay / 4)

    # -- Jira --------------------------------------------------------------

    def bulk_fetch_issues(self, keys: Sequence[str]) -> BulkFetchResult:
        """Fetch up to 100 issues in one call, status field only."""
        payload = self._request(
            "POST",
            "/rest/api/3/issue/bulkfetch",
            json={"issueIdsOrKeys": list(keys), "fields": ["status"]},
        )
        issues = []
        for issue in payload.get("issues", []):
            status = (issue.get("fields") or {}).get("status") or {}
            category = status.get("statusCategory") or {}
            issues.append(
                IssueState(
                    key=str(issue.get("key", "")),
                    status=str(status.get("name", "")),
                    status_category=str(category.get("key", "")),
                )
            )
        errors: dict[str, str] = {}
        for entry in payload.get("issueErrors", []):
            key = str(entry.get("id") or entry.get("key") or "")
            messages = entry.get("errorMessages") or []
            errors[key] = "; ".join(str(m) for m in messages) or "not found"
        return BulkFetchResult(issues=issues, errors=errors)

    def upsert_remote_link(
        self, *, issue_key: str, global_id: str, url: str, title: str
    ) -> None:
        # Same-globalId POSTs update in place — Jira's native idempotent
        # upsert (ADR-011).
        self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/remotelink",
            json={"globalId": global_id, "object": {"url": url, "title": title}},
            ok_statuses=(200, 201),
        )

    # -- Confluence --------------------------------------------------------

    def _space_id(self, space_key: str) -> str:
        if space_key not in self._space_ids:
            payload = self._request(
                "GET", "/wiki/api/v2/spaces", params={"keys": space_key}
            )
            results = payload.get("results", [])
            if not results:
                raise RuntimeError(f"Confluence space not found: {space_key!r}")
            self._space_ids[space_key] = str(results[0]["id"])
        return self._space_ids[space_key]

    def find_managed_page(
        self, *, space_key: str, artifact_id: str
    ) -> ManagedPage | None:
        # CQL property search is a v1-only surface; page detail and the
        # property body come from v2.
        cql = (
            f'space = "{space_key}" and type = page and '
            f'content.property[{PROPERTY_KEY}].artifact_id = "{artifact_id}"'
        )
        payload = self._request(
            "GET",
            "/wiki/rest/api/content/search",
            params={"cql": cql, "limit": 2},
        )
        results = payload.get("results", [])
        if not results:
            return None
        page_id = str(results[0]["id"])
        page = self._request("GET", f"/wiki/api/v2/pages/{page_id}")
        prop = self._find_property(page_id)
        body_hash = None
        if prop is not None:
            value = prop.get("value") or {}
            if isinstance(value, dict) and isinstance(value.get("body_hash"), str):
                body_hash = value["body_hash"]
        return ManagedPage(
            page_id=page_id,
            version=int((page.get("version") or {}).get("number", 1)),
            title=str(page.get("title", "")),
            body_hash=body_hash,
        )

    def _find_property(self, page_id: str) -> dict[str, Any] | None:
        payload = self._request(
            "GET",
            f"/wiki/api/v2/pages/{page_id}/properties",
            params={"key": PROPERTY_KEY},
        )
        results = payload.get("results", [])
        return results[0] if results else None

    def create_page(self, *, space_key: str, title: str, storage_body: str) -> str:
        payload = self._request(
            "POST",
            "/wiki/api/v2/pages",
            json={
                "spaceId": self._space_id(space_key),
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": storage_body},
            },
            ok_statuses=(200, 201),
        )
        return str(payload["id"])

    def update_page(
        self, *, page_id: str, version: int, title: str, storage_body: str
    ) -> None:
        client = self._ensure_client()
        response = client.request(
            "PUT",
            f"/wiki/api/v2/pages/{page_id}",
            json={
                "id": page_id,
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": storage_body},
                "version": {"number": version + 1},
            },
        )
        if response.status_code == 409:
            raise VersionConflictError(page_id)
        if response.status_code in (401, 403):
            raise AtlassianAuthError(
                f"PUT pages/{page_id}: HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"PUT pages/{page_id}: HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

    def set_managed_property(
        self, *, page_id: str, artifact_id: str, body_hash: str
    ) -> None:
        value = {"artifact_id": artifact_id, "body_hash": body_hash}
        existing = self._find_property(page_id)
        if existing is None:
            self._request(
                "POST",
                f"/wiki/api/v2/pages/{page_id}/properties",
                json={"key": PROPERTY_KEY, "value": value},
                ok_statuses=(200, 201),
            )
            return
        current = int((existing.get("version") or {}).get("number", 1))
        self._request(
            "PUT",
            f"/wiki/api/v2/pages/{page_id}/properties/{existing['id']}",
            json={
                "key": PROPERTY_KEY,
                "value": value,
                "version": {"number": current + 1},
            },
        )

    def add_label(self, *, page_id: str, label: str) -> None:
        # Label writes are a v1-only surface.
        self._request(
            "POST",
            f"/wiki/rest/api/content/{page_id}/label",
            json=[{"prefix": "global", "name": label}],
            ok_statuses=(200, 201),
        )


def client_from_env() -> HttpAtlassianClient:
    """Build the real client from the ``ATLASSIAN_*`` environment variables."""
    return HttpAtlassianClient()
