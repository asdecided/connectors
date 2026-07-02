"""End-to-end CLI behaviour for the `rac-connect atlassian` verbs."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from rac_connectors import cli

_FIXTURE = Path(__file__).parent / "fixtures_graph_atlassian.json"

_ATLASSIAN_ENV = (
    "ATLASSIAN_BASE_URL",
    "ATLASSIAN_EMAIL",
    "ATLASSIAN_API_TOKEN",
)


def _clear_env(monkeypatch) -> None:
    for var in _ATLASSIAN_ENV:
        monkeypatch.delenv(var, raising=False)


def test_verify_dry_run_needs_no_credentials(monkeypatch, capsys) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(_FIXTURE.read_text()))
    rc = cli.main(["atlassian", "verify", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr()
    assert "check PROJ-123" in out.out
    assert "2 checked" in out.err


def test_verify_live_without_credentials_exits_two(monkeypatch, capsys) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(_FIXTURE.read_text()))
    rc = cli.main(["atlassian", "verify"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "ATLASSIAN_API_TOKEN" in err


def test_verify_malformed_graph_exits_one(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    rc = cli.main(["atlassian", "verify", "--dry-run"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_verify_findings_exit_three(monkeypatch, capsys) -> None:
    class FindingVerifier:
        name = "atlassian"

        def verify(self, graph, *, dry_run=False):
            from rac_connectors.base import VerifySummary

            summary = VerifySummary(backend="atlassian")
            summary.record_missing("PROJ-404", "issue does not exist <- RAC-2")
            return summary

    monkeypatch.setattr(cli, "AtlassianVerifier", lambda client=None: FindingVerifier())
    monkeypatch.setattr(cli, "atlassian_client_from_env", lambda: object())
    monkeypatch.setattr("sys.stdin", io.StringIO(_FIXTURE.read_text()))
    rc = cli.main(["atlassian", "verify"])
    assert rc == 3
    out = capsys.readouterr()
    assert "missing PROJ-404" in out.out  # findings print without --verbose
    assert "1 missing" in out.err


def test_verify_reads_input_file(tmp_path, capsys) -> None:
    path = tmp_path / "graph.json"
    path.write_text(_FIXTURE.read_text(), encoding="utf-8")
    rc = cli.main(["atlassian", "verify", "--dry-run", "--input", str(path)])
    assert rc == 0
    assert "check PROJ-123" in capsys.readouterr().out


def test_verify_warns_on_contract_major_mismatch(monkeypatch, capsys) -> None:
    payload = json.loads(_FIXTURE.read_text())
    payload["schema_version"] = "2"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.warns(UserWarning, match="schema_version"):
        rc = cli.main(["atlassian", "verify", "--dry-run"])
    assert rc == 0


def test_atlassian_requires_a_verb() -> None:
    with pytest.raises(SystemExit):
        cli.main(["atlassian"])


_DOCS = Path(__file__).parent / "fixtures_documents.jsonl"


def test_publish_dry_run_needs_no_credentials_or_space(monkeypatch, capsys) -> None:
    _clear_env(monkeypatch)
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_SPACE", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(_DOCS.read_text()))
    rc = cli.main(["atlassian", "publish", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr()
    assert "would upsert page" in out.out
    assert "pushed" in out.err


def test_publish_live_without_space_exits_two(monkeypatch, capsys) -> None:
    _clear_env(monkeypatch)
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_SPACE", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(_DOCS.read_text()))
    rc = cli.main(["atlassian", "publish"])
    assert rc == 2
    assert "ATLASSIAN_CONFLUENCE_SPACE" in capsys.readouterr().err


def test_publish_live_without_credentials_exits_two(monkeypatch, capsys) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(_DOCS.read_text()))
    rc = cli.main(["atlassian", "publish", "--space", "DOCS"])
    assert rc == 2
    assert "ATLASSIAN_API_TOKEN" in capsys.readouterr().err


def test_publish_skips_malformed_line_and_reports(monkeypatch, capsys) -> None:
    lines = _DOCS.read_text() + '{"id": ""}\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(lines))
    rc = cli.main(["atlassian", "publish", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr()
    assert "skip line" in out.out


def test_publish_strict_fails_on_malformed_line(monkeypatch, capsys) -> None:
    lines = _DOCS.read_text() + '{"id": ""}\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(lines))
    rc = cli.main(["atlassian", "publish", "--dry-run", "--strict"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
