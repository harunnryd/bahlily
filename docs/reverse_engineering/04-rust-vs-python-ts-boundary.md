# Rust vs. Python/TypeScript: Where the Line Should Be

> Scope: this document evaluates, subsystem by subsystem, whether Meetily's current all-Rust implementation (living inside the Tauri desktop shell at `frontend/src-tauri/src/`) has a **hard technical requirement** to stay in Rust, or whether it can move to Python/TypeScript in a microservice rewrite without losing capability, performance, or reliability. The guiding principle, as stated by the project owner: *"Rust ini powerful untuk handle yang gak bisa dihandle Python/TS"* — Rust earns its keep only where Python/TS genuinely cannot do the job (no mature binding, hard real-time constraints, or raw OS/FFI access that scripting-language bindings don't cleanly expose). Everywhere else, the LangChain/LangGraph/DeepEval-centric Python ecosystem and the productivity of TypeScript should win.

Findings below are based on reading the current implementation under `frontend/src-tauri/src/{audio,audio_v2,whisper_engine,parakeet_engine,summary,database}/` and its `Cargo.toml`, plus current-state research on the Python/Node library ecosystem.

---

## 1. OS-level audio capture (mic + system, simultaneous)

**Verdict: Rust required (hard boundary)**

The current implementation captures microphone and system audio *simultaneously* through `cpal` on top of platform APIs: ScreenCaptureKit on macOS (via the `cidre` crate's Objective-C bindings, `frontend/src-tauri/src/audio/capture/core_audio.rs` and `devices/platform/macos.rs`), WASAPI loopback on Windows, and ALSA/PulseAudio on Linux (`devices/platform/{windows,macos,linux}.rs`). This is the single hardest subsystem to replicate outside Rust. Python's closest equivalents are `sounddevice`/PortAudio (WASAPI loopback flags exist on Windows, but macOS system-audio capture requires `pyobjc-framework-ScreenCaptureKit`, which as of 2026 still has open bugs around dropped callbacks and `SCStreamErrorDomain` failures on macOS 15) and on Node, `naudiodon`/`naudiodon-loopback`, which are thin, less-maintained PortAudio wrappers with no first-class ScreenCaptureKit story at all. None of these give a *simultaneous, jitter-controlled, cross-platform* mic+system capture path with the maturity of Meetily's current cpal+ScreenCaptureKit/WASAPI/ALSA code, and the Objective-C/COM-level interop this requires (raw `AVFoundation`/`SCStream` delegate callbacks, WASAPI `IAudioClient` COM objects) is exactly the kind of unsafe, ABI-sensitive surface that Python/Node bindings wrap loosely and inconsistently, not the kind a scripting runtime should own directly.

**Recommendation**: keep OS audio capture in Rust, exposed as a small local IPC/gRPC service (or Tauri sidecar) that streams raw PCM chunks outward; do not attempt a Python/Node rewrite of this layer.

---

## 2. Real-time audio mixing (ring buffer, RMS ducking, clip prevention)

**Verdict: Rust required (soft-hard boundary — could move, but wouldn't be worth it)**

`audio/pipeline.rs`'s `AudioMixerRingBuffer` and the newer `audio_v2/{mixer.rs,limiter.rs,normalizer.rs,resampler.rs,sync.rs}` perform windowed alignment of two independently-clocked streams (mic and system audio, arriving at different rates and with jitter — the code explicitly tunes buffer sizes around Core Audio jitter), RMS-based ducking, resampling (`rubato`), and a loudness limiter. This is tight numerical DSP directly downstream of the raw capture callbacks in section 1. Nothing here is algorithmically impossible in Python/NumPy or Node — the math is straightforward — but it sits on the *same hot path* as the capture callbacks, meaning GIL pauses (Python) or GC pauses/event-loop jitter (Node) would reintroduce exactly the jitter problems the current code works hard to compensate for. Since the upstream capture layer is staying in Rust anyway (section 1), keeping the mixer in the same process/language avoids an extra IPC hop on the hottest part of the pipeline and avoids a second, redundant clock-sync problem at the process boundary.

**Recommendation**: keep the mixer/ring-buffer/ducking logic bundled with the capture service in Rust as one cohesive "audio capture + mixing" sidecar; do not split it out to a scripting-language process.

---

## 3. Voice Activity Detection (VAD) filtering

**Verdict: hybrid — Rust for the inline gate, Python viable for anything downstream**

Meetily currently uses `silero-rs` (`audio/vad.rs`, `ContinuousVadProcessor`) running inline on the same thread/pipeline as capture, gating which audio reaches the transcription path. Silero VAD itself is model-agnostic to language: the reference model is a small (~1-2MB) ONNX/JIT model, and the official `silero-vad` Python package processes 32ms chunks in under 1ms on CPU — plenty fast for real-time use in isolation. The reason this stays coupled to Rust in Meetily specifically is that it runs *inline* in the same low-latency audio thread as capture and mixing (section 2), consuming the ring-buffer output directly; moving only the VAD step to a separate Python process would add an IPC hop per 30ms chunk for no real benefit, since the mixing stage it depends on isn't moving either.

**Recommendation**: keep VAD gating inside the same Rust audio pipeline process as capture/mixing (call it via `ort` or a small Rust Silero binding, as today); if a future rewrite ever separates the mixing stage, VAD could ride along with the transcription service instead, in Python, using `silero-vad`.

---

## 4. Whisper transcription (whisper-rs / whisper.cpp, GPU-accelerated)

**Verdict: move to Python/TS**

The current code uses `whisper-rs` bindings to whisper.cpp with per-platform GPU features (Metal/CoreML on macOS, CUDA/Vulkan/HIP on Windows/Linux — see the `Cargo.toml` feature flags and `whisper_engine/acceleration.rs`). This was a reasonable choice when everything lived in one Rust binary, but it is not a hard requirement. `faster-whisper` (Python, CTranslate2-backed) is the current GPU-production standard — roughly 4x faster than whisper.cpp on NVIDIA GPUs at INT8 quantization, per 2026 comparisons, with identical accuracy since both run the same Whisper weights. On Apple Silicon, whisper.cpp with Metal/CoreML remains the faster CPU/edge option, but Python has first-class access to that too, either by shelling out to whisper.cpp/whisper-cpp-python bindings or via MLX-based Whisper implementations — there is no scenario where transcription needs Rust's memory model or FFI access; it's a batch/streaming inference workload that Python's ML ecosystem is built for.

**Recommendation**: move Whisper transcription to a Python service (`faster-whisper` on CUDA/x86, whisper.cpp/MLX bindings on Apple Silicon), fed by the Rust audio pipeline's VAD-filtered speech segments over local IPC.

---

## 5. Parakeet transcription (ONNX Runtime)

**Verdict: move to Python/TS**

Meetily currently uses the `ort` crate (ONNX Runtime Rust bindings) for Parakeet inference (`parakeet_engine/`). ONNX Runtime's Python bindings (`onnxruntime`) are Microsoft's primary-supported binding target, at least as mature as the Rust `ort` crate, and the broader Python ASR ecosystem has already converged on Parakeet-over-ONNX: the `onnx-asr` package explicitly supports NVIDIA NeMo Conformer/FastConformer/Parakeet/Canary models with CTC/RNN-T/TDT decoders, and NVIDIA's own Parakeet-TDT ONNX exports are published and consumed directly from Python. There is no capability, performance, or GPU execution-provider gap between the Rust and Python ONNX Runtime bindings for this workload — both call into the same native ONNX Runtime library.

**Recommendation**: move Parakeet transcription to the same Python transcription service as Whisper (section 4), using `onnxruntime` + `onnx-asr` or an equivalent NeMo-based loader.

---

## 6. Summarization + prompt templating + multi-provider LLM client

**Verdict: move to Python/TS (clear win)**

This is the most clear-cut case in the entire audit. The current `summary/` module (`llm_client.rs`, `processor.rs`, `templates/`, provider modules for `ollama`, `anthropic`, `groq`, `openrouter`, `openai`) reimplements, in Rust via `reqwest`, functionality that LangChain and LangGraph provide off the shelf in Python: unified multi-provider LLM clients, prompt template management, structured output parsing, retries/streaming, and agentic orchestration graphs. Moving this to Python unlocks the explicit goals stated for this rewrite — LangChain/LangGraph for prompt/graph orchestration and DeepEval for automated evaluation of summarization quality — none of which have equivalent Rust tooling, and reimplementing them in Rust would mean permanently forking effort away from the fast-moving Python LLM-tooling ecosystem. There is no real-time constraint here (LLM round-trips are seconds, not milliseconds) and no OS-level access requirement at all — this is pure HTTP client + templating + orchestration logic.

**Recommendation**: move summarization, prompt templating, and multi-provider LLM orchestration to a Python service built on LangChain/LangGraph, with DeepEval wired in for evaluation; TypeScript is a secondary option only if the team wants this service co-located with a Node-based orchestration layer, but Python is the stronger default given the target ecosystem.

---

## 7. Local SQLite storage (meetings/transcripts/summaries)

**Verdict: move to Python/TS**

The current `database/` module uses `sqlx` (async, compile-time-checked SQL) as a repository layer over SQLite. For a single-user local desktop app, this is not a workload with any real-time or concurrency pressure that would favor Rust: Python's built-in `sqlite3` (or SQLAlchemy/SQLModel for a repository-pattern ORM) and Node's `better-sqlite3` (synchronous, extremely fast, actively maintained, no async overhead to fight) are both mature, battle-tested, and more than fast enough for meeting/transcript/summary CRUD at desktop-app scale (thousands, not millions, of rows). `sqlx`'s compile-time query checking is a nice Rust-specific ergonomic, but it is not a capability gap — Python/TS equivalents (typed ORMs, migration tools like Alembic or Prisma/Drizzle) cover the same ground. There is no plausible argument that Rust's SQLite bindings meaningfully outperform or outreliability `better-sqlite3` or Python's `sqlite3` for this access pattern.

**Recommendation**: move meeting/transcript/summary persistence to whichever service owns that domain data most naturally — likely the same Python service that owns summarization (section 6) and/or a TypeScript backend-for-frontend layer, using `better-sqlite3` (Node) or SQLAlchemy/SQLModel (Python) as the repository layer. Pick one authoritative owner of the SQLite file to avoid multi-writer contention; do not keep this in Rust "by default."

---

## 8. Desktop shell (window management, tray, single-instance, notifications, auto-updater)

**Verdict: hybrid — keep Tauri, but as a thin shell only**

Three options were considered:

- **Tauri (Rust shell), kept thin**: window management, system tray, single-instance enforcement, native notifications, and auto-update (`tauri-plugin-{updater,notification,single-instance,store}`) are precisely the category of OS-integration surface Tauri's Rust core is built for, and these plugins are mature, first-party, and low-maintenance. None of this requires business logic to live in the same process.
- **Electron (Node shell)**: would let the shell and business-logic sidecars share one language, but trades away Tauri's binary size, memory footprint, and native-webview model for a bundled Chromium + Node runtime — a real regression for a "privacy-first, local, lightweight" positioning, with no functional gain since the shell's job (windowing/tray/notifications/updater) is not where LangChain/DeepEval matter.
- **Fully separate Python/Node services + thin native launcher (no Tauri)**: loses the polished native window chrome, OS notification integration, and auto-updater Tauri already provides for free, and would mean re-solving single-instance enforcement and tray integration from scratch per platform.

Tauri's actual advantage here is that it already supports the target architecture directly: a Rust shell that does only window/tray/IPC/updater duties, launching Python and/or Node **sidecar processes** for everything else (this is a well-established, actively-used 2026 pattern — Tauri v2's sidecar mechanism bundles a Python/FastAPI or Node executable that the Rust core spawns and proxies to over localhost HTTP or stdio, with no end-user Python/Node install required). This is the best-of-both-worlds option: Rust owns only what genuinely needs OS-level integration (windowing, tray, notifications, single-instance, updater, plus the audio capture/mixing pipeline from sections 1–2), and every other subsystem runs as a Python or TypeScript sidecar the shell manages as a process, not as compiled-in logic.

**Recommendation**: keep Tauri, but shrink its Rust surface to shell duties + audio capture/mixing/VAD; run transcription (Whisper/Parakeet), summarization/LLM orchestration, and storage as Python and/or TypeScript sidecar processes launched and supervised by the Tauri core.

---

## 9. Speaker diarization (not yet in the codebase, but relevant to a rewrite)

**Verdict: move to Python/TS (Python-native by default)**

No diarization module currently exists in `frontend/src-tauri/src/`, but it's a natural next feature and worth deciding up front. The dominant diarization tooling — `pyannote.audio`, NeMo's diarization pipelines, and most speaker-embedding models — is Python-native with no meaningful Rust ecosystem equivalent. This is squarely an ML-inference workload, not an OS-integration or hard-real-time one (diarization typically runs on completed or near-real-time speech segments, not on the raw capture hot path), so it belongs with the other ML-heavy subsystems.

**Recommendation**: if/when diarization is added, place it in the same Python transcription service as Whisper/Parakeet (section 4/5), consuming VAD-filtered speech segments over the same IPC path.

---

## Summary Table

| Subsystem | Verdict | Target language | Why (one line) |
|---|---|---|---|
| OS-level audio capture (mic + system) | Rust required | Rust | No mature Python/Node binding does simultaneous ScreenCaptureKit/WASAPI/ALSA capture at this reliability; needs raw Obj-C/COM FFI. |
| Real-time audio mixing (ring buffer, ducking) | Rust required | Rust | Same hot path as capture; GIL/GC pauses would reintroduce the jitter the code already fights. |
| VAD filtering | Hybrid | Rust (inline) | Silero itself is fast enough in Python, but it's coupled to the Rust mixing pipeline it gates — no benefit to splitting it out alone. |
| Whisper transcription | Move | Python | `faster-whisper` matches/beats whisper-rs on GPU; whisper.cpp/MLX still available from Python on Apple Silicon. |
| Parakeet transcription | Move | Python | `onnxruntime` Python bindings are Microsoft's primary target, equally capable; `onnx-asr` already supports Parakeet directly. |
| Summarization + LLM orchestration | Move | Python | LangChain/LangGraph/DeepEval are Python-first; no Rust equivalent tooling exists; pure HTTP + templating logic, no real-time constraint. |
| SQLite storage | Move | Python or TS | Single-user desktop CRUD; `better-sqlite3`/`sqlite3`/SQLAlchemy are equally mature; no Rust performance edge at this scale. |
| Desktop shell (window/tray/notify/updater) | Hybrid | Rust (thin) | Tauri's native plugins are the best tool for OS chrome; keep the shell, strip out business logic into sidecars. |
| Speaker diarization (future) | Move | Python | `pyannote.audio`/NeMo are the dominant tools and are Python-native; belongs with the other ML-inference services. |

---

## Recommended Split

For a microservice architecture design, the concrete language assignment is:

**Rust — one process, kept intentionally small**: OS-level audio capture (mic + system, via cpal/ScreenCaptureKit/WASAPI/ALSA), the real-time mixing/ducking/clip-prevention pipeline, and inline VAD gating, all exposed as a local streaming service (e.g., a Tauri sidecar or in-process module emitting VAD-filtered speech segments over a local socket/IPC channel). This same Rust codebase also hosts the Tauri desktop shell itself — window management, system tray, single-instance enforcement, native notifications, and auto-update — since these are OS-integration duties Tauri's plugins already solve well. Nothing that touches LLMs, ASR models, or SQL persistence should live in this process going forward.

**Python — the ML/LLM service tier**: a transcription service combining Whisper (`faster-whisper` for GPU/x86, whisper.cpp or MLX bindings for Apple Silicon) and Parakeet (`onnxruntime` + `onnx-asr`), consuming speech segments streamed from the Rust audio process; a summarization/orchestration service built on LangChain/LangGraph handling prompt templating and multi-provider LLM calls (Ollama, Anthropic, Groq, OpenRouter, OpenAI), with DeepEval integrated for automated quality evaluation of summaries; and, when added, speaker diarization (`pyannote.audio`/NeMo) alongside the transcription service. These can be one Python process or split into two (transcription vs. LLM/summarization) depending on desired independent scaling/restart boundaries — either is defensible, but both belong in Python regardless of that split.

**TypeScript — the UI and orchestration-facing tier**: the existing Next.js/React frontend stays TypeScript, and it's the natural home for the SQLite-backed persistence layer (meetings/transcripts/summaries) via `better-sqlite3` if the team wants that data owned close to the UI, or alternatively that persistence layer can live in the Python service if co-locating it with summarization is preferred — pick one owner, not both, to avoid multi-writer contention on the SQLite file. The Tauri Rust shell coordinates all of this: it launches and supervises the Python sidecar(s) as child processes, relays events between the audio pipeline, the ML services, and the UI, and remains the only place Rust's OS-level and real-time guarantees are actually being spent.

The net effect: Rust shrinks from "the entire application" to "the audio capture/mixing engine plus the native shell chrome" — the two places in this system where Python/TS genuinely cannot do the job — while everything LLM-, ASR-, and storage-related moves to the Python/TypeScript ecosystem the team wants to build in.

---

## Sources

- [Failed to Capture System Audio with ScreenCaptureKit on macOS 15 (SCStreamErrorDomain -3805 or No Callbacks) – pyobjc#647](https://github.com/ronaldoussoren/pyobjc/issues/647) — supports §1's claim that `pyobjc-framework-ScreenCaptureKit` still has open reliability bugs on current macOS.
- [ScreenCaptureKit System Audio Capture Crashes with EXC_BAD_ACCESS – Apple Developer Forums](https://developer.apple.com/forums/thread/775307) — further evidence of ScreenCaptureKit-via-Python instability under sustained capture, reinforcing §1's "keep audio capture in Rust" verdict.
- [faster-whisper vs whisper.cpp speed comparison (2026) – CodersEra](https://codersera.com/blog/faster-whisper-vs-whisper-cpp-speech-to-text-2026/) and [whisper.cpp vs faster-whisper: Speed and Accuracy Compared – BuilderAI](https://builderai.tools/blog/whisper-cpp-vs-faster-whisper-speed-and-accuracy) — basis for §4's GPU performance claim (faster-whisper's CTranslate2 backend outperforming whisper.cpp's CUDA path, e.g. ~12x vs ~8x real-time for large-v3 on an RTX 4070) and the Apple Silicon caveat (whisper.cpp/Metal/CoreML remains the stronger choice there).
- [onnx-asr – PyPI](https://pypi.org/project/onnx-asr/) and [istupakov/onnx-asr – GitHub](https://github.com/istupakov/onnx-asr) — confirms §5's claim that `onnx-asr` directly supports NVIDIA NeMo Conformer/FastConformer/Parakeet/Canary architectures with CTC/RNN-T/TDT decoders from Python.
- [better-sqlite3 – npm](https://www.npmjs.com/package/better-sqlite3) and [Understanding better-sqlite3: The Fastest SQLite Library for Node.js – DEV Community](https://dev.to/lovestaco/understanding-better-sqlite3-the-fastest-sqlite-library-for-nodejs-4n8) — supports §7's claim that a synchronous Node SQLite driver is fast enough (and often preferred over async wrappers) for single-user desktop CRUD, with no plausible Rust performance edge at this scale.

These sources back the specific technical claims cited above; the broader architectural reasoning (why each subsystem is coupled or decoupled from the audio hot path) is derived from reading the current implementation under `frontend/src-tauri/src/`, not from external sources. Given how fast the ML/ASR tooling landscape moves, treat the speed/maturity comparisons here as directionally correct as of mid-2026, not permanent — re-benchmark before committing (see `06-migration-roadmap.md`'s per-phase verification steps).
