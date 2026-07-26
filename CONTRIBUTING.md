# Contributing

## Setup

Each service is independent. Pick the one you're touching and set it up on its own.

- Rust: `cargo check` from the repo root (workspace covers `shell/` and `shell/audio-core/`).
- Python services: `cd services/<name> && uv sync`, then `uv run pytest`.
- Frontend: not scaffolded yet, see `docs/roadmap.md`.
- Once per checkout: `uvx pre-commit install --hook-type pre-commit --hook-type commit-msg`, so formatting, lint, and commit message checks run locally before you push.

## Before opening a PR

- Format: `cargo fmt` for Rust, `ruff format` inside the relevant `services/<name>`.
- Lint: `cargo clippy`, `ruff check`.
- Tests pass for whatever service you touched. If you changed a shared contract (e.g. the `AudioSegment`/`TranscriptSegment` shapes in `docs/transcription-service.md`), check the other side of that contract still holds.
- Docs updated if the change affects anything described in `docs/`.

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

Keep them scoped to one service or one concern where possible. Explain the why in the description; the diff already shows the what. Link the roadmap phase or feature note it relates to if there is one. Every PR uses the PR template's Definition of Done checklist; don't remove items from it, check them honestly.

One issue, one PR. If an issue is too big to close with a single reviewable PR, split it into sub-issues first rather than opening one PR that closes several issues at once.

## Project board

Every tracked issue lives on the [project board](https://github.com/users/harunnryd/projects/8), with a `Phase` field matching `docs/roadmap.md` and a `Status` field with three states:

- **Todo**: not started.
- **In Progress**: a PR referencing the issue (`Closes #N`) is open, or someone has explicitly picked it up.
- **Done**: the PR merged, CI was green on that merge, and the issue is closed. Not "code written", not "mostly works": merged and green.

Reference the issue you're closing in the PR description (`Closes #N`) so the link between issue, PR, and board status stays automatic instead of something someone has to remember to update by hand.

## Code review expectations

Anyone reviewing should check against `AGENTS.md`, particularly: no unnecessary comments, no speculative abstraction, real tests over mocked-everything tests, and service boundaries respected (no reaching into another service's internals or opening its database directly).
