# Archived tooling

These scripts are kept as a record of how earlier versions of the dataset
were collected and migrated. They are **not maintained**, are excluded from
linting and tests, and are not expected to run as-is: they depend on the
structure of third-party websites as of early 2026, on Playwright, and in
places on modules from the repository they were originally developed in.

| Directory | Contents |
|---|---|
| `acquisition/` | Crawlers and extractors used to gather candidate images and text from MSHA, CSB, InterNACHI, equipment manuals, and fault-code databases. Most of what they collected was withdrawn in v0.2.1; see [LICENSE_STATEMENT.md](../LICENSE_STATEMENT.md#history). |
| `migrations/` | One-off scripts: `sanitize_manifest.py` (v0.2.1 manifest cleanup), `normalize_attachments.py` (attachment path migration), and `import_reddit_vision.py` (import of the Reddit photo cases, including the source-URL reconstruction discussed in the license statement). |

Maintained tooling lives in
[`src/fieldopsbench/scripts/`](../src/fieldopsbench/scripts/) and
[`scripts/`](../scripts/).
