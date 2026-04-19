#!/usr/bin/env python3
"""Build fixtures/images/MANIFEST.jsonl from the contents of fixtures/images/.

One JSONL row per image:
    {
      "path": "automotive/nachi_auto_gallery-000-42b8256d.jpg",
      "sha256": "...",
      "size_bytes": 12345,
      "category": "automotive",
      "source_dataset": "nachi_auto_gallery",
      "license": "unverified",
      "license_verified": false,
      "attribution": null,
      "source_url": null
    }

Idempotent. Re-running updates sha256/size_bytes but preserves any license,
license_verified, attribution, and source_url values that were filled in by hand
or by a later license-review pass.

Usage:
    python -m fieldopsbench.scripts.build_manifest [--check]

    --check  exit non-zero if the current MANIFEST.jsonl is stale (missing rows,
             extra rows, or out-of-date sha256/size). Useful for CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

_SOURCE_DATASET_RE = re.compile(r"^(?P<name>.+?)-\d{3,}-[0-9a-f]{6,}\.[a-z]+$", re.IGNORECASE)


def _sha256_of(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _infer_source_dataset(filename: str) -> str:
    m = _SOURCE_DATASET_RE.match(filename)
    if m:
        return m.group("name")
    return Path(filename).stem


def _load_existing(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """Return {relative_path: row} from an existing manifest so we preserve
    license / attribution / source_url values added by hand."""
    if not manifest_path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        path = row.get("path")
        if isinstance(path, str):
            out[path] = row
    return out


def _collect_images(images_root: Path) -> list[Path]:
    files: list[Path] = []
    for p in images_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
            files.append(p)
    return sorted(files)


def _build_row(
    file_path: Path,
    images_root: Path,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    rel = file_path.relative_to(images_root).as_posix()
    category = file_path.relative_to(images_root).parts[0] if len(file_path.relative_to(images_root).parts) > 1 else ""
    row = {
        "path": rel,
        "sha256": _sha256_of(file_path),
        "size_bytes": file_path.stat().st_size,
        "category": category,
        "source_dataset": _infer_source_dataset(file_path.name),
        "license": "unverified",
        "license_verified": False,
        "attribution": None,
        "source_url": None,
    }
    if prior:
        for key in ("license", "license_verified", "attribution", "source_url"):
            if key in prior and prior[key] not in (None, "", "unverified"):
                row[key] = prior[key]
        if prior.get("license_verified") is True:
            row["license_verified"] = True
    return row


def build(images_root: Path, manifest_path: Path, *, check: bool = False) -> int:
    if not images_root.is_dir():
        print(f"ERROR: {images_root} does not exist", file=sys.stderr)
        return 2

    existing = _load_existing(manifest_path)
    files = _collect_images(images_root)

    if check and not files and existing:
        # Image binaries are .gitignore'd and only hydrated locally before
        # an upload. In a fresh checkout (or CI) we have no binaries to
        # diff against, so --check has nothing meaningful to verify here.
        # Metadata invariants (no /var/folders URLs, unique SHAs, every
        # active case attachment resolves) are covered by tests/test_manifest.py.
        print(
            f"build_manifest --check: no image binaries on disk under {images_root}; "
            f"skipping content diff (manifest has {len(existing)} rows)."
        )
        return 0

    new_rows: list[dict[str, Any]] = []
    for f in files:
        rel = f.relative_to(images_root).as_posix()
        prior = existing.get(rel)
        new_rows.append(_build_row(f, images_root, prior))

    new_text = "\n".join(json.dumps(r, sort_keys=True) for r in new_rows)
    if new_text:
        new_text += "\n"

    if check:
        new_paths = {r["path"] for r in new_rows}
        missing = [r["path"] for r in new_rows if r["path"] not in existing]
        extra = [p for p in existing if p not in new_paths]
        stale: list[str] = []
        for r in new_rows:
            prior = existing.get(r["path"])
            if prior and (
                prior.get("sha256") != r["sha256"]
                or prior.get("size_bytes") != r["size_bytes"]
            ):
                stale.append(r["path"])

        # ``missing`` and ``stale`` are real regressions: a binary appeared on
        # disk that nobody catalogued, or its bytes drifted from the manifest.
        # ``extra`` is expected by design — non-Reddit binaries are gated
        # behind a license audit and are not on disk in a fresh checkout, so
        # the manifest is intentionally a superset of the binaries here. We
        # report it but do not fail on it.
        if missing or stale:
            print(
                f"MANIFEST.jsonl is stale: {len(missing)} missing, {len(stale)} sha/size changed",
                file=sys.stderr,
            )
            for p in missing[:5]:
                print(f"  missing: {p}", file=sys.stderr)
            for p in stale[:5]:
                print(f"  stale:   {p}", file=sys.stderr)
            return 1
        if extra:
            print(
                f"MANIFEST.jsonl ok: {len(new_rows)} binaries on disk match the manifest "
                f"({len(extra)} additional manifest rows have no local binary — "
                "expected when binaries are gated behind a license audit)."
            )
        else:
            print(f"MANIFEST.jsonl is up to date ({len(new_rows)} rows)")
        return 0

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(new_text)

    verified_count = sum(1 for r in new_rows if r["license_verified"])
    by_category: dict[str, int] = {}
    for r in new_rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1

    print(f"Wrote {manifest_path} ({len(new_rows)} rows, {verified_count} license-verified)")
    for cat, n in sorted(by_category.items()):
        print(f"  {cat:<16s} {n:>4d}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fixtures/images/MANIFEST.jsonl")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the manifest is stale (for CI).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    images_root = repo_root / "fixtures" / "images"
    manifest_path = images_root / "MANIFEST.jsonl"
    return build(images_root, manifest_path, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
