# Proposed Architecture — Meetily Rewrite

Synthesizes `01`-`04`: what exists today, what "Pro" needs to become, and where the Rust/Python/TS line sits. This is a service-boundary design, not a code plan.

## Design constraints carried over from the current product

1. **Local-first, cloud-optional** (`01`): transcription and storage must work with zero network access; every LLM provider stays user-configured and swappable, never hardcoded.
2. **No bot-in-the-call model** (`03`): all four competitors get their calendar/auto-join/diarization accuracy advantage from a cloud bot joining the call as a participant. Copying that literally trades away the privacy positioning that differentiates Meetily. The recommended design instead auto-*starts Meetily's own local recorder* off calendar signals, accepting a real accuracy tradeoff on participant-name-derived speaker labels (documented in `03`'s diarization gotchas) in exchange for keeping audio on-device.
3. **Rust shrinks to two things** (`04`): OS-level audio capture+mixing+VAD (hard technical requirement, real-time, FFI-heavy) and a thin Tauri desktop shell (window/tray/notifications/updater). Everything ML-, LLM-, and storage-related moves to Python/TS.
4. **Permissive licensing** (`03`): avoid GPL (`caldav`) in the core; isolate LGPL (`pynput`) as a narrowly-scoped, process-boundary-separated optional component.

## Service boundaries

```
┌─────────────────────────────────────────────────────────────────────┐
│  Tauri Shell (Rust, thin)                                            │
│  window/tray/notifications/single-instance/auto-updater               │
│  spawns + supervises sidecars, proxies UI ↔ services over localhost   │
└───────────┬─────────────────────────────────────────────┬───────────┘
            │                                             │
   ┌────────▼─────────┐                          ┌────────▼──────────┐
   │ Audio Core (Rust) │  VAD-filtered speech →   │  Next.js UI (TS)   │
   │ capture+mixing+VAD │─────────────┐            │  existing frontend │
   └────────────────────┘             │            └────────┬───────────┘
                                      │                     │ HTTP/IPC
                        ┌─────────────▼─────────────────────▼───────────┐
                        │        Python Services (sidecars)              │
                        │                                                 │
                        │  ┌─────────────────┐  ┌───────────────────────┐│
                        │  │ Transcription    │  │ Summarization /       ││
                        │  │ Svc: faster-     │→ │ Orchestration Svc:    ││
                        │  │ whisper, onnx-   │  │ LangChain/LangGraph,  ││
                        │  │ asr (Parakeet),  │  │ multi-provider LLM,   ││
                        │  │ pyannote         │  │ templates, DeepEval   ││
                        │  │ (diarization)    │  │                       ││
                        │  └─────────────────┘  └──────────┬────────────┘│
                        │                                   │             │
                        │  ┌───────────────────────┐  ┌─────▼──────────┐ │
                        │  │ Calendar/Auto-start   │  │ Chat/RAG Svc    │ │
                        │  │ Svc: Google Cal /     │  │ (vector store + │ │
                        │  │ MS Graph + icalendar  │  │ LangChain RAG)  │ │
                        │  └───────────────────────┘  └─────────────────┘ │
                        │                                                 │
                        │  ┌───────────────────────┐  ┌─────────────────┐│
                        │  │ Storage Svc (SQLite)   │  │ Export Svc      ││
                        │  │ single writer, owns    │  │ python-docx,    ││
                        │  │ meetings/transcripts/  │  │ weasyprint/     ││
                        │  │ summaries/embeddings   │  │ reportlab, MD   ││
                        │  └───────────────────────┘  └─────────────────┘│
                        └─────────────────────────────────────────────────┘
```

**Rust — one process**: audio capture (cpal/ScreenCaptureKit/WASAPI/ALSA) + real-time mixing/ducking + inline VAD gating, bundled with the Tauri shell (window/tray/notifications/single-instance/updater). This is the only place OS-level/real-time guarantees are spent (`04` §1-2, §8). It streams VAD-filtered speech segments outward over local IPC/localhost and does nothing else — no LLM calls, no SQL, no HTTP to external providers.

**Python — the ML/LLM tier**, organized as separable services so restart/scaling boundaries can differ, but all in Python regardless of how many processes this becomes:
- **Transcription service**: Whisper (`faster-whisper` on CUDA/x86, whisper.cpp/MLX on Apple Silicon) + Parakeet (`onnxruntime`/`onnx-asr`) + diarization (`pyannote-audio` + `MahmoudAshraf97/whisper-diarization`), consuming speech segments from the Rust audio core (`04` §4-5, §9; `03` §1).
- **Summarization/orchestration service**: LangChain/LangGraph for prompt templating, structured-output (Pydantic-validated) summaries, multi-provider LLM client (Ollama/Anthropic/Groq/OpenRouter/OpenAI), DeepEval wired in for automated summary-quality evaluation (`04` §6; `03` §5).
- **Chat/RAG service**: chunk on diarization/utterance boundaries, embed (`nomic-embed-text` via Ollama or `sentence-transformers`), local vector store (`chromadb` or `sqlite-vec`), LangChain conversational-retrieval chain; optionally expose an MCP tool surface for transcript search, bound to localhost with auth — never repeat the archived FastAPI backend's unauthenticated-CORS posture (`03` §2).
- **Calendar/auto-start service**: Google Calendar API + Microsoft Graph API (official SDKs), `icalendar` for parsing; detects a Zoom/Meet/Teams link in an upcoming event and prompts (or auto-starts) Meetily's own local recorder — no bot joins the call (`03` §3).
- **Export service**: one canonical structured-summary schema (Pydantic), three renderers off it — Markdown (direct template), DOCX (`python-docx`), PDF (Jinja2 → HTML → `weasyprint`/`reportlab`) (`03` §4).

**Storage — single authoritative owner**: SQLite via `better-sqlite3` (if colocated with the TS layer) or SQLAlchemy/SQLModel (if colocated with the Python summarization/chat services). `04` explicitly warns against multi-writer contention — pick exactly one service as the writer; every other service reads through it or via a lightweight query API, never opens the SQLite file directly.

**TypeScript — UI**: the existing Next.js/React frontend is kept as-is architecturally (component structure, BlockNote editor) but now talks to Python services (transcription status, summaries, chat, export, calendar) instead of Tauri Rust commands for everything non-audio. Tauri `invoke`/`emit` remains the transport for audio-core control (start/stop recording, device selection) since that stays Rust; everything else goes over local HTTP/IPC to the Python sidecars.

## Communication

- **Rust audio core → Python transcription service**: local streaming IPC (Unix domain socket / named pipe, or a lightweight localhost gRPC stream) carrying VAD-filtered PCM segments — this is the one latency-sensitive cross-process hop, so avoid HTTP overhead here.
- **UI ↔ Python services**: localhost HTTP (FastAPI is a reasonable default per-service framework — reuses the team's existing FastAPI familiarity from the archived backend, this time scoped correctly) or a single BFF gateway in front of all Python services if the team prefers one network surface over several.
- **Tauri shell**: owns process lifecycle for every sidecar (spawn on app start, health-check, restart on crash, clean shutdown) using Tauri v2's sidecar mechanism — no separately-installed Python/Node runtime required for end users; sidecars are bundled executables (e.g., via PyInstaller/PyOxidizer for Python services).

## Deployment shape — two options, left open per the project owner's request

**Option A: Desktop-first, fully embedded sidecars** (closest to current positioning)
- Every service above runs as a local sidecar process spawned by the Tauri shell. No mandatory network access ever. Matches the current "entirely on local infrastructure" privacy claim exactly.
- Tradeoff: no multi-device sync, no team/shared-workspace story, every install carries the full Python ML stack (larger disk footprint than today's single Rust binary, though comparable to what a Pro/Enterprise competitor's local agent would need anyway).

**Option B: Local-first + optional self-hosted sync service**
- Same local sidecars as Option A for capture/transcription/summarization (keeps the audio and inference pipeline private by default), but an additional **optional, user-run** sync/server component (self-hostable — a small FastAPI-based service is a reasonable default given the rest of the stack, backed by whatever server-grade database the team prefers, e.g. Postgres) that a user can point multiple devices or a small team at for shared meeting libraries — opt-in, not bundled by default, and never a vendor-hosted cloud (preserves "self-hosted deployment" as a real open-source feature rather than an Enterprise-only sales line per the current README). **Note**: the specific choice of FastAPI/Postgres here is an architectural assumption for illustration, not a conclusion from `03`/`04`'s research — neither document evaluates sync-service technology, since Option B is explicitly out of scope until Option A ships (see `06-migration-roadmap.md`). Revisit this choice when Option B is actually scoped.
- Tradeoff: real architectural surface area (auth, multi-writer conflict resolution, a second deployable artifact to maintain) for a capability most solo/privacy-focused users won't use.

**Recommendation**: build Option A first — it's a strict subset of Option B's local pipeline and delivers the entire Pro feature set (diarization, chat, calendar, export, templates) without touching sync/multi-user complexity. Treat Option B's sync service as a *later, additive* module with its own service boundary (a 10th box in the diagram above, not a redesign of it) once the core local pipeline is stable — this keeps the migration roadmap (`06`) linear instead of forcing a sync-architecture decision before there's a working local product to sync.

**Open question deliberately deferred**: if/when Option B is built, the *UI surface* for the sync service still needs a decision — does it stay desktop-only (the existing Next.js/Tauri app is simply the client for multiple synced devices, no browser access), gain a full web dashboard (browser-based access, which pulls in account-based auth instead of purely local/device auth — closer to how Otter/Fireflies operate), or land in between (desktop stays the only full-featured client, but the sync service can mint read-only public share links for individual meeting summaries, similar to competitors' "share this recap" feature)? This is a product-scope decision, not an architecture one, and it only needs answering once Option B is actually being scoped — it does not block anything in `06-migration-roadmap.md`, which stays entirely within Option A.

## Why this is easier to maintain by outside contributors

Compared to today's one-giant-Rust-binary structure (`01`'s "known pain points"), each Python service is a small, independently runnable, independently testable unit with a narrow responsibility and a mainstream tech stack (FastAPI + LangChain are broadly known; whisper-rs + Tauri internals are a much smaller expertise pool). A contributor can work on the chat/RAG service without touching audio capture at all, and the Rust surface area is small enough that "learn the whole codebase before contributing" stops being a prerequisite.
