"""Manifest invariants — the artifacts most likely to leak credibility issues.

These run without any image binaries on disk; they only read the JSONL.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "fixtures" / "images" / "MANIFEST.jsonl"
PUBLIC_CASES_DIR = REPO_ROOT / "cases" / "public"


@pytest.fixture(scope="module")
def manifest_rows() -> list[dict]:
    assert MANIFEST_PATH.exists(), f"missing {MANIFEST_PATH}"
    return [json.loads(line) for line in MANIFEST_PATH.read_text().splitlines() if line.strip()]


def test_no_local_temp_paths_in_source_url(manifest_rows: list[dict]) -> None:
    """Earlier acquisition runs left /var/folders/... temp paths in 558/851
    rows. Those are not real provenance; the sanitize pass is supposed to
    remove every one. This test will catch any regression at the next
    acquisition run."""
    bad = [
        r for r in manifest_rows
        if not isinstance(r.get("source_url"), str)
        or not r["source_url"].startswith(("http://", "https://"))
    ]
    assert not bad, (
        f"{len(bad)} manifest row(s) lack an http(s) source_url; "
        f"sample paths: {[r.get('path') for r in bad[:3]]}"
    )


def test_no_duplicate_sha256(manifest_rows: list[dict]) -> None:
    counts = collections.Counter(r.get("sha256") for r in manifest_rows)
    duped = {sha: n for sha, n in counts.items() if n > 1}
    assert not duped, f"duplicate sha256s in MANIFEST.jsonl: {duped}"


def test_every_row_has_required_fields(manifest_rows: list[dict]) -> None:
    required = {"path", "sha256", "size_bytes", "source_url", "source_dataset", "license"}
    for r in manifest_rows:
        missing = required - set(r.keys())
        assert not missing, f"row {r.get('path')} missing fields {missing}"


def test_no_known_chrome_url_substrings(manifest_rows: list[dict]) -> None:
    """Catch web-chrome scrape artifacts (logos, layout images) that
    sneak in alongside real subject photos."""
    bad_subs = (
        "/cms/images/layout/",
        "/images/logo",
        "/wp-content/themes/",
        "favicon",
    )
    chrome = []
    for r in manifest_rows:
        u = (r.get("source_url") or "").lower()
        for sub in bad_subs:
            if sub in u:
                chrome.append((r.get("path"), u))
                break
    assert not chrome, f"manifest contains likely website chrome: {chrome[:5]}"


def _normalize_attachment(att: str) -> str:
    """Map an EvalCase ``attachments`` entry to a MANIFEST.jsonl ``path``.

    Cases historically wrote either ``images/<rel>``, ``fixtures/images/<rel>``,
    or already-stripped ``<rel>``. Manifest paths are always relative to
    ``fixtures/images/``. Normalize all three forms onto that root.
    """
    for prefix in ("fixtures/images/", "images/"):
        if att.startswith(prefix):
            return att[len(prefix):]
    return att


def test_active_case_attachments_resolve(manifest_rows: list[dict]) -> None:
    """Every attachment referenced by a non-deprecated case must exist in
    the manifest."""
    if not PUBLIC_CASES_DIR.is_dir():
        pytest.skip(f"no public cases dir at {PUBLIC_CASES_DIR}")
    manifest_paths = {r["path"] for r in manifest_rows}
    missing: list[tuple[str, str]] = []
    for jsonl in sorted(PUBLIC_CASES_DIR.glob("*.jsonl")):
        for line in jsonl.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if case.get("deprecated"):
                continue
            for att in (case.get("attachments") or []):
                rel = _normalize_attachment(att)
                if rel not in manifest_paths:
                    missing.append((case.get("id"), att))
    assert not missing, (
        f"{len(missing)} active case attachment(s) do not resolve to a "
        f"manifest row; sample: {missing[:5]}"
    )
