# Bahlily

[![CI](https://github.com/harunnryd/bahlily/actions/workflows/ci.yml/badge.svg)](https://github.com/harunnryd/bahlily/actions/workflows/ci.yml)
[![CodeRabbit Pull Request Reviews](https://img.shields.io/coderabbit/prs/github/harunnryd/bahlily?utm_source=oss&utm_medium=github&utm_campaign=harunnryd%2Fbahlily&labelColor=171717&color=FF570A&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit+Reviews)](https://coderabbit.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status: early development](https://img.shields.io/badge/status-early%20development-orange)](docs/roadmap.md)

Privacy-first, fully open-source AI meeting assistant. Local transcription, speaker diarization, summarization, chat over your meetings, calendar-triggered recording, and rich export, all running on-device by default, with nothing gated behind a paid tier.

<details>
<summary>Table of contents</summary>

- [Project status](#project-status)
- [Why Bahlily](#why-bahlily)
- [Planned features](#planned-features)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

</details>

## Project status

Bahlily is in early development. There's no built application yet, only the project skeleton: a Rust workspace, six independent Python services scaffolded with `uv`, CI, and the architecture docs that guide the build order. If you're looking for a working meeting assistant today, this isn't it yet. If you want to build one in the open, start with [`docs/roadmap.md`](docs/roadmap.md).

## Why Bahlily

- **Local first.** Transcription, diarization, and storage run on your machine. Nothing is required to leave your device.
- **No paid tier.** Every feature is open source from day one, including the ones most competing tools charge for: diarization, custom summary templates, rich export, chat over your meetings.
- **Small, honest Rust core.** Rust is used only where it's genuinely load-bearing (native audio capture, the desktop shell). Everything else is Python, so the project can build on LangChain, LangGraph, and DeepEval instead of reimplementing that ecosystem.
- **Built to be contributed to.** Each service is independent, with its own tests, its own lint config, and its own `pyproject.toml`. You can work on one without standing up the rest of the stack. See [`AGENTS.md`](AGENTS.md) for the standard every change is held to.

## Planned features

- Real-time local transcription (Whisper via `faster-whisper`, and Parakeet via `onnx-asr`)
- Speaker diarization (`pyannote.audio`, optional via `uv sync --extra diarization`)
- AI summaries with a multi-provider LLM client (Ollama, Anthropic, Groq, OpenRouter, OpenAI)
- Custom, user-authored summary templates
- Chat over your own meeting history (retrieval-augmented, local vector store)
- Calendar-triggered local recording, no meeting bot, no audio leaving your device
- Export to Markdown, DOCX, and PDF from one structured summary schema

None of this is built yet. See [`docs/feature-notes.md`](docs/feature-notes.md) for how each one is planned to work, and [`docs/roadmap.md`](docs/roadmap.md) for build order.

## Architecture

Full reasoning in [`docs/architecture.md`](docs/architecture.md).

```
bahlily/
├── shell/
│   └── audio-core/
├── services/
│   ├── transcription/
│   ├── orchestration/
│   ├── chat/
│   ├── calendar/
│   ├── export/
│   └── storage/
├── frontend/
└── site/
```

- `shell/` is the Tauri (Rust) desktop shell: window, tray, updater. `audio-core/` is the one Rust business-logic crate, handling mic+system capture, real-time mixing, and VAD.
- `services/` holds the Python sidecar services, one responsibility each: `transcription` (Whisper + Parakeet + diarization), `orchestration` (LangChain/LangGraph summarization, prompt templates, multi-provider LLM, DeepEval), `chat` (RAG over transcripts), `calendar` (meeting-link detection, local auto-start), `export` (Markdown/DOCX/PDF renderers), `storage` (the single authoritative SQLite owner).
- `frontend/` is the Next.js/React UI, talking to the Python services and the Rust shell.
- `site/` is the public marketing site (a separate, standalone Next.js static export — no shared code with `frontend/`, no server, deployed independently).

No cross-language monorepo tool (Turborepo, Nx). Each service uses its own language's native tooling: Cargo for Rust, `uv` for Python, pnpm for the frontend.

## Getting started

There's nothing to run end to end yet, but each piece can be built and tested independently:

```bash
# Rust workspace (shell/, shell/audio-core/)
cargo check

# any Python service
cd services/<name>
uv sync
uv run pytest

# Speaker diarization requires the optional `diarization` extra
# (pulls in pyannote.audio and ~80 transitive deps including torch):
cd services/transcription
uv sync --extra diarization
export BAHLILY_TRANSCRIPTION_HF_TOKEN=hf_...
```

Once per checkout, install the local hooks that enforce this project's standards automatically:

```bash
uvx pre-commit install --hook-type pre-commit --hook-type commit-msg
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full setup, branching model, and PR checklist.

## Roadmap

Build order and what's deliberately deferred: [`docs/roadmap.md`](docs/roadmap.md).

## Contributing

Contributions are welcome. [`AGENTS.md`](AGENTS.md) sets the standard for code, tests, and commits, whether you're a human or an AI agent. [`CONTRIBUTING.md`](CONTRIBUTING.md) covers setup, branching, and what a PR needs before review.

## Security

Found a vulnerability? Please don't open a public issue. See [`SECURITY.md`](SECURITY.md) for how to report it.

## License

MIT. See [`LICENSE`](LICENSE).
