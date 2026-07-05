"""The cross-repo contract, exercised against a LIVE ``rac`` engine.

Every other test in this suite parses committed fixture bytes, which pins the
connector's *reader* but not the *seam*: nothing proved that what ``rac
export`` actually emits still satisfies this reader. This test closes that
gap — it is the contract test the rac-core rebuild is gated on (roadmap
``rebuild-scale``): a rebuilt engine that breaks these assertions has broken
the frozen export contract, whether or not any rac-core test notices.

Skips (never fails) when no ``rac`` is on PATH, so the suite stays
dependency-free for connector-only development (this repo's ADR-008: the
dependency is the contract major, never the package).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from rac_connectors import (
    SUPPORTED_CONTRACT_VERSION,
    parse_documents,
    parse_graph,
)

CORPUS = Path(__file__).parent.parent / "rac"

pytestmark = pytest.mark.skipif(
    shutil.which("rac") is None, reason="no live rac engine on PATH"
)


def _export(flag: str) -> str:
    proc = subprocess.run(
        ["rac", "export", str(CORPUS), flag],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"rac export {flag} exited {proc.returncode}: {proc.stderr[-500:]}"
    return proc.stdout


def test_live_documents_export_satisfies_the_reader() -> None:
    payload = _export("--documents")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a contract-major warning is a failure here
        records = list(parse_documents(payload.splitlines()))
    assert records, "live --documents export produced no records"
    for record in records:
        assert record.id
        assert record.type
        assert record.title
        assert record.text
        assert record.metadata.get("source") == "rac"


def test_live_documents_export_declares_the_supported_major() -> None:
    first = json.loads(_export("--documents").splitlines()[0])
    major = first["schema_version"].split(".", 1)[0].strip()
    assert major == SUPPORTED_CONTRACT_VERSION


def test_live_graph_export_satisfies_the_reader() -> None:
    payload = _export("--graph")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse_graph(payload)
    assert graph.nodes, "live --graph export produced no nodes"
    node_ids = {node.id for node in graph.nodes}
    for edge in graph.edges:
        assert edge.source in node_ids, f"edge source {edge.source!r} not among nodes"


def test_live_documents_and_graph_agree_on_ids() -> None:
    doc_ids = {
        json.loads(line)["id"] for line in _export("--documents").splitlines() if line.strip()
    }
    graph = parse_graph(_export("--graph"))
    assert doc_ids == {node.id for node in graph.nodes}
