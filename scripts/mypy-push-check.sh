#!/usr/bin/env bash
# Run mypy in every Python service and package that changed between the local
# branch and the remote tracking branch. Services whose venv is not yet set
# up (no .venv/) are skipped with a notice — run `uv sync` inside the service
# directory to set them up.
set -euo pipefail

if git rev-parse --verify "@{upstream}" >/dev/null 2>&1; then
  changed=$(git diff --name-only "@{upstream}...HEAD")
elif git rev-parse --verify "origin/main" >/dev/null 2>&1; then
  base=$(git merge-base "origin/main" HEAD)
  changed=$(git diff --name-only "${base}..HEAD")
else
  echo "mypy-push-check: no upstream tracking branch and no origin/main; cannot determine changed files" >&2
  exit 1
fi

if [ -z "$changed" ]; then
  exit 0
fi

failed=0

run_mypy() {
  local dir="$1"
  if grep -q "^${dir}/" <<< "$changed" && [ -d "${dir}/.venv" ]; then
    echo "mypy: ${dir}"
    (cd "$dir" && uv run mypy .) || failed=1
  elif grep -q "^${dir}/" <<< "$changed" && [ ! -d "${dir}/.venv" ]; then
    echo "mypy: ${dir} — skipped (run 'uv sync' inside ${dir} to enable)"
  fi
}

run_mypy "services/calendar"
run_mypy "services/chat"
run_mypy "services/export"
run_mypy "services/orchestration"
run_mypy "services/storage"
run_mypy "services/transcription"
run_mypy "packages/bahlily-logging"

exit $failed
