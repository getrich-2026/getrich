"""Static analyzer for silent-failure patterns in try/except blocks.

Walks the source tree looking for ``try``/``except`` blocks whose
handler ONLY logs (no ``return`` / ``raise`` / explicit recovery).
These are the most common silent-failure shape: an exception
fires, gets logged, and the function returns as if nothing happened.

The scanner is intentionally permissive: it surfaces EVERY
try/except that only logs. The operator must then triage the
result, because most of them are intentional ("best effort"
cleanups, fallbacks to a sane default, etc.). A second pass —
the triage pass — classifies each finding as:

  * P0              — caller would want the failure propagated
  * OK              — intentional "log + continue" (cleanup,
                       config fallback, optional import)

Implementation
--------------
Round #1141: switched from regex + manual line-walking to Python's
:mod:`ast` module. AST mode correctly handles:

* **Nested try/except.** Each :class:`ast.Try` is walked once
  (via :func:`ast.walk`) and yields ONE finding per handler.
  The legacy scanner iterated line-by-line with indent-based
  heuristics and could mis-classify inner try bodies as part of
  the outer try's body.
* **Handlers longer than 8 lines.** The legacy scanner capped
  the handler body capture at 8 non-empty lines. A real-world
  30-line handler with a single ``log.warning()`` at the top and
  no other statements would be silently miscounted as "OK"
  because the side-effect scan never saw the bottom of the
  handler. AST gives us the full structured body.
* **Indentation quirks.** Tabs vs spaces, line continuations,
  multi-line statements, decorators, etc. The legacy scanner's
  indent-based stop condition (``if not lines[k].startswith(...)``)
  was fragile. AST doesn't care about whitespace.
* **PEP 654 ``except*:``** is recognized when running on 3.11+.

Suppression
-----------
A finding is suppressed (skipped) when a comment on the 4
non-blank lines BEFORE *or* AFTER the ``except:`` matches::

    # silent-fail-ok: <reason>

The reason is a free-form string. Use the comment to document
WHY the swallow is intentional (e.g. "best-effort resample",
"SMTP teardown — process is exiting"). The suppression makes
the operator's intent visible at the call site and survives a
code review.

The suppression check itself is still a line-based scan (4
lines before / 4 after the ``except:``) because the comment is
a pure-lexical artifact — there's no AST shape for "a comment
adjacent to this node". We use the handler's :attr:`lineno` as
the anchor and walk the source lines from there.

Modes
-----
* default (no flag): print the triage table, exit 0.
* ``--strict``: print the triage table, exit 1 if any
  un-suppressed P0_REVIEW finding exists. Use this in CI
  to fail the build on a new un-triaged silent-fail.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING


ROOT = pathlib.Path("src/getrich")

# Comment on the line right after ``except:`` that marks
# the finding as an intentional best-effort swallow. The
# reason text is for human consumption only.
SUPPRESSION_RE = re.compile(r"^\s*#\s*silent-fail-ok\s*[:：]")

# Modules in this list are known to be third-party
# (vendored research code). The scanner still surfaces
# findings from them, but they are flagged as
# `VENDORED` so the operator knows not to fix them
# in this repo.
VENDORED_DIR_PREFIXES = (
    "src/getrich/optionLib/",
    "src/getrich/research/",
)

# If the handler body contains ANY of these tokens (in
# addition to a `log.*` call) the exception is NOT silently
# swallowed — the handler has observable side effects
# (state mutation, control flow, network I/O, ...). We
# flag such handlers as LIKELY_OK to reduce false positives.
#
# The check runs against :func:`ast.unparse` of the handler
# body (not raw source lines), so the matches are exact token
# boundaries. The leading/trailing space in some tokens is
# preserved to avoid partial matches (e.g. ``return`` vs
# ``return_value``).
SIDE_EFFECT_TOKENS = (
    "self.",
    "return ",  # space to avoid matching `return_value`
    "continue",
    "break",
    "yield ",
    "await ",
    "raise ",
    "sys.exit",  # process-fail-loudly (CLI config errors)
    # state-mutating assignments
    " = None",
    " = []",
    " = {}",
    " = 0",
    " = False",
    " = True",
    " = 100",
    " = 1440",
    " = 168",
    ' = ""',
    # config-fallback helpers
    "_warn(",
)

# ``ast.TryStar`` (PEP 654 ``except*:``) is a 3.11+ node.
# Probe the attribute so the scanner keeps running on 3.10.
_TRY_NODE_TYPES: tuple[type[ast.AST], ...] = (ast.Try,)
if hasattr(ast, "TryStar"):
    _TRY_NODE_TYPES = _TRY_NODE_TYPES + (ast.TryStar,)


@dataclass
class Finding:
    file: str
    try_line: int
    except_line: str
    first_handler_line: str
    is_vendored: bool
    is_likely_ok: bool
    is_suppressed: bool
    suppression_reason: str | None


def scan_file(path: pathlib.Path) -> list[Finding]:
    """Return suspicious try/except blocks in ``path``.

    Parses the file with :mod:`ast` and walks every
    :class:`ast.Try` / :class:`ast.TryStar` node (recursively,
    via :func:`ast.walk`). Each handler on each ``try`` becomes
    one finding — so a single ``try`` with three ``except``
    clauses produces three findings, and a nested ``try``
    inside a handler produces a separate finding for the
    inner ``try``'s handlers.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        # Unparseable — leave for the type checker / ruff / CI lint.
        # A silent-fail scan that crashes the build on broken syntax
        # would mask the real lint failure.
        return []

    rel = str(path).replace("\\", "/")
    is_vendored = any(rel.startswith(p) for p in VENDORED_DIR_PREFIXES)
    findings: list[Finding] = []

    for try_node in ast.walk(tree):
        if not isinstance(try_node, _TRY_NODE_TYPES):
            continue
        for handler in try_node.handlers:
            finding = _make_finding(
                path=path,
                try_node=try_node,
                handler=handler,
                lines=lines,
                is_vendored=is_vendored,
            )
            if finding is not None:
                findings.append(finding)
    return findings


def _make_finding(
    *,
    path: pathlib.Path,
    try_node: ast.Try | ast.TryStar,
    handler: ast.ExceptHandler,
    lines: list[str],
    is_vendored: bool,
) -> Finding | None:
    """Build a single :class:`Finding` from one handler, or
    ``None`` if the handler has an observable outcome
    (return / raise / break / continue / yield)."""
    body = handler.body
    if _has_observable_outcome(body):
        # Handler returns / re-raises / breaks out of the loop.
        # Not a silent fail — the caller (or the loop) sees it.
        return None

    handler_text = _flatten_body(body)
    is_likely_ok = (
        any(tok in handler_text for tok in SIDE_EFFECT_TOKENS)
        or _has_state_mutation(body)
    )
    # `handler.lineno` is 1-indexed (Python AST convention);
    # `_check_suppression` takes 0-indexed.
    is_suppressed, reason = _check_suppression(lines, handler.lineno - 1)
    return Finding(
        file=str(path),
        try_line=try_node.lineno,
        except_line=_format_handler_header(
            handler,
            is_try_star=isinstance(try_node, ast.TryStar),
        ),
        first_handler_line=_first_handler_line(handler, lines),
        is_vendored=is_vendored,
        is_likely_ok=is_likely_ok,
        is_suppressed=is_suppressed,
        suppression_reason=reason,
    )


def _has_observable_outcome(body: list[ast.stmt]) -> bool:
    """``True`` if any statement in ``body`` would re-raise, return,
    or otherwise let the caller observe the exception (or branch
    around it).

    ``ast.Pass`` and ``ast.Expr`` (a bare expression like a log call)
    are NOT observable — they are the silent-fail shape we want
    to surface.
    """
    if not body:
        # Empty handler (`except: pass` is implicit). That's the
        # canonical silent-fail — surface it.
        return False
    # Walk the entire body. The body is a list of top-level
    # statements, so we wrap in a Module node for ast.walk.
    module = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(module):
        if isinstance(
            node, (ast.Return, ast.Raise, ast.Break, ast.Continue, ast.Yield, ast.YieldFrom)
        ):
            return True
    return False


def _has_state_mutation(body: list[ast.stmt]) -> bool:
    """``True`` if the handler body mutates any local / module-level
    / instance state via assignment.

    This is the AST-structural replacement for the literal-value
    pattern matching in ``SIDE_EFFECT_TOKENS`` (e.g. `` = 100``,
    `` = None``). The regex list is brittle — every new fallback
    value requires a new entry. AST catches ALL assignments
    uniformly:

    * ``x = 1``               → ast.Assign
    * ``a, b = 1, 2``         → ast.Assign with Tuple target
    * ``x += 1``              → ast.AugAssign
    * ``self.conn = None``    → ast.Assign with Attribute target
                               (already caught by ``self.`` token
                               but we include for completeness)

    The check intentionally does NOT consider ``x = compute()``
    separately from ``x = 1`` — both are observable state
    mutations from the caller's perspective (and ``x = compute()``
    also implies a function call, which is itself a side effect).
    """
    if not body:
        return False
    module = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(module):
        # ast.Assign covers plain = and tuple/list unpacking
        # (the targets list contains Tuple/List nodes).
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            return True
    return False


def _flatten_body(body: list[ast.stmt]) -> str:
    """Unparse a handler body to a single text string for token scanning.

    Falls back to per-statement unparse if the whole-body unparse
    fails (e.g. some :class:`ast.Match` shapes on 3.10).
    """
    if not body:
        return ""
    try:
        return ast.unparse(ast.Module(body=body, type_ignores=[]))
    except Exception:
        chunks: list[str] = []
        for stmt in body:
            try:
                chunks.append(ast.unparse(stmt))
            except Exception:
                chunks.append("<unparseable>")
        return "\n".join(chunks)


def _format_handler_header(handler: ast.ExceptHandler, *, is_try_star: bool = False) -> str:
    """Render ``except [TYPE] [as NAME]:`` for the report.

    Bare ``except:`` renders as just ``except:`` (no type, no name).
    The colon is always glued to the preceding token (no space)
    so the report matches what an actual Python source line would
    look like (``except Exception:``, not ``except Exception :``).

    When the parent is a PEP 654 ``ast.TryStar`` node, the
    handler is rendered with a ``*`` (``except* ValueError:``) —
    this is information that lives on the parent, not on the
    handler, so :func:`ast.unparse` on a single handler drops it.
    Round #1152: callers must pass ``is_try_star=True`` to opt in.
    """
    parts = ["except*"] if is_try_star else ["except"]
    if handler.type is not None:
        try:
            type_text = ast.unparse(handler.type)
        except Exception:
            type_text = "<unparseable>"
        parts.append(type_text.strip())
    if handler.name is not None:
        parts.append(f"as {handler.name}")
    # Join everything except the trailing colon with spaces, then
    # concatenate the colon directly so there's no space before it.
    return " ".join(parts) + ":"


def _first_handler_line(handler: ast.ExceptHandler, lines: list[str]) -> str:
    """First non-empty source line of the handler body, for the report.

    The legacy scanner reported ``<empty>`` for empty handlers, which
    is what we keep here. (Empty handler body is rare in practice —
    Python inserts an implicit ``pass`` — but the AST still gives us
    a 0-length body, so we handle it gracefully.)
    """
    if not handler.body:
        return "<empty handler>"
    start = handler.body[0].lineno
    for i in range(start - 1, min(start + 8, len(lines))):
        if 0 <= i < len(lines) and lines[i].strip():
            return lines[i].strip()
    return "<empty handler>"


def _check_suppression(lines: list[str], except_line: int) -> tuple[bool, str | None]:
    """Look for a suppression comment of the form
    ``# silent-fail-ok: <reason>`` in the 4 non-blank lines
    either BEFORE or AFTER the ``except:`` line.

    Engineers naturally write the annotation as a "what
    this except is for" comment immediately ABOVE the
    `except:` keyword (between the `try` body and the
    handler). The 4 non-blank lines after the `except:`
    are also accepted for the rarer "explanation above
    the body" style.

    Returns ``(True, reason)`` if found, else ``(False, None)``.
    """
    candidates: list[int] = []
    # Before the except: walk backwards, skipping blanks.
    # Each loop tracks its OWN count — they share the ``candidates``
    # list but the cap is per-direction (4 above + 4 below = 8 total).
    # Sharing the cap (the v1 bug) caused the AFTER loop to break on
    # its first append whenever the BEFORE loop filled 4, so the
    # most common annotation style — a one-line ``# silent-fail-ok:``
    # comment directly under ``except:`` — was silently missed.
    before_count = 0
    for offset in range(except_line - 1, max(except_line - 8, -1), -1):
        if lines[offset].strip():
            candidates.append(offset)
            before_count += 1
            if before_count >= 4:
                break
    after_count = 0
    for offset in range(except_line + 1, min(except_line + 8, len(lines))):
        if lines[offset].strip():
            candidates.append(offset)
            after_count += 1
            if after_count >= 4:
                break
    for offset in candidates:
        line = lines[offset]
        if SUPPRESSION_RE.match(line):
            tail = SUPPRESSION_RE.sub("", line).strip()
            return True, tail or None
    return False, None


def classify(findings: list[Finding]) -> dict[str, list[Finding]]:
    """Group findings into triage buckets.

    Suppressed P0_REVIEW findings are pulled out into their
    own bucket so a ``--strict`` build can fail on un-suppressed
    P0s without yelling at the operator for every annotated
    best-effort swallow.
    """
    buckets: dict[str, list[Finding]] = {
        "P0_REVIEW": [],
        "P0_SUPPRESSED": [],
        "LIKELY_OK": [],
        "VENDORED": [],
    }
    for f in findings:
        if f.is_vendored:
            buckets["VENDORED"].append(f)
        elif f.is_likely_ok:
            buckets["LIKELY_OK"].append(f)
        elif f.is_suppressed:
            buckets["P0_SUPPRESSED"].append(f)
        else:
            buckets["P0_REVIEW"].append(f)
    return buckets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan src/getrich for silent-failure try/except blocks."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit 1 if any P0_REVIEW finding is un-suppressed. "
            "Use in CI to fail the build on a new un-triaged "
            "silent-fail."
        ),
    )
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    for p in ROOT.rglob("*.py"):
        findings.extend(scan_file(p))
    if not findings:
        print("(no silent-failure patterns found)")
        return 0
    buckets = classify(findings)
    print(
        f"Found {len(findings)} try/except blocks that only log.\n"
        f"  P0_REVIEW:       {len(buckets['P0_REVIEW'])}\n"
        f"  P0_SUPPRESSED:   {len(buckets['P0_SUPPRESSED'])} "
        f"(annotated best-effort, skipped under --strict)\n"
        f"  LIKELY_OK:       {len(buckets['LIKELY_OK'])} (intentional fallbacks)\n"
        f"  VENDORED:        {len(buckets['VENDORED'])} (third-party — do not fix here)\n"
    )
    for label in ("P0_REVIEW", "P0_SUPPRESSED", "LIKELY_OK", "VENDORED"):
        fs = buckets[label]
        if not fs:
            continue
        print(f"=== {label} ({len(fs)}) ===")
        for f in fs:
            print(f"  {f.file}:{f.try_line}")
            print(f"    {f.except_line}")
            print(f"    handler: {f.first_handler_line}")
            if f.suppression_reason:
                print(f"    silent-fail-ok: {f.suppression_reason}")
            print()
    if args.strict and buckets["P0_REVIEW"]:
        print(
            f"FAIL: {len(buckets['P0_REVIEW'])} un-suppressed P0_REVIEW finding(s). "
            "Annotate with `# silent-fail-ok: <reason>` (justified swallow) "
            "or fix the underlying bug."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
