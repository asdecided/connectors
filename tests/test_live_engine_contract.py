"""Cross-repo contract test: the live rac engine's export vs. the connector parsers.

Every other test in this suite feeds the parsers hand-written fixture JSON. This
module is the one place a *real* export — produced by the actual rac-core engine
(``rac export --documents`` / ``--graph``) — is driven through the connector's
own readers (:mod:`rac_connectors.records`, :mod:`rac_connectors.graph`). It is
the frozen cross-repo contract: if a rebuilt engine changes the export shape or
bumps the contract major, these tests fail where a hand-written fixture never
could, because the fixture *is* the change under test.

The module skips cleanly when no ``rac`` engine is on PATH, so the connector's
normal engine-free CI (fixtures only, no live backend) is unaffected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from rac_connectors.contract import SUPPORTED_CONTRACT_VERSION, ContractVersionWarning
from rac_connectors.graph import parse_graph
from rac_connectors.records import parse_documents

# Collection-time guard: if the engine is not on PATH, skip the whole module so
# the fixture-only CI stays green without it. ``rac`` IS resolved at run time via
# ``shutil.which`` and invoked by absolute path, never assumed to be the default.
pytestmark = pytest.mark.skipif(
    shutil.which("rac") is None,
    reason="rac engine not on PATH",
)

# Canonical ids use the engine's required <KEY>-<12-char Crockford base32> shape;
# an invalid suffix fails ``rac validate`` and the fixture would never build.
_BASE_DECISION = "RAC-01JY4M8X2Q01"
_REPLACEMENT_DECISION = "RAC-01JY4M8X2Q02"
_DANGLING_DECISION = "RAC-01JY4M8X2Q03"
_WIDGET_REQUIREMENT = "RAC-01JY4M8X2Q04"

# A phantom reference that resolves to no in-corpus artifact — exercises the
# graph export's resolved=False, literal-target path.
_DANGLING_TARGET = "adr-999-nonexistent"

# A small but contract-complete corpus: a supersedes chain (adr-002 supersedes
# and relates-to adr-001), a dangling in-corpus reference (adr-003 → a phantom),
# and a requirement that relates to a decision. Between them the graph export
# exercises resolved=True, resolved=False, directed (supersedes), and undirected
# (related_*) edges.
_ARTIFACTS: dict[str, str] = {
    "rac/decisions/adr-001-base.md": f"""\
---
schema_version: 1
id: {_BASE_DECISION}
type: decision
---
# ADR-001: Base Decision

## Status

Accepted

## Category

Architecture

## Context

The original approach to widget storage.

## Decision

Store widgets in a flat file.

## Consequences

Simple but limited.
""",
    "rac/decisions/adr-002-replacement.md": f"""\
---
schema_version: 1
id: {_REPLACEMENT_DECISION}
type: decision
---
# ADR-002: Replacement Decision

## Status

Accepted

## Category

Architecture

## Context

Flat-file storage no longer scales.

## Decision

Replace flat-file storage with a database.

## Consequences

More robust.

## Supersedes

- adr-001-base

## Related Decisions

- adr-001-base
""",
    "rac/decisions/adr-003-dangling.md": f"""\
---
schema_version: 1
id: {_DANGLING_DECISION}
type: decision
---
# ADR-003: Dangling Reference Decision

## Status

Accepted

## Category

Technical

## Context

This decision references one that does not exist in the corpus.

## Decision

Point at a phantom decision to exercise the unresolved edge.

## Consequences

The reference stays literal and unresolved.

## Related Decisions

- {_DANGLING_TARGET}
""",
    "rac/requirements/widget-capability.md": f"""\
---
schema_version: 1
id: {_WIDGET_REQUIREMENT}
type: requirement
---
# Requirement: Widget Storage Capability

## Status

Accepted

## Problem

Users need durable widget storage.

## Requirements

- [REQ-001] The system MUST persist widgets across restarts.

## Related Decisions

- adr-002-replacement
""",
}


def _rac() -> str:
    """Absolute path to the ``rac`` engine (guaranteed by the module skipif)."""
    engine = shutil.which("rac")
    assert engine is not None  # the module-level skipif guards collection
    return engine


def _export(corpus: Path, mode: str) -> str:
    """Run one export mode against the corpus and return its stdout."""
    result = subprocess.run(
        [_rac(), "export", str(corpus / "rac"), mode],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"`rac export {mode}` failed:\n{result.stderr}"
    return result.stdout


@pytest.fixture(scope="session")
def live_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Materialise the real corpus once, and prove it is valid before exporting.

    Verifying with ``rac validate`` makes a malformed fixture fail loudly here
    rather than skewing the contract assertions downstream.
    """
    corpus = tmp_path_factory.mktemp("live-corpus")
    for rel, body in _ARTIFACTS.items():
        path = corpus / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    result = subprocess.run(
        [_rac(), "validate", str(corpus / "rac")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"fixture corpus failed `rac validate`:\n{result.stdout}\n{result.stderr}"
    )
    return corpus


def test_documents_export_parses_into_records(live_corpus: Path) -> None:
    """A real ``--documents`` export feeds the record parser cleanly."""
    lines = _export(live_corpus, "--documents").splitlines()

    with warnings.catch_warnings():
        # A supported major must be silent: any ContractVersionWarning (indeed
        # any warning) raised while parsing fails the test — the absence check.
        warnings.simplefilter("error", ContractVersionWarning)
        records = list(parse_documents(lines))

    assert len(records) == len(_ARTIFACTS)
    for record in records:
        assert record.id
        assert record.type
        assert record.status
        assert record.title
        assert record.text
        major = record.schema_version.split(".", 1)[0]
        assert major == SUPPORTED_CONTRACT_VERSION
        assert record.metadata.get("source") == "rac"


def test_graph_export_parses_into_typed_graph(live_corpus: Path) -> None:
    """A real ``--graph`` export parses into typed nodes and edges."""
    graph = parse_graph(_export(live_corpus, "--graph"))

    node_ids = {node.id for node in graph.nodes}
    assert len(graph.nodes) == len(_ARTIFACTS)
    assert node_ids == {
        _BASE_DECISION,
        _REPLACEMENT_DECISION,
        _DANGLING_DECISION,
        _WIDGET_REQUIREMENT,
    }

    # The supersedes chain: exactly one directed, resolved decision→decision edge
    # whose type and direction come from rac's relationship-type registry.
    supersedes = [edge for edge in graph.edges if edge.type == "supersedes"]
    assert len(supersedes) == 1
    chain = supersedes[0]
    assert chain.source == _REPLACEMENT_DECISION
    assert chain.target == _BASE_DECISION
    assert chain.directed is True
    assert chain.resolved is True

    # The dangling reference survives as an unresolved edge carrying the literal
    # reference text, and invents no phantom node for the missing target.
    dangling = [edge for edge in graph.edges if not edge.resolved]
    assert len(dangling) == 1
    assert dangling[0].source == _DANGLING_DECISION
    assert dangling[0].target == _DANGLING_TARGET
    assert dangling[0].target not in node_ids

    # Ids round-trip: every edge endpoint is either an in-corpus node id (when
    # resolved) or the preserved literal target (when not).
    for edge in graph.edges:
        assert edge.source in node_ids
        if edge.resolved:
            assert edge.target in node_ids


def test_export_pins_contract_major_one(live_corpus: Path) -> None:
    """The exported contract major is exactly ``1``.

    If a rebuilt engine bumps the ``schema_version`` major on either projection,
    this test MUST fail — that is its purpose. It pins the frozen cross-repo
    contract the connector's parsers are written against (ADR-007, ADR-063).
    """
    doc_lines = (
        line
        for line in _export(live_corpus, "--documents").splitlines()
        if line.strip()
    )
    doc_line = next(doc_lines)
    doc_major = str(json.loads(doc_line)["schema_version"]).split(".", 1)[0]

    graph_payload = json.loads(_export(live_corpus, "--graph"))
    graph_major = str(graph_payload["schema_version"]).split(".", 1)[0]

    assert doc_major == "1"
    assert graph_major == "1"
    assert SUPPORTED_CONTRACT_VERSION == "1"
