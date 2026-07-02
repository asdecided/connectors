"""Deterministic Markdown → Confluence storage-format rendering (ADR-011).

A deliberately small subset — headings, paragraphs, emphasis, inline code,
fenced code blocks, flat lists, links — rendered escape-first: every piece
of corpus text is HTML-escaped before any markup is emitted, because
artifact content is untrusted input (rac-core ADR-065). No macro names or
raw XHTML can pass through from the corpus. Unknown constructs degrade to
escaped paragraph text.

Same input, same bytes: :func:`body_hash` over the rendered output is the
publish idempotency signal, so nothing here may depend on time, locale, or
dict order.
"""

from __future__ import annotations

import hashlib
import html
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ORDERED_ITEM = re.compile(r"^\d+[.)]\s+(.*)$")
_UNORDERED_ITEM = re.compile(r"^[-*+]\s+(.*)$")
_FENCE = re.compile(r"^```")

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

_SAFE_LINK_SCHEMES = ("http://", "https://", "mailto:")


def body_hash(storage: str) -> str:
    """The sha256 of a rendered body — the change-detection key (ADR-011)."""
    return hashlib.sha256(storage.encode("utf-8")).hexdigest()


def _render_inline(escaped: str) -> str:
    """Inline markup over already-escaped text."""
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)

    def link(match: re.Match[str]) -> str:
        text, url = match.group(1), match.group(2)
        # The URL is corpus content too: only plainly-safe schemes become
        # anchors; anything else stays inert escaped text.
        if url.startswith(_SAFE_LINK_SCHEMES):
            return f'<a href="{url}">{text}</a>'
        return match.group(0)

    return _LINK.sub(link, escaped)


def _inline(text: str) -> str:
    return _render_inline(html.escape(text, quote=True))


def _code_macro(lines: list[str]) -> str:
    body = "\n".join(lines)
    # CDATA cannot contain its own terminator; split it across sections.
    body = body.replace("]]>", "]]]]><![CDATA[>")
    return (
        '<ac:structured-macro ac:name="code">'
        f"<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def render_storage(markdown: str) -> str:
    """Render artifact Markdown to storage-format XHTML, deterministically."""
    blocks: list[str] = []
    lines = markdown.splitlines()
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if _FENCE.match(stripped):
            code: list[str] = []
            index += 1
            while index < total and not _FENCE.match(lines[index].strip()):
                code.append(lines[index])
                index += 1
            index += 1  # consume the closing fence (or run off the end)
            blocks.append(_code_macro(code))
            continue

        heading = _HEADING.match(stripped)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if _UNORDERED_ITEM.match(stripped) or _ORDERED_ITEM.match(stripped):
            ordered = bool(_ORDERED_ITEM.match(stripped))
            pattern = _ORDERED_ITEM if ordered else _UNORDERED_ITEM
            items: list[str] = []
            while index < total:
                item = pattern.match(lines[index].strip())
                if item is None:
                    break
                items.append(f"<li>{_inline(item.group(1))}</li>")
                index += 1
            tag = "ol" if ordered else "ul"
            blocks.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        paragraph: list[str] = []
        while index < total:
            current = lines[index].strip()
            if (
                not current
                or _FENCE.match(current)
                or _HEADING.match(current)
                or _UNORDERED_ITEM.match(current)
                or _ORDERED_ITEM.match(current)
            ):
                break
            paragraph.append(current)
            index += 1
        blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")

    return "".join(blocks)
