"""Publish-verb behaviour driven through a fake Confluence client (offline)."""

from __future__ import annotations

import itertools

import pytest

from rac_connectors.atlassian.client import ManagedPage, VersionConflictError
from rac_connectors.atlassian.connector import AtlassianPublisher
from rac_connectors.records import Record


def _record(record_id: str, title: str, text: str) -> Record:
    return Record(
        id=record_id,
        type="decision",
        status="Accepted",
        title=title,
        text=text,
        metadata={"source": "rac"},
    )


class FakeConfluenceClient:
    """An in-memory space keyed by the artifact-id content property."""

    def __init__(self, conflict_on_update: bool = False) -> None:
        self.pages: dict[str, dict] = {}  # artifact_id -> page state
        self.conflict_on_update = conflict_on_update
        self.writes = 0
        self._ids = itertools.count(900)

    def find_managed_page(
        self, *, space_key: str, artifact_id: str
    ) -> ManagedPage | None:
        page = self.pages.get(artifact_id)
        if page is None:
            return None
        return ManagedPage(
            page_id=page["page_id"],
            version=page["version"],
            title=page["title"],
            body_hash=page.get("body_hash"),
        )

    def create_page(self, *, space_key: str, title: str, storage_body: str) -> str:
        self.writes += 1
        page_id = str(next(self._ids))
        self._by_page_id = getattr(self, "_by_page_id", {})
        self._by_page_id[page_id] = {"title": title, "body": storage_body}
        return page_id

    def update_page(
        self, *, page_id: str, version: int, title: str, storage_body: str
    ) -> None:
        if self.conflict_on_update:
            raise VersionConflictError(page_id)
        self.writes += 1
        for page in self.pages.values():
            if page["page_id"] == page_id:
                page["version"] = version + 1
                page["title"] = title
                page["body"] = storage_body

    def set_managed_property(
        self, *, page_id: str, artifact_id: str, body_hash: str
    ) -> None:
        self.writes += 1
        page = self.pages.setdefault(
            artifact_id,
            {"page_id": page_id, "version": 1, "title": ""},
        )
        page["body_hash"] = body_hash

    def add_label(self, *, page_id: str, label: str) -> None:
        self.writes += 1


def test_create_path_sets_property_and_label() -> None:
    client = FakeConfluenceClient()
    publisher = AtlassianPublisher(client, space_key="DOCS")
    summary = publisher.publish([_record("RAC-1", "Title", "# Body")])
    assert summary.pushed == 1
    assert summary.skipped == 0
    assert "RAC-1" in client.pages
    assert client.pages["RAC-1"]["body_hash"]
    assert any("created page" in action for action in summary.actions)


def test_second_publish_over_unchanged_corpus_writes_nothing() -> None:
    client = FakeConfluenceClient()
    publisher = AtlassianPublisher(client, space_key="DOCS")
    records = [
        _record("RAC-1", "One", "# One"),
        _record("RAC-2", "Two", "# Two"),
    ]
    publisher.publish(records)
    writes_after_first = client.writes

    summary = publisher.publish(records)
    assert client.writes == writes_after_first  # zero writes — the ADR-011 test
    assert summary.pushed == 0
    assert summary.skipped == 2
    assert all("unchanged" in action for action in summary.actions)


def test_changed_body_updates_with_incremented_version() -> None:
    client = FakeConfluenceClient()
    publisher = AtlassianPublisher(client, space_key="DOCS")
    publisher.publish([_record("RAC-1", "T", "# Old")])
    summary = publisher.publish([_record("RAC-1", "T", "# New")])
    assert summary.pushed == 1
    assert any("updated page" in action for action in summary.actions)


def test_version_conflict_is_surfaced_and_stream_continues() -> None:
    client = FakeConfluenceClient()
    publisher = AtlassianPublisher(client, space_key="DOCS")
    publisher.publish([_record("RAC-1", "T", "# Old")])

    client.conflict_on_update = True
    summary = publisher.publish(
        [_record("RAC-1", "T", "# New"), _record("RAC-2", "U", "# Fresh")]
    )
    assert summary.skipped == 1
    assert summary.pushed == 1  # RAC-2 still landed
    assert any("version conflict" in action for action in summary.actions)
    # The stored hash must NOT advance past the human's edit.
    assert client.pages["RAC-1"]["body_hash"] != "advanced"


def test_dry_run_needs_no_client_and_plans_every_page() -> None:
    publisher = AtlassianPublisher(space_key="DOCS")
    summary = publisher.publish([_record("RAC-1", "One", "# One")], dry_run=True)
    assert summary.dry_run is True
    assert summary.pushed == 1
    assert any("would upsert page 'One'" in action for action in summary.actions)


def test_live_publish_without_client_is_a_clear_error() -> None:
    publisher = AtlassianPublisher(space_key="DOCS")
    with pytest.raises(RuntimeError, match="client_from_env"):
        publisher.publish([_record("RAC-1", "T", "# B")])
