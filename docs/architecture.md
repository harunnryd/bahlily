# Architecture

Bahlily splits into a small Rust core (native OS integration only) and a set of independent Python services (everything ML/LLM/storage), coordinated by a thin desktop shell.

## Why Rust is scoped down to two things

**Audio capture (mic + system, simultaneous)** is the one subsystem with a hard technical requirement for Rust. Capturing microphone and system audio at the same time means going through ScreenCaptureKit (macOS 13+), WASAPI loopback (Windows), or ALSA/PulseAudio (Linux) — raw, callback-driven, ABI-sensitive OS APIs. Python's closest equivalents (`sounddevice`/PortAudio, `pyobjc-framework-ScreenCaptureKit`) are meaningfully less reliable for this: ScreenCaptureKit access from Python still has open issues around dropped callbacks and stream errors on current macOS, and Node's PortAudio wrappers have no first-class loopback story at all. This is exactly the kind of unsafe, FFI-heavy surface a scripting runtime shouldn't own directly.

**Real-time audio mixing and VAD gating** sit on the same hot path as capture — windowed alignment of two independently-clocked streams, RMS-based ducking, clip prevention, voice-activity filtering before anything reaches transcription. Nothing here is algorithmically hard in Python, but it shares a process with the capture callbacks; a scripting-runtime pause (GIL, GC) on that hot path would reintroduce the exact jitter this code exists to prevent. Kept in Rust, in the same process as capture.

**The desktop shell** (window management, tray, single-instance enforcement, notifications, auto-update) is native OS-integration surface Tauri's Rust plugins already solve well — no reason to reimplement it, and no reason for it to carry any ML/LLM logic.

Everything else moves to Python:

- **Whisper transcription** — `faster-whisper` (CTranslate2) is the current GPU-production standard, meaningfully faster than whisper.cpp on NVIDIA hardware at equal accuracy (same underlying weights); whisper.cpp/MLX bindings remain available from Python for Apple Silicon.
- **Parakeet transcription** — ONNX Runtime's Python bindings (`onnxruntime`) are Microsoft's primary-supported target, and `onnx-asr` already supports NeMo Conformer/Parakeet/Canary architectures directly — no capability gap versus a Rust ONNX binding.
- **Speaker diarization** — `pyannote.audio`/NeMo are the dominant tools and are Python-native; there's no serious Rust equivalent.
- **Summarization, prompt templating, multi-provider LLM orchestration** — a clear win for Python: LangChain/LangGraph provide unified LLM clients, structured output, and agentic orchestration off the shelf, and DeepEval gives automated evaluation of summary quality. No real-time constraint here — LLM round-trips are seconds, not milliseconds.
- **Local storage** — SQLite via a Python ORM (or `better-sqlite3` if colocated with a TypeScript layer) is more than sufficient for single-user desktop CRUD at meeting-app scale; there's no plausible performance argument for keeping this in Rust.

## Service boundaries

```
┌─────────────────────────────────────────────────────────────────────┐
│  Desktop Shell (Rust, thin)                                          │
│  window/tray/notifications/single-instance/auto-updater               │
│  spawns + supervises sidecars, proxies UI ↔ services over localhost   │
└───────────┬─────────────────────────────────────────────┬───────────┘
            │                                             │
   ┌────────▼─────────┐                          ┌────────▼──────────┐
   │ Audio Core (Rust) │  VAD-filtered speech →   │  Frontend (TS)     │
   │ capture+mixing+VAD │─────────────┐            │  Next.js UI        │
   └────────────────────┘             │            └────────┬───────────┘
                                      │                     │ HTTP/IPC
                        ┌─────────────▼─────────────────────▼───────────┐
                        │        Python Services (sidecars)              │
                        │                                                 │
                        │  transcription   summarization/orchestration   │
                        │  (Whisper/Parakeet/diarization) → LangGraph,   │
                        │                                   DeepEval     │
                        │                                                 │
                        │  calendar/auto-start        chat/RAG           │
                        │                                                 │
                        │  storage (SQLite, single writer)   export      │
                        └─────────────────────────────────────────────────┘
```

- **Audio core → transcription service**: local streaming IPC (Unix domain socket / named pipe, or a lightweight localhost gRPC stream) carrying VAD-filtered PCM segments — the one latency-sensitive cross-process hop.
- **UI ↔ Python services**: localhost HTTP (FastAPI per service, or a single BFF gateway) — no external network access required by default.
- **Storage**: exactly one service is the SQLite writer; every other service reads through it, never opens the file directly. Multi-writer contention is a design bug, not an edge case to handle.
- **Shell**: owns process lifecycle for every sidecar (spawn, health-check, restart on crash, clean shutdown) via Tauri's sidecar mechanism — bundled executables, no separately-installed Python/Node runtime required by end users.

## Deployment shape

Local-first by default: every service above runs as a sidecar spawned by the desktop shell, with zero mandatory network access. An optional, user-run sync service (self-hostable, opt-in, never a vendor-hosted cloud) can be added later for multi-device or small-team use — it's an additive module on top of a working local pipeline, not a redesign of it, and its own UI surface (desktop-only vs. a web dashboard vs. read-only share links) is a decision to make once it's actually being built, not before.

## Maintainability

Each Python service is small, independently runnable, and independently testable with a mainstream stack (FastAPI + LangChain are broadly known). A contributor can work on the chat/RAG service without touching audio capture at all, and the Rust surface area is small enough that understanding the whole codebase isn't a prerequisite to contributing to most of it.
