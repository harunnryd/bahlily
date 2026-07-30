# Contributing

## Setup

Each service is independent. Pick the one you're touching and set it up on its own.

- Rust: `cargo check` from the repo root (workspace covers `shell/` and `shell/audio-core/`).
- Python services: `cd services/<name> && uv sync`, then `uv run pytest`.
- Frontend: not scaffolded yet, see `docs/roadmap.md`.

Once per checkout, install the local hooks that enforce this project's standards automatically:

```bash
uvx pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

What each hook type does:
- **pre-commit**: ruff format + lint, cargo fmt, actionlint (CI YAML correctness), zizmor (CI security)
- **commit-msg**: conventional commit format check
- **pre-push**: mypy strict in every Python service you changed; run `uv sync` inside each service directory before pushing

## Before opening a PR

Run these from the service directory before marking the PR ready:

```bash
# format + lint (pre-commit runs this too, but good to run explicitly)
uv run ruff format . && uv run ruff check .

# types — must pass with zero errors
uv run mypy .

# tests
uv run pytest
```

If you touched `.github/workflows/`, run these from the repository root:

```bash
actionlint .github/workflows/*.yml
uvx zizmor .github/workflows/*.yml
```

If you touched the Rust workspace, run these from the repository root:

```bash
cargo fmt --all && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
```

Docs updated if the change affects anything described in `docs/`.

## Commit messages

Conventional Commits, lowercase, one line: `type(scope): short description`. See `AGENTS.md` for the full convention and examples.

## Branching model

Trunk-based. `main` is always in a working, releasable state. No `develop`, no long-lived release branches.

- Branch off `main`, name it `type/short-desc` using the same types as commit messages: `feat/parakeet-model-registry`, `fix/audio-device-switch`, `docs/roadmap-phase-2`.
- Keep branches short-lived, ideally merged within a day or two. If a feature is bigger than that, split it: land the parts behind a small interface or a feature flag rather than keeping a long-lived branch around.
- Rebase onto `main` before opening a PR and before merging, rather than merging `main` into your branch. Keeps history linear.
- Merge with a fast-forward or squash once CI is green. Delete the branch afterward.
- CI must pass before merge. Once this repo has a remote, turn on branch protection on `main`: require the CI check, require the branch to be up to date, no direct pushes.

## Working in parallel with git worktrees

Since each service is independent, worktrees are the natural way to work on more than one thing at once without stashing.

```
git worktree add ../bahlily-transcription-parakeet feat/parakeet-model-registry
git worktree add ../bahlily-orchestration-deepeval feat/deepeval-wiring
```

Each worktree is a full checkout on its own branch, sharing the same `.git`. Run a service's own setup (`uv sync`, `cargo check`) inside its worktree as normal. Remove a worktree once its branch is merged:

```
git worktree remove ../bahlily-transcription-parakeet
```

This is also the expected pattern for agents working on this repo: if two agents (or two independent tasks) touch different services at the same time, give each its own worktree rather than sharing one working directory.

## Pull requests

Open as draft first. Convert to ready only when:
- All local checks above pass
- CI is green on the branch
- You've worked through the PR template's Definition of Done checklist honestly

Keep PRs scoped to one service or one concern. Explain the why in the description; the diff already shows the what. Link the roadmap phase or feature note if there is one.

One issue, one PR. If an issue is too big to close with a single reviewable PR, split it into sub-issues first.

## Project board

Every tracked issue lives on the [project board](https://github.com/users/harunnryd/projects/8), with a `Phase` field matching `docs/roadmap.md` and a `Status` field with three states:

- **Todo**: not started.
- **In Progress**: a PR referencing the issue (`Closes #N`) is open, or someone has explicitly picked it up.
- **Done**: the PR merged, CI was green on that merge, and the issue is closed. Not "code written", not "mostly works": merged and green.

Reference the issue you're closing in the PR description (`Closes #N`) so the link between issue, PR, and board status stays automatic.

## Code review expectations

Anyone reviewing should check against `AGENTS.md`, particularly:
- No comments explaining what code does; only non-obvious why
- No speculative abstraction; built only for the feature at hand
- Real tests over mocked-everything tests; own logic exercised for real
- Service boundaries respected; no cross-service imports, no direct SQLite access outside `services/storage`
- All GitHub Actions references pinned to SHA, shell steps use `set -euo pipefail`
