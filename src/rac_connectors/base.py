"""The shared connector seam every backend module implements.

One repo, one module per backend (ADR-073). Supermemory is module one; this is
the small shape the next backend (Mem0, Zep, a vector store, a graph backend)
slots into without reworking the CLI. The seam is deliberately minimal — push a
stream of records, optionally as a dry run, get back a deterministic summary —
so it does not over-generalise before a second backend exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .graph import Graph
from .records import Record


@dataclass
class PushSummary:
    """The outcome of a push, the same shape for every backend.

    ``actions`` records one line per item describing what was (or, under a dry
    run, would be) sent — keyed by canonical ``id`` so a re-push is legible as
    the idempotent update it is. The same summary serves the documents push (one
    record per line) and the graph push (nodes and edges).
    """

    backend: str
    pushed: int = 0
    skipped: int = 0
    dry_run: bool = False
    actions: list[str] = field(default_factory=list)

    def record_push(self, item_id: str, detail: str) -> None:
        self.pushed += 1
        self.actions.append(f"push {item_id}: {detail}")

    def record_skip_item(self, label: str, reason: str) -> None:
        self.skipped += 1
        self.actions.append(f"skip {label}: {reason}")

    def record_skip(self, line_number: int, reason: str) -> None:
        self.record_skip_item(f"line {line_number}", reason)

    def summary_line(self) -> str:
        mode = "dry-run" if self.dry_run else "push"
        return f"{self.backend} {mode}: {self.pushed} pushed, {self.skipped} skipped"


@dataclass
class VerifySummary:
    """The outcome of an external-reference verification (ADR-010).

    The verify seam returns a report, never records — the shape itself keeps
    the rejected recall/re-rank surface impossible. ``missing`` and
    ``forbidden`` are findings; ``skipped`` counts external edges the
    verifier deliberately did not check (other providers, provider-less
    ``verified_by`` edges, unparseable targets).
    """

    backend: str
    checked: int = 0
    exists: int = 0
    missing: int = 0
    forbidden: int = 0
    skipped: int = 0
    dry_run: bool = False
    actions: list[str] = field(default_factory=list)

    def record_exists(self, key: str, detail: str) -> None:
        self.checked += 1
        self.exists += 1
        self.actions.append(f"exists {key}: {detail}")

    def record_missing(self, key: str, detail: str) -> None:
        self.checked += 1
        self.missing += 1
        self.actions.append(f"missing {key}: {detail}")

    def record_forbidden(self, key: str, detail: str) -> None:
        self.checked += 1
        self.forbidden += 1
        self.actions.append(f"forbidden {key}: {detail}")

    def record_skip_item(self, label: str, reason: str) -> None:
        self.skipped += 1
        self.actions.append(f"skip {label}: {reason}")

    @property
    def findings(self) -> int:
        return self.missing + self.forbidden

    @property
    def exit_code(self) -> int:
        # 3 is the CI-gateable "references failed verification" contract
        # (ADR-010) — distinct from malformed input (1) and missing creds (2).
        return 3 if self.findings else 0

    def summary_line(self) -> str:
        mode = "dry-run" if self.dry_run else "verify"
        return (
            f"{self.backend} {mode}: {self.checked} checked, "
            f"{self.exists} exist, {self.missing} missing, "
            f"{self.forbidden} forbidden, {self.skipped} skipped"
        )


@runtime_checkable
class Connector(Protocol):
    """Outbound-only sink for export records.

    Connectors push to the backend and never read back, re-rank, or route (the
    re-rank / memory-router approach was explicitly rejected — see the interplay
    design in rac-core). ``push`` must be idempotent on each record's canonical
    ``id`` so re-running an export updates rather than duplicates.
    """

    name: str

    def push(self, records: Iterable[Record], *, dry_run: bool = False) -> PushSummary:
        """Upsert ``records`` into the backend, returning a :class:`PushSummary`.

        With ``dry_run=True`` the connector must describe what it would send
        without making any network call.
        """
        ...


@runtime_checkable
class GraphConnector(Protocol):
    """Outbound-only sink for the ``--graph`` projection (typed nodes + edges).

    The sibling of :class:`Connector` for graph backends. The input shape differs
    — one whole :class:`~rac_connectors.graph.Graph`, not a stream of records —
    so it is a separate seam (ADR-003), but it shares the CLI, the
    :class:`PushSummary`, and the dry-run contract. ``push_graph`` must be
    idempotent on each node's and edge's canonical identity so re-running an
    export updates rather than duplicates.
    """

    name: str

    def push_graph(self, graph: Graph, *, dry_run: bool = False) -> PushSummary:
        """Upsert a graph's nodes and edges, returning a :class:`PushSummary`.

        With ``dry_run=True`` the connector must describe what it would write
        without connecting to the backend.
        """
        ...


@runtime_checkable
class TicketVerifier(Protocol):
    """Read-only checker for external ticket references (ADR-010).

    An operator-facing state check delegated by rac-core ADR-087 — not a
    recall surface for reading agents, which ADR-002 rejects. ``verify``
    writes nothing anywhere; it reports whether the ``external`` ticket edges
    in a ``--graph`` export still point at real, reachable issues.
    """

    name: str

    def verify(self, graph: Graph, *, dry_run: bool = False) -> VerifySummary:
        """Check the graph's ticket references, returning a :class:`VerifySummary`.

        With ``dry_run=True`` the verifier must list what it would check
        without making any network call.
        """
        ...


@runtime_checkable
class PagePublisher(Protocol):
    """Outbound page mirror for the ``--documents`` projection (ADR-010).

    Like :class:`Connector` it only writes outward and must be idempotent on
    each record's canonical ``id`` — for pages, via the artifact-id content
    property and body-hash skip recorded in ADR-011.
    """

    name: str

    def publish(
        self, records: Iterable[Record], *, dry_run: bool = False
    ) -> PushSummary:
        """Upsert ``records`` as managed pages, returning a :class:`PushSummary`.

        With ``dry_run=True`` the publisher must describe what it would write
        without making any network call.
        """
        ...
