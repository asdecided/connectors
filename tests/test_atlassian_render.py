"""Golden and safety coverage for the storage-format renderer (ADR-011)."""

from __future__ import annotations

from rac_connectors.atlassian.render import body_hash, render_storage

_DOCUMENT = """\
# Title

Intro paragraph with **bold**, *italic*, `code`, and a
[link](https://example.com/page).

## Section

- first item
- second item

1. one
2. two

```python
print("hi")
```
"""

_GOLDEN = (
    "<h1>Title</h1>"
    "<p>Intro paragraph with <strong>bold</strong>, <em>italic</em>, "
    '<code>code</code>, and a <a href="https://example.com/page">link</a>.</p>'
    "<h2>Section</h2>"
    "<ul><li>first item</li><li>second item</li></ul>"
    "<ol><li>one</li><li>two</li></ol>"
    '<ac:structured-macro ac:name="code">'
    '<ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body>'
    "</ac:structured-macro>"
)


def test_golden_document_renders_exactly() -> None:
    assert render_storage(_DOCUMENT) == _GOLDEN


def test_rendering_is_deterministic_and_hash_stable() -> None:
    first, second = render_storage(_DOCUMENT), render_storage(_DOCUMENT)
    assert first == second
    assert body_hash(first) == body_hash(second)
    assert body_hash(first) != body_hash(render_storage("# Other"))


def test_hostile_html_is_escaped_not_emitted() -> None:
    rendered = render_storage("<script>alert(1)</script>")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_hostile_macro_text_stays_inert() -> None:
    rendered = render_storage('injected <ac:structured-macro ac:name="html">')
    # The only macro in the output must be one the renderer itself emitted.
    assert "<ac:structured-macro" not in rendered
    assert "&lt;ac:structured-macro" in rendered


def test_cdata_terminator_cannot_break_out_of_code_blocks() -> None:
    rendered = render_storage("```\n]]><evil/>\n```")
    assert "]]><evil/>" not in rendered
    assert "]]]]><![CDATA[>" in rendered


def test_unsafe_link_schemes_stay_text() -> None:
    rendered = render_storage("[click](javascript:alert(1))")
    assert "<a href" not in rendered
    assert "javascript:alert(1)" in rendered


def test_quotes_in_text_are_attribute_safe() -> None:
    rendered = render_storage('say "hello" & goodbye')
    assert "&quot;hello&quot;" in rendered
    assert "&amp;" in rendered


def test_unclosed_fence_still_renders_a_code_block() -> None:
    rendered = render_storage("```\ndangling")
    assert "<![CDATA[dangling]]>" in rendered
