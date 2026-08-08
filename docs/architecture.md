# Architecture

Bahlily splits into a small Rust core for native OS integration and a set of independent Python services for everything ML, LLM, and storage related, coordinated by a thin desktop shell.

## Why Rust is scoped down to two things

Audio capture (mic and system audio at the same time) is the one subsystem with a hard technical requirement for Rust. Capturing both streams simultaneously means going through ScreenCaptureKit on macOS 13+, WASAPI loopback on Windows, or ALSA/PulseAudio on Linux. These are raw, callback-driven, ABI-sensitive OS APIs. Python's closest equivalents, `sounddevice`/PortAudio or `pyobjc-framework-ScreenCaptureKit`, are meaningfully less reliable here: ScreenCaptureKit access from Python still has open issues around dropped callbacks and stream errors on current macOS, and Node's PortAudio wrappers don't have a first-class loopback story at all. This is the kind of unsafe, FFI-heavy surface a scripting runtime shouldn't own directly.

Real-time audio mixing and VAD gating sit on the same hot path as capture: windowed alignment of two independently clocked streams, RMS-based ducking, clip prevention, voice-activity filtering before anything reaches transcription. None of this is algorithmically hard in Python, but it shares a process with the capture callbacks. A scripting-runtime pause, whether from the GIL or garbage collection, on that hot path would reintroduce the exact jitter this code exists to prevent. So it stays in Rust, in the same process as capture.

The desktop shell (window management, tray, single-instance enforcement, notifications, auto-update) is native OS-integration surface that Tauri's Rust plugins already handle well. No reason to reimplement it, and no reason for it to carry any ML or LLM logic.

Everything else moves to Python:

- **Whisper transcription.** `faster-whisper` (CTranslate2) is the current GPU-production standard, meaningfully faster than whisper.cpp on NVIDIA hardware at equal accuracy since both run the same underlying weights. whisper.cpp/MLX bindings remain available from Python for Apple Silicon.
- **Parakeet transcription.** ONNX Runtime's Python bindings (`onnxruntime`) are Microsoft's primary-supported target, and `onnx-asr` already supports NeMo Conformer/Parakeet/Canary architectures directly. No capability gap versus a Rust ONNX binding.
- **Speaker diarization.** `pyannote.audio` and NeMo are the dominant tools here and are Python-native. There isn't a serious Rust equivalent.
- **Summarization, prompt templating, multi-provider LLM orchestration.** This is a clear win for Python. LangChain and LangGraph provide unified LLM clients, structured output, and agentic orchestration off the shelf, and DeepEval gives automated evaluation of summary quality. There's no real-time constraint here either; LLM round-trips take seconds, not milliseconds.
- **Local storage.** SQLite via a Python ORM (or `better-sqlite3` if colocated with a TypeScript layer) is more than sufficient for single-user desktop CRUD at meeting-app scale. There's no real performance argument for keeping this in Rust.

## Service boundaries

```
Desktop Shell (Rust, thin)
  window/tray/notifications/single-instance/auto-updater
  spawns and supervises sidecars, proxies UI <-> services over localhost
        |
        +--- Audio Core (Rust): capture + mixing + VAD
        |       sends VAD-filtered speech segments onward
        |
        +--- Frontend (TypeScript/Next.js UI)
        |
        +--- Python Services (sidecars)
                transcription (Whisper/Parakeet/diarization, diarization is the opt-in `diarization` extra)
                summarization/orchestration (LangGraph, DeepEval)
                calendar/auto-start
                chat/RAG
                storage (SQLite, single writer)
                export
```

The audio core talks to the transcription service over local streaming IPC (a Unix domain socket or named pipe, or a lightweight localhost gRPC stream). This is the one latency-sensitive cross-process hop. The UI talks to the Python services over localhost HTTP, either one FastAPI process per service or a single BFF gateway in front of them. No external network access is required by default.

Storage has exactly one writer. Every other service reads through it rather than opening the SQLite file directly. Multi-writer contention is a design bug here, not an edge case to handle later.

The shell owns process lifecycle for every sidecar: spawn, health-check, restart on crash, clean shutdown, all via Tauri's sidecar mechanism. Sidecars ship as bundled executables, so end users never need to install Python or Node themselves.

## Deployment shape

Local-first by default. Every service above runs as a sidecar spawned by the desktop shell, with zero mandatory network access. An optional, user-run sync service can be added later for multi-device or small-team use. It should be self-hostable and opt-in by default. A vendor-hosted, paid tier may be offered later as an additional convenience option — never a replacement for the local-first path, which stays free and default. Treat it as an additive module on top of a working local pipeline rather than a redesign of it, and leave the question of its UI surface (desktop-only, a full web dashboard, or read-only share links) for whenever it's actually being built.

## Maintainability

Each Python service is small, independently runnable, and independently testable, built on a mainstream stack that most contributors already know. Someone can work on the chat/RAG service without touching audio capture at all, and the Rust surface area stays small enough that understanding the whole codebase isn't a prerequisite for contributing to most of it.
