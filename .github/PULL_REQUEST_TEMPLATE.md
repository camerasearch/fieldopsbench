<!--
Thanks for the PR. Before requesting review, please confirm the items below.
The CI workflow runs `bash scripts/preflight.sh` on every push and PR; it
must be green for a maintainer to look at the change.
-->

## Summary

<!-- 1-3 sentences. What does this PR change and why? -->

## Type of change

- [ ] Bug fix (regression test included)
- [ ] New evaluation case(s)
- [ ] New / updated model runner
- [ ] New / updated scoring dimension
- [ ] Documentation only
- [ ] Other (describe):

## Checklist

- [ ] `bash scripts/preflight.sh` exits 0 locally.
- [ ] If I changed a count claim (trades, code bodies, cases, images),
      I updated **all** of: `README.md`, `pyproject.toml`,
      `DATASHEET.md`, `LICENSE_STATEMENT.md`, `CHANGELOG.md`.
- [ ] If I added a new public claim in docs (a metric, a guarantee, a
      defense), I added a test under `tests/` that demonstrates it.
- [ ] No tracked changes under `cases/private/` or `candidates/`.
- [ ] No new image binaries committed (binaries are gitignored; the
      manifest is the source of truth in git).
- [ ] If I added a new visual case, the image flowed through
      `fixtures/images/intake/` + `scripts/intake_visual.py` and the
      manifest row records `source_url`, `attribution`, `license`.
- [ ] If I touched the dataset canary string
      (`FIELDOPSBENCH_DATASET_CANARY`), I have read SECURITY.md and
      understand this invalidates prior contamination probes.

## Notes for the reviewer

<!-- Anything non-obvious about the change. Edge cases handled, follow-ups deferred, etc. -->
