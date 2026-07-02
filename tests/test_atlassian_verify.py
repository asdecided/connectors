"""Verify-verb behaviour driven through a fake Jira client (offline)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from rac_connectors.atlassian.client import (
    AtlassianAuthError,
    BulkFetchResult,
    IssueState,
)
from rac_connectors.atlassian.connector import AtlassianVerifier
from rac_connectors.atlassian.jira import BULK_FETCH_BATCH, extract_issue_key
from rac_connectors.graph import Graph, GraphEdge, GraphNode, parse_graph

_FIXTURE = Path(__file__).parent / "fixtures_graph_atlassian.json"


class FakeJiraClient:
    """Scripted bulk-fetch results keyed by issue key."""

    def __init__(
        self,
        existing: dict[str, tuple[str, str]] | None = None,
        errors: dict[str, str] | None = None,
        fail_auth: bool = False,
    ) -> None:
        self.existing = existing or {}
        self.errors = errors or {}
        self.fail_auth = fail_auth
        self.batches: list[list[str]] = []
        self.links: list[dict[str, str]] = []

    def bulk_fetch_issues(self, keys: Sequence[str]) -> BulkFetchResult:
        if self.fail_auth:
            raise AtlassianAuthError("HTTP 403")
        self.batches.append(list(keys))
        issues = [
            IssueState(key=key, status=name, status_category=category)
            for key, (name, category) in self.existing.items()
            if key in keys
        ]
        errors = {key: msg for key, msg in self.errors.items() if key in keys}
        return BulkFetchResult(issues=issues, errors=errors)

    def upsert_remote_link(
        self, *, issue_key: str, global_id: str, url: str, title: str
    ) -> None:
        self.links.append({"issue_key": issue_key, "global_id": global_id})


def _fixture_graph() -> Graph:
    return parse_graph(_FIXTURE.read_text(encoding="utf-8"))


def _jira_edge(source: str, target: str) -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        type="related_tickets",
        directed=False,
        resolved=False,
        external=True,
        provider="jira",
    )


def _graph(edges: list[GraphEdge]) -> Graph:
    nodes = [GraphNode("RAC-1", "roadmap", "Planned", "R")]
    return Graph(source="rac", nodes=nodes, edges=edges)


def test_extract_issue_key_handles_bare_keys_and_urls() -> None:
    assert extract_issue_key("PROJ-123") == "PROJ-123"
    assert (
        extract_issue_key("https://x.atlassian.net/browse/ABC-9?focused=1") == "ABC-9"
    )
    assert extract_issue_key("no key here") is None


def test_selects_only_jira_edges_and_skips_the_rest() -> None:
    client = FakeJiraClient(existing={"PROJ-123": ("Done", "done")})
    summary = AtlassianVerifier(client).verify(_fixture_graph())
    # PROJ-123 exists, PROJ-404 (browse URL) missing; github and verified_by
    # edges are skipped; the in-corpus edge is not counted at all.
    assert summary.checked == 2
    assert summary.exists == 1
    assert summary.missing == 1
    assert summary.skipped == 2
    assert summary.exit_code == 3


def test_clean_graph_exits_zero() -> None:
    client = FakeJiraClient(
        existing={"PROJ-123": ("Done", "done"), "PROJ-404": ("Open", "new")}
    )
    summary = AtlassianVerifier(client).verify(_fixture_graph())
    assert summary.findings == 0
    assert summary.exit_code == 0
    assert any("Done (done)" in action for action in summary.actions)


def test_results_attribute_source_artifacts() -> None:
    edges = [
        _jira_edge("RAC-1", "PROJ-7"),
        _jira_edge("RAC-2", "PROJ-7"),
    ]
    client = FakeJiraClient(errors={"PROJ-7": "issue does not exist"})
    summary = AtlassianVerifier(client).verify(_graph(edges))
    assert summary.missing == 1  # deduped: one key, two sources
    assert any("RAC-1, RAC-2" in action for action in summary.actions)


def test_batches_at_one_hundred_keys() -> None:
    edges = [_jira_edge("RAC-1", f"PROJ-{n}") for n in range(1, 102)]
    client = FakeJiraClient(
        existing={f"PROJ-{n}": ("Open", "new") for n in range(1, 102)}
    )
    summary = AtlassianVerifier(client).verify(_graph(edges))
    assert summary.checked == 101
    assert [len(batch) for batch in client.batches] == [BULK_FETCH_BATCH, 1]


def test_permission_hinted_error_classifies_as_forbidden() -> None:
    client = FakeJiraClient(
        errors={"PROJ-1": "you do not have permission to view this issue"}
    )
    summary = AtlassianVerifier(client).verify(_graph([_jira_edge("RAC-1", "PROJ-1")]))
    assert summary.forbidden == 1
    assert summary.missing == 0


def test_auth_failure_marks_batch_forbidden() -> None:
    client = FakeJiraClient(fail_auth=True)
    summary = AtlassianVerifier(client).verify(_fixture_graph())
    assert summary.forbidden == 2
    assert summary.exit_code == 3


def test_unparseable_target_is_skipped_not_checked() -> None:
    client = FakeJiraClient()
    summary = AtlassianVerifier(client).verify(
        _graph([_jira_edge("RAC-1", "not a ticket")])
    )
    assert summary.checked == 0
    assert summary.skipped == 1
    assert summary.exit_code == 0


def test_dry_run_needs_no_client_and_makes_no_calls() -> None:
    summary = AtlassianVerifier().verify(_fixture_graph(), dry_run=True)
    assert summary.dry_run is True
    assert summary.checked == 2
    assert summary.exit_code == 0  # a plan has no findings
    assert any(action.startswith("check PROJ-123") for action in summary.actions)
    assert any("bulk-fetch batch" in action for action in summary.actions)


def test_live_verify_without_client_is_a_clear_error() -> None:
    with pytest.raises(RuntimeError, match="client_from_env"):
        AtlassianVerifier().verify(_fixture_graph())


def test_empty_graph_verifies_clean() -> None:
    graph = parse_graph(json.dumps({"source": "rac", "nodes": [], "edges": []}))
    summary = AtlassianVerifier(FakeJiraClient()).verify(graph)
    assert summary.checked == 0
    assert summary.exit_code == 0
