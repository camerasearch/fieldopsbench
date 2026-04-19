"""FieldOpsBench pre-commit contamination guard.

Rejects a commit if any of the following are staged:

  1. Any path under `cases/private/`
  2. Any path under `candidates/`
  3. Any file whose contents contain the dataset-level canary string
     (which lives in the private split only).

The intent is to make it architecturally impossible to accidentally publish
held-out evaluation material to the company software repo.

Exit codes:
  0 = OK
  1 = blocked (prints reasons, commit should fail)
  2 = internal error

Invoked from .git/hooks/pre-commit (installed via scripts/install_hooks.sh).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the canary constant without requiring pydantic (hooks must be fast
# and must not explode on environments that don't have project deps).
# ---------------------------------------------------------------------------
_THIS = Path(__file__).resolve()
_PKG_DIR = _THIS.parent.parent       # src/fieldopsbench/
_FOB_DIR = _PKG_DIR                   # schema.py lives here


def _load_dataset_canary() -> str | None:
    """Parse schema.py for FIELDOPSBENCH_DATASET_CANARY without importing."""
    schema = _FOB_DIR / "schema.py"
    if not schema.exists():
        return None
    for line in schema.read_text().splitlines():
        if line.startswith("FIELDOPSBENCH_DATASET_CANARY"):
            # FIELDOPSBENCH_DATASET_CANARY = "..."
            _, _, rhs = line.partition("=")
            rhs = rhs.strip().strip('"').strip("'")
            return rhs or None
    return None


BLOCKED_PREFIXES = (
    "cases/private/",
    "candidates/",
)


def staged_files() -> list[str]:
    """Return staged paths (added/modified/renamed/copied)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"pre-commit: git diff failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)
    return [p for p in result.stdout.splitlines() if p.strip()]


def staged_blob(path: str) -> bytes:
    """Return the staged (index) contents of a file, or empty bytes."""
    result = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return b""
    return result.stdout


def main() -> int:
    canary = _load_dataset_canary()
    if not canary:
        print(
            "pre-commit: WARNING — could not locate FIELDOPSBENCH_DATASET_CANARY "
            "in schema.py; running path-only checks.",
            file=sys.stderr,
        )

    staged = staged_files()
    if not staged:
        return 0

    reasons: list[str] = []

    # Rule 1+2: blocked prefixes
    for p in staged:
        for prefix in BLOCKED_PREFIXES:
            if p.startswith(prefix):
                reasons.append(
                    f"  - {p}\n      → blocked path (contamination boundary: {prefix})"
                )

    # Rule 3: dataset canary in any staged file
    if canary:
        canary_bytes = canary.encode("utf-8")
        for p in staged:
            if any(p.startswith(b) for b in BLOCKED_PREFIXES):
                continue  # already reported
            blob = staged_blob(p)
            if blob and canary_bytes in blob:
                reasons.append(
                    f"  - {p}\n      → contains FIELDOPSBENCH_DATASET_CANARY; "
                    f"this string belongs only in the private split."
                )

    if not reasons:
        return 0

    print(
        "\nFieldOpsBench pre-commit guard BLOCKED this commit:\n\n"
        + "\n".join(reasons)
        + "\n\nWhy: these files form the contamination-control boundary of the\n"
        "held-out evaluation set. Publishing them to the company software repo\n"
        "would leak the private benchmark into public indexes.\n\n"
        "To work around (only if you know what you're doing):\n"
        "  git commit --no-verify\n\n"
        "To publish private assets intentionally, use:\n"
        "  python -m fieldopsbench.scripts.upload_fixtures \\\n"
        "      --private --include-private\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
