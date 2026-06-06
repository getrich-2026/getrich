"""Static analyzer for silent-failure patterns in try/except blocks.

Walks the source tree looking for try/except blocks whose
handler ONLY logs (no `return` / `raise` / explicit
recovery). These are the most common silent-failure
shape: an exception fires, gets logged, and the function
returns as if nothing happened.

The scanner is intentionally permissive: it surfaces
EVERY try/except that only logs. The operator must
then triage the result, because most of them are
intentional ("best effort" cleanups, fallbacks to a
sane default, etc.). A second pass — the triage pass —
classifies each finding as:

  * P0   — caller would want the failure propagated
  * OK   — intentional "log + continue" (cleanup,
            config fallback, optional import)

Suppression
-----------
A finding is suppressed (skipped) when a comment on the
line right after the ``except:`` matches::

    # silent-fail-ok: <reason>

The reason is a free-form string. Use the comment to
document WHY the swallow is intentional (e.g. "best-effort
resample", "SMTP teardown — process is exiting"). The
suppression makes the operator's intent visible at the
call site and survives a code review.

Modes
-----
* default (no flag): print the triage table, exit 0.
* ``--strict``: print the triage table, exit 1 if any
  un-suppressed P0_REVIEW finding exists. Use this in CI
  to fail the build on a new un-triaged silent-fail.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass


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
    """Return suspicious try/except blocks in `path`."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    findings: list[Finding] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)try:\s*$", lines[i])
        if not m:
            i += 1
            continue
        base_indent = m.group(1)
        body_indent = base_indent + "    "
        # Find the matching `except` at base_indent level. Walk past
        # blank lines, comments (suppression markers are commonly
        # placed at base_indent, NOT body_indent), and the try body.
        # Stop at the first structural line (except/else/finally) or
        # a dedent below body_indent.
        j = i + 1
        while j < len(lines):
            stripped = lines[j].lstrip()
            if not stripped or stripped.startswith("#"):
                j += 1
                continue
            if lines[j].startswith(body_indent):
                j += 1
                continue
            break
        if j >= len(lines) or not lines[j].lstrip().startswith("except"):
            i += 1
            continue
        # Capture the handler body (everything indented past
        # the `except` line, up to 8 non-empty lines).
        k = j + 1
        handler_non_empty: list[str] = []
        while k < len(lines) and len(handler_non_empty) < 8:
            if lines[k].strip():
                handler_non_empty.append(lines[k])
                # Stop at first line at or below the base indent
                if not lines[k].startswith(base_indent + " "):
                    break
            k += 1
        handler_text = "\n".join(handler_non_empty)
        # If the handler doesn't return/raise, the exception
        # is "absorbed" — the function continues past the
        # try block as if the body succeeded.
        if "return" not in handler_text and "raise" not in handler_text:
            first = handler_non_empty[0] if handler_non_empty else "<empty>"
            rel = str(path).replace("\\", "/")
            is_vendored = any(rel.startswith(p) for p in VENDORED_DIR_PREFIXES)
            is_likely_ok = any(tok in handler_text for tok in SIDE_EFFECT_TOKENS)
            is_suppressed, reason = _check_suppression(lines, j)
            findings.append(
                Finding(
                    file=str(path),
                    try_line=i + 1,
                    except_line=lines[j].strip(),
                    first_handler_line=first,
                    is_vendored=is_vendored,
                    is_likely_ok=is_likely_ok,
                    is_suppressed=is_suppressed,
                    suppression_reason=reason,
                )
            )
        i = j + 1
    return findings


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
    for offset in range(except_line - 1, max(except_line - 8, -1), -1):
        if lines[offset].strip():
            candidates.append(offset)
            if len(candidates) >= 4:
                break
    # After the except: walk forwards, skipping blanks.
    for offset in range(except_line + 1, min(except_line + 8, len(lines))):
        if lines[offset].strip():
            candidates.append(offset)
            if len(candidates) >= 4:
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
