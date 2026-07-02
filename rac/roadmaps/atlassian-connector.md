---
schema_version: 1
id: LCON-KWGHWMPN043M
type: roadmap
---
# Atlassian Connector: Verify and Publish

## Status

Planned

## Context

rac-core schedules the Atlassian suite (roadmap `atlassian`, ADR-090) and
delegates Jira existence/state checks to this repo (rac-core ADR-087). This
item is the delivery track for the first two surfaces: the `verify` verb
over the `--graph` projection and the `publish` verb over `--documents`,
under the seams fixed by ADR-010 and the identity model fixed by ADR-011.

## Outcomes

- `rac export <dir> --graph | rac-connect atlassian verify` checks every
  Jira `related_tickets` reference against the operator's instance and
  exits 3 on missing/forbidden references, 0 when clean.
- `rac export <dir> --documents | rac-connect atlassian publish` mirrors
  artifacts into a Confluence space as managed pages; a second run over an
  unchanged corpus performs zero writes.
- The connector ships as `rac_connectors.atlassian` with an `[atlassian]`
  extra, offline tests, and a docs page — the repo's standard shape.

## Initiatives

- **Contract reader** — surface the graph edges' `external`/`provider`
  markers already emitted by the export (additive to `graph.py`).
- **Client** — env-configured `httpx` client with Basic auth, backoff, and
  the Jira/Confluence Protocol pair (ADR-010).
- **Verify verb** — edge selection, key extraction, bulk fetch,
  classification, `VerifySummary`, CLI wiring, exit-code contract.
- **Publish verb** — deterministic storage-format rendering, property-keyed
  page upsert, hash skip, conflict surfacing (ADR-011), CLI wiring.
- **Docs and packaging** — connector page (with the live smoke-test
  checklist that gates any release tag), README sync, CHANGELOG, extra,
  CI install.

## Success Measures

- The full battery passes offline on 3.11–3.13 with and without `httpx`
  installed.
- Verify: dry-run needs no credentials; missing creds exit 2 naming the
  variables; findings exit 3; a graph with only github/`verified_by`
  edges exits 0 with everything counted as skipped.
- Publish: the idempotence test (second run = zero writes) and the 409
  conflict test pass; hostile corpus content renders escaped in the golden
  fixtures.

## Assumptions

- Export contract major 1; edges carry `external`/`provider` as shipped in
  rac-core v0.25.0.
- One Cloud site and one Confluence space per run is enough for the first
  delivery.
- `httpx` is an acceptable optional dependency for CI contract tests
  (ADR-010).

## Risks

- Endpoint churn on Jira Cloud (the `/search` removal precedent).
  Mitigation: bulkfetch-first design, thin client, smoke-test checklist
  before any tag.
- Rendering fidelity disappointments. Mitigation: small pinned subset,
  golden tests, additive growth.
- Scope pull toward inbound sync. Mitigation: inbound ingest and
  comment-mode stay separate, gated roadmap items (rac-core ADR-017,
  ADR-065).

## Related Decisions

- adr-010
- adr-011
- adr-002
- adr-003
- adr-008

## Related Designs

- atlassian-connector-shape

## Related Roadmaps

- graph-connector

## Related Tickets

- itsthelore/rac-connectors#4
- itsthelore/rac-connectors#5
- itsthelore/rac-connectors#6
- itsthelore/rac-connectors#7
- itsthelore/rac-connectors#8
- itsthelore/rac-connectors#9
- itsthelore/rac-connectors#10
