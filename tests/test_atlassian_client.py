"""Wire-contract tests for the Atlassian HTTP client (mock transport, offline)."""

from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from rac_connectors.atlassian.client import (  # noqa: E402
    BASE_URL_ENV,
    EMAIL_ENV,
    TOKEN_ENV,
    AtlassianAuthError,
    HttpAtlassianClient,
    MissingCredentialsError,
    VersionConflictError,
    client_from_env,
)

_CREDS = {
    "base_url": "https://example.atlassian.net",
    "email": "op@example.com",
    "api_token": "token-123",
}


def _client(handler, sleeps=None):
    recorded: list[float] = [] if sleeps is None else sleeps
    return HttpAtlassianClient(
        **_CREDS,
        transport=httpx.MockTransport(handler),
        sleep=recorded.append,
    )


def test_missing_credentials_name_every_absent_variable(monkeypatch) -> None:
    for env in (BASE_URL_ENV, EMAIL_ENV, TOKEN_ENV):
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(MissingCredentialsError) as excinfo:
        client_from_env()
    message = str(excinfo.value)
    assert BASE_URL_ENV in message
    assert EMAIL_ENV in message
    assert TOKEN_ENV in message


def test_bulk_fetch_sends_basic_auth_and_narrow_fields() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "status": {
                                "name": "Done",
                                "statusCategory": {"key": "done"},
                            }
                        },
                    }
                ],
                "issueErrors": [
                    {"id": "PROJ-404", "errorMessages": ["issue does not exist"]}
                ],
            },
        )

    result = _client(handler).bulk_fetch_issues(["PROJ-1", "PROJ-404"])
    assert str(seen["auth"]).startswith("Basic ")
    assert str(seen["url"]).endswith("/rest/api/3/issue/bulkfetch")
    assert seen["body"] == {
        "issueIdsOrKeys": ["PROJ-1", "PROJ-404"],
        "fields": ["status"],
    }
    assert result.issues[0].key == "PROJ-1"
    assert result.issues[0].status == "Done"
    assert result.issues[0].status_category == "done"
    assert result.errors == {"PROJ-404": "issue does not exist"}


def test_429_retries_after_header_then_succeeds() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"issues": [], "issueErrors": []})

    result = _client(handler, sleeps).bulk_fetch_issues(["PROJ-1"])
    assert calls["n"] == 3
    assert sleeps == [2.0, 2.0]  # Retry-After honoured verbatim
    assert result.issues == []


def test_persistent_429_exhausts_capped_retries() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    with pytest.raises(RuntimeError, match="HTTP 429"):
        _client(handler, sleeps).bulk_fetch_issues(["PROJ-1"])
    assert len(sleeps) == 4  # capped retry budget, then surfaced


def test_auth_failure_raises_without_retry() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errorMessages": ["forbidden"]})

    with pytest.raises(AtlassianAuthError):
        _client(handler, sleeps).bulk_fetch_issues(["PROJ-1"])
    assert sleeps == []


def test_remote_link_upsert_carries_global_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 1})

    _client(handler).upsert_remote_link(
        issue_key="PROJ-1",
        global_id="lore:RAC-1",
        url="https://example.com/RAC-1",
        title="RAC-1",
    )
    assert str(seen["url"]).endswith("/rest/api/3/issue/PROJ-1/remotelink")
    assert seen["body"] == {
        "globalId": "lore:RAC-1",
        "object": {"url": "https://example.com/RAC-1", "title": "RAC-1"},
    }


def _confluence_handler(state: dict) -> object:
    """A tiny scripted Confluence covering the publish call sequence."""

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/wiki/api/v2/spaces":
            return httpx.Response(200, json={"results": [{"id": "111"}]})
        if path == "/wiki/rest/api/content/search":
            state["cql"] = dict(request.url.params)["cql"]
            found = state.get("page")
            results = [{"id": found["id"]}] if found else []
            return httpx.Response(200, json={"results": results})
        if method == "GET" and path == "/wiki/api/v2/pages/900":
            return httpx.Response(
                200,
                json={"id": "900", "title": "Old", "version": {"number": 4}},
            )
        if method == "GET" and path == "/wiki/api/v2/pages/900/properties":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "77",
                            "key": "lore",
                            "value": {"artifact_id": "RAC-1", "body_hash": "abc"},
                            "version": {"number": 2},
                        }
                    ]
                },
            )
        if method == "POST" and path == "/wiki/api/v2/pages":
            state["created"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "901"})
        if method == "PUT" and path == "/wiki/api/v2/pages/900":
            state["updated"] = json.loads(request.content)
            return httpx.Response(state.get("update_status", 200), json={})
        if path == "/wiki/api/v2/pages/901/properties" and method == "GET":
            return httpx.Response(200, json={"results": []})
        if path == "/wiki/api/v2/pages/901/properties" and method == "POST":
            state["property"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "78"})
        if path == "/wiki/rest/api/content/901/label":
            state["label"] = json.loads(request.content)
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected call: {method} {path}")

    return handler


def test_find_managed_page_reads_version_and_hash() -> None:
    state: dict = {"page": {"id": "900"}}
    page = _client(_confluence_handler(state)).find_managed_page(
        space_key="DOCS", artifact_id="RAC-1"
    )
    assert page is not None
    assert (page.page_id, page.version, page.body_hash) == ("900", 4, "abc")
    assert 'content.property[lore].artifact_id = "RAC-1"' in str(state["cql"])


def test_find_managed_page_returns_none_when_absent() -> None:
    state: dict = {}
    page = _client(_confluence_handler(state)).find_managed_page(
        space_key="DOCS", artifact_id="RAC-404"
    )
    assert page is None


def test_create_page_then_property_and_label() -> None:
    state: dict = {}
    client = _client(_confluence_handler(state))
    page_id = client.create_page(space_key="DOCS", title="T", storage_body="<p>b</p>")
    client.set_managed_property(page_id=page_id, artifact_id="RAC-1", body_hash="h")
    client.add_label(page_id=page_id, label="lore-managed")
    assert page_id == "901"
    created = state["created"]
    assert created["spaceId"] == "111"
    assert created["body"] == {"representation": "storage", "value": "<p>b</p>"}
    assert state["property"]["value"] == {"artifact_id": "RAC-1", "body_hash": "h"}
    assert state["label"] == [{"prefix": "global", "name": "lore-managed"}]


def test_update_page_sends_incremented_version() -> None:
    state: dict = {"page": {"id": "900"}}
    client = _client(_confluence_handler(state))
    client.update_page(page_id="900", version=4, title="New", storage_body="<p>x</p>")
    assert state["updated"]["version"] == {"number": 5}


def test_update_conflict_raises_version_conflict() -> None:
    state: dict = {"page": {"id": "900"}, "update_status": 409}
    client = _client(_confluence_handler(state))
    with pytest.raises(VersionConflictError):
        client.update_page(page_id="900", version=4, title="N", storage_body="b")
