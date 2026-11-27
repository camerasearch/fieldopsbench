"""Sanitize fixtures/images/MANIFEST.jsonl in place.

Drops rows that fail any of these provenance / hygiene invariants:

1. ``source_url`` does not start with ``http://`` or ``https://``
   (the previous acquisition pipeline left ``/var/folders/...`` temp paths
   in 558 / 851 rows; those cannot be verified by anyone outside the
   author's machine and read as fake provenance).
2. ``source_dataset`` is on a known-bad denylist:
   - ``nachi_auto_gallery`` — 30 rows, all certification logos / website
     chrome rather than mechanical photos.
   - ``osha_*`` — OSHA SLTC pages were scraped for chrome (logos, page
     furniture) rather than the actual photo library; re-acquire from the
     real source before re-adding.
3. The sha256 has already been kept once (deduplicate).

Usage::

    python -m fieldopsbench.scripts.sanitize_manifest                  # dry-run
    python -m fieldopsbench.scripts.sanitize_manifest --execute        # rewrite manifest
    python -m fieldopsbench.scripts.sanitize_manifest --execute --backup MANIFEST.jsonl.bak

Idempotent: running again on a sanitized manifest is a no-op.
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
MANIFEST_PATH = _REPO_ROOT / "fixtures" / "images" / "MANIFEST.jsonl"

DENY_DATASETS: frozenset[str] = frozenset({
    "nachi_auto_gallery",
})
DENY_DATASET_PREFIXES: tuple[str, ...] = ("osha_",)

# URL substrings that mark scraped page furniture (logos, icons, layout
# imagery) rather than the actual subject photos we want.
DENY_URL_SUBSTRINGS: tuple[str, ...] = (
    "/cms/images/layout/",
    "/images/logo",
    "/images/icons/",
    "/assets/icons/",
    "/wp-content/themes/",
    "favicon",
    "/maineditordimension/",
    "/mainfckeditordimension/",
)


def _classify(row: dict, seen_sha: set[str]) -> tuple[bool, str]:
    url = row.get("source_url") or ""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False, "non_http_source_url"
    url_l = url.lower()
    for sub in DENY_URL_SUBSTRINGS:
        if sub in url_l:
            return False, "deny_url_chrome"

    ds = row.get("source_dataset") or ""
    if ds in DENY_DATASETS:
        return False, f"deny_dataset:{ds}"
    for pref in DENY_DATASET_PREFIXES:
        if ds.startswith(pref):
            return False, f"deny_prefix:{pref}"

    sha = row.get("sha256")
    if not isinstance(sha, str) or not sha:
        return False, "missing_sha256"
    if sha in seen_sha:
        return False, "duplicate_sha"

    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Write sanitized manifest in place.")
    parser.add_argument(
        "--backup",
        type=str,
        default=None,
        help="Optional path (relative to fixtures/images/) to copy the pre-sanitize manifest to before rewrite.",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=None,
        help="Override path to MANIFEST.jsonl (default: %s)" % MANIFEST_PATH,
    )
    args = parser.parse_args()

    manifest = Path(args.manifest) if args.manifest else MANIFEST_PATH
    if not manifest.exists():
        print(f"ERROR: missing {manifest}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))

    seen_sha: set[str] = set()
    kept: list[dict] = []
    drop_reasons: collections.Counter[str] = collections.Counter()
    for r in rows:
        ok, why = _classify(r, seen_sha)
        if ok:
            kept.append(r)
            seen_sha.add(r["sha256"])
        else:
            drop_reasons[why] += 1

    print(f"manifest: {manifest.relative_to(_REPO_ROOT)}")
    print(f"  input rows : {len(rows)}")
    print(f"  kept rows  : {len(kept)}")
    print(f"  dropped    : {len(rows) - len(kept)}")
    if drop_reasons:
        print("  drop reasons:")
        for reason, n in drop_reasons.most_common():
            print(f"    {reason:<32s} {n}")

    by_dataset: collections.Counter[str] = collections.Counter(
        r.get("source_dataset", "") for r in kept
    )
    print("  kept by source_dataset:")
    for ds, n in by_dataset.most_common():
        print(f"    {ds:<40s} {n}")

    if not args.execute:
        print("\nDry-run only. Re-run with --execute to rewrite manifest.")
        return 0

    if args.backup:
        backup_path = manifest.parent / args.backup
        shutil.copy2(manifest, backup_path)
        print(f"\nBacked up original to {backup_path.relative_to(_REPO_ROOT)}")

    body = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in kept)
    if body:
        body += "\n"
    manifest.write_text(body, encoding="utf-8")
    print(f"\nWrote sanitized manifest with {len(kept)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
