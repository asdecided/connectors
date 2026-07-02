"""Jira reference verification over the ``--graph`` projection (ADR-010).

Selects the export's Jira ticket edges by contract markers (``external`` +
``provider == "jira"``), checks them against the operator's instance in
bulk, and reports per reference — read-only, nothing is written anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..base import VerifySummary
from ..graph import Graph, GraphEdge
from .client import AtlassianAuthError, JiraClient

BULK_FETCH_BATCH = 100

# A Jira issue key inside a bare reference or a /browse/ URL.
_ISSUE_KEY = re.compile(r"\b([A-Z][A-Z0-9]*-\d+)\b")

_PERMISSION_HINTS = ("permission", "forbidden", "401", "403")


def extract_issue_key(target: str) -> str | None:
    """Pull the issue key out of an edge target (bare key or browse URL)."""
    match = _ISSUE_KEY.search(target)
    return match.group(1) if match else None


def _jira_edges(graph: Graph) -> tuple[list[GraphEdge], list[GraphEdge]]:
    """Split external edges into Jira ticket edges and everything else.

    Only ``external`` edges are in scope; in-corpus relationship edges are
    not references to verify. ``verified_by`` edges carry ``provider: None``
    (rac-core ADR-096) and land in the skipped bucket by construction.
    """
    jira: list[GraphEdge] = []
    other: list[GraphEdge] = []
    for edge in graph.edges:
        if not edge.external:
            continue
        (jira if edge.provider == "jira" else other).append(edge)
    return jira, other


def _keys_with_sources(
    edges: Sequence[GraphEdge], summary: VerifySummary
) -> dict[str, list[str]]:
    """Dedupe issue keys, remembering every source artifact per key."""
    keys: dict[str, list[str]] = {}
    for edge in edges:
        key = extract_issue_key(edge.target)
        if key is None:
            summary.record_skip_item(edge.target, "no Jira issue key in target")
            continue
        sources = keys.setdefault(key, [])
        if edge.source not in sources:
            sources.append(edge.source)
    return keys


def _batches(keys: Sequence[str]) -> list[list[str]]:
    return [
        list(keys[start : start + BULK_FETCH_BATCH])
        for start in range(0, len(keys), BULK_FETCH_BATCH)
    ]


def verify_graph(
    graph: Graph, client: JiraClient | None, *, dry_run: bool = False
) -> VerifySummary:
    """Verify the graph's Jira ticket references, batching through bulk fetch.

    With ``dry_run=True`` no client is needed and no call is made — the
    summary lists the keys and batches that a live run would check.
    """
    summary = VerifySummary(backend="atlassian", dry_run=dry_run)

    jira_edges, other_external = _jira_edges(graph)
    for edge in other_external:
        provider = edge.provider or "no provider"
        summary.record_skip_item(edge.target, f"{provider} reference, not checked")

    keys = _keys_with_sources(jira_edges, summary)
    ordered = sorted(keys)

    if dry_run:
        for key in ordered:
            summary.checked += 1
            summary.actions.append(
                f"check {key}: referenced by {', '.join(sorted(keys[key]))}"
            )
        batches = len(_batches(ordered))
        if batches:
            summary.actions.append(
                f"plan: {len(ordered)} issue(s) in {batches} bulk-fetch batch(es)"
            )
        return summary

    if client is None:
        raise RuntimeError(
            "a live verify needs a Jira client; pass client_from_env() or use "
            "dry_run=True"
        )

    for batch in _batches(ordered):
        try:
            result = client.bulk_fetch_issues(batch)
        except AtlassianAuthError as exc:
            for key in batch:
                summary.record_forbidden(key, _attributed(str(exc), keys[key]))
            continue
        found = {issue.key: issue for issue in result.issues}
        for key in batch:
            sources = keys[key]
            if key in found:
                issue = found[key]
                detail = f"{issue.status} ({issue.status_category})"
                summary.record_exists(key, _attributed(detail, sources))
            elif key in result.errors:
                reason = result.errors[key]
                if any(hint in reason.lower() for hint in _PERMISSION_HINTS):
                    summary.record_forbidden(key, _attributed(reason, sources))
                else:
                    summary.record_missing(key, _attributed(reason, sources))
            else:
                summary.record_missing(key, _attributed("not returned", sources))
    return summary


def _attributed(detail: str, sources: Sequence[str]) -> str:
    return f"{detail} <- {', '.join(sorted(sources))}"
