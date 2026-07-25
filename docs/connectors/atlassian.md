<!-- rac-connector
name: Atlassian
tagline: Jira related_tickets verification + Confluence managed-page publish over the export contracts
category: Workspace & ticketing
extra: atlassian
order: 70
status: drafted (live run pending)
-->
# Atlassian (Jira + Confluence)

The Atlassian suite connector (rac-core ADR-090): **verify** that every Jira
reference in the corpus still points at a real, reachable issue, and
**publish** the corpus into a Confluence space as managed pages. Both verbs
are thin consumers of the export contracts; the engine never talks to
Atlassian (rac-core ADR-087), and the connector only ever contacts the
instance you configure (rac-core ADR-086). No Atlassian SDK — an internal
`httpx` client, see [ADR-010](../../rac/decisions/adr-010-atlassian-verify-publish-seams.md).

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
artifact id ([ADR-011](../../rac/decisions/adr-011-confluence-page-identity-and-idempotency.md)):

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
[`atlassian-connector`](../../rac/roadmaps/atlassian-connector.md) roadmap.

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
