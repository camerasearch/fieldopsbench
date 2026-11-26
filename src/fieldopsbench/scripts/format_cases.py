"""Rewrite case files in canonical form, or check that they already are.

Canonical form: one JSON object per line, fields in schema order, UTF-8,
every schema field present, trade labels normalized.

    python -m fieldopsbench.scripts.format_cases           # rewrite in place
    python -m fieldopsbench.scripts.format_cases --check   # exit 1 if any file would change
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fieldopsbench.paths import cases_dir
from fieldopsbench.schema import EvalCase


def canonical_line(raw: str) -> str:
    case = EvalCase.model_validate_json(raw)
    return json.dumps(case.model_dump(mode="json"), ensure_ascii=False)


def format_file(path: Path) -> str:
    lines = [canonical_line(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report files that are not canonical")
    args = parser.parse_args()

    changed = []
    for path in sorted(cases_dir().glob("*/*.jsonl")):
        formatted = format_file(path)
        if formatted != path.read_text(encoding="utf-8"):
            changed.append(path)
            if not args.check:
                path.write_text(formatted, encoding="utf-8")

    for path in changed:
        print(f"{'would reformat' if args.check else 'reformatted'} {path}")
    if args.check and changed:
        sys.exit(1)


if __name__ == "__main__":
    main()
