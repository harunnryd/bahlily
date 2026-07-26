# Transcription Service

## Data contracts

**Input** — streamed from the Rust audio core over local IPC, one message per VAD-filtered speech segment:

```
AudioSegment {
  data: float32[]          # mono speech audio
  sample_rate: uint32      # native capture rate; service resamples to 16kHz if needed
  timestamp: float64       # seconds from recording start
  segment_id: uint64       # monotonic, preserves ordering downstream
  device_type: "microphone" | "system"
}
```

**Output** — to the storage/orchestration layer:

```
TranscriptSegment {
  text: string
  segment_id: uint64        # echoes input, guarantees ordering/joinability
  confidence: float | null  # null for engines that don't produce one
  is_partial: bool
  engine: "whisper" | "parakeet"
  model_name: string
  audio_start_time: float64
  audio_end_time: float64
  language: string | null
}
```

## Engine abstraction

One interface, two interchangeable backends — the processing loop never branches on engine type:

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

- **Whisper**: `faster-whisper` (CTranslate2) on CUDA/x86, whisper.cpp/MLX bindings on Apple Silicon. Confidence derived from per-segment `avg_logprob`/`no_speech_prob`.
- **Parakeet**: `onnxruntime` + `onnx-asr`. English-focused models — no confidence score or language parameter; report those fields as `null` honestly rather than fabricate a value.

Default engine selection favors Parakeet where its language coverage matches the meeting, falling back to Whisper (`large-v3-turbo` or a distilled variant) otherwise — Parakeet's published real-time factor and word-error-rate are both meaningfully better than full Whisper on supported languages.

## Model management

One `ModelRegistry` component, parameterized by engine:

- Catalog as data (a JSON/YAML manifest per engine: name, download URL, size, accuracy/speed tier, checksum), not hardcoded — adding a model variant is a data change.
- Status machine: `Available | Missing | Downloading(progress) | Error | Corrupted`.
- Async streaming download with progress callback, checksum verification before marking a model `Available`.

## API surface

One small, engine-parameterized surface over localhost HTTP/gRPC:

| Endpoint | Purpose |
|---|---|
| `GET /models/{engine}` | list available/downloaded models |
| `GET /models/{engine}/current` | currently loaded model |
| `POST /models/{engine}/load {name}` | switch model |
| `POST /models/{engine}/download {name}` | download, progress via SSE/websocket |
| `POST /models/{engine}/download/{name}/cancel` | cancel an in-progress download |
| `DELETE /models/{engine}/{name}` | remove a model |
| (stream) `AudioSegment` in → `TranscriptSegment` out | the hot path — a persistent stream, not a request per chunk |

`engine` is a parameter, not a duplicated code path — Whisper and Parakeet share every endpoint.

## Concurrency model

Single worker per active recording, processing segments in order — this preserves chronological transcript ordering, which matters more than raw throughput for a live meeting transcript. Ordering is enforced by `segment_id` sequencing so a future move to bounded concurrency (e.g. one worker per device type, merged by timestamp) stays possible without breaking order. Multiple concurrent recordings map to independent worker instances, never a shared queue.

To capture batching speedups (`faster-whisper`/`onnx-asr` both benefit substantially from batched inference), the worker should micro-batch queued segments within a short window (e.g. 200–500ms) rather than transcribing one segment per call.

## Error handling and retry

- `max_retries = 3` with exponential backoff.
- Per-segment timeout, tuned from real measured latency rather than guessed.
- On exhausted retries: emit an explicit error segment (or typed error event) rather than silently dropping the chunk.
- Typed error taxonomy: `ModelNotLoaded`, `AudioTooShort`, `EngineFailed`, `UnsupportedLanguage`.
- End-of-recording integrity check: verify segments queued equals segments completed before finalizing a transcript.

## Streaming

Batch-based by default — both `faster-whisper` and `onnx-asr` are segment/batch inference APIs, not token-streaming ones out of the box, and nothing in the current feature set requires sub-segment latency. Real incremental streaming (sliding-window re-transcription with interim results) is worth adding only if a concrete UX need shows up (e.g. live captions during the meeting itself, not just a post-meeting transcript) — not a v1 target.

## Testing

- Golden-set WER + latency comparison across engines and platforms (macOS Metal, NVIDIA CUDA, CPU-only).
- Ordering integrity test: synthetic segments with known `segment_id` order, injected processing jitter, assert output preserves order regardless of completion order.
- Retry-path test: inject transient engine failures, assert retry-then-succeed or a surfaced typed error — never a silent drop.
- Model-registry test: corrupt a downloaded model file, assert checksum verification catches it.
