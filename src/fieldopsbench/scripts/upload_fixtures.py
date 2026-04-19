#!/usr/bin/env python3
"""Push FieldOpsBench assets to a HuggingFace dataset repo.

Default target: public repo `camerasearch/fieldopsbench` with
  - cases/public/
  - candidates/
  - fixtures/images/
  - fixtures/manuals/
  - LICENSE_STATEMENT.md, DATASHEET.md, METHODOLOGY.md, README.md

cases/private/ is EXCLUDED by default. It's the held-out eval set; even
with a fair-use license posture, pushing it publicly destroys the
contamination-resistance property of the benchmark. Opt in via
--include-private if you explicitly want to publish the eval set.

Setup (one time):
    pip install huggingface_hub
    huggingface-cli login        # or export HF_TOKEN=hf_xxx

Typical use:
    # Dry-run (default): show what would be uploaded
    python scripts/upload_fixtures.py

    # Upload to PUBLIC repo (fair-use posture, documented in LICENSE_STATEMENT.md)
    python scripts/upload_fixtures.py --execute --public

    # Upload to a PRIVATE repo (internal mirror before public release)
    python scripts/upload_fixtures.py --execute --private --repo-id camerasearch/fieldopsbench-assets

    # Include the held-out eval set (will leak into training data if pushed public -- be sure)
    python scripts/upload_fixtures.py --execute --public --include-private

    # Partial: only image binaries
    python scripts/upload_fixtures.py --execute --public --images-only

The script runs `build_manifest.py --check` before uploading images and
refuses to proceed if the manifest is stale. Override with --skip-manifest-check.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_PUBLIC_REPO_ID = "camerasearch/fieldopsbench"
DEFAULT_PRIVATE_REPO_ID = "camerasearch/fieldopsbench-assets"
DEFAULT_REPO_TYPE = "dataset"

UPLOAD_TARGETS = {
    "docs": {
        "path": ".",
        "patterns": ["README.md", "LICENSE_STATEMENT.md", "DATASHEET.md", "METHODOLOGY.md"],
        "description": "dataset card, license statement, methodology",
    },
    "public_cases": {
        "path": "cases/public",
        "patterns": ["*.jsonl"],
        "description": "public dev cases (JSONL)",
    },
    "private_cases": {
        "path": "cases/private",
        "patterns": ["*.jsonl"],
        "description": "HELD-OUT eval cases (off by default)",
    },
    "candidates": {
        "path": "candidates",
        "patterns": ["*.jsonl", "needs_review/*.jsonl", "verified/*.jsonl"],
        "description": "raw acquisition candidates",
    },
    "images": {
        "path": "fixtures/images",
        "patterns": ["**/*.jpg", "**/*.jpeg", "**/*.png", "**/*.webp", "MANIFEST.jsonl"],
        "description": "visual-case image binaries",
    },
    "manuals": {
        "path": "fixtures/manuals",
        "patterns": ["**/*.pdf"],
        "description": "manual PDFs",
    },
}


def _count_files(root: Path, rel_path: str, patterns: list[str]) -> int:
    base = root / rel_path
    if not base.is_dir() and rel_path != ".":
        return 0
    if rel_path == ".":
        base = root
    seen: set[Path] = set()
    for pat in patterns:
        for p in base.glob(pat):
            if p.is_file():
                seen.add(p)
    return len(seen)


def _verify_manifest_in_sync(root: Path) -> bool:
    script = root / "scripts" / "build_manifest.py"
    if not script.exists():
        print("WARN: build_manifest.py missing; skipping manifest sync check.", file=sys.stderr)
        return True
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode == 0


def _ensure_repo(repo_id: str, make_public: bool, token: str | None) -> bool:
    """Create the repo if missing. If it exists, accept its current visibility
    and print a notice if it doesn't match the requested visibility."""
    from huggingface_hub import HfApi
    from huggingface_hub.errors import RepositoryNotFoundError

    api = HfApi(token=token)
    try:
        info = api.repo_info(repo_id=repo_id, repo_type=DEFAULT_REPO_TYPE)
        current_private = bool(info.private)
        want_private = not make_public
        if current_private != want_private:
            print(
                f"NOTE: repo {repo_id} is currently {'PRIVATE' if current_private else 'PUBLIC'} "
                f"but --{'private' if want_private else 'public'} was requested.",
            )
            print("Repo visibility is not auto-changed; leaving as-is and proceeding with upload.")
        else:
            print(f"repo {repo_id} exists ({'private' if current_private else 'public'}); proceeding.")
        return True
    except RepositoryNotFoundError:
        visibility = "private" if not make_public else "public"
        print(f"repo {repo_id} not found; creating as {visibility} dataset...")
        api.create_repo(
            repo_id=repo_id,
            repo_type=DEFAULT_REPO_TYPE,
            private=not make_public,
            exist_ok=True,
        )
        print(f"created {visibility} dataset repo {repo_id}.")
        return True


def _upload_target(
    repo_id: str,
    token: str | None,
    root: Path,
    target_name: str,
    target: dict,
) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    if target["path"] == ".":
        folder = root
        path_in_repo = "."
    else:
        folder = root / target["path"]
        path_in_repo = target["path"]

    if not folder.is_dir():
        print(f"  [{target_name}] skipped (missing: {folder})")
        return

    print(f"  [{target_name}] uploading {folder} -> {path_in_repo}/ ...")
    api.upload_folder(
        folder_path=str(folder),
        repo_id=repo_id,
        repo_type=DEFAULT_REPO_TYPE,
        path_in_repo=path_in_repo,
        allow_patterns=target["patterns"],
        commit_message=f"upload {target_name}: {target['description']}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--public", action="store_true", help="Target repo is public (fair-use posture).")
    visibility.add_argument("--private", action="store_true", help="Target repo is private.")

    parser.add_argument(
        "--repo-id",
        default=os.environ.get("FIELDOPSBENCH_HF_REPO"),
        help=(
            "HF repo id. Defaults: public -> camerasearch/fieldopsbench, "
            "private -> camerasearch/fieldopsbench-assets. "
            "Override via --repo-id or FIELDOPSBENCH_HF_REPO env var."
        ),
    )
    parser.add_argument(
        "--include-private",
        action="store_true",
        help=(
            "Include cases/private/ (held-out eval set) in the upload. "
            "DANGEROUS when combined with --public: breaks contamination resistance."
        ),
    )
    parser.add_argument("--cases-only", action="store_true", help="Upload only cases + docs.")
    parser.add_argument("--images-only", action="store_true", help="Upload only images + MANIFEST + docs.")
    parser.add_argument("--no-candidates", action="store_true")
    parser.add_argument("--no-manuals", action="store_true")
    parser.add_argument("--no-docs", action="store_true", help="Skip pushing README/LICENSE_STATEMENT/DATASHEET/METHODOLOGY.")
    parser.add_argument("--skip-manifest-check", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Actually upload. Without this, dry-run only.")
    args = parser.parse_args()

    make_public = args.public and not args.private
    # Default: public when no flag given (matches the new fair-use posture)
    if not args.public and not args.private:
        make_public = True

    if args.repo_id:
        repo_id = args.repo_id
    else:
        repo_id = DEFAULT_PUBLIC_REPO_ID if make_public else DEFAULT_PRIVATE_REPO_ID

    root = Path(__file__).resolve().parents[1]

    if args.cases_only and args.images_only:
        print("ERROR: --cases-only and --images-only are mutually exclusive.", file=sys.stderr)
        return 2

    selected: list[str] = []
    if not args.no_docs:
        selected.append("docs")
    if args.cases_only:
        selected.append("public_cases")
        if args.include_private:
            selected.append("private_cases")
    elif args.images_only:
        selected.append("images")
    else:
        selected.append("public_cases")
        if args.include_private:
            selected.append("private_cases")
        if not args.no_candidates:
            selected.append("candidates")
        selected.append("images")
        if not args.no_manuals:
            selected.append("manuals")

    visibility_label = "PUBLIC" if make_public else "PRIVATE"
    print(f"repo:       {repo_id}  [{visibility_label}]")
    print(f"root:       {root}")
    print(f"targets:    {', '.join(selected)}")

    if make_public and args.include_private:
        print()
        print("!! WARNING: --public + --include-private will publish the held-out eval set.")
        print("!! This permanently breaks contamination resistance for the benchmark.")
        print("!! If you want fair-use public release WITH contamination control, drop --include-private.")

    if make_public:
        license_statement = root / "LICENSE_STATEMENT.md"
        if not license_statement.exists():
            print(
                "\nERROR: LICENSE_STATEMENT.md is missing. A public upload requires the fair-use posture "
                "to be documented at the dataset root. Create LICENSE_STATEMENT.md and re-run.",
                file=sys.stderr,
            )
            return 1

    print()
    print("Planned uploads:")
    any_files = False
    for name in selected:
        t = UPLOAD_TARGETS[name]
        n = _count_files(root, t["path"], t["patterns"])
        any_files = any_files or (n > 0)
        print(f"  [{name:14s}] {n:>5d} files from {t['path']}/  ({t['description']})")

    if not any_files:
        print("\nNothing to upload.")
        return 0

    if "images" in selected and not args.skip_manifest_check:
        print("\nVerifying MANIFEST.jsonl is in sync with fixtures/images/ ...")
        if not _verify_manifest_in_sync(root):
            print(
                "\nManifest is stale. Run `python scripts/build_manifest.py` and re-run upload.\n"
                "(Or pass --skip-manifest-check to override.)",
                file=sys.stderr,
            )
            return 1

    if not args.execute:
        print("\n[dry-run] no files uploaded. Re-run with --execute to actually push.")
        return 0

    try:
        from huggingface_hub import HfApi  # noqa: F401
    except ImportError:
        print("\nERROR: huggingface_hub not installed. Run: pip install huggingface_hub", file=sys.stderr)
        return 1

    token = os.environ.get("HF_TOKEN")
    if not _ensure_repo(repo_id, make_public, token):
        return 1

    print("\nUploading...")
    for name in selected:
        _upload_target(repo_id, token, root, name, UPLOAD_TARGETS[name])

    print("\nupload complete.")
    if make_public:
        print(f"public URL: https://huggingface.co/datasets/{repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
