"""The Atlassian seam implementations: verifier now, publisher beside it.

Both follow the repo convention: construct without a client for a
credential-free ``--dry-run``, and a live run without a client is a clear
error rather than a silent no-op.
"""

from __future__ import annotations

from ..base import VerifySummary
from ..graph import Graph
from .client import JiraClient
from .jira import verify_graph

BACKEND = "atlassian"


class AtlassianVerifier:
    """Implements the ``TicketVerifier`` seam for Jira references (ADR-010)."""

    name = BACKEND

    def __init__(self, client: JiraClient | None = None) -> None:
        self._client = client

    def verify(self, graph: Graph, *, dry_run: bool = False) -> VerifySummary:
        return verify_graph(graph, self._client, dry_run=dry_run)
