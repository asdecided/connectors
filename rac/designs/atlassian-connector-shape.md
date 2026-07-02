---
schema_version: 1
id: LCON-KWGHWMFFTHY7
type: design
---
# Atlassian Connector Shape: Client, Verify, Publish

## Context

ADR-010 fixes the seams (`TicketVerifier.verify`, `PagePublisher.publish`,
no SDK, Cloud first) and ADR-011 fixes the publish identity model. This
design works the *how*: module layout, client shape, transport behaviour,
the verify report, the rendering subset, and the CLI tree. It is the
Atlassian sibling of `graph-connector-shape`.

## User Need

An operator with a corpus full of `related_tickets` Jira references wants a
CI-runnable check that every reference still points at a real, reachable
issue — and a way to mirror the corpus into the Confluence space where the
rest of the organisation reads, without hand-copying or clobbering human
edits. Both must run from the export contract alone, with `--dry-run`
needing no credentials.

## Design

Module layout, mirroring the per-backend convention:

```text
src/rac_connectors/atlassian/
  __init__.py     re-exports: AtlassianVerifier, AtlassianPublisher, BACKEND,
                  MissingCredentialsError, client_from_env
  client.py       env credentials, JiraClient / ConfluenceClient Protocols,
                  HttpAtlassianClient (httpx, lazy import), backoff
  jira.py         verify_graph(): edge selection, key extraction, bulk fetch,
                  classification; remote-link upsert helper
  render.py       render_storage(markdown) -> str, body_hash(storage) -> str
  confluence.py   publish_records(): property lookup, create/update/skip
  connector.py    AtlassianVerifier / AtlassianPublisher seam implementations
```

`VerifySummary` sits beside `PushSummary` in the shared `base.py`, where the
`TicketVerifier` and `PagePublisher` Protocols also live (the ADR-003
precedent: seams are shared shape, implementations are per-backend).

**Client.** `HttpAtlassianClient` implements both Protocols over one `httpx`
client (imported lazily so the core install stays dependency-free). Base
URLs derive from `ATLASSIAN_BASE_URL`: Jira under `/rest/api/3/`, Confluence
under `/wiki/api/v2/`. Auth is Basic `email:api_token`. Every request runs
through one `_request()` helper: timeout ~30s, sequential (no concurrency),
and a retry loop for 429/5xx honouring `Retry-After` with capped, jittered
exponential backoff (at most 4 retries; the sleep function is injectable so
tests run instantly). 409 on a page update raises `VersionConflictError`;
401/403 raise a permission error the callers classify.

**Verify.** `verify_graph(graph, client, *, dry_run)`:

1. Select edges with `external and provider == "jira"` (ADR-010); count
   everything else it skips (other providers, `verified_by`, in-corpus).
2. Extract issue keys from edge targets — bare `PROJ-123` or a full browse
   URL — and dedupe while remembering every source artifact per key.
3. Batch keys 100 at a time through `POST /issue/bulkfetch` with
   `fields=["status"]`.
4. Classify each key: `exists` (with status name and statusCategory),
   `missing`, or `forbidden`; attribute results back to source artifacts in
   the action log (`RAC-XXXX -> PROJ-123: missing`).

`VerifySummary` carries counts (`checked/exists/missing/forbidden/skipped`),
the per-key action log, a `summary_line()`, and `exit_code` (0 clean, 3
findings). Dry-run lists the keys and batches it would check — no client,
no network.

**Render.** A deterministic Markdown → storage-format subset: ATX headings,
paragraphs, bold/italic/inline code, fenced code blocks (a `code`
structured macro with CDATA-safe escaping), ordered/unordered lists, links.
Everything is HTML-escaped before markup is emitted; unknown constructs
degrade to escaped text. Same input, same bytes — `body_hash` is sha256
over the rendered output.

**Publish.** For each record: render, hash, look up the page by the
`lore.artifact_id` content property in the configured space. Not found →
create (title from the record, optional parent), then set the property
(artifact id + body hash) and the `lore-managed` label. Found, hash equal →
skip as `unchanged`. Found, hash differs → `PUT` with `version.number + 1`
and refresh the property; a 409 becomes a `conflict` action and the stream
continues. The summary is the shared `PushSummary`.

**CLI.**

```text
rac-connect atlassian verify   --input graph.json  [--dry-run] [--verbose]
rac-connect atlassian publish  --input docs.jsonl  [--dry-run] [--strict]
                               [--space KEY] [--verbose]
```

Nested verbs under one `atlassian` subparser, each with its own
`set_defaults(func=...)` — `main()` untouched. Exit codes: verify
0/1/2/3 per ADR-010; publish the standard 0/1/2. Missing credentials name
the exact environment variables. `--space` overrides
`ATLASSIAN_CONFLUENCE_SPACE`.

**Testing.** Connector behaviour and CLI tests drive in-memory fakes of the
two Protocols (the repo's standard pattern). Client contract tests use
`httpx.MockTransport` behind `pytest.importorskip("httpx")`: auth header
shape, bulkfetch body, 429 retry with patched sleep, 409 mapping. Render
has golden fixtures including hostile input (`<script>`, `]]>`, `ac:`
strings). An idempotence test publishes twice and asserts zero writes on
the second pass.

## Constraints

- Consume only the published export contract; never re-derive from Markdown
  (rac-core ADR-063, ADR-073).
- Offline CI: no network, no live Atlassian account, `httpx` optional.
- Corpus content is untrusted input — escape-first rendering, no macro or
  raw-XHTML pass-through (rac-core ADR-065).
- Air-gap posture: the connector talks only to the operator's configured
  instance (rac-core ADR-086).
- Cloud endpoints only in this pass; the Data Center profile is a named
  deferral (ADR-010).

## Rationale

The shape is the smallest one that discharges ADR-087's delegated checks
and ADR-090's publish surface while reusing everything the repo already
has: the graph and documents readers, `PushSummary`, the dry-run
convention, the per-backend module pattern, and the offline test style. The
internal client exists because six endpoints do not justify a wrapper
dependency; the injectable transport and sleep make the risky parts —
backoff, conflict handling — the best-tested parts.

## Alternatives

- **One combined `sync` verb** — rejected: verify is read-only and CI-gated,
  publish writes; conflating them blurs both contracts (ADR-010).
- **Async/concurrent requests** — rejected for now: corpus sizes make
  sequential + bulkfetch fast enough, and determinism matters more than
  throughput.
- **Rendering via a full Markdown-to-XHTML library** — rejected: the corpus
  subset is small, and a hand-rolled deterministic renderer keeps golden
  tests byte-stable and the escape path auditable.

## Accessibility

Published pages carry the artifact's heading structure so Confluence's own
navigation and screen-reader affordances work; the renderer never emits
colour- or layout-only semantics. CLI output stays plain-text,
line-oriented, and readable without colour.

## Style Guidance

Follow the repo's connector conventions: frozen dataclasses for summaries,
`Missing*Error` naming, `client_from_env()`, `--dry-run` that needs no
credentials, action-log lines in the `<verb> <id>: <detail>` shape used by
`PushSummary`, and docs-page metadata driving the README grouping.

## Open Questions

- Orphan adoption: should a later verb list `lore-managed` pages whose
  property no longer matches any exported artifact?
- Page tree shape: flat under one parent first; mirror the corpus directory
  structure later?
- `--json` report output for verify: scheduled as a follow-up; the exit
  code is the day-one machine contract.

## Related Decisions

- adr-010
- adr-011

## Related Roadmaps

- atlassian-connector
