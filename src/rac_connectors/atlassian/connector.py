"""The Atlassian seam implementations: verifier now, publisher beside it.

Both follow the repo convention: construct without a client for a
credential-free ``--dry-run``, and a live run without a client is a clear
error rather than a silent no-op.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..base import PushSummary, VerifySummary
from ..graph import Graph
from ..records import Record
from .client import ConfluenceClient, JiraClient
from .confluence import publish_records
from .jira import verify_graph

BACKEND = "atlassian"


class AtlassianVerifier:
    """Implements the ``TicketVerifier`` seam for Jira references (ADR-010)."""

    name = BACKEND

    def __init__(self, client: JiraClient | None = None) -> None:
        self._client = client

    def verify(self, graph: Graph, *, dry_run: bool = False) -> VerifySummary:
        return verify_graph(graph, self._client, dry_run=dry_run)


class AtlassianPublisher:
    """Implements the ``PagePublisher`` seam for managed pages (ADR-011)."""

    name = BACKEND

    def __init__(
        self, client: ConfluenceClient | None = None, *, space_key: str = ""
    ) -> None:
        self._client = client
        self._space_key = space_key

    def publish(
        self, records: Iterable[Record], *, dry_run: bool = False
    ) -> PushSummary:
        return publish_records(
            records, self._client, space_key=self._space_key, dry_run=dry_run
        )
