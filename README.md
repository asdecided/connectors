# AsDecided Connectors

<p align="center">
<a href="#quickstart">Quickstart</a> ·
<a href="#how-it-works">How it works</a> ·
<a href="#connectors">Connectors</a> ·
<a href="#add-a-backend">Add a backend</a> ·
<a href="https://github.com/asdecided/core">Lore / RAC</a>
</p>

<p align="center">
<a href="https://github.com/asdecided/connectors/actions/workflows/ci.yml"><img src="https://github.com/asdecided/connectors/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python">
<a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/types-Mypy-blue.svg" alt="Typed"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0"></a>
</p>

> **Push the decisions your team already recorded into the memory and RAG tools your agent already uses — so it can recall fuzzily there, then verify in Lore.**

This repository is the **outbound** companion to [AsDecided Core](https://github.com/asdecided/core). It ships stable export payloads into the external memory, RAG, graph, and collaboration backends a team already runs. It is a *consumer of the engine contract*, not part of the engine: embeddings, vectors, and model calls remain the configured backend's responsibility.

## How it compares

A connector isn't a sync tool or a second source of truth — it keeps a fuzzy
backend **fresh** so an agent can recall loosely, then return to Lore for the
exact, current decision. Recall fuzzily, verify in Lore.

| | Lore | The backend (Supermemory / RAG / memory) |
|---|---|---|
| Good at | the exact, current decision | finding what's *near* a question |
| Retrieval | deterministic, reproducible | similarity-ranked, varies by run |
| Role | source of truth, read-only | a fast index this connector keeps fresh |
| Direction | the agent verifies here | this connector pushes here, one-way |

## Quickstart

1. **Install** a connector — pick your backend from [Connectors](#connectors) and
   install its extra (see [Install](#install) for the from-source command until
   it's on PyPI):

   ```bash
   pip install 'rac-connectors[supermemory]'
   ```

2. **Authenticate** the backend via the environment (never hard-coded):

   ```bash
   export SUPERMEMORY_API_KEY=sk-...
   ```

3. **Push** the corpus — pipe a `rac export --documents` stream straight in:

   ```bash
   rac export rac/ --documents | rac-connect supermemory
   ```

4. **Preview** first if you like — `--dry-run` calls no API:

   ```bash
   rac export rac/ --documents | rac-connect supermemory --dry-run
   ```

Re-running is idempotent: a re-push updates rather than duplicates. Each
backend's exact commands, auth, and flags live under [Connectors](#connectors).

## Install

There is nothing to build — it's pure Python. Installing puts a `rac-connect`
command on your PATH.

**From PyPI** (once published — the name is reserved):

```bash
pip install 'rac-connectors[supermemory]'
```

**From source today** (pre-release — install straight from the repo):

```bash
# one-liner, no clone:
pip install 'rac-connectors[supermemory] @ git+https://github.com/asdecided/connectors.git'

# or from a clone (editable, for hacking on it):
git clone https://github.com/asdecided/connectors.git
cd rac-connectors
pip install -e '.[supermemory]'
```

| Extra | Gets you |
|---|---|
| *(none)* | the `rac-connect` CLI + the connector library + `--dry-run` |
| `[<backend>]` | + that backend's SDK, needed for a live push — one per connector (see [Connectors](#connectors)) |
| `[dev]` | + ruff, mypy, and pytest for development |

Requires Python 3.11+, and the [`rac`](https://github.com/asdecided/core)
engine (`pip install requirements-as-code`) to produce the export. The core
install and the whole test-suite are dependency-free — provider SDKs are
optional extras, so CI never needs a live backend.

## How it works

```text
rac export rac/ --documents        # Lore emits one JSON line per artifact
        │
        ▼
rac-connect supermemory           # this repo: upsert each record into the backend
        │
        ▼
Supermemory  (fuzzy, associative recall)
        │
        ▼  the agent recalls a candidate by id, then…
get_artifact / rac resolve         # …verifies the authoritative text in Lore
```

- **One-way, outbound only.** The connector pushes to the backend and never
  pulls, re-ranks, or routes; the verify-in-Lore loop is the reading agent's
  job, not this connector's.
- **Idempotent on the canonical `id`.** Each record maps to
  `add(content=text, container_tag=metadata.source, metadata={id, type, status, …}, custom_id=id)`,
  so re-exporting and re-pushing updates the stored copy instead of duplicating
  it.
- **No embeddings here.** The backend embeds; the connector only ships text and
  metadata (rac-core ADR-002, ADR-066).

## Connectors

One package, one CLI: pick a backend with a subcommand (`rac-connect
<backend>`) and pull only its SDK via the matching extra. Each connector's full
page lives in [`docs/connectors/`](docs/connectors/); the collapsible sections
below are generated from those pages, so this README and the pages never drift.

<!-- GENERATED:CONNECTORS -->
<!-- Generated from docs/connectors/*.md by scripts/sync_readme.py — do not edit by hand. -->

### Memory & RAG

<details>
<summary><strong>Supermemory</strong> — documents → server-side embedding, idempotent on the canonical id</summary>

A one-way, outbound push of the `rac export --documents` stream into
[Supermemory](https://supermemory.ai).

```bash
pip install 'rac-connectors[supermemory]'
export SUPERMEMORY_API_KEY=sk-...

rac export rac/ --documents | rac-connect supermemory            # upsert every record
rac export rac/ --documents | rac-connect supermemory --dry-run  # preview, no API call
rac-connect supermemory --input corpus.jsonl                     # read a file, not stdin
```

Each record maps to a Supermemory upsert:

```
record → add(content=text,
             container_tag=metadata.source,
             metadata={rac id, type, status, title, path, …},
             custom_id=id)
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print what would be sent; make no API call. |
| `--input`, `-i` | Read JSONL from a file (default: stdin; `-` also means stdin). |
| `--strict` | Fail on a malformed line instead of skipping it. |
| `--verbose`, `-v` | Print per-record actions on a live push too. |

- **Idempotent on the canonical `id`.** `custom_id=id` makes a re-push an update,
  not a duplicate.
- **No embeddings here.** Supermemory embeds; the connector only ships text +
  metadata.
- **Auth via `SUPERMEMORY_API_KEY`** — never hard-coded. Set
  `SUPERMEMORY_BASE_URL` to point at a self-hosted instance.

Decision: [`rac/decisions/`](rac/decisions) — the connector seam (ADR-002).

**Full page:** [`docs/connectors/supermemory.md`](docs/connectors/supermemory.md)

</details>

<details>
<summary><strong>Mem0</strong> — documents → server-side embedding; idempotent by container resync</summary>

A one-way, outbound push of the `rac export --documents` stream into
[Mem0](https://mem0.ai). Same stream and flags as the other documents backends,
a different subcommand:

```bash
pip install 'rac-connectors[mem0]'
export MEM0_API_KEY=m0-...

rac export rac/ --documents | rac-connect mem0            # upsert every record
rac export rac/ --documents | rac-connect mem0 --dry-run  # preview, no API call
rac-connect mem0 --input corpus.jsonl                     # read a file, not stdin
```

- **Stores the text as-is.** `infer=False` skips Mem0's LLM fact-extraction, so it
  only embeds the artifact text; the canonical `rac_id`, `type`, `status`, and
  `title` ride in metadata for the verify-in-Lore loop.
- **Idempotent by container resync.** Mem0 has no per-record upsert key, so each
  push clears the corpus partition (Mem0 `user_id = source`) and re-adds —
  re-running never duplicates. The trade-off (a wipe-and-rebuild rather than a
  surgical update) is recorded in the decision.
- **No embeddings here.** Mem0 embeds; the connector only ships text + metadata.
- **Auth via `MEM0_API_KEY`** — never hard-coded.

Decision: [`rac/decisions/`](rac/decisions) — ADR-004 (Mem0 backend, resync idempotency).

**Full page:** [`docs/connectors/mem0.md`](docs/connectors/mem0.md)

</details>

<details>
<summary><strong>Qdrant</strong> — documents → external embedding → a Qdrant collection; idempotent on the canonical id</summary>

A one-way, outbound push of the `rac export --documents` stream into
[Qdrant](https://qdrant.tech), the open-source vector database.

Qdrant stores vectors but does **not** produce them (unlike Supermemory/Mem0/Zep,
which embed server-side). So this connector embeds each record's text through a
**configured external embedding service** — any OpenAI-compatible `/embeddings`
endpoint, with a [LiteLLM](https://litellm.ai) gateway the reference deployment —
then upserts the vector. The model and credentials live in that endpoint, never
in RAC (the engine stays AI-optional, rac-core ADR-002/ADR-066); see
[ADR-009](rac/decisions/adr-009-vector-store-connectors-embed-externally.md).

```bash
pip install 'rac-connectors[qdrant]'
export QDRANT_URL=http://localhost:6333          # and QDRANT_API_KEY if your server needs auth
export RAC_EMBED_BASE_URL=https://your-litellm/v1 # OpenAI-compatible /embeddings endpoint
export RAC_EMBED_MODEL=text-embedding-3-small      # whatever your gateway routes
export RAC_EMBED_API_KEY=sk-...                    # if the endpoint requires auth

rac export rac/ --documents | rac-connect qdrant            # embed + upsert every record
rac export rac/ --documents | rac-connect qdrant --dry-run  # preview, no embed, no API call
rac-connect qdrant --input corpus.jsonl                     # read a file, not stdin
```

Each record maps to one Qdrant point:

```
record → upsert(point_id=uuid5(canonical id),
                vector=embed(text),
                payload={rac_id, type, status, title, text, …metadata})
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print what would be sent; embed nothing and call no API. |
| `--input`, `-i` | Read JSONL from a file (default: stdin; `-` also means stdin). |
| `--strict` | Fail on a malformed line instead of skipping it. |
| `--verbose`, `-v` | Print per-record actions on a live push too. |

- **Idempotent on the canonical `id`.** The point id is `uuid5(id)`, so a re-push
  upserts in place rather than duplicating.
- **One collection per corpus `source`** (falling back to `lore`); the collection
  is created on first use with the embedder's vector dimension and cosine distance.
- **Embeddings live in the external endpoint**, not here. **Pin the embedding
  model** — the vectors, and the collection's dimension, are tied to it; changing
  the model means re-embedding the corpus.
- **Auth via `QDRANT_URL` / `QDRANT_API_KEY`** and the `RAC_EMBED_*` variables —
  never hard-coded.

### Live smoke test

The connector is wired and unit-tested against fakes, but the live path (a real
Qdrant plus a real embeddings endpoint) is unproven until someone runs it — this
page is `drafted (live run pending)`. To validate end to end:

1. **Start Qdrant:** `docker run -p 6333:6333 qdrant/qdrant`.
2. **Pick an embeddings endpoint** — a LiteLLM (or any OpenAI-compatible)
   `/embeddings` gateway; note the model and its vector dimension.
3. **Configure the environment:**

   ```bash
   export QDRANT_URL=http://localhost:6333       # + QDRANT_API_KEY if needed
   export RAC_EMBED_BASE_URL=https://your-litellm/v1
   export RAC_EMBED_MODEL=text-embedding-3-small
   export RAC_EMBED_API_KEY=sk-...                # if the endpoint requires it
   ```

4. **Dry-run first** (no embed, no calls) — confirms records and collections:
   `rac export rac/ --documents | rac-connect qdrant --dry-run`.
5. **Live push:** `rac export rac/ --documents | rac-connect qdrant`.
6. **Verify in Qdrant:** the collection (named after the corpus `source`,
   default `lore`) exists with the model's vector size; the point count equals the
   artifact count; a point's payload carries `rac_id`, `type`, `status`, `title`,
   and `text`.
7. **Re-run the push** and confirm the point count is unchanged — the upsert is
   idempotent on `uuid5(rac_id)`.

Then flip this page's `status` to `shipped`.

**Full page:** [`docs/connectors/qdrant.md`](docs/connectors/qdrant.md)

</details>

<details>
<summary><strong>Letta</strong> — documents → Letta archives (cloud or self-hosted); idempotent by archive resync</summary>

A one-way, outbound push of the `rac export --documents` stream into
[Letta](https://letta.com) archives. Same stream and flags as the other
documents backends, a different subcommand:

```bash
pip install 'rac-connectors[letta]'
export LETTA_API_KEY=...                       # Letta Cloud
# or, self-hosted:  export LETTA_BASE_URL=http://localhost:8283

rac export rac/ --documents | rac-connect letta            # upsert every record
rac export rac/ --documents | rac-connect letta --dry-run  # preview, no API call
rac-connect letta --input corpus.jsonl                     # read a file, not stdin
```

- **A corpus maps to a Letta archive.** A `source` becomes a named archive; each
  record is added as a passage carrying the canonical `rac_id`, `type`,
  `status`, and `title` in metadata. (The connector resolves the opaque
  `archive_id` internally, so you address it by the source name.)
- **Idempotent by archive resync.** Letta has no per-record upsert key, so each
  push deletes and recreates the corpus archive, then re-adds — re-running never
  duplicates.
- **Cloud or self-hosted.** Auth via `LETTA_API_KEY` (Letta Cloud) **or**
  `LETTA_BASE_URL` (a self-hosted server). Letta embeds the passages; nothing is
  embedded here.

Decision: [`rac/decisions/`](rac/decisions) — ADR-006 (Letta backend, archive-resync idempotency).

**Full page:** [`docs/connectors/letta.md`](docs/connectors/letta.md)

</details>

### Knowledge graph

<details>
<summary><strong>Zep</strong> — documents → a Zep knowledge graph; idempotent by graph resync</summary>

A one-way, outbound push of the `rac export --documents` stream into
[Zep Cloud](https://getzep.com). Same stream and flags as the other documents
backends, a different subcommand:

```bash
pip install 'rac-connectors[zep]'
export ZEP_API_KEY=z_...

rac export rac/ --documents | rac-connect zep            # upsert every record
rac export rac/ --documents | rac-connect zep --dry-run  # preview, no API call
rac-connect zep --input corpus.jsonl                     # read a file, not stdin
```

- **A corpus maps to a Zep graph.** A `source` becomes a Zep `graph_id`; each
  record is added as a `type="text"` episode carrying the canonical `rac_id`,
  `type`, `status`, and `title` in metadata.
- **Idempotent by graph resync.** Zep has no per-record upsert key, so each push
  deletes and recreates the corpus graph, then re-adds — re-running never
  duplicates.
- **No embeddings here.** Zep derives its knowledge graph and embeds; the
  connector only ships text + metadata. Zep's copy is an associative index, not a
  citation — authoritative text is always re-fetched from Lore.
- **Auth via `ZEP_API_KEY`** — never hard-coded.

Decision: [`rac/decisions/`](rac/decisions) — ADR-005 (Zep backend, graph-resync idempotency).

**Full page:** [`docs/connectors/zep.md`](docs/connectors/zep.md)

</details>

<details>
<summary><strong>Cognee</strong> — documents → a Cognee knowledge graph; content-hash idempotent</summary>

The odd one out: [Cognee](https://www.cognee.ai) is an async pipeline that builds
the corpus into a **knowledge graph** (`add` then `cognify`) rather than a
per-record store. It still consumes the same `rac export --documents` stream:

```bash
pip install 'rac-connectors[cognee]'
export LLM_API_KEY=...        # Cognee needs an LLM to cognify

rac export rac/ --documents | rac-connect cognee            # build the graph
rac export rac/ --documents | rac-connect cognee --dry-run  # preview, no pipeline run
rac-connect cognee --input corpus.jsonl                     # read a file, not stdin
```

- **A corpus maps to a Cognee dataset.** Each record is staged with a `Rac-Id:`
  provenance header (Cognee has no per-record metadata filter), then the whole
  dataset is built once via `add` + `cognify`.
- **Content-hash idempotency, not a resync.** Cognee's native
  `incremental_loading` dedups by content hash, so re-pushing unchanged records
  is a no-op. **Caveat:** it does **not** prune artifacts deleted from the corpus
  (unlike the wipe-and-rebuild backends).
- **No embeddings here.** Cognee builds the graph and embeds; the connector only
  ships text. Auth via `LLM_API_KEY` (Cognee's LLM credential).

Decision: [`rac/decisions/`](rac/decisions) — ADR-007 (Cognee backend, two-phase pipeline, the deletion-prune trade-off).

**Full page:** [`docs/connectors/cognee.md`](docs/connectors/cognee.md)

</details>

<details>
<summary><strong>Neo4j</strong> — graph → typed nodes & edges via Cypher MERGE; idempotent on the canonical id</summary>

The other export projection, `rac export --graph`, is Lore's *real, validated*
relationship graph — typed nodes and edges (`supersedes`, `related_decisions`,
…). The [Neo4j](https://neo4j.com) connector loads it so an agent can traverse
the actual decision graph instead of one an LLM inferred from prose:

```bash
pip install 'rac-connectors[neo4j]'
export NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=...

rac export rac/ --graph | rac-connect neo4j            # upsert nodes + edges
rac export rac/ --graph | rac-connect neo4j --dry-run  # preview, no connection
rac-connect neo4j --input graph.json                   # read a file, not stdin
```

- **Idempotent via Cypher `MERGE`** on the canonical `id` — nodes
  `MERGE (n:Artifact {id})`, edges `MERGE (a)-[r:REL {type}]->(b)` — so a re-push
  updates in place and never duplicates a node or relationship.
- **Faithful to the export.** Undirected edges (`directed:false`) are written
  once carrying `directed=false`; unresolved references (`resolved:false`) are
  skipped, never written as phantom nodes.
- **Injection-safe.** Every node and edge value is a query parameter; only the
  fixed labels `Artifact`/`REL` are interpolated, so no corpus content reaches
  Cypher as code.
- **Outbound only.** It writes the graph and never queries, traverses, or
  analyses — the verify-in-Lore loop stays the agent's job. Auth via `NEO4J_URI`
  / `NEO4J_USERNAME` / `NEO4J_PASSWORD`.

### The `--graph` contract it consumes

`rac export <dir> --graph` emits one JSON object of typed nodes and edges:

```json
{"schema_version":"1","source":"rac",
 "nodes":[{"id":"RAC-…","type":"decision","status":"Accepted","title":"…"}],
 "edges":[{"source":"RAC-…","target":"RAC-…","type":"supersedes",
           "directed":true,"resolved":true}]}
```

`edges[].type` is the real relationship kind with its registry direction;
`resolved:false` means the reference didn't resolve and `target` is literal text.
The contract is additive and stable (rac-core ADR-007).

### Python API

```python
from rac_connectors import parse_graph
from rac_connectors.neo4j import Neo4jConnector, client_from_env

graph = parse_graph(open("graph.json").read())
summary = Neo4jConnector(client_from_env()).push_graph(graph)
print(summary.summary_line())       # -> "neo4j push: 1494 pushed, 0 skipped"
```

Pass `dry_run=True` to preview without a client or a connection.

Design + decision: [`rac/designs/`](rac/designs) (graph-connector-shape) and
[`rac/decisions/`](rac/decisions) (ADR-003).

**Full page:** [`docs/connectors/neo4j.md`](docs/connectors/neo4j.md)

</details>

### Workspace & ticketing

<details>
<summary><strong>Atlassian</strong> — Jira related_tickets verification + Confluence managed-page publish over the export contracts</summary>

The Atlassian suite connector (rac-core ADR-090): **verify** that every Jira
reference in the corpus still points at a real, reachable issue, and
**publish** the corpus into a Confluence space as managed pages. Both verbs
are thin consumers of the export contracts; the engine never talks to
Atlassian (rac-core ADR-087), and the connector only ever contacts the
instance you configure (rac-core ADR-086). No Atlassian SDK — an internal
`httpx` client, see [ADR-010](rac/decisions/adr-010-atlassian-verify-publish-seams.md).

```bash
pip install 'rac-connectors[atlassian]'
export ATLASSIAN_BASE_URL=https://yourorg.atlassian.net
export ATLASSIAN_EMAIL=you@example.com
export ATLASSIAN_API_TOKEN=...                 # id.atlassian.com API token
export ATLASSIAN_CONFLUENCE_SPACE=DOCS         # publish only; or pass --space

rac export rac/ --graph     | rac-connect atlassian verify            # check Jira refs
rac export rac/ --graph     | rac-connect atlassian verify --dry-run  # list, no calls
rac export rac/ --documents | rac-connect atlassian publish           # mirror pages
rac export rac/ --documents | rac-connect atlassian publish --dry-run # plan, no calls
```

## `verify` — read-only Jira reference checks

Selects the `--graph` projection's ticket edges by contract markers
(`external: true`, `provider: "jira"` — set from your repo's
`ticketing.provider`, rac-core ADR-087), dedupes the issue keys (bare
`PROJ-123` or full `/browse/` URLs), fetches them 100 at a time through
Jira's bulk-fetch endpoint with `fields=["status"]`, and reports each as
**exists** (with status and statusCategory), **missing**, or **forbidden**
— attributed back to the referencing artifacts. `verified_by` edges
(rac-core ADR-096) and other providers' tickets are counted as skipped,
never guessed at. It writes nothing, anywhere.

| Exit code | Meaning |
|---|---|
| 0 | Every checked reference exists. |
| 1 | The input was not a valid `--graph` payload. |
| 2 | Credentials missing from the environment. |
| 3 | One or more references are missing or forbidden — the CI gate. |

| Flag | Meaning |
|---|---|
| `--dry-run` | List the references and batches that would be checked; no client, no calls. |
| `--input`, `-i` | Read the `--graph` JSON from a file (default: stdin; `-` also means stdin). |
| `--verbose`, `-v` | Print per-reference results on a live verify too (findings always print). |

## `publish` — managed Confluence pages

Mirrors the `--documents` stream into one space, idempotent on the canonical
artifact id ([ADR-011](rac/decisions/adr-011-confluence-page-identity-and-idempotency.md)):

- **Page identity is a content property** (`lore.artifact_id`) plus a
  `lore-managed` label — never the title, so artifact renames are ordinary
  updates; and no page id is ever written back into the corpus (write-back
  is propose-only via human PR, rac-core ADR-065).
- **Unchanged pages are skipped without a write.** The property stores a
  sha256 of the rendered body; a second publish over an unchanged corpus
  performs zero writes.
- **Conflicts are surfaced, never clobbered.** Updates send
  `version + 1`; a 409 means a human edited the page — it is reported as a
  skip and left alone.
- **Rendering is deterministic and escape-first.** A small Markdown subset
  (headings, paragraphs, emphasis, code, fenced blocks, flat lists, links)
  becomes storage format; corpus content is untrusted input, so hostile
  HTML/macro text stays inert and only `http`/`https`/`mailto` links become
  anchors. Tables are not yet rendered (they degrade to escaped text).

| Flag | Meaning |
|---|---|
| `--space` | Confluence space key (default: `ATLASSIAN_CONFLUENCE_SPACE`). |
| `--dry-run` | Print the pages that would be upserted; no client, no calls. |
| `--input`, `-i` | Read JSONL from a file (default: stdin; `-` also means stdin). |
| `--strict` | Fail on a malformed line instead of skipping it. |
| `--verbose`, `-v` | Print per-page actions on a live publish too. |

Exit codes are the standard 0 (done) / 1 (malformed input) / 2 (missing
credentials or space).

## Auth

API token + Basic auth against Atlassian Cloud — mint a token at
id.atlassian.com and set the three `ATLASSIAN_*` variables; one credential
serves Jira and Confluence. Tokens expire; rotate them like any secret.
Data Center (Bearer PAT, v2 Jira endpoints), OAuth, inbound Confluence
ingest, and Jira comment-mode are named deferrals on the
[`atlassian-connector`](rac/roadmaps/atlassian-connector.md) roadmap.

### Python API

```python
from rac_connectors import parse_documents, parse_graph
from rac_connectors.atlassian import (
    AtlassianPublisher,
    AtlassianVerifier,
    client_from_env,
)

client = client_from_env()
report = AtlassianVerifier(client).verify(parse_graph(open("graph.json").read()))
summary = AtlassianPublisher(client, space_key="DOCS").publish(
    parse_documents(open("corpus.jsonl"))
)
```

### Live smoke test

The connector is wired and unit-tested against fakes and a mock transport,
but the live path (a real Cloud site) is unproven until someone runs it —
this page is `drafted (live run pending)`. To validate end to end:

1. **Configure the environment** with a real site, account, and API token
   (all four variables above; pick a scratch Confluence space).
2. **Verify, dry-run first:**
   `rac export rac/ --graph | rac-connect atlassian verify --dry-run`, then
   live. With a corpus referencing one known-good and one deleted issue,
   confirm the exists/missing split and exit code 3.
3. **Publish twice into the scratch space:**
   `rac export rac/ --documents | rac-connect atlassian publish`. First run
   creates every page (property + `lore-managed` label set); the second run
   must report all pages `unchanged` and perform **zero writes**.
4. **Rename check:** change one artifact's title, re-publish, and confirm
   the same page updates in place (no duplicate).
5. **Conflict check:** hand-edit a managed page in Confluence, re-publish a
   changed body for that artifact, and confirm the run reports a version
   conflict and leaves the human edit alone.
6. **429 behaviour** (optional): run against a busy site and confirm
   retries honour `Retry-After` rather than hammering.

Then flip this page's `status` to `shipped` — and only then consider a
release tag (the gate recorded on asdecided/connectors#10).

**Full page:** [`docs/connectors/atlassian.md`](docs/connectors/atlassian.md)

</details>

<!-- /GENERATED:CONNECTORS -->

## Run it in CI

`rac-connect` is a one-shot command — it pushes and exits — so keeping a
backend fresh is just a job that runs the pipe whenever the corpus changes. A
GitHub Actions step on merge to `main`:

```yaml
name: Sync corpus to Supermemory
on:
  push:
    branches: [main]
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
      - run: pip install requirements-as-code 'rac-connectors[supermemory]'
      - run: rac export rac/ --documents | rac-connect supermemory
        env:
          SUPERMEMORY_API_KEY: ${{ secrets.SUPERMEMORY_API_KEY }}
```

The same one-liner works from a cron job or a git post-commit hook. Because the
push is idempotent on the canonical `id`, running it on every change only
updates — it never duplicates — so you don't need to diff or prune first.

## The export contract

`rac export <dir> --documents` emits JSON Lines, one record per artifact:

```json
{"schema_version":"1","id":"RAC-…","type":"decision","status":"Accepted",
 "title":"ADR-001: Markdown First","text":"…Markdown body, frontmatter stripped…",
 "metadata":{"path":"…","aliases":["adr-001"],"tags":[],"source":"rac"}}
```

`text` is the Markdown body (backends embed text, not HTML); `id` is the
canonical handle for the verify-in-Lore round-trip; `status` lets a reader drop
retired or superseded items. The contract is additive and stable (rac-core
ADR-007) — connectors depend only on it.

The connector targets export **`schema_version` 1** — the only thing it depends
on across repos (not the `rac` package version). It reads from any `rac` release
that emits version 1, and warns (on stderr) if it ever sees a newer contract
major. See `rac/decisions/` (ADR-008).

## Python API

The connector is a library too. Parse a `--documents` stream into records and
push them through any backend module:

```python
from rac_connectors import parse_documents
from rac_connectors.supermemory import SupermemoryConnector, client_from_env

records = parse_documents(open("corpus.jsonl"))
summary = SupermemoryConnector(client_from_env()).push(records)
print(summary.summary_line())       # -> "supermemory push: 263 pushed, 0 skipped"
```

Pass `dry_run=True` to preview without a client or an API call.

## One package, many backends

There is **one** `rac-connectors` package on PyPI, not one per provider. As
more backends land, you don't install or learn a new tool — you:

- **pick the backend with a CLI subcommand:** `rac-connect supermemory`,
  later `rac-connect mem0`, `rac-connect neo4j`, …; and
- **pull only the SDKs you use, as extras:**
  `pip install 'rac-connectors[supermemory,mem0]'`. The base install and the
  test-suite stay dependency-free; a provider's SDK arrives only with its extra.

This is a recorded decision, not a convenience: rac-core ADR-073 keeps all
backend connectors in one repo (the export contract is the product, so most
backends need no per-provider package), and this repo's ADR-002 fixes "one
outbound `push` seam, one module per backend, one CLI subcommand each." A
provider only graduates to its own package if it grows into an installable
product with independent cadence — the documented escape hatch, not the default.

## Add a backend

A new backend is a module under `src/rac_connectors/` implementing one outbound
seam — record parsing, the CLI, dry-run, and the summary shape are shared:

```python
class Connector(Protocol):
    name: str
    def push(self, records: Iterable[Record], *, dry_run: bool = False) -> PushSummary: ...
```

The module supplies the upsert mapping behind a thin, mockable client, and adds
its subcommand and optional `[backend]` extra. Document it once in
`docs/connectors/<backend>.md` (with a `<!-- rac-connector -->` metadata header)
and run `python scripts/sync_readme.py` — that stitches the page into the
[Connectors](#connectors) section above, so each connector owns its own file and
the README never drifts. Named future targets (shape only, not built):
documents → Mem0, Zep, Letta, Cognee, Pinecone, Weaviate, Qdrant, Chroma, Milvus,
pgvector, LanceDB; graph → Neo4j, Zep Graphiti, Cognee, Microsoft GraphRAG.

## Who it's for

- **Teams running Lore** who also run a memory or RAG backend and want the
  agent to recall fuzzily there, then verify against the authoritative corpus.
- **Teams who want semantic recall over their decisions** without putting a
  fuzzy component inside Lore's deterministic serving path.
- **Anyone wiring Lore's export into the backend they already operate** — the
  export contract is the product; this repo is the reference adapter.

## Documentation

This repo consumes Lore's export contract; the engine and its CLI are
documented with Lore.

- [Lore / RAC](https://github.com/asdecided/core) — the engine, CLI, and MCP server
- [CLI reference — `rac export`](https://asdecided.github.io/core/cli/#export) — the `--documents` / `--graph` contract this consumes

## Origin

rac-connectors is the **connector companion** to Lore / RAC. rac-core ADR-073
settles the topology: backend connectors are export-contract consumers, so they
consolidate into **one** repo with one module per backend — not a repo per
provider, and never inside the engine (it stays pure-Python, AI-optional, and
offline). This repo dogfoods Lore for its own decisions under `rac/`.

## Repository layout

```text
rac-connectors/
  src/rac_connectors/   the connector library: the documents reader, the shared
                         push seam, the rac-connect CLI, and one module per
                         backend (supermemory/ first)
  tests/                 the suite, driven against a fake client — no live API
  rac/                   the dogfood corpus: this repo's own decisions (ADRs),
                         keyed LCON
  .github/workflows/     CI — ruff, mypy, and the test-suite
```

## Test

```bash
pip install -e .[dev]
python -m pytest
```

`ruff check`, `ruff format --check`, and `mypy src/` run in CI alongside the
test-suite across Python 3.11–3.13.

## Project status

Early and evolving alongside Lore. The Supermemory connector ships today;
further backends slot in as new modules (see [Add a backend](#add-a-backend)).
Contributions, ideas, and experiments welcome.

## License

[Apache License 2.0](LICENSE). Matches `rac-core`.
