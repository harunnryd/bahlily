# Contributing

## Setup

Each service is independent. Pick the one you're touching and set it up on its own.

- Rust: `cargo check` from the repo root (workspace covers `shell/` and `shell/audio-core/`).
- Python services: `cd services/<name> && uv sync`, then `uv run pytest`.
- Frontend: not scaffolded yet, see `docs/roadmap.md`.

## Before opening a PR

- Format: `cargo fmt` for Rust, `ruff format` inside the relevant `services/<name>`.
- Lint: `cargo clippy`, `ruff check`.
- Tests pass for whatever service you touched. If you changed a shared contract (e.g. the `AudioSegment`/`TranscriptSegment` shapes in `docs/transcription-service.md`), check the other side of that contract still holds.
- Docs updated if the change affects anything described in `docs/`.

## Commit messages

Conventional Commits, lowercase, one line: `type(scope): short description`. See `AGENTS.md` for the full convention and examples.

## Pull requests

Keep them scoped to one service or one concern where possible. Explain the why in the description; the diff already shows the what. Link the roadmap phase or feature note it relates to if there is one.

## Code review expectations

Anyone reviewing should check against `AGENTS.md`, particularly: no unnecessary comments, no speculative abstraction, real tests over mocked-everything tests, and service boundaries respected (no reaching into another service's internals or opening its database directly).
