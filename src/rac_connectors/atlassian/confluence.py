"""Confluence page publish over the ``--documents`` projection (ADR-011).

For each record: render, hash, resolve the managed page by the artifact-id
content property, then create / update / skip. A version conflict is a
human's edit — recorded and left alone, never overwritten. A second publish
over an unchanged corpus performs zero writes (the hash skip).
"""

from __future__ import annotations

from collections.abc import Iterable

from ..base import PushSummary
from ..records import Record
from .client import MANAGED_LABEL, ConfluenceClient, VersionConflictError
from .render import body_hash, render_storage


def publish_records(
    records: Iterable[Record],
    client: ConfluenceClient | None,
    *,
    space_key: str,
    dry_run: bool = False,
) -> PushSummary:
    """Upsert ``records`` as managed pages in ``space_key``.

    With ``dry_run=True`` no client is needed and no call is made — the
    summary lists each page that would be upserted with its body hash.
    """
    summary = PushSummary(backend="atlassian", dry_run=dry_run)

    if not dry_run and client is None:
        raise RuntimeError(
            "a live publish needs a Confluence client; pass client_from_env() "
            "or use dry_run=True"
        )

    for record in records:
        storage = render_storage(record.text)
        digest = body_hash(storage)

        if dry_run:
            space = space_key or "<space unset>"
            summary.record_push(
                record.id,
                f"would upsert page {record.title!r} in {space} (hash {digest[:12]})",
            )
            continue

        assert client is not None  # narrowed by the guard above
        page = client.find_managed_page(space_key=space_key, artifact_id=record.id)

        if page is None:
            page_id = client.create_page(
                space_key=space_key, title=record.title, storage_body=storage
            )
            client.set_managed_property(
                page_id=page_id, artifact_id=record.id, body_hash=digest
            )
            client.add_label(page_id=page_id, label=MANAGED_LABEL)
            summary.record_push(record.id, f"created page {page_id} {record.title!r}")
            continue

        if page.body_hash == digest:
            summary.record_skip_item(record.id, f"unchanged (page {page.page_id})")
            continue

        try:
            client.update_page(
                page_id=page.page_id,
                version=page.version,
                title=record.title,
                storage_body=storage,
            )
        except VersionConflictError:
            # A human edited the page since our last write; surface it and
            # move on — the connector never wins that race (ADR-011).
            summary.record_skip_item(
                record.id,
                f"version conflict on page {page.page_id}; not overwritten",
            )
            continue
        client.set_managed_property(
            page_id=page.page_id, artifact_id=record.id, body_hash=digest
        )
        summary.record_push(record.id, f"updated page {page.page_id}")

    return summary
