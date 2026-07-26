# Migration Roadmap

A phased path from today's single-Rust-binary-in-Tauri app to the service architecture in `05-proposed-architecture.md`. Ordered by leverage (value delivered) vs. risk (chance of regressing something that already works), not by dependency order alone.

## Phase 0 — Keep as-is, don't touch yet

- **Audio capture + mixing + VAD** (`frontend/src-tauri/src/audio/`, `audio_v2/`). This is the one subsystem confirmed Rust-required (`04` §1-2). Leave it running inside the current Tauri process initially; it becomes the "Audio Core" sidecar in `05` later, but re-plumbing it is the last, not first, step — it's the riskiest thing to break (real-time, platform-specific, hardest to test) and the least valuable thing to migrate (it's already correct Rust, per `04`).
- **Desktop shell** (tray, single-instance, updater, notifications). Stays Tauri/Rust indefinitely per `04` §8 — nothing to migrate here at all.

## Phase 1 — Extract summarization/LLM orchestration first (highest leverage, lowest risk)

Per `04` §6, this is the "clear win" with no real-time constraint, meaning it's the safest first cut: stand up a Python service using LangChain/LangGraph that replicates today's `summary/` module (prompt templates, multi-provider LLM client for Ollama/Anthropic/Groq/OpenRouter/OpenAI). Point the existing Tauri app at this new service over localhost HTTP instead of calling the Rust `summary/` module directly, feature-flagged so the old Rust path stays available as a fallback until the Python service is verified equivalent on real meeting data.

Why first: it's pure logic with no OS dependency, it's where DeepEval and LangGraph deliver immediate value (the explicit motivation for this whole rewrite), and a regression here is visible/recoverable (bad summary text) rather than silent/catastrophic (dropped audio).

## Phase 2 — Transcription service

Stand up the Python transcription service (`faster-whisper`/whisper.cpp-MLX + `onnxruntime`/`onnx-asr` for Parakeet, per `04` §4-5), fed by the still-Rust audio core over the local IPC path described in `05`. Validate against the same benchmark meetings used for Phase 1 (WER, latency, GPU utilization) before cutting over — `04` flags `faster-whisper` as ~4x faster than whisper.cpp on CUDA but notes Apple Silicon needs its own path (whisper.cpp/MLX from Python), so this phase should explicitly test both platforms, not just the developer's primary machine.

## Phase 3 — Storage cutover

Pick the single authoritative SQLite owner now (Python service colocated with summarization, per `05`'s recommendation, or a TS layer if the team prefers) and migrate the existing local SQLite schema/data over. Do this only after Phases 1-2 are stable, since every other service will depend on this one being correct and this is the phase most likely to affect existing users' historical meeting data — plan a migration script and a rollback path, not a live schema rewrite.

## Phase 4 — Net-new Pro-track features (build in this order, per `03`'s findings)

1. **Custom/expanded summary templates** — no new infrastructure needed once Phase 1's LangChain service exists (`03` §5); lowest effort, ships value immediately.
2. **Advanced export** (Markdown/DOCX/PDF) — depends on Phase 1's structured-summary schema existing; straightforward once that schema is fixed (`03` §4).
3. **Chat with meetings** — depends on Phases 1-3 (needs the LLM service, transcripts, and stable storage); add the RAG/vector-store layer per `03` §2 and `05`.
4. **Speaker diarization** — depends on Phase 2 (needs the transcription service's segment timestamps to link against); budget real GPU/compute headroom since `03` §1 notes it roughly doubles inference cost per meeting.
5. **Calendar integration + local auto-start** — mostly independent of the other services (new service, `icalendar` + Google/MS Graph APIs per `03` §3); can be built in parallel with 1-4, but sequenced last here because it's the feature most likely to need its own UX design pass (permission prompts, auto-start opt-in) before it's worth building.

Rationale for this order: 1-2 reuse Phase 1 infrastructure directly with minimal new surface area; 3 is higher-value but has real accuracy/compute gotchas (`03` documents these in depth) that deserve dedicated attention rather than being rushed alongside other features; 4 is architecturally separate and can proceed on its own timeline.

## What stays explicitly out of scope until Phase 4 is done

Per `05`'s deployment-shape section: **no sync/multi-device/self-hosted-server component** until the full local pipeline (Phases 0-4) is working end-to-end for a single user. Building Option B (optional sync service) before Option A is solid would mean designing multi-writer conflict resolution against a data model that's still changing.

## Suggested new-project repo layout

```
meetily/ (or new repo name)
├── shell/                  # Tauri Rust shell — window/tray/updater/notifications
│   └── audio-core/         # capture + mixing + VAD, the one Rust business-logic module
├── services/
│   ├── transcription/      # Python: faster-whisper, onnx-asr, pyannote
│   ├── orchestration/      # Python: LangChain/LangGraph, multi-provider LLM, DeepEval
│   ├── chat/                # Python: RAG, vector store, optional MCP surface
│   ├── calendar/            # Python: Google Calendar/MS Graph, icalendar
│   ├── export/               # Python: python-docx, weasyprint/reportlab
│   └── storage/               # single SQLite owner (Python or TS, per team decision)
├── frontend/                   # existing Next.js/React UI, minimal changes to component tree
└── docs/reverse_engineering/     # this folder
```

Each `services/*` directory should be independently runnable (its own `pyproject.toml`/entrypoint, its own tests) so a contributor can clone the repo and work on, say, `services/chat/` without standing up the audio pipeline or a GPU — directly serving the open-source-maintainability goal from `05`.

## Verification per phase

- **Phase 1**: run the same meeting transcript through old (Rust) and new (Python/LangChain) summarization paths side by side; diff summary quality manually and, once DeepEval is wired in, automatically.
- **Phase 2**: WER comparison old (whisper-rs) vs. new (faster-whisper/onnx-asr) on a fixed benchmark set of real recorded meetings, per platform (macOS Metal, NVIDIA CUDA, at minimum).
- **Phase 3**: row-count and spot-check data integrity before/after migration on a copy of a real user's local database, plus a rollback script tested before cutover.
- **Phase 4 features**: each ships behind its own settings toggle (mirroring the existing `betaFeatures` pattern already in the codebase) so new, less-proven features (diarization, calendar auto-start) can be disabled without affecting the stable core.
