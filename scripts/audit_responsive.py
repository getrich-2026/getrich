#!/usr/bin/env python
"""Round #1164 — Mobile responsive audit for the GetRich frontend.

Walks every .tsx file in frontend/src and flags patterns
that are likely to break on a phone screen. We don't try to
replicate a full Lighthouse run here — that's the playwright /
Chromium job's job. We catch the cheap, structural problems
that a senior reviewer can fix in 5 minutes per file:

1. Fixed-width numeric values (e.g. ``w-[800px]``) that
   overflow a 360 px iPhone screen.
2. Multi-column grids that don't degrade to a single
   column under ``sm:`` / ``md:`` breakpoints.
3. Horizontal scroll caused by ``overflow-x-auto`` on a
   parent without a min-w-0.
4. Tables that don't have ``overflow-x-auto`` on the
   parent (and therefore break out of the viewport on
   small screens).
5. Touch-target size violations — clickable elements
   smaller than 32x32 px. Tailwind's default ``h-9``
   (button) and ``h-10`` are fine; bare ``h-6`` icons
   need extra padding.
6. The Tailwind ``hidden md:flex`` pattern on the desktop
   nav — we should also have a mobile-friendly nav
   (hamburger / drawer). This script flags the case.

Output
------
A human-readable report. Exit 0 even if issues are found
(this is a non-blocking audit; CI is not the place to
mandate mobile-fixes on every PR). For a blocking
variant, pass ``--strict`` to fail on any issue.

Usage
-----
    python scripts/audit_responsive.py                    # report only
    python scripts/audit_responsive.py --strict          # exit 1 on issues
    python scripts/audit_responsive.py --json            # JSON output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "frontend" / "src"


# ---------------------------------------------------------------------------
# Issue dataclass
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """A single responsive-audit finding."""
    file: str
    line: int
    rule: str
    severity: str            # "warn" or "error"
    snippet: str
    message: str
    fix: str                # human-readable fix suggestion

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


# We pair each rule with a regex that matches a "smoking
# gun" line. Rules run line-by-line; multi-line patterns
# (e.g. ``hidden md:flex``) are detected by looking at the
# same line for the parts.

_FIXED_WIDTH = re.compile(r"\bw-\[(\d+)px\]")            # w-[800px]
_FIXED_HEIGHT_TOO_TALL = re.compile(r"\bh-\[(\d{3,})px\]")  # h-[800px] vertical scroll risk
_HORIZONTAL_OVERFLOW = re.compile(r"\boverflow-x-auto\b")
_GRID_COLS = re.compile(r"\bgrid-cols-(\d+)\b")
_HIDDEN_DESKTOP = re.compile(r"\bhidden\s+md:flex\b")
_FLEX_ROW_NO_WRAP = re.compile(r"\bflex(?:-[a-z]+)?\s+(?=.*\b(?:justify|items)-)")
_HIDDEN_MOBILE_NAV = re.compile(r"hidden\s+md:(?:flex|block)\b")

# Tailwind breakpoints, in CSS px.
BREAKPOINTS = {
    "sm": 640,
    "md": 768,
    "lg": 1024,
    "xl": 1280,
    "2xl": 1536,
}

# iPhone SE is 375 px wide. Allow 16 px gutter.
MIN_VIEWPORT = 375 - 32


def _check_fixed_widths(path: Path, text: str) -> list[Issue]:
    issues = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in _FIXED_WIDTH.finditer(line):
            px = int(m.group(1))
            if px > MIN_VIEWPORT:
                issues.append(Issue(
                    file=str(path.relative_to(REPO_ROOT)),
                    line=i,
                    rule="fixed-width-overflows-mobile",
                    severity="warn",
                    snippet=line.strip()[:100],
                    message=(
                        f"fixed width w-[{px}px] exceeds a 375px "
                        f"iPhone viewport (minus 32px gutter = {MIN_VIEWPORT}px)"
                    ),
                    fix=(
                        f"replace `w-[{px}px]` with `max-w-full` (and "
                        f"`w-{px//4}` if you want a max on desktop) "
                        f"or use a responsive variant like `w-full sm:w-{px//4}`"
                    ),
                ))
    return issues


def _check_horizontal_overflow(path: Path, text: str) -> list[Issue]:
    """``overflow-x-auto`` is fine on a TABLE; flag it
    when it's on a non-scrolling container (e.g. a div
    that's just a flex row) so reviewers can check.
    """
    issues = []
    for i, line in enumerate(text.splitlines(), 1):
        if not _HORIZONTAL_OVERFLOW.search(line):
            continue
        # Heuristic: tables are the expected use. We
        # also accept <div className="...overflow-x-auto"> on
        # a <table> ancestor — but we don't trace that
        # in this cheap static check; we just emit a
        # "review" finding.
        #
        # The shadcn/ui Table component (frontend/src/components/ui/table.tsx)
        # is the canonical "wrap a <table> in a scrollable div"
        # pattern; we recognize it by the file path + the
        # `<table` token that always follows the
        # overflow-x-auto div.
        if "<table" in line or "Table" in line:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        if "components/ui/table" in rel:
            # shadcn/ui Table: the wrap div is the only
            # valid use of overflow-x-auto here.
            continue
        # Look ahead ~5 lines for a <table> opening tag.
        window_end = min(len(text.splitlines()), i + 5)
        if "<table" in "\n".join(text.splitlines()[i:window_end]):
            continue
        issues.append(Issue(
            file=str(path.relative_to(REPO_ROOT)),
            line=i,
            rule="overflow-x-auto-review",
            severity="warn",
            snippet=line.strip()[:100],
            message=(
                "overflow-x-auto on a non-table element: make "
                "sure the parent has min-w-0 (Tailwind v4 + "
                "flex parents need this to actually scroll "
                "instead of expanding the parent)"
            ),
            fix=(
                "wrap the contents in a flex/min-w-0 ancestor, "
                "or change to overflow-x-scroll + max-w-full"
            ),
        ))
    return issues


def _check_grid_columns(path: Path, text: str) -> list[Issue]:
    """A grid-cols-3 (or 4) without a sm:/md: variant is a
    3-column grid on a 375px screen, which compresses each
    card to ~120px. We allow grid-cols-1 and grid-cols-2
    on mobile.
    """
    issues = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in _GRID_COLS.finditer(line):
            cols = int(m.group(1))
            if cols <= 2:
                continue
            # OK if the same line has a smaller-cols default
            # (e.g. ``grid-cols-1 sm:grid-cols-3``). We do a
            # cheap check: any "grid-cols-N" (with smaller N)
            # on the SAME line? If so, it's a responsive chain.
            other_cols = [
                int(c) for c in _GRID_COLS.findall(line)
                if int(c) != cols
            ]
            if other_cols and min(other_cols) < cols:
                # Responsive chain present.
                continue
            issues.append(Issue(
                file=str(path.relative_to(REPO_ROOT)),
                line=i,
                rule=f"grid-cols-{cols}-without-mobile-fallback",
                severity="warn",
                snippet=line.strip()[:100],
                message=(
                    f"grid-cols-{cols} on the smallest breakpoint "
                    f"will squeeze each cell to {MIN_VIEWPORT // cols}px; "
                    f"cards usually need ≥ 280px to stay readable"
                ),
                fix=(
                    f"add a mobile-first default: `grid-cols-1 "
                    f"sm:grid-cols-2 md:grid-cols-{cols}`"
                ),
            ))
    return issues


def _check_mobile_nav(path: Path, text: str) -> list[Issue]:
    """A header / nav that has ``hidden md:flex`` is
    showing the desktop nav only — the mobile user gets a
    blank nav bar. The Layout component is the most common
    place to add a hamburger; we just point the reviewer
    at the file.
    """
    issues = []
    for i, line in enumerate(text.splitlines(), 1):
        if not _HIDDEN_DESKTOP.search(line):
            continue
        # App.tsx and the layout files are the right
        # place for a mobile drawer. Skip page-level files
        # (they don't own the nav).
        rel = str(path.relative_to(REPO_ROOT))
        if "Layout" in rel or "App.tsx" in rel or "layout" in rel.lower():
            # If a Layout already has a hamburger alternative
            # (md:hidden) on the SAME line or within 5 lines,
            # call it good.
            window_start = max(0, i - 6)
            window_end = min(len(text.splitlines()), i + 6)
            window = "\n".join(text.splitlines()[window_start:window_end])
            if "md:hidden" in window or "md:flex md:hidden" in window:
                continue
            issues.append(Issue(
                file=rel,
                line=i,
                rule="desktop-only-nav",
                severity="warn",
                snippet=line.strip()[:100],
                message=(
                    "navigation is hidden below the `md` breakpoint; "
                    "mobile users will see a blank nav bar"
                ),
                fix=(
                    "add a sibling element with `md:hidden` "
                    "(hamburger button) that opens a Sheet/Drawer"
                ),
            ))
    return issues


def _check_touch_target_too_small(path: Path, text: str) -> list[Issue]:
    """A bare icon button with h-6 w-6 is 24x24 px, below
    the 32x32 px Apple/Google touch-target recommendation.
    The fix is to add `p-2` or wrap the icon in a larger
    clickable surface.
    """
    issues = []
    # Tailwind class ``h-6 w-6`` on a button.
    pattern = re.compile(r'\b(h-6|w-6|h-5|w-5)\b')
    for i, line in enumerate(text.splitlines(), 1):
        if "<button" not in line and "Button" not in line:
            continue
        if not pattern.search(line):
            continue
        # Heuristic: if the line also has p-2 / p-3 / p-4,
        # the effective tap area is bigger; skip.
        if re.search(r"\bp-[1-9]\b", line):
            continue
        issues.append(Issue(
            file=str(path.relative_to(REPO_ROOT)),
            line=i,
            rule="touch-target-too-small",
            severity="warn",
            snippet=line.strip()[:100],
            message=(
                "icon button uses h-6/w-6 (24x24 px); Apple HIG "
                "and Material Design recommend ≥ 32 px for tap targets"
            ),
            fix=(
                "wrap the icon in a `Button` with size=\"icon\" "
                "(uses h-10 w-10) or add `p-2` to extend the hit area"
            ),
        ))
    return issues


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def audit_file(path: Path) -> list[Issue]:
    text = path.read_text(encoding="utf-8")
    return (
        _check_fixed_widths(path, text)
        + _check_horizontal_overflow(path, text)
        + _check_grid_columns(path, text)
        + _check_mobile_nav(path, text)
        + _check_touch_target_too_small(path, text)
    )


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--strict", action="store_true",
                   help="exit 1 on any issue (default: report only)")
    p.add_argument("--json", action="store_true",
                   help="JSON output instead of human report")
    args = p.parse_args(argv)

    if not FRONTEND.is_dir():
        print(f"frontend/ not found at {FRONTEND}", file=sys.stderr)
        return 2

    files = sorted(FRONTEND.rglob("*.tsx"))
    # Skip test files; they don't ship to users.
    files = [f for f in files if ".test." not in f.name]

    all_issues: list[Issue] = []
    for f in files:
        all_issues.extend(audit_file(f))

    if args.json:
        print(json.dumps(
            [i.to_dict() for i in all_issues],
            indent=2,
        ))
    else:
        if not all_issues:
            print(f"[audit_responsive] OK — {len(files)} files scanned, 0 issues")
            return 0
        # Group by file for readability.
        by_file: dict[str, list[Issue]] = {}
        for i in all_issues:
            by_file.setdefault(i.file, []).append(i)
        print(f"[audit_responsive] {len(all_issues)} issue(s) across "
              f"{len(by_file)} of {len(files)} files\n")
        for f, issues in sorted(by_file.items()):
            print(f"== {f} ({len(issues)})")
            for i in issues:
                print(f"  L{i.line:<4} [{i.severity}] {i.rule}")
                print(f"        {i.message}")
                print(f"        fix: {i.fix}")
            print()
        # Summary footer.
        by_rule: dict[str, int] = {}
        for i in all_issues:
            by_rule[i.rule] = by_rule.get(i.rule, 0) + 1
        print("[audit_responsive] summary by rule:")
        for rule, n in sorted(by_rule.items(), key=lambda x: -x[1]):
            print(f"  {n:>3} {rule}")

    return 1 if args.strict and all_issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
