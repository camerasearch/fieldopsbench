#!/usr/bin/env bash
# Install FieldOpsBench pre-commit contamination guard.
#
# Usage:
#   bash scripts/install_hooks.sh
#
# Finds the repo root via `git rev-parse --show-toplevel` and wires up
# .git/hooks/pre-commit to call scripts/pre_commit_check.py. Preserves any
# existing hook by chaining it (runs the old hook first, then ours).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="${REPO_ROOT}/.git/hooks"
HOOK_PATH="${HOOKS_DIR}/pre-commit"
GUARD_SCRIPT="src/fieldopsbench/scripts/pre_commit_check.py"
MARKER="# fieldopsbench-contamination-guard"

mkdir -p "${HOOKS_DIR}"

if [[ -f "${HOOK_PATH}" ]]; then
    if grep -q "${MARKER}" "${HOOK_PATH}"; then
        echo "pre-commit hook already installed at ${HOOK_PATH}"
        exit 0
    fi
    echo "Backing up existing pre-commit hook to ${HOOK_PATH}.backup"
    cp "${HOOK_PATH}" "${HOOK_PATH}.backup"
fi

cat > "${HOOK_PATH}" <<EOF
#!/usr/bin/env bash
${MARKER}
set -euo pipefail

# Chain to any previously-installed hook first.
if [[ -f "\$(dirname "\$0")/pre-commit.backup" ]]; then
    bash "\$(dirname "\$0")/pre-commit.backup" || exit \$?
fi

REPO_ROOT="\$(git rev-parse --show-toplevel)"
exec python3 "\${REPO_ROOT}/${GUARD_SCRIPT}"
EOF

chmod +x "${HOOK_PATH}"
echo "Installed FieldOpsBench pre-commit guard at ${HOOK_PATH}"
echo "Run 'git commit --no-verify' to bypass if ever needed."
