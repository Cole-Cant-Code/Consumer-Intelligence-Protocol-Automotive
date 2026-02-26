#!/usr/bin/env python3
"""CI enforcement: warn on manual threshold comparisons in store.py.

Detects patterns like ``score >= 22`` or ``score >= 10`` that should be
replaced with ``infer_lead_status()``.

Exit 0 (warning only) during stabilization.  Promote to exit 1 after
two release cycles with no fallback anomalies.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGET_FILE = Path(__file__).resolve().parent.parent / "auto_mcp" / "data" / "store.py"

# Thresholds that indicate manual status inference
KNOWN_THRESHOLDS = {10, 22}


def check() -> list[str]:
    violations: list[str] = []
    try:
        tree = ast.parse(TARGET_FILE.read_text())
    except (SyntaxError, FileNotFoundError) as exc:
        print(f"ERROR: cannot parse {TARGET_FILE}: {exc}", file=sys.stderr)
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            # Look for patterns: score >= 22, score >= 10
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.GtE, ast.Gt)) and isinstance(
                    comparator, ast.Constant
                ):
                    if isinstance(comparator.value, (int, float)):
                        if comparator.value in KNOWN_THRESHOLDS:
                            violations.append(
                                f"store.py:{node.lineno}: manual threshold "
                                f"comparison (>= {comparator.value})"
                            )
    return violations


def main() -> None:
    violations = check()
    if violations:
        print("WARNING: manual threshold comparisons found in store.py:")
        for v in violations:
            print(f"  {v}")
        print("\nThese should use infer_lead_status() from cip_protocol.")
        # Exit 0 for now (warning). Change to sys.exit(1) after stabilization.
        sys.exit(0)
    else:
        print("OK: no manual threshold comparisons in store.py")


if __name__ == "__main__":
    main()
