# Agent instructions

This file sets the standard for any AI coding agent (or human) working in this repo. Read `docs/architecture.md` first for the why behind the service split; this file is about how code should look and behave once written.

Writing a rule down here is not enough to guarantee it gets followed, by an agent or by a human. Where a rule can be checked mechanically (commit message format, formatting, lint, types, tests), it must be enforced by `pre-commit` and CI, not left to memory or good intentions. The first thing to do in a fresh checkout, before making any commit, is `uvx pre-commit install --hook-type pre-commit --hook-type commit-msg`. If you catch a rule in this repo that's documented but not enforced by a hook or CI check, that's a gap, fix the gap, don't just try harder to remember.

## Scope and boundaries

- Each directory under `services/` is an independently runnable Python service with its own `pyproject.toml`. Don't add cross-service imports; if two services need to share logic, it belongs in a small published package, not a relative import across service boundaries.
- `shell/audio-core` is the only place native OS audio APIs get touched. Don't reach for OS-level audio/window APIs anywhere else.
- Storage has exactly one writer, defined in `services/storage`. No other service opens the SQLite file directly. If a service needs data it doesn't own, it goes through storage's API.
- Don't add a monorepo build tool (Turborepo, Nx, Bazel). Each language keeps its own native tooling.

## Code style

- No comments that explain what the code does. Names, function boundaries, and structure should make that obvious on their own. A comment is only acceptable when it captures a non-obvious why: a workaround for a specific external bug, a constraint that isn't visible from the code itself, an invariant a reader could easily violate by "cleaning up" the code. If you'd delete the comment and nothing would be lost, it shouldn't be there.
- No docstrings that restate the function signature in prose. Document the non-obvious behavior only, and only where it exists.
- Match existing formatting tools per language rather than hand-formatting: `rustfmt` for Rust, `ruff format` for Python, `prettier`/`biome` for the frontend once it exists. Run the formatter before committing; don't leave that to review.
- Don't add error handling for cases that can't happen given the code's own guarantees. Validate at real boundaries (user input, external API responses, file/network I/O), not internally between functions that already trust each other.
- No speculative abstraction. Build for the feature in front of you. If the same three lines show up a third time, that's when it becomes a shared function, not before.
- Don't leave partially finished work committed. A stub with a `NotImplementedError` and a matching open issue is fine; a half-working feature pretending to be done is not.

## Testing

- New behavior needs a test that would fail without it. Skip this only for pure scaffolding/config changes.
- Prefer testing at the boundary the service actually exposes (its API, its public functions) over mocking internals.
- Don't mock things you own just to make a test pass faster. Mock external services (LLM providers, calendar APIs) and OS-level dependencies; exercise your own logic for real.
- See `docs/transcription-service.md`'s testing section for the kind of test coverage expected of a service with real-time/ordering constraints (ordering integrity, retry-path, corruption handling), not just happy-path coverage.

## Commits

Conventional Commits, lowercase, one line, no period at the end: `type(scope): short description`. Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`, `perf`. Keep the summary line under about 60 characters; if more context is genuinely needed, a short body is fine, but the default should be a single line. No em-dashes, no filler like "this commit adds..." Say what changed, plainly.

Examples:
```
feat(transcription): add parakeet model registry
fix(audio-core): stop dropping samples on device switch
docs: update roadmap phase 2 checklist
```

`pre-commit` enforces the format on the `commit-msg` hook, and formatting/lint on the `pre-commit` hook. Run `pre-commit install` once per checkout so this happens automatically instead of getting caught in review.

## Branching and CI

Trunk-based: `main` stays releasable, branches are short-lived and named `type/short-desc` matching the commit types above. See `CONTRIBUTING.md` for the full branching model and how to use git worktrees when working on more than one service at a time.

CI (`.github/workflows/ci.yml`) runs `cargo fmt --check` + `clippy` + `cargo check` for the Rust workspace, and `ruff format --check` + `ruff check` + `mypy` + `pytest` for every service under `services/`. Treat these as the actual bar, not `pre-commit` alone: `pre-commit` is the fast local approximation, CI on the PR is what's authoritative. Don't consider a change done until both are green.

## Licensing

MIT is the project license. Keep dependencies permissively licensed (MIT, Apache-2.0, BSD). Avoid copyleft (GPL, LGPL) in anything linked into a shipped binary; if a GPL dependency is genuinely the best option for an optional, isolated feature, it needs to run as a separate process, not be imported directly, and it needs a note explaining why.

## Writing docs

Same as code: no em-dashes, no formulaic repeated section templates padded out for length. Write like you're explaining it to a colleague, not filling out a report. Update `docs/` alongside the code that changes the behavior it describes; a stale architecture doc is worse than no doc.
