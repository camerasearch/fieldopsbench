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

- [ ] `bash scripts/preflight.sh` passes locally.
- [ ] If this changes any score, it has a `CHANGELOG.md` entry and
      `METHODOLOGY.md` is updated.
- [ ] If this changes case counts, the README, datasheet, and dataset card
      are updated and `make figures` was re-run.
- [ ] New or changed cases were formatted with
      `python -m fieldopsbench.scripts.format_cases`.
- [ ] No files under `cases/private/` and no image binaries are included.
- [ ] New images have a manifest row with a working `source_url`, an
      attribution, and a license.

## Notes for the reviewer

<!-- Anything non-obvious about the change. Edge cases handled, follow-ups deferred, etc. -->
