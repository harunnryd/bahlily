# Agent instructions

This file sets the standard for any AI coding agent (or human) working in this repo. Read `docs/architecture.md` first for the why behind the service split; this file is about how code should look and behave once written.

Writing a rule down here is not enough to guarantee it gets followed. Where a rule can be checked mechanically (commit message format, formatting, lint, types, tests, CI security), it must be enforced by `pre-commit` and CI, not left to memory or good intentions. The first thing to do in a fresh checkout, before making any commit, is:

```bash
uvx pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

This installs three hooks:
- **pre-commit**: ruff format + lint, cargo fmt, actionlint, zizmor
- **commit-msg**: conventional commit format
- **pre-push**: mypy in every Python service you changed

If you catch a rule that's documented here but not enforced by a hook or CI check, that's a gap. Fix the gap; don't just try harder to remember.

## Scope and boundaries

- Each directory under `services/` is an independently runnable Python service with its own `pyproject.toml`. Don't add cross-service imports; if two services need to share logic, it belongs in a package under `packages/`, not a relative import across service boundaries.
- `shell/audio-core` is the only place native OS audio APIs get touched. Don't reach for OS-level audio or window APIs anywhere else.
- Storage has exactly one writer, defined in `services/storage`. No other service opens the SQLite file directly. If a service needs data it doesn't own, it goes through storage's API.
- Don't add a monorepo build tool (Turborepo, Nx, Bazel). Each language keeps its own native tooling.

## Code style

- No comments that explain what the code does. Names, function boundaries, and structure should make that obvious on their own. A comment is only acceptable when it captures a non-obvious why: a workaround for a specific external bug, a constraint that isn't visible from the code itself, an invariant a reader could easily violate by "cleaning up" the code. If you'd delete the comment and nothing would be lost, it shouldn't be there.
- No docstrings that restate the function signature in prose. Document the non-obvious behavior only, and only where it exists.
- Match existing formatting tools per language: `rustfmt` for Rust, `ruff format` for Python, `prettier`/`biome` for the frontend once it exists. The pre-commit hook runs these automatically; don't hand-format.
- All public Python functions and methods must have type annotations. `mypy --strict` must pass in every service. The pre-push hook enforces this locally; CI enforces it on the PR.
- Validate at real input boundaries: user-supplied request bodies, external API responses, file and network I/O. Don't add validation between internal functions that already trust each other's outputs. Examples of real boundaries: a FastAPI request handler (validate with Pydantic `Field`), the output of an LLM call (validate the structured response schema), a YAML file loaded from disk. Examples of non-boundaries: a private helper called only by code you own.
- Don't add error handling for cases that can't happen given the code's own guarantees.
- No speculative abstraction. Build for the feature in front of you. If the same three lines show up a third time, that's when it becomes a shared function, not before.
- Don't leave partially finished work committed. A stub with a `NotImplementedError` and a matching open issue is fine; a half-working feature pretending to be done is not.

## Testing

- New behavior needs a test that would fail without it. Skip this only for pure scaffolding or config changes.
- Test at the boundary the service exposes (its HTTP endpoints, its public functions), not at the level of internal implementation details.
- Mock only what crosses a real process boundary: LLM provider HTTP calls, calendar API calls, OS-level audio drivers, the filesystem in integration tests. Don't mock your own service's code to make a test faster or simpler; exercise your own logic for real. If a test only passes because you mocked out most of the thing you're testing, you don't have a test.
- Concrete examples of what to mock: `init_chat_model` (external LLM), a calendar OAuth client, `ScreenCaptureKit`. Concrete examples of what not to mock: `build_prompt`, `classify_provider_exception`, your own Pydantic models.
- Test the failure paths that matter: required field missing, empty input rejected, provider auth error mapped to the right HTTP status, retry budget exhausted. These are the paths CodeRabbit and real users will hit first.

## GitHub Actions

- All action references (`uses:`) must be pinned to a full commit SHA with an inline comment identifying the version: `uses: actions/checkout@11bd7190... # v5.0.0`. Mutable tags (`@v4`, `@stable`) are not acceptable. `zizmor` (run by pre-commit) enforces this.
- No `curl | sh` or equivalent remote-code execution without downloading to a temp file, verifying a checksum, and running separately.
- Every job must have `timeout-minutes`. Use judgment: fast lint jobs get 5–10 min, Rust builds 20 min, Python services 15 min, eval jobs with model downloads 30 min.
- Jobs that only apply to certain paths must use the `changes` job's outputs (`if: needs.changes.outputs.X == 'true'`), not run unconditionally. The `changes` job uses `dorny/paths-filter`.
- Shell steps in workflows follow the same rules as application shell scripts: `set -euo pipefail`, quote variables, no bare `$1` expansions. `shellcheck` (run by `actionlint`) enforces this.

## Dependencies

- Keep dependencies permissively licensed (MIT, Apache-2.0, BSD). Avoid copyleft (GPL, LGPL) in anything linked into a shipped binary.
- Runtime dependencies belong in `[project] dependencies`. Libraries used only for testing belong in `[dependency-groups] dev`. Libraries used only for evaluation (e.g. `deepeval`) belong in their own named group (e.g. `[dependency-groups] eval`). CI installs the eval group only in the eval job, not in the main Python matrix.
- When adding a dependency, pin a minimum version (`>=x.y`). Don't pin an exact version unless you have a specific reproducibility requirement and a plan to keep it updated.

## Commits

Conventional Commits, lowercase, one line, no period: `type(scope): short description`. Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`, `perf`. Keep the summary under about 60 characters; if more context is needed, a short body is fine. No em-dashes, no filler like "this commit adds..." Say what changed, plainly.

```text
feat(transcription): add parakeet model registry
fix(audio-core): stop dropping samples on device switch
docs: update roadmap phase 2 checklist
```

The `commit-msg` hook enforces the format.

## Branching and CI

Trunk-based: `main` stays releasable, branches are short-lived and named `type/short-desc` matching the commit types above. See `CONTRIBUTING.md` for the full branching model and git worktree usage.

CI (`.github/workflows/ci.yml`) runs:
- Rust: `cargo fmt --check` + `clippy` + `cargo test`
- Python (each service): `ruff format --check` + `ruff check` + `mypy` + `pytest`
- Error catalog: above checks + `bahlily-logging-check-catalog`
- Orchestration eval: Ollama + `pytest eval/` — only on push to `main` when `services/orchestration/**` changed

All jobs are path-filtered via a `changes` job so only affected jobs run per push. Don't consider a change done until CI is green on the PR; `pre-commit` is the fast local approximation, CI is what's authoritative.

## Writing docs

Same as code: no em-dashes, no formulaic repeated section templates padded for length. Write like you're explaining it to a colleague. Update `docs/` alongside the code that changes the behavior it describes; a stale architecture doc is worse than no doc.
