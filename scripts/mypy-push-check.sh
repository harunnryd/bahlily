#!/usr/bin/env bash
# Run mypy in every Python service and package that changed between the local
# branch and the remote tracking branch. Services whose venv is not yet set
# up (no .venv/) are skipped with a notice — run `uv sync` inside the service
# directory to set them up.
set -euo pipefail

changed=$(git diff --name-only "@{upstream}...HEAD" 2>/dev/null \
  || git diff --name-only "HEAD~1..HEAD" 2>/dev/null \
  || true)

if [ -z "$changed" ]; then
  exit 0
fi

failed=0

run_mypy() {
  local dir="$1"
  if echo "$changed" | grep -q "^${dir}/" && [ -d "${dir}/.venv" ]; then
    echo "mypy: ${dir}"
    (cd "$dir" && uv run mypy .) || failed=1
  elif echo "$changed" | grep -q "^${dir}/" && [ ! -d "${dir}/.venv" ]; then
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
