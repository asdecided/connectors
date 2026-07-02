---
schema_version: 1
id: LCON-KWGHWM84VSVH
type: decision
---
# ADR-011: Confluence Page Identity and Idempotent Publish

## Context

The `publish` seam (ADR-010) mirrors corpus artifacts into a Confluence
space. Every existing connector is idempotent on the canonical artifact `id`
(ADR-002), and publish must be too — but Confluence has no native
upsert-by-external-id. The mature Markdown publishers show the failure
modes: title-keyed lookup orphans pages on rename and creates duplicates;
writing the page id back into the source binds cleanly but mutates the
input. Our input is a read-only export stream, and corpus writes are
propose-only via human PR review (rac-core ADR-065) — id write-back is not
available to us even if we wanted it.

Two further Confluence realities shape the decision: the API normalizes
stored XHTML, so read-body-and-compare is not a reliable change detector;
and updates are optimistic-concurrency versioned, so a stale version number
means someone else edited the page.

## Decision

- **Page identity is a content property, never the title.** Each managed
  page carries the content property `lore.artifact_id` holding the canonical
  artifact id, plus a `lore-managed` label. Upsert resolves artifact →
  page by that property within the configured space; the title is display
  only and free to change with the artifact.
- **No state outside Confluence.** The artifact-to-page mapping lives on
  the pages themselves — no local state file, no id write-back into the
  corpus (rac-core ADR-065).
- **Change detection is a body hash.** The property also stores a sha256 of
  the rendered storage-format body. Unchanged hash → the record is skipped
  without a write, so a second publish over an unchanged corpus performs
  zero writes.
- **Updates are version-checked and never forced.** `PUT` sends
  `version.number = current + 1`; a 409 conflict is recorded as a conflict
  action in the summary and the stream continues. The connector never
  overwrites an edit it did not make.
- **Rendering is deterministic and escape-first.** Artifact Markdown renders
  to storage format through a fixed, deliberately small subset (headings,
  paragraphs, emphasis, code, fenced blocks, lists, links). All corpus
  content is HTML-escaped before any markup is emitted — artifact content is
  untrusted input (rac-core ADR-065), so no corpus text can smuggle a macro
  or raw XHTML into the page.
- **Jira backlinks ride the same idempotency.** When publish is asked to
  link referenced issues back to their artifacts, it upserts a remote issue
  link with `globalId = "lore:<ARTIFACT_ID>"` — Jira's native
  same-`globalId` upsert makes re-runs update in place, never duplicate.

## Consequences

### Positive

- Re-publish is safe by construction, mirroring every other connector's
  idempotent-on-`id` contract; renames are ordinary updates.
- Human edits to managed pages are surfaced as conflicts, not silently
  clobbered — consistent with the trust boundary that humans, not tools,
  have the last word.
- The hash check makes the steady-state publish cheap: reads only.

### Negative / trade-offs

- A page manually stripped of its property/label becomes invisible to the
  connector and a fresh publish creates a sibling. Accepted: the label makes
  managed pages discoverable, and adopting orphans is a listable follow-up.
- The rendering subset drops constructs (tables first among them) that
  full-fat publishers support. Accepted: fidelity grows additively; golden
  tests pin what is supported.

### Risks

- Confluence content-property APIs differ subtly between Cloud v2 and Data
  Center. Mitigation: Cloud first (ADR-010); the property/label scheme
  itself is portable.
- Hash-skip hides drift if Confluence rewrites stored XHTML more
  aggressively than expected. Mitigation: the hash is of *our* rendered
  output, not the read-back body, so skips are decided entirely on our side.

## Status

Accepted

## Category

Architecture

## Alternatives Considered

### Title-keyed page lookup

Rejected: renames orphan pages and duplicate on next publish — the exact
failure mode the property scheme exists to prevent.

### Page-id write-back into the corpus

Rejected: the export stream is a read-only contract surface, and corpus
writes are propose-only via human PR (rac-core ADR-065).

### Read the stored body and diff for change detection

Rejected: Confluence normalizes stored XHTML, so byte comparison flaps;
hashing our own rendered output is deterministic.

### Force updates on version conflict

Rejected: a conflict means a human edited the page; the connector defers to
humans by contract.

## Related Decisions

- adr-010
- adr-002

## Related Designs

- atlassian-connector-shape

## Related Roadmaps

- atlassian-connector

## Review Date

Revisit when orphan adoption, table rendering, or the Data Center profile is
scheduled, or if Confluence ships a native external-id upsert.
