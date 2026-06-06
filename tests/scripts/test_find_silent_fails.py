"""Tests for ``scripts/find_silent_fails.py``.

The scanner is pure stdlib — it walks ``src/getrich`` for try/except
blocks whose handler only logs (no ``return`` / ``raise`` / state
mutation). Triaged findings fall into four buckets:

* ``P0_REVIEW``      — un-suppressed; ``--strict`` exits 1 if any
* ``P0_SUPPRESSED``  — annotated with ``# silent-fail-ok: <reason>``
* ``LIKELY_OK``      — handler has a side-effect token (``self.``, etc.)
* ``VENDORED``       — third-party code (``optionLib/``, ``research/``)

These tests lock in the suppression mechanism and the
walk-past-comments behavior (suppression markers at ``base_indent``
between the ``try:`` body and the ``except:`` must not break the
scan).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import TYPE_CHECKING

import pytest


# ---------------------------------------------------------------------------
# Load the scanner as a module. ``scripts/`` is not on the import path
# (the project keeps it out of ``src/``) and we don't want to add it
# to the production import graph, so we load by file path.
# ---------------------------------------------------------------------------

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "scripts"
SCANNER_PATH = SCRIPTS_DIR / "find_silent_fails.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("find_silent_fails", SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("find_silent_fails", mod)
    spec.loader.exec_module(mod)
    return mod


if TYPE_CHECKING:
    pass


@pytest.fixture(scope="module")
def scanner():
    return _load_scanner()


def _write(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """Write a tiny Python file with the given body and return its path."""
    p = tmp_path / "snippet.py"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _check_suppression
# ---------------------------------------------------------------------------


def test_check_suppression_finds_comment_above_except(scanner):
    """A ``# silent-fail-ok: <reason>`` comment in the 4 lines
    BEFORE the ``except:`` is detected and the reason is returned."""
    lines = [
        "def f():",
        "    try:",
        "        do_thing()",
        "    # silent-fail-ok: best-effort cleanup",
        "    except Exception:",
        "        log.warning('oops')",
    ]
    is_sup, reason = scanner._check_suppression(lines, 4)
    assert is_sup is True
    assert reason == "best-effort cleanup"


def test_check_suppression_finds_comment_below_except(scanner):
    """The same comment AFTER the ``except:`` (4-line window) is
    also accepted."""
    lines = [
        "def f():",
        "    try:",
        "        do_thing()",
        "    except Exception:",
        "        # silent-fail-ok: one channel failing is fine",
        "        log.warning('oops')",
    ]
    is_sup, reason = scanner._check_suppression(lines, 3)
    assert is_sup is True
    assert reason == "one channel failing is fine"


def test_check_suppression_returns_false_when_no_marker(scanner):
    """A nearby comment that does NOT match the marker is ignored."""
    lines = [
        "def f():",
        "    try:",
        "        do_thing()",
        "    # this is just a comment",
        "    except Exception:",
        "        log.warning('oops')",
    ]
    is_sup, reason = scanner._check_suppression(lines, 4)
    assert is_sup is False
    assert reason is None


def test_check_suppression_supports_chinese_colon(scanner):
    """The marker regex accepts the full-width colon (``:``) for
    CJK-keyboard ergonomics."""
    lines = [
        "def f():",
        "    try:",
        "        do_thing()",
        "    # silent-fail-ok：中文理由",
        "    except Exception:",
        "        log.warning('oops')",
    ]
    is_sup, reason = scanner._check_suppression(lines, 4)
    assert is_sup is True
    assert reason == "中文理由"


def test_check_suppression_finds_marker_when_before_loop_is_full(scanner):
    """Regression test for the v1 counter-reuse bug: when the BEFORE
    loop fills its 4-candidate quota, the AFTER loop must STILL scan
    for markers. The v1 code shared a single ``len(candidates) >= 4``
    cap between both loops, so the AFTER loop broke on its first
    append and missed markers placed 2+ lines below ``except:`` —
    which is exactly the shape used by the SSE poll-loop swallow in
    ``backtest_job.py`` / ``backtest_sweep.py`` / ``backtest_walk_forward.py``.

    The synthetic layout below forces the BEFORE loop to collect 4
    candidates (lines 3, 2, 1, 0 — all non-blank try/except context),
    and then puts the marker on the 2nd line after ``except:``. The
    v1 code would have returned ``(False, None)`` here.
    """
    lines = [
        "    if condition:",                              # before_count = 1
        "        await poll_loop()",                      # before_count = 2
        "    try:",                                       # before_count = 3
        "        await asyncio.wait_for(ev.wait(), t)",   # before_count = 4 (BEFORE loop full)
        "    except asyncio.TimeoutError:",
        "        pass",                                   # after_count = 1
        "        # silent-fail-ok: documented fallthrough to DB poll",  # after_count = 2 — THE MARKER
        "    else:",
    ]
    is_sup, reason = scanner._check_suppression(lines, 4)
    assert is_sup is True
    assert reason == "documented fallthrough to DB poll"


def test_check_suppression_after_loop_finds_marker_at_offset_2(scanner):
    """The classic annotation shape — ``# silent-fail-ok:`` on the
    2nd line below ``except:`` — is detected even when the BEFORE
    loop is empty. Locks in the AFTER direction independently."""
    lines = [
        "def poll():",
        "    try:",
        "        await wait()",
        "    except asyncio.TimeoutError:",
        "        pass",
        "        # silent-fail-ok: timer-based fallthrough",
        "        # a coarser strategy polls the DB.",
    ]
    is_sup, reason = scanner._check_suppression(lines, 3)
    assert is_sup is True
    assert reason == "timer-based fallthrough"


# ---------------------------------------------------------------------------
# scan_file — walk-past-comments (Round #1059 regression test)
# ---------------------------------------------------------------------------


def test_scan_file_finds_except_after_suppression_comment(scanner, tmp_path):
    """Regression test: suppression markers between the ``try:`` body
    and the ``except:`` are commonly placed at ``base_indent`` (not
    ``body_indent``). The scanner must walk past them, not stop
    early and silently drop the try block."""
    p = _write(
        tmp_path,
        (
            "def send_batch(items):\n"
            "    for item in items:\n"
            "        try:\n"
            "            deliver(item)\n"
            "        # silent-fail-ok: best-effort per item\n"
            "        # a coarser strategy falls through.\n"
            "        except Exception:\n"
            "            log.warning('failed: %s', item)\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    f = findings[0]
    assert f.is_suppressed is True
    assert f.is_likely_ok is False
    assert f.is_vendored is False
    assert f.suppression_reason == "best-effort per item"


def test_scan_file_classifies_raise_handler_as_ok(scanner, tmp_path):
    """A handler with ``raise`` re-raises the exception, which is
    NOT a silent-fail. No finding is produced."""
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        log.warning('re-raising')\n"
            "        raise\n"
        ),
    )
    assert scanner.scan_file(p) == []


def test_scan_file_classifies_state_mutation_as_likely_ok(scanner, tmp_path):
    """A handler that mutates state (``self.x = None``) is NOT
    a silent-fail — caller can observe the mutation. Classified as
    ``LIKELY_OK``."""
    p = _write(
        tmp_path,
        (
            "class C:\n"
            "    def close(self):\n"
            "        try:\n"
            "            self._conn.close()\n"
            "        except Exception:\n"
            "            self._conn = None\n"
            "            log.warning('reset handle')\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    assert findings[0].is_likely_ok is True
    assert findings[0].is_suppressed is False


def test_scan_file_pure_log_is_p0_review(scanner, tmp_path):
    """A handler that ONLY logs (no return/raise/mutation) lands in
    ``P0_REVIEW`` when un-suppressed."""
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        log.error('boom')\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    f = findings[0]
    assert f.is_likely_ok is False
    assert f.is_suppressed is False
    assert f.is_vendored is False


# ---------------------------------------------------------------------------
# scan_file — AST-specific capabilities (Round #1141 regression tests)
# ---------------------------------------------------------------------------


def test_scan_file_nested_try_yields_two_findings(scanner, tmp_path):
    """A nested ``try`` inside a handler is a separate finding.

    The legacy regex scanner walked line-by-line and the inner
    ``try`` was either double-counted or missed depending on
    indentation quirks. AST mode correctly walks both — the outer
    handler swallows (no return/raise), and the inner handler
    also swallows. Two P0_REVIEW findings, one per handler.
    """
    p = _write(
        tmp_path,
        (
            "def outer():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        try:\n"
            "            recover()\n"
            "        except Exception:\n"
            "            pass\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 2
    # Both are un-suppressed pure-passes (silent fails).
    assert all(f.is_likely_ok is False for f in findings)
    assert all(f.is_suppressed is False for f in findings)
    # Both are at different try_line values (outer @ 2, inner @ 5).
    assert findings[0].try_line == 2
    assert findings[1].try_line == 5
    assert findings[0].try_line < findings[1].try_line


def test_scan_file_handler_longer_than_8_lines(scanner, tmp_path):
    """A handler body of 20 lines is fully captured.

    The legacy scanner capped handler body capture at 8 non-empty
    lines. A real-world long handler with a single ``log.warning``
    at line 1 and a 19-line side-effect at the bottom would have
    been mis-classified because the side-effect never entered the
    text used for the SIDE_EFFECT_TOKENS check. AST mode walks
    the full structured body — no line cap.
    """
    body = "\n".join(f"        line_{i} = {i}" for i in range(20))
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            f"{body}\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    # All 20 `line_N = N` assignments are state mutations, so
    # the handler is LIKELY_OK (not a silent fail).
    assert findings[0].is_likely_ok is True


def test_scan_file_return_after_handler_not_counted(scanner, tmp_path):
    """Regression test for the account_loader.py:82 false negative.

    The legacy scanner's "capture up to 8 non-empty lines after
    except:" heuristic would include a ``return 1`` line from
    AFTER the handler body (same indent as ``try:``) and
    mis-classify the handler as LIKELY_OK (has 'return ' token).
    AST mode uses structural boundaries: only statements inside
    the ``handler.body`` count.
    """
    p = _write(
        tmp_path,
        (
            "def resolve():\n"
            "    try:\n"
            "        fetch_mapping()\n"
            "    except Exception:\n"
            "        log.debug('mapping table missing')\n"
            "    return 1\n"  # same indent as try: — NOT in the handler
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    # The `return 1` is at the function level, not the handler level.
    # The handler is a pure log → silent fail → P0_REVIEW.
    assert findings[0].is_likely_ok is False
    assert findings[0].is_suppressed is False


def test_scan_file_detects_tuple_unpacking_state_mutation(scanner, tmp_path):
    """``a, b = 1, 2`` is state mutation even though it doesn't
    match any literal-value SIDE_EFFECT_TOKEN (e.g. `` = 100``).

    AST mode catches this via ``ast.Assign`` with a ``Tuple``
    target. The legacy scanner would have flagged it as P0_REVIEW
    because no token in the literal-value list matched.
    """
    p = _write(
        tmp_path,
        (
            "def cfg():\n"
            "    try:\n"
            "        int(value_str)\n"
            "    except (TypeError, ValueError):\n"
            "        min_size, max_size = 2, 20\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    assert findings[0].is_likely_ok is True


def test_scan_file_aug_assign_is_state_mutation(scanner, tmp_path):
    """``x += 1`` is also a state mutation (``ast.AugAssign``)."""
    p = _write(
        tmp_path,
        (
            "def counter():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        counter.x += 1\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    assert findings[0].is_likely_ok is True


def test_scan_file_empty_handler_is_p0_review(scanner, tmp_path):
    """``except: pass`` (implicit empty body) is the canonical
    silent-fail and should land in P0_REVIEW. AST mode reports
    an empty body as a finding; the legacy scanner skipped it."""
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        pass\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    assert findings[0].is_likely_ok is False
    assert findings[0].is_suppressed is False


@pytest.mark.skipif(not hasattr(__import__("ast"), "TryStar"), reason="PEP 654 except* requires Python 3.11+")
def test_scan_file_detects_try_star_handler(scanner, tmp_path):
    """PEP 654 ``except*`` (Python 3.11+) is recognized by the
    scanner via ``ast.TryStar``."""
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except* ValueError as eg:\n"
            "        log.warning('group failed')\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    assert findings[0].except_line.startswith("except*")


def test_scan_file_format_handler_header_no_trailing_space(scanner, tmp_path):
    """The report's ``except_line`` should be ``except Exception:`` —
    no space before the colon. Regression for an ``ast.unparse``
    formatting artifact."""
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        log.error('boom')\n"
        ),
    )
    findings = scanner.scan_file(p)
    assert len(findings) == 1
    assert findings[0].except_line == "except Exception:"


def test_scan_file_multiple_handlers_yield_multiple_findings(scanner, tmp_path):
    """A single ``try`` with N ``except`` clauses produces N
    findings — one per handler. Each is independently classified."""
    p = _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except ValueError:\n"
            "        log.warning('value error')\n"
            "    except TypeError:\n"
            "        raise\n"  # observable — not a silent fail
            "    except Exception:\n"
            "        log.error('fallback')\n"
        ),
    )
    findings = scanner.scan_file(p)
    # ValueError and Exception handlers both swallow (P0_REVIEW).
    # TypeError re-raises, so it's not a finding.
    assert len(findings) == 2
    except_types = {f.except_line for f in findings}
    assert "except ValueError:" in except_types
    assert "except Exception:" in except_types


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def test_classify_routes_suppressed_to_p0_suppressed_bucket(scanner):
    """``classify()`` must put ``is_suppressed`` findings in the
    ``P0_SUPPRESSED`` bucket, not the ``P0_REVIEW`` bucket — this is
    what makes ``--strict`` a clean signal."""
    f_p0 = scanner.Finding(
        file="x.py",
        try_line=1,
        except_line="except Exception:",
        first_handler_line="log.error('boom')",
        is_vendored=False,
        is_likely_ok=False,
        is_suppressed=False,
        suppression_reason=None,
    )
    f_sup = scanner.Finding(
        file="x.py",
        try_line=10,
        except_line="except Exception:",
        first_handler_line="log.error('teardown')",
        is_vendored=False,
        is_likely_ok=False,
        is_suppressed=True,
        suppression_reason="teardown",
    )
    f_likely = scanner.Finding(
        file="x.py",
        try_line=20,
        except_line="except Exception:",
        first_handler_line="self.x = None",
        is_vendored=False,
        is_likely_ok=True,
        is_suppressed=False,
        suppression_reason=None,
    )
    f_vend = scanner.Finding(
        file="vendor/x.py",
        try_line=1,
        except_line="except Exception:",
        first_handler_line="print('oops')",
        is_vendored=True,
        is_likely_ok=False,
        is_suppressed=False,
        suppression_reason=None,
    )
    buckets = scanner.classify([f_p0, f_sup, f_likely, f_vend])
    assert f_p0 in buckets["P0_REVIEW"]
    assert f_sup in buckets["P0_SUPPRESSED"]
    assert f_likely in buckets["LIKELY_OK"]
    assert f_vend in buckets["VENDORED"]


# ---------------------------------------------------------------------------
# main() — strict-mode exit code (CI contract)
# ---------------------------------------------------------------------------


def test_main_strict_exits_1_when_un_suppressed_p0_exists(scanner, tmp_path, monkeypatch):
    """A new un-triaged silent-fail causes ``--strict`` to exit 1.
    This is the CI contract: a new try/except that only logs is
    impossible to merge without a suppression annotation."""
    _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        log.error('boom')\n"
        ),
    )
    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    rc = scanner.main(["--strict"])
    assert rc == 1


def test_main_strict_exits_0_when_all_suppressed(scanner, tmp_path, monkeypatch):
    """With all P0 findings annotated, ``--strict`` exits 0."""
    _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    # silent-fail-ok: documented\n"
            "    except Exception:\n"
            "        log.error('boom')\n"
        ),
    )
    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    rc = scanner.main(["--strict"])
    assert rc == 0


def test_main_default_exits_0_even_with_p0(scanner, tmp_path, monkeypatch, capsys):
    """Default mode (no ``--strict``) prints the triage table and
    always exits 0 — the table is informational, not a gate."""
    _write(
        tmp_path,
        (
            "def f():\n"
            "    try:\n"
            "        do_thing()\n"
            "    except Exception:\n"
            "        log.error('boom')\n"
        ),
    )
    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    rc = scanner.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "P0_REVIEW" in out
