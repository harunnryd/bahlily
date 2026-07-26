# Transcription Service

## Data contracts

Input comes streamed from the Rust audio core over local IPC, one message per VAD-filtered speech segment:

```
AudioSegment {
  data: float32[]          # mono speech audio
  sample_rate: uint32      # native capture rate; service resamples to 16kHz if needed
  timestamp: float64       # seconds from recording start
  segment_id: uint64       # monotonic, preserves ordering downstream
  device_type: "microphone" | "system"
}
```

Output goes to the storage/orchestration layer:

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

One interface, two interchangeable backends. The processing loop never branches on engine type:

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

Whisper runs on `faster-whisper` (CTranslate2) for CUDA/x86, and whisper.cpp/MLX bindings on Apple Silicon. Confidence comes from per-segment `avg_logprob`/`no_speech_prob`.

Parakeet runs on `onnxruntime` plus `onnx-asr`. Its models are English-focused and don't produce a confidence score or take a language parameter, so those fields should just report `null` honestly rather than fake a value.

Default engine selection favors Parakeet where its language coverage matches the meeting, falling back to Whisper (`large-v3-turbo` or a distilled variant) otherwise. Parakeet's published real-time factor and word-error-rate are both meaningfully better than full Whisper on the languages it supports.

## Model management

One `ModelRegistry` component, parameterized by engine. The catalog is data (a JSON/YAML manifest per engine listing name, download URL, size, accuracy/speed tier, checksum), not hardcoded, so adding a model variant is a data change rather than a code change. Status is tracked as `Available | Missing | Downloading(progress) | Error | Corrupted`. Downloads stream asynchronously with a progress callback, and a checksum is verified before a model is marked `Available`.

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
| (stream) `AudioSegment` in, `TranscriptSegment` out | the hot path, a persistent stream rather than a request per chunk |

`engine` is a parameter here, not a duplicated code path. Whisper and Parakeet share every endpoint.

## Concurrency model

One worker per active recording, processing segments in order. This preserves chronological transcript ordering, which matters more for a live meeting transcript than raw throughput. Ordering is enforced by `segment_id` sequencing, so a future move to bounded concurrency (say, one worker per device type, merged by timestamp) stays possible without breaking order. Multiple concurrent recordings map to independent worker instances, never a shared queue.

To capture batching speedups (both `faster-whisper` and `onnx-asr` benefit substantially from batched inference), the worker should micro-batch queued segments within a short window, something like 200 to 500ms, rather than transcribing one segment per call.

## Error handling and retry

Three retries with exponential backoff. A per-segment timeout tuned from real measured latency rather than guessed. On exhausted retries, emit an explicit error segment (or a typed error event) instead of silently dropping the chunk. The error taxonomy is `ModelNotLoaded`, `AudioTooShort`, `EngineFailed`, `UnsupportedLanguage`. At the end of a recording, verify that the number of segments queued matches the number completed before finalizing the transcript.

## Streaming

Batch-based by default. Both `faster-whisper` and `onnx-asr` are segment/batch inference APIs rather than token-streaming ones out of the box, and nothing in the current feature set needs sub-segment latency. Real incremental streaming, a sliding-window re-transcription that emits interim results, is worth adding only if a concrete need for it shows up, like live captions during the meeting itself rather than just a post-meeting transcript. Not a v1 target.

## Testing

Run a golden-set WER and latency comparison across engines and platforms (macOS Metal, NVIDIA CUDA, CPU-only). Test ordering integrity with synthetic segments at a known `segment_id` order, injecting processing jitter and confirming output still preserves order regardless of completion order. Test the retry path by injecting transient engine failures and confirming a retry-then-succeed or a surfaced typed error, never a silent drop. Test the model registry by corrupting a downloaded model file and confirming checksum verification catches it.
