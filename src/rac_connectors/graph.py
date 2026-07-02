"""Parse the ``rac export --graph`` contract into a typed node/edge graph.

The graph projection (rac-core ADR-074) is a single JSON object of typed nodes
and edges with ``directed`` / ``resolved`` flags — a different shape from the
``--documents`` stream, so it has its own reader. Like ``records.py`` this is a
*consumer* of a stable contract (ADR-063); it never re-derives anything from raw
Markdown. Unknown additive fields are tolerated (rac-core ADR-007).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .contract import check_contract_version


class MalformedGraphError(ValueError):
    """The ``--graph`` payload could not be parsed into a valid graph."""


@dataclass(frozen=True)
class GraphNode:
    """One artifact as a graph node, mirroring the contract's node object."""

    id: str
    type: str
    status: str
    title: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        for key in ("id", "type", "status", "title"):
            if not isinstance(data.get(key), str):
                raise MalformedGraphError(f"node missing or non-string {key!r}")
        if not data["id"]:
            raise MalformedGraphError("node 'id' must be non-empty")
        return cls(
            id=data["id"],
            type=data["type"],
            status=data["status"],
            title=data["title"],
        )


@dataclass(frozen=True)
class GraphEdge:
    """One typed relationship edge.

    ``type`` is the real relationship kind (``supersedes``, ``related_decisions``,
    …) from rac's registry; ``directed`` carries its registry direction.
    ``resolved`` is False when the reference did not resolve uniquely, in which
    case ``target`` is the literal reference text rather than a canonical id.
    ``external`` marks an external-target edge (``related_tickets``, rac-core
    ADR-087; ``verified_by``, rac-core ADR-096) — unresolved by design, not a
    dangling in-corpus link. ``provider`` carries the repository's configured
    ticketing provider on ticket edges and is None everywhere else.
    """

    source: str
    target: str
    type: str
    directed: bool
    resolved: bool
    external: bool = False
    provider: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphEdge:
        for key in ("source", "target", "type"):
            if not isinstance(data.get(key), str):
                raise MalformedGraphError(f"edge missing or non-string {key!r}")
        if not data["source"] or not data["target"]:
            raise MalformedGraphError("edge 'source'/'target' must be non-empty")
        provider = data.get("provider")
        return cls(
            source=data["source"],
            target=data["target"],
            type=data["type"],
            # Defaults keep the reader tolerant of additive contract growth.
            directed=bool(data.get("directed", True)),
            resolved=bool(data.get("resolved", True)),
            external=bool(data.get("external", False)),
            provider=provider if isinstance(provider, str) else None,
        )


@dataclass(frozen=True)
class Graph:
    """The whole corpus as typed nodes + edges (one ``--graph`` object)."""

    source: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    schema_version: str = "1"


def parse_graph(payload: str) -> Graph:
    """Parse a ``--graph`` JSON document (one object) into a :class:`Graph`.

    Raises :class:`MalformedGraphError` if the payload is not a JSON object or a
    node/edge is structurally invalid. Whole-graph parsing is fail-fast: unlike
    the line-oriented documents reader, a graph is a single object, so a broken
    structure is not something to skip past.
    """
    text = payload.strip()
    if not text:
        raise MalformedGraphError("empty graph payload")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedGraphError(f"invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise MalformedGraphError("graph payload is not a JSON object")

    source = data.get("source")
    if not isinstance(source, str):
        raise MalformedGraphError("graph missing or non-string 'source'")

    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise MalformedGraphError("graph 'nodes'/'edges' must be arrays")

    schema_version = data.get("schema_version", "1")
    if not isinstance(schema_version, str):
        schema_version = str(schema_version)
    check_contract_version(schema_version)

    return Graph(
        source=source,
        nodes=[GraphNode.from_dict(n) for n in raw_nodes],
        edges=[GraphEdge.from_dict(e) for e in raw_edges],
        schema_version=schema_version,
    )
