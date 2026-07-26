# Current Architecture (Community Edition)

## Directory map

```
meetily/
├── frontend/                      # THE supported product
│   ├── src/                       # Next.js 14 + React 18 + TypeScript UI
│   │   ├── app/                   # routes: settings, meeting-details, notes, _components
│   │   ├── components/            # Sidebar, MainNav, MainContent, MeetingDetails, AISummary,
│   │   │                          # BlockNoteEditor, ImportAudio, DatabaseImport,
│   │   │                          # TranscriptRecovery, ConfirmationModel, onboarding, ui/, molecules/
│   │   ├── contexts/, hooks/, services/, lib/, config/, constants/, types/
│   └── src-tauri/src/             # Rust core — everything the UI cannot do itself
│       ├── audio/, audio_v2/      # capture, mixing, VAD, encode/decode (ffmpeg), recording
│       │                          # pipeline, retranscription, import — audio_v2 is an in-progress
│       │                          # rewrite of audio/ (see CLEANUP_PLAN.md)
│       ├── whisper_engine/        # whisper-rs (whisper.cpp bindings), GPU-accelerated
│       ├── parakeet_engine/       # ONNX Runtime (`ort` crate) STT alternative
│       ├── summary/               # summary_engine/, templates/, LLM client abstraction
│       ├── ollama/ anthropic/ groq/ openrouter/ openai/   # one module per LLM provider
│       ├── database/              # SQLite manager, repositories, models
│       ├── notifications/, analytics/ (PostHog), api/, tray.rs, onboarding.rs, config.rs, state.rs
├── backend/                        # ARCHIVED — Python/FastAPI + custom whisper.cpp server.
│                                    # Explicitly marked unsupported in backend/README.md.
│                                    # Not part of the current product; excluded from this analysis
│                                    # except as historical context for diarization attempts.
└── docs/                           # this folder, plus existing architecture.md, GPU docs, images
```

## Communication pattern

Frontend and Rust core communicate exclusively through **Tauri commands and events** — there is no HTTP API in the supported path:

- **Command** (TS → Rust): `invoke('start_recording', { mic_device_name, system_device_name, meeting_name })` → `#[tauri::command] async fn start_recording(...)`.
- **Event** (Rust → TS): Rust emits (`app.emit("transcript-update", payload)`), TS listens (`listen('transcript-update', handler)`).

All commands are registered in one place: `frontend/src-tauri/src/lib.rs`'s `tauri::generate_handler![...]` list — this is the single source of truth for the app's entire API surface today.

## Audio pipeline (the most complex subsystem)

Two parallel paths off the same captured audio:

```
Raw Audio (Mic + System)
   → Audio Pipeline Manager (audio/pipeline.rs)
        ├─ Recording Path (pre-mixed, RMS-based ducking, clip prevention) → RecordingSaver
        └─ Transcription Path (VAD-filtered speech only) → WhisperEngine / ParakeetEngine
```

Mic and system audio arrive asynchronously; a `VecDeque`-based ring buffer aligns 50ms windows before mixing. VAD filtering cuts ~70% of audio reaching Whisper. This is real-time, native-OS-API-dependent code (ScreenCaptureKit on macOS, WASAPI on Windows, ALSA/PulseAudio on Linux) — see `04-rust-vs-python-ts-boundary.md` for whether this must stay Rust in a rewrite.

## Transcription

Two selectable engines, both local/on-device:
- **Whisper** (`whisper_engine/`) via `whisper-rs`, with Metal/CoreML (macOS), CUDA/Vulkan/HIP (Windows/Linux) GPU acceleration.
- **Parakeet** (`parakeet_engine/`) via ONNX Runtime (`ort` crate).

## Summarization + LLM integration

`summary/` owns prompt templating (`templates/loader.rs`, `templates/defaults.rs`, two built-in templates — `daily_standup.json`, `standard_meeting.json` — embedded via `include_str!`) and a provider-agnostic LLM client. Five provider modules exist side by side, each with its own `commands.rs`: Ollama (local, recommended default), Anthropic Claude, Groq, OpenRouter, OpenAI (incl. custom OpenAI-compatible endpoints). None are mandatory — the app has no required cloud dependency.

## Storage

Local SQLite only, via `database/` (manager + repository pattern + models) — meetings, transcripts, summaries, metadata. No sync, no remote database, by design (privacy-first positioning).

## Editor / notes

BlockNote-based rich text editor (`components/BlockNoteEditor/`, `@blocknote/*`), with a `SummaryFormat` type supporting `'legacy' | 'markdown' | 'blocknote'` and markdown conversion helpers (`lib/blocknote-markdown.ts`). Older Remirror/TipTap editor dependencies are still present but superseded.

## Supporting systems

- **Notifications** (`notifications/settings.rs`): system notifications, time-based reminders. References "meeting_reminders" conceptually tied to calendar events, but **no calendar integration exists** — this is a UI/config stub only.
- **Analytics**: PostHog, with explicit sanitization of sensitive fields (meeting titles, file paths) before sending — `analytics/analytics.rs`.
- **Onboarding, tray icon, single-instance enforcement, auto-update** via `tauri-plugin-updater` against GitHub Releases.

## Known in-progress pain points (evidence for the rewrite to solve, not repeat)

- `audio_v2/` exists alongside `audio/` with a `compatibility.rs` shim — an incomplete in-flight modularization of what was previously a 1028-line monolithic `core.rs`.
- `frontend/src-tauri/CLEANUP_PLAN.md`, plus `lib_old_complex.rs`, `recording_saver_old.rs`, `core-old.rs`, `recording_commands.rs.backup` — multiple generations of refactor debris still in the tree.
- All business logic (audio, transcription, summarization, LLM orchestration, storage) lives in one Rust binary shipped inside the Tauri shell — there is no process/service boundary at all today, which is precisely the constraint the microservice rewrite is meant to remove.

## External dependencies (all optional, no forced cloud dependency)

| Dependency | Purpose | Required? |
|---|---|---|
| Ollama | Local LLM inference | No (default/recommended) |
| Anthropic / Groq / OpenRouter / OpenAI | Cloud LLM alternatives | No, user-configured |
| PostHog | Product analytics | No, can be disabled |
| GitHub Releases | Auto-update channel | No, app works without it |

This "local-first, cloud-optional" property is a hard constraint the new architecture must preserve — it's the product's core privacy claim, not an implementation detail.
