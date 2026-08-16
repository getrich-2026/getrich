"""Tests for the user-content HTML sanitizer.

`apps/web/services/sanitize.py` is the **second** of three layers of
defense against stored XSS on `strategies.detail_html`:

  1. Schema (Postgres `CHECK` in `migrations/024_*.sql`)
  2. **This module** — `normalize_detail_html` strips dangerous tags/
     attributes/URIs and caps the length before the value lands in the DB
  3. Render (`frontend/src/lib/sanitize.ts::sanitizeHtml`)

The allow-list intentionally matches the frontend's DOMPurify config. We
run the same cases (and a couple more for Python-specific quirks) to
guard against silent drift.
"""

from __future__ import annotations

from gr_api.services.sanitize import (
    MAX_LENGTH,
    MAX_REASON_LENGTH,
    normalize_detail_html,
    normalize_reason,
)


class TestNormalizeDetailHtml:
    def test_returns_empty_for_none_and_empty(self) -> None:
        assert normalize_detail_html(None) == ""
        assert normalize_detail_html("") == ""

    def test_strips_script_tag(self) -> None:
        # Bleach with `strip=True` keeps the text content of stripped
        # tags (e.g. `alert(1)` survives as literal text) but drops the
        # tag itself — so the JS payload never executes. The frontend's
        # DOMPurify path has slightly different defaults and *also*
        # strips the body; the security property we care about is the
        # same: no `<script>` in the output.
        out = normalize_detail_html("<script>alert(1)</script><h2>OK</h2>")
        assert "<script" not in out.lower()
        # h2 is preserved verbatim.
        assert "<h2>OK</h2>" in out

    def test_keeps_safe_passthrough(self) -> None:
        out = normalize_detail_html("<h2>OK</h2>")
        assert out == "<h2>OK</h2>"

    def test_strips_event_handler_attributes(self) -> None:
        out = normalize_detail_html('<img src="x" onerror="window.__xss=true">')
        assert "onerror" not in out.lower()
        assert "<img" in out  # the tag itself is allowed
        assert 'src="x"' in out

    def test_strips_javascript_uri(self) -> None:
        out = normalize_detail_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in out.lower()
        # Anchor text remains.
        assert "click" in out

    def test_strips_data_uri(self) -> None:
        out = normalize_detail_html('<a href="data:text/html,<script>alert(1)</script>">x</a>')
        assert "data:" not in out.lower()

    def test_preserves_safe_http_https_mailto_and_relative(self) -> None:
        out = normalize_detail_html(
            '<a href="https://example.com">a</a>'
            '<a href="http://example.com">b</a>'
            '<a href="mailto:hi@example.com">c</a>'
            '<a href="/relative/path">d</a>'
        )
        assert 'href="https://example.com"' in out
        assert 'href="http://example.com"' in out
        assert 'href="mailto:hi@example.com"' in out
        assert 'href="/relative/path"' in out

    def test_preserves_table_structure_with_colspan_and_rowspan(self) -> None:
        out = normalize_detail_html(
            "<table>"
            "<thead><tr><th colspan=2>Header</th></tr></thead>"
            "<tbody><tr><td rowspan=2>Cell</td><td>x</td></tr></tbody>"
            "</table>"
        )
        assert "<table>" in out
        assert "<thead>" in out
        assert "<th" in out
        assert "colspan" in out
        assert "rowspan" in out
        assert "<td" in out

    def test_strips_dangerous_tags(self) -> None:
        out = normalize_detail_html(
            "<style>body{background:red}</style>"
            '<iframe src="evil"></iframe>'
            '<object data="evil"></object>'
            '<embed src="evil">'
            '<form action="evil"><input name="x"></form>'
        )
        for tag in ("<style", "<iframe", "<object", "<embed", "<form", "<input"):
            assert tag not in out.lower()

    def test_caps_output_at_max_length(self) -> None:
        long = "<p>" + ("a" * (MAX_LENGTH + 1000)) + "</p>"
        out = normalize_detail_html(long)
        assert len(out) <= MAX_LENGTH


class TestNormalizeReason:
    """`signals.reason` is plain text by contract. `normalize_reason`
    runs bleach with an empty tag allow-list so any HTML payload
    that lands in the column is reduced to literal text — third
    layer of XSS defense on the field, after the React text-node
    render and the DB CHECK constraint.
    """

    def test_returns_empty_for_none_and_empty(self) -> None:
        assert normalize_reason(None) == ""
        assert normalize_reason("") == ""

    def test_passes_through_plain_text_unchanged(self) -> None:
        # The field is plain text; algorithmic explanations survive
        # verbatim.
        out = normalize_reason("MA(5) crossed above MA(20) with Z-score 2.3")
        assert out == "MA(5) crossed above MA(20) with Z-score 2.3"

    def test_strips_script_tag(self) -> None:
        # The XSS payload we care about: even if a future write path
        # forgets to escape, the response must not contain a
        # `<script>` element.
        out = normalize_reason("<script>alert(1)</script>MA crossed")
        assert "<script" not in out.lower()
        # The text content of the stripped tag survives (bleach
        # `strip=True` semantics, matching `sanitizeHtml`).
        assert "alert(1)" in out
        assert "MA crossed" in out

    def test_strips_img_with_onerror(self) -> None:
        out = normalize_reason('<img src=x onerror="alert(1)">signal')
        assert "<img" not in out.lower()
        assert "onerror" not in out.lower()
        assert "signal" in out

    def test_strips_stylized_html(self) -> None:
        out = normalize_reason("<style>body{color:red}</style>actual reason")
        assert "<style" not in out.lower()
        assert "actual reason" in out

    def test_strips_html_comments(self) -> None:
        # ``<!-- ... -->`` should not survive the empty allow-list
        # even though it's "text" — otherwise an attacker could
        # inject the comment terminator mid-string and rewrite the
        # surrounding content. ``strip_comments=True`` closes the
        # gap.
        out = normalize_reason("ok<!-- evil -->more")
        # The comment body is dropped entirely (different from
        # `<script>`, where bleach keeps the text content).
        assert "<!--" not in out
        assert "evil" not in out
        # The surrounding plain text survives.
        assert "ok" in out
        assert "more" in out

    def test_strips_iframe_object_embed(self) -> None:
        out = normalize_reason(
            '<iframe src="evil"></iframe><object data="evil"></object><embed src="evil">reason'
        )
        for tag in ("<iframe", "<object", "<embed"):
            assert tag not in out.lower()
        assert "reason" in out

    def test_caps_output_at_max_reason_length(self) -> None:
        long = "a" * (MAX_REASON_LENGTH + 500)
        out = normalize_reason(long)
        assert len(out) == MAX_REASON_LENGTH

    def test_preserves_newlines_and_indentation(self) -> None:
        # Plain text with multi-line content (the live signal
        # producer may emit formatted explanations) must round-trip
        # through the sanitizer unchanged.
        out = normalize_reason("line 1\nline 2\n  indented")
        assert out == "line 1\nline 2\n  indented"
