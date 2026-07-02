"""``rac-connect`` — the CLI entrypoint for the rac-connectors companion.

One subcommand per backend. The documents backends read a ``rac export
--documents`` JSON Lines stream; the graph backends read a ``rac export --graph``
object::

    rac export rac/ --documents | rac-connect supermemory
    rac export rac/ --documents | rac-connect mem0 --dry-run
    rac export rac/ --graph     | rac-connect neo4j
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Iterator
from typing import TextIO

from .atlassian import AtlassianVerifier
from .atlassian.client import (
    MissingCredentialsError as AtlassianMissingCredentialsError,
)
from .atlassian.client import client_from_env as atlassian_client_from_env
from .base import Connector, PushSummary
from .cognee import CogneeConnector
from .cognee.client import MissingCredentialsError as CogneeMissingCredentialsError
from .cognee.client import client_from_env as cognee_client_from_env
from .embedding import MissingEmbeddingConfigError, embedder_from_env
from .graph import MalformedGraphError, parse_graph
from .letta import LettaConnector
from .letta.client import MissingCredentialsError as LettaMissingCredentialsError
from .letta.client import client_from_env as letta_client_from_env
from .mem0 import Mem0Connector
from .mem0.client import MissingApiKeyError as Mem0MissingApiKeyError
from .mem0.client import client_from_env as mem0_client_from_env
from .neo4j import Neo4jConnector
from .neo4j.client import MissingCredentialsError
from .neo4j.client import client_from_env as neo4j_client_from_env
from .qdrant import QdrantConnector
from .qdrant.client import MissingCredentialsError as QdrantMissingCredentialsError
from .qdrant.client import client_from_env as qdrant_client_from_env
from .records import MalformedRecordError, Record, parse_documents
from .supermemory import SupermemoryConnector
from .supermemory.client import MissingApiKeyError, client_from_env
from .zep import ZepConnector
from .zep.client import MissingApiKeyError as ZepMissingApiKeyError
from .zep.client import client_from_env as zep_client_from_env


def _open_stream(path: str | None) -> tuple[TextIO, bool]:
    """Return the input stream and whether the caller owns closing it."""
    if path is None or path == "-":
        return sys.stdin, False
    return open(path, encoding="utf-8"), True


def _records_with_skip_report(
    lines: Iterable[str], summary: PushSummary, *, strict: bool
) -> Iterator[Record]:
    """Parse lines, routing malformed ones to the summary (or raising if strict).

    Wrapping ``parse_documents`` line-by-line lets a skipped malformed line be
    reported in the summary instead of silently dropped, while ``--strict`` turns
    the same guard into a hard failure.
    """
    for index, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            record = next(parse_documents([raw], strict=True))
        except MalformedRecordError as exc:
            if strict:
                raise MalformedRecordError(index, exc.reason, raw) from None
            summary.record_skip(index, exc.reason)
            continue
        yield record


def _run_supermemory(args: argparse.Namespace) -> int:
    connector = SupermemoryConnector()
    stream, owned = _open_stream(args.input)
    try:
        if args.dry_run:
            # Stream straight through the connector; it never calls the API.
            summary = _push_with_skips(
                connector, stream, dry_run=True, strict=args.strict
            )
        else:
            try:
                connector = SupermemoryConnector(client_from_env())
            except MissingApiKeyError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            summary = _push_with_skips(
                connector, stream, dry_run=False, strict=args.strict
            )
    except MalformedRecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if owned:
            stream.close()

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _run_mem0(args: argparse.Namespace) -> int:
    connector: Connector = Mem0Connector()
    stream, owned = _open_stream(args.input)
    try:
        if not args.dry_run:
            try:
                connector = Mem0Connector(mem0_client_from_env())
            except Mem0MissingApiKeyError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        try:
            summary = _push_with_skips(
                connector, stream, dry_run=args.dry_run, strict=args.strict
            )
        except MalformedRecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        if owned:
            stream.close()

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _run_qdrant(args: argparse.Namespace) -> int:
    connector: Connector = QdrantConnector()
    stream, owned = _open_stream(args.input)
    try:
        if not args.dry_run:
            try:
                connector = QdrantConnector(
                    qdrant_client_from_env(), embedder_from_env()
                )
            except (QdrantMissingCredentialsError, MissingEmbeddingConfigError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        try:
            summary = _push_with_skips(
                connector, stream, dry_run=args.dry_run, strict=args.strict
            )
        except MalformedRecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        if owned:
            stream.close()

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _run_zep(args: argparse.Namespace) -> int:
    connector: Connector = ZepConnector()
    stream, owned = _open_stream(args.input)
    try:
        if not args.dry_run:
            try:
                connector = ZepConnector(zep_client_from_env())
            except ZepMissingApiKeyError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        try:
            summary = _push_with_skips(
                connector, stream, dry_run=args.dry_run, strict=args.strict
            )
        except MalformedRecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        if owned:
            stream.close()

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _run_letta(args: argparse.Namespace) -> int:
    connector: Connector = LettaConnector()
    stream, owned = _open_stream(args.input)
    try:
        if not args.dry_run:
            try:
                connector = LettaConnector(letta_client_from_env())
            except LettaMissingCredentialsError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        try:
            summary = _push_with_skips(
                connector, stream, dry_run=args.dry_run, strict=args.strict
            )
        except MalformedRecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        if owned:
            stream.close()

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _run_cognee(args: argparse.Namespace) -> int:
    connector: Connector = CogneeConnector()
    stream, owned = _open_stream(args.input)
    try:
        if not args.dry_run:
            try:
                connector = CogneeConnector(cognee_client_from_env())
            except CogneeMissingCredentialsError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        try:
            summary = _push_with_skips(
                connector, stream, dry_run=args.dry_run, strict=args.strict
            )
        except MalformedRecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        if owned:
            stream.close()

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _push_with_skips(
    connector: Connector,
    stream: Iterable[str],
    *,
    dry_run: bool,
    strict: bool,
) -> PushSummary:
    """Push a stream, accumulating malformed-line skips into the one summary."""
    summary = PushSummary(backend=connector.name, dry_run=dry_run)
    records = _records_with_skip_report(stream, summary, strict=strict)
    pushed = connector.push(records, dry_run=dry_run)
    # Merge the connector's push results onto the summary that holds the skips.
    summary.pushed = pushed.pushed
    summary.actions = pushed.actions + summary.actions
    return summary


def _run_neo4j(args: argparse.Namespace) -> int:
    stream, owned = _open_stream(args.input)
    try:
        payload = stream.read()
    finally:
        if owned:
            stream.close()

    try:
        graph = parse_graph(payload)
    except MalformedGraphError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        connector = Neo4jConnector()
    else:
        try:
            connector = Neo4jConnector(neo4j_client_from_env())
        except MissingCredentialsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    summary = connector.push_graph(graph, dry_run=args.dry_run)

    if args.dry_run or args.verbose:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    return 0


def _run_atlassian_verify(args: argparse.Namespace) -> int:
    stream, owned = _open_stream(args.input)
    try:
        payload = stream.read()
    finally:
        if owned:
            stream.close()

    try:
        graph = parse_graph(payload)
    except MalformedGraphError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        verifier = AtlassianVerifier()
    else:
        try:
            verifier = AtlassianVerifier(atlassian_client_from_env())
        except AtlassianMissingCredentialsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    summary = verifier.verify(graph, dry_run=args.dry_run)

    if args.dry_run or args.verbose or summary.findings:
        for action in summary.actions:
            print(action)
    print(summary.summary_line(), file=sys.stderr)
    # 3 = references failed verification (ADR-010) — CI can gate on state
    # without conflating it with malformed input (1) or missing creds (2).
    return summary.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rac-connect",
        description=(
            "Push a 'rac export --documents' stream into an external memory / "
            "RAG / graph backend. Outbound only — the verify-in-Lore loop is "
            "the reading agent's job."
        ),
    )
    sub = parser.add_subparsers(dest="backend", required=True)

    sm = sub.add_parser(
        "supermemory",
        help="Upsert documents into Supermemory (idempotent on canonical id).",
    )
    sm.add_argument(
        "--input",
        "-i",
        default=None,
        help="JSONL file to read (default: stdin). '-' also means stdin.",
    )
    sm.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without calling the API.",
    )
    sm.add_argument(
        "--strict",
        action="store_true",
        help="Fail on a malformed line instead of skipping it.",
    )
    sm.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-record actions on a live push too.",
    )
    sm.set_defaults(func=_run_supermemory)

    mem = sub.add_parser(
        "mem0",
        help="Upsert documents into Mem0 (idempotent by container resync).",
    )
    mem.add_argument(
        "--input",
        "-i",
        default=None,
        help="JSONL file to read (default: stdin). '-' also means stdin.",
    )
    mem.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without calling the API.",
    )
    mem.add_argument(
        "--strict",
        action="store_true",
        help="Fail on a malformed line instead of skipping it.",
    )
    mem.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-record actions on a live push too.",
    )
    mem.set_defaults(func=_run_mem0)

    qd = sub.add_parser(
        "qdrant",
        help="Embed documents and upsert into Qdrant (idempotent on canonical id).",
    )
    qd.add_argument(
        "--input",
        "-i",
        default=None,
        help="JSONL file to read (default: stdin). '-' also means stdin.",
    )
    qd.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without embedding or calling the API.",
    )
    qd.add_argument(
        "--strict",
        action="store_true",
        help="Fail on a malformed line instead of skipping it.",
    )
    qd.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-record actions on a live push too.",
    )
    qd.set_defaults(func=_run_qdrant)

    zep = sub.add_parser(
        "zep",
        help="Upsert documents into Zep (idempotent by graph resync).",
    )
    zep.add_argument(
        "--input",
        "-i",
        default=None,
        help="JSONL file to read (default: stdin). '-' also means stdin.",
    )
    zep.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without calling the API.",
    )
    zep.add_argument(
        "--strict",
        action="store_true",
        help="Fail on a malformed line instead of skipping it.",
    )
    zep.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-record actions on a live push too.",
    )
    zep.set_defaults(func=_run_zep)

    letta = sub.add_parser(
        "letta",
        help="Upsert documents into Letta (idempotent by archive resync).",
    )
    letta.add_argument(
        "--input",
        "-i",
        default=None,
        help="JSONL file to read (default: stdin). '-' also means stdin.",
    )
    letta.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without calling the API.",
    )
    letta.add_argument(
        "--strict",
        action="store_true",
        help="Fail on a malformed line instead of skipping it.",
    )
    letta.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-record actions on a live push too.",
    )
    letta.set_defaults(func=_run_letta)

    cog = sub.add_parser(
        "cognee",
        help="Build documents into a Cognee knowledge graph (content-hash idempotent).",
    )
    cog.add_argument(
        "--input",
        "-i",
        default=None,
        help="JSONL file to read (default: stdin). '-' also means stdin.",
    )
    cog.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without running the pipeline.",
    )
    cog.add_argument(
        "--strict",
        action="store_true",
        help="Fail on a malformed line instead of skipping it.",
    )
    cog.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-record actions on a live push too.",
    )
    cog.set_defaults(func=_run_cognee)

    neo = sub.add_parser(
        "neo4j",
        help="Upsert the --graph projection into Neo4j (idempotent via MERGE).",
    )
    neo.add_argument(
        "--input",
        "-i",
        default=None,
        help="--graph JSON file to read (default: stdin). '-' also means stdin.",
    )
    neo.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the nodes/edges that would be written without connecting.",
    )
    neo.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-node/edge actions on a live push too.",
    )
    neo.set_defaults(func=_run_neo4j)

    # The Atlassian suite is one backend with several verbs (ADR-010): nested
    # subcommands keep `rac-connect <backend>` a single namespace as
    # comment-mode and ingest verbs join later.
    atl = sub.add_parser(
        "atlassian",
        help="Verify Jira references and publish Confluence pages (ADR-010/011).",
    )
    atl_sub = atl.add_subparsers(dest="verb", required=True)

    ver = atl_sub.add_parser(
        "verify",
        help=(
            "Check the --graph projection's Jira related_tickets references "
            "against the instance (read-only; exit 3 on findings)."
        ),
    )
    ver.add_argument(
        "--input",
        "-i",
        default=None,
        help="--graph JSON file to read (default: stdin). '-' also means stdin.",
    )
    ver.add_argument(
        "--dry-run",
        action="store_true",
        help="List the references that would be checked without calling Jira.",
    )
    ver.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-reference results on a live verify too.",
    )
    ver.set_defaults(func=_run_atlassian_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # A downstream consumer (e.g. `| head`) closed the pipe early; exit
        # quietly rather than tracebacking on the next write.
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
