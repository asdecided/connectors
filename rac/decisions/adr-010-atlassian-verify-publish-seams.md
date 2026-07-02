---
schema_version: 1
id: LCON-KWGHWM0W2DMV
type: decision
---
# ADR-010: Atlassian Verify and Publish Seams, No SDK

## Context

rac-core ADR-090 places the Atlassian suite in this repo — `atlassian/`, one
subdir spanning both directions on shared Cloud auth — and rac-core ADR-087
explicitly delegates ticket **existence and state checks** here: the engine
format-lints `related_tickets` references offline and never contacts a
ticketing system. The engine side is live: `rac export --graph` marks ticket
edges `external: true` with the configured `provider` (rac-core ADR-074).

Two of the suite's surfaces are scheduled (roadmap `atlassian-connector`):
verifying Jira references, and publishing corpus artifacts to Confluence.
Neither fits the existing seams. `Connector.push` (ADR-002) is an outbound
memory upsert; `GraphConnector.push_graph` (ADR-003) loads a graph image.
Verification is *read-shaped* — it fetches issue state and writes nothing —
and Confluence publish, while outbound, has page-identity and versioning
semantics no memory backend has. ADR-002's rule that a connector "pushes, and
never pulls" guards against one specific shape: a recall/re-rank surface that
would couple reading agents to a backend. An operator-facing state check is
not that shape, but the distinction must be recorded, not assumed.

## Decision

- **Two sibling seams, not overloads.** Following ADR-003's precedent:

  ```python
  class TicketVerifier(Protocol):
      name: str
      def verify(self, graph: Graph, *, dry_run: bool = False) -> VerifySummary: ...

  class PagePublisher(Protocol):
      name: str
      def publish(self, records: Iterable[Record], *, dry_run: bool = False) -> PushSummary: ...
  ```

  `Connector`, `GraphConnector`, their readers, and the existing CLI
  subcommands are untouched (additive — rac-core ADR-007, ADR-063).
- **`verify` does not reopen ADR-002.** It is an operator-facing state check
  delegated by rac-core ADR-087, run against the operator's own instance
  (rac-core ADR-086); it exposes no recall, search, or re-rank surface to a
  reading agent, and it never writes — not to Atlassian, not to the corpus.
- **Verify selects edges by contract markers.** Only edges with
  `external: true` and `provider == "jira"` are checked. `verified_by` edges
  (rac-core ADR-096) carry `provider: null` and are excluded by construction;
  other providers are skipped and counted, never guessed at.
- **No Atlassian SDK.** The connector needs roughly six endpoints; a thin
  internal client on `httpx` (the `[atlassian]` extra) keeps the supply chain
  one dependency wide and makes contract tests trivial via a mock transport.
  This deviates from ADR-002's "backend SDK behind a thin client Protocol"
  pattern deliberately: there is no official Atlassian Python SDK worth
  pinning, and the wrapper libraries chase API churn we would then chase
  second-hand. The client Protocols still exist; only the adapter behind
  them is ours.
- **Cloud first, API-token Basic auth.** Credentials come from the
  environment (`ATLASSIAN_BASE_URL`, `ATLASSIAN_EMAIL`,
  `ATLASSIAN_API_TOKEN`), never hard-coded. The Data Center profile (Bearer
  PAT, v2 Jira endpoints) is a named deferral; the auth seam leaves the slot.
- **Jira reads use bulk fetch.** Verification batches issue keys through
  `POST /rest/api/3/issue/bulkfetch` (100 keys, narrow fields). The classic
  `/search` endpoint no longer exists in Jira Cloud; if search is ever
  needed, it is `POST /search/jql` with cursor pagination.
- **CLI verbs nest under one backend.** `rac-connect atlassian verify` and
  `rac-connect atlassian publish` — the suite will grow verbs (comment-mode,
  ingest), and a flat `atlassian-verify` would fork the backend namespace.
- **Verify exits 3 on findings.** 0 = all references verified, 1 = malformed
  input, 2 = missing credentials (the existing vocabulary), and 3 = one or
  more references missing or forbidden — distinct so CI can gate on state
  without conflating it with operator error.

## Consequences

### Positive

- ADR-087's delegated obligation is discharged on the published contract
  alone; the engine stays offline and pure.
- The seam split keeps the rejected recall/re-rank shape structurally
  impossible: `verify` returns a report, not records.
- Contract tests drive the real request/response wire shape through a mock
  transport instead of faking an SDK's object model.

### Negative / trade-offs

- Four seams now live in `base.py` (`push`, `push_graph`, `verify`,
  `publish`). Accepted: the inputs and outputs are genuinely different
  shapes, and each seam is a handful of lines.
- Owning the HTTP client means owning retry/backoff behaviour. Accepted:
  that behaviour is the part worth testing anyway, and 429/`Retry-After`
  handling is recorded in the design and covered offline.

### Risks

- Atlassian Cloud API churn lands on us directly rather than via a wrapper
  release. Mitigation: a pinned, deliberately small endpoint set; the docs
  page carries a live smoke-test checklist that gates any release tag.
- The verify report tempts growth toward a state-sync. Mitigation: the seam
  returns a summary only; mirroring ticket state into the corpus is
  explicitly out (rac-core ADR-017).

## Status

Accepted

## Category

Architecture

## Alternatives Considered

### Route verification through `GraphConnector.push_graph`

Rejected: verification writes nothing; pretending a read is a push would
falsify the seam's contract and its `PushSummary` shape.

### Use `atlassian-python-api` or `jira` (pycontribs)

Rejected: kitchen-sink wrappers with heavy transitive dependencies, uneven
Cloud/Data-Center behaviour, and their own lag behind Atlassian's endpoint
removals — for six endpoints, a wrapper is more surface than the client it
wraps.

### Flat CLI subcommands (`atlassian-verify`, `atlassian-publish`)

Rejected: the suite is one backend with several verbs (ADR-090 names more to
come); nesting keeps `rac-connect <backend>` one namespace.

### Report findings via exit 0 and output parsing

Rejected: the whole point of verify is a CI gate; a distinct exit code is the
deterministic contract for that.

## Related Decisions

- adr-002
- adr-003
- adr-008
- adr-011

## Related Designs

- atlassian-connector-shape

## Related Roadmaps

- atlassian-connector

## Review Date

Revisit when the Data Center profile or a second verb family (comment-mode,
ingest) is scheduled, or if Atlassian ships an official Python SDK worth
adopting.
