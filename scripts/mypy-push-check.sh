#!/usr/bin/env bash
# Run mypy in every Python service and package that changed between the local
# branch and the remote tracking branch. Fails if any changed service or
# package has no .venv — run `uv sync` inside the directory before pushing.
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
    echo "mypy: ${dir} — no .venv found; run 'uv sync' inside ${dir} before pushing" >&2
    failed=1
  fi
}

while IFS= read -r dir; do
  run_mypy "$dir"
done < <(find services packages -maxdepth 2 -name pyproject.toml -exec dirname {} \; | sort)

exit "$failed"
