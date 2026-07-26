# Transcription Service — Detailed Design

Deep-dive on the one service in `05-proposed-architecture.md` that replaces `frontend/src-tauri/src/{whisper_engine,parakeet_engine,audio/transcription}/`. Baseline is the **current Rust interface** (read directly from the code, not guessed) — this doc keeps what already works well, and calls out specifically where the rewrite should do better rather than port bugs/inconsistencies as-is.

## What exists today (baseline contract)

The current implementation already has a reasonable shape worth preserving conceptually:

- A shared abstraction, `TranscriptionProvider` (`audio/transcription/provider.rs`): `transcribe(audio, language) -> TranscriptResult{text, confidence, is_partial}`, `is_model_loaded`, `get_current_model`, `provider_name` — with `WhisperProvider`/`ParakeetProvider` as concrete implementations.
- Per-engine model catalogs (`WHISPER_MODEL_CATALOG`, an equivalent Parakeet catalog) with discovery against a local `models_dir`, reporting `ModelStatus::{Available, Missing, Downloading{progress}, Error, Corrupted}`.
- A single serial transcription worker (`worker.rs`, `NUM_WORKERS = 1`) consuming `AudioChunk{data, sample_rate, timestamp, chunk_id, device_type}` off an mpsc channel, explicitly kept single-threaded **to preserve chronological transcript ordering** — this is a real constraint, not an oversight, and the rewrite must preserve it.
- 24 near-duplicate Tauri commands (12 Whisper + 12 Parakeet) that mirror each other 1:1 (`{engine}_init`, `_get_available_models`, `_load_model`, `_transcribe_audio`, `_download_model`, etc.) instead of going through the shared trait.

**What the rewrite should NOT repeat** (these are the concrete "do better" targets, not vague cleanup):
1. **Duplicated per-engine commands.** The trait already exists (`TranscriptionProvider`) but the command layer and the worker (`worker.rs` still pattern-matches `Whisper`/`Parakeet` variants directly) don't consistently go through it. The Python service should expose *one* engine-agnostic API surface, with Whisper/Parakeet as interchangeable backend implementations behind it — no per-engine command duplication.
2. **Two parallel retry systems, one of them dead.** The *active* serial worker has **no retry on failure** (a failed chunk is just logged and marked complete); real retry/backoff/timeout logic (`ProcessorConfig{max_retries: 3, retry_delay_ms: 1000}`, a `retry_queue`, `tokio::time::timeout(120s)`) exists only in the *legacy, largely-unused* `parallel_processor.rs`. The rewrite should have exactly one retry path, used by the one worker that actually runs.
3. **Two separate, hand-maintained model catalogs** (Whisper's and Parakeet's), each with its own download/progress/corruption-detection code that's ~90% identical. Should be one generic model-registry component parameterized by engine.
4. **`is_partial` is a heuristic, not a real signal** (`duration_seconds < 15.0` for Whisper; always `false` for Parakeet) — not true incremental/streaming transcription. Worth deciding explicitly whether the rewrite adds real streaming (see "Streaming" below) or keeps this as an honestly-labeled batch system.

## Data contracts

**Input** — from the Rust audio-core process (kept as-is per `04`), streamed over local IPC per segment:

```
AudioSegment {
  data: float32[]          # VAD-filtered speech, mono
  sample_rate: uint32      # native capture rate; service resamples to 16kHz if needed
  timestamp: float64       # seconds from recording start
  segment_id: uint64       # monotonic, used to preserve ordering downstream
  device_type: "microphone" | "system"
}
```

This is a direct carry-over of today's `AudioChunk` — it's a clean contract and there's no reason to change its shape, only its transport (local socket/gRPC instead of an in-process Rust channel).

**Output** — back to the storage/orchestration layer:

```
TranscriptSegment {
  text: string
  segment_id: uint64        # echoes input, guarantees ordering/joinability
  confidence: float | null  # null for engines that don't produce one (e.g. Parakeet today)
  is_partial: bool          # honestly derived — see Streaming section
  engine: "whisper" | "parakeet"
  model_name: string
  audio_start_time: float64
  audio_end_time: float64
  language: string | null   # detected or requested
}
```

Kept intentionally close to today's `TranscriptUpdate` shape (`worker.rs:27`) since the frontend/storage consumers already expect these fields — no reason to force a UI-side migration just because the backend language changed.

## Engine abstraction

Mirror `TranscriptionProvider` as a Python `Protocol` (or ABC), one implementation per engine, so the service's job-processing loop never branches on engine type:

```python
class TranscriptionEngine(Protocol):
    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult: ...
    def is_model_loaded(self) -> bool: ...
    def current_model(self) -> str | None: ...
    def load_model(self, name: str) -> None: ...
    def unload_model(self) -> None: ...
    @property
    def name(self) -> str: ...
```

- **`WhisperTranscriptionEngine`**: wraps `faster-whisper` (CTranslate2) on CUDA/x86, falls back to whisper.cpp Python bindings or an MLX-based Whisper implementation on Apple Silicon — the platform branch `04` §4 already recommends. Confidence comes from `faster-whisper`'s per-segment `avg_logprob`/`no_speech_prob`, which is a real signal (today's Rust `transcribe_audio_with_confidence` derives confidence similarly from whisper.cpp internals) — no regression here.
- **`ParakeetTranscriptionEngine`**: wraps `onnxruntime` + `onnx-asr` (`04` §5). Note from the baseline: Parakeet currently has **no confidence score and no language parameter** (English-only models) — the Python engine should keep `confidence: None` and `language: None` honestly rather than fabricate a value, matching today's honest gap.

Both implementations live behind the one `TranscriptionEngine` protocol so the model-registry, worker, and API layers below are engine-agnostic — fixing target #1 above by construction.

## Model management (one component, not two)

A single `ModelRegistry` service component, parameterized by engine, replacing the two duplicated catalogs:

- **Catalog as data, not code**: today's `WHISPER_MODEL_CATALOG` is a static Rust array; the rewrite should ship this as a small JSON/YAML manifest per engine (name, download URL, size, accuracy/speed tier, checksum) so adding a model variant is a data change, not a code change.
- **Status machine carried over as-is** — `Available | Missing | Downloading(progress) | Error | Corrupted` is a good state model; keep it.
- **Download**: async HTTP fetch with progress callback (today's `reqwest` + progress-tick pattern → Python `httpx`/`aiohttp` streaming download), checksum verification before marking `Available` (today's corruption detection is *post-hoc*, via `expected_min_size` — a checksum is a strict improvement over a size-floor heuristic).
- **Defaults preserved**: `large-v3-turbo` (Whisper), `parakeet-tdt-0.6b-v3-int8` (Parakeet) — no reason to change defaults the team already validated.

## API surface

Replace the 24 duplicated Tauri commands with one small, engine-parameterized surface (exposed over localhost HTTP or gRPC per `05`):

| Endpoint | Replaces | Notes |
|---|---|---|
| `POST /models/{engine}/load {name}` | `{whisper,parakeet}_load_model` | engine is a path param, not a duplicated command |
| `GET /models/{engine}` | `{whisper,parakeet}_get_available_models` | returns `ModelInfo[]` |
| `GET /models/{engine}/current` | `{whisper,parakeet}_get_current_model` | |
| `POST /models/{engine}/download {name}` | `{whisper,parakeet}_download_model` | progress via SSE/websocket, replacing today's `model-download-progress` Tauri event |
| `POST /models/{engine}/download/{name}/cancel` | `{whisper,parakeet}_cancel_download` | |
| `DELETE /models/{engine}/{name}` | `{whisper,parakeet}_delete_corrupted_model` | |
| (stream) `AudioSegment` in → `TranscriptSegment` out | `{whisper,parakeet}_transcribe_audio` | the hot path; a persistent stream/socket, not a request-per-chunk call, to avoid per-segment connection overhead |

One code path handles both engines; `engine` is data, not two copy-pasted command sets.

## Concurrency model

**Keep the single-worker-per-recording ordering guarantee** — this is a deliberate, correct design choice in the current code (`NUM_WORKERS = 1`, explicitly commented as preserving chronological order), not a limitation to "fix" by adding parallelism. What changes:

- Ordering is enforced by `segment_id` sequencing rather than relying purely on a single-threaded queue, so a future move to bounded concurrency (e.g., one worker per *device_type* — mic and system transcribed independently, then merged by timestamp) stays possible without breaking transcript order, if that's ever wanted.
- Multiple **concurrent recordings** (if the product ever supports more than one meeting at a time) should map to independent worker instances/queues, not a shared single worker — today's code is implicitly single-recording; the Python service should make this an explicit constraint in its design rather than an accidental one.

## Error handling and retry (fixing target #2)

One retry path, modeled on the *legacy* `ProcessorConfig` (which was already well-designed, just not wired into the live path):

- `max_retries = 3`, exponential backoff starting at `retry_delay_ms = 1000` (today's fixed 1s delay is fine to keep as a starting point, but exponential is a cheap improvement over fixed).
- Per-segment timeout (today's 120s is generous for a single VAD-filtered speech chunk — worth tightening to something like 30-45s once real-world Python-engine latency is benchmarked, per `06`'s per-phase verification step).
- On exhausted retries: emit the segment as an explicit `TranscriptSegment{text: "", error: "..."}` (or a typed error event) rather than silently dropping it — the current live worker's silent-log-and-continue behavior is exactly the gap to close; the "zero chunk loss" completion-verification the current worker already does (polling `chunks_queued` vs `chunks_completed`) is worth keeping as an end-of-recording integrity check regardless.
- Typed error taxonomy carried over from `TranscriptionError` (`ModelNotLoaded`, `AudioTooShort`, `EngineFailed`, `UnsupportedLanguage`) — these are good, specific error variants; keep them, translated to Python exceptions or a tagged result type.

## Streaming — an explicit decision point, not a default

Today's system is **honestly batch-based** dressed up with a heuristic `is_partial` flag. Two options for the rewrite, worth deciding deliberately rather than silently carrying the heuristic forward:

1. **Stay batch, drop the fake `is_partial` heuristic** — simplest, matches what both engines can actually do today (`faster-whisper` and `onnx-asr` are both segment/batch inference APIs, not token-streaming ones out of the box). Recommended default.
2. **Add real streaming** via a sliding-window re-transcription approach (common pattern: re-run on a growing buffer, emit interim results, replace with the final on segment close) — meaningfully more complex, and only worth it if a product requirement (e.g., live captions during the meeting, not just post-meeting transcript) actually needs sub-segment latency. Nothing in the current feature set (`02-feature-inventory.md`) requires this — flag as a "build only if a concrete UX need shows up," not a v1 target.

## Testing/verification plan

- **Golden-set WER comparison**: run the same fixed set of real recorded meetings (mixed mic+system, multiple speakers, at least one noisy sample) through today's Rust engines and the new Python engines; this is `06`'s Phase 2 verification step, restated here with the concrete metric (WER + latency, per platform: macOS Metal, NVIDIA CUDA, CPU-only fallback).
- **Ordering integrity test**: feed a synthetic sequence of `AudioSegment`s with known `segment_id` order through the worker under induced latency jitter (delay a random subset) and assert output `TranscriptSegment`s arrive/are stored in `segment_id` order regardless of processing-completion order.
- **Retry-path test**: inject a transient engine failure (mock the engine to fail N times then succeed) and assert the segment is retried per the configured policy and eventually succeeds or surfaces a typed error — not silently dropped.
- **Model-registry test**: corrupt a downloaded model file deliberately and assert checksum verification catches it (regression test against today's weaker size-floor heuristic).
