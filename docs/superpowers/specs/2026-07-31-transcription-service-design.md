# Transcription Service Design

Phase 2 of the bahlily roadmap. Receives VAD-filtered audio segments from the
Rust audio core over gRPC, transcribes them via Whisper or Parakeet, and
broadcasts `TranscriptSegment` messages over a second gRPC stream for downstream
consumers (storage in Phase 3, orchestration, frontend).

## Decisions made during design

- **Platform:** cross-platform from day one (macOS Apple Silicon, macOS Intel,
  Linux CUDA/CPU, Windows).
- **Engines:** both Whisper and Parakeet in v1; they share a common Protocol.
- **Model registry:** full registry with async download, SHA-256 verification,
  and status tracking in v1.
- **IPC in:** gRPC (audio-core already implements `AudioService.StreamAudio`).
- **IPC out:** gRPC broadcast stream (mirrors audio-core pattern).
- **Download progress:** SSE via `sse-starlette`.
- **Concurrency:** async-native — single process, asyncio event loop,
  `ThreadPoolExecutor` for CPU-bound inference.
- **Retry:** `stamina` (opinionated tenacity wrapper with structlog integration).

## Architecture

One Python process, five components sharing an asyncio event loop:

```
┌─────────────────────────────────────────────────────────────────┐
│                    bahlily-transcription                        │
│                                                                 │
│  ┌──────────────┐    ┌─────────────────┐    ┌───────────────┐  │
│  │ gRPC Client  │───▶│  Session Worker  │───▶│  gRPC Server  │  │
│  │ (audio-core) │    │  (per recording) │    │(TranscriptSeg)│  │
│  └──────────────┘    └────────┬────────┘    └───────────────┘  │
│                               │ ThreadPoolExecutor              │
│                      ┌────────▼────────┐                       │
│                      │  Engine Layer   │                       │
│                      │ Whisper/Parakeet│                       │
│                      └─────────────────┘                       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              FastAPI HTTP (port 8002)                    │  │
│  │   /models/{engine}  /sessions  /health  SSE download    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Model Registry                              │  │
│  │   YAML manifest · async download · SHA-256 verify       │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Ports:**
- `50052` — gRPC server (TranscriptSegment stream out), configurable via
  `TRANSCRIPTION_GRPC_PORT`
- `8002` — FastAPI HTTP (management + SSE)
- gRPC client connects to audio-core at `localhost:50051`, configurable via
  `AUDIO_CORE_GRPC_ADDR`

**File layout:**

```
services/transcription/
├── proto/transcription/v1/transcription.proto
├── src/bahlily_transcription/
│   ├── pb/                    # generated gRPC bindings (both protos)
│   ├── models.py              # Pydantic data contracts
│   ├── engine.py              # TranscriptionEngine Protocol
│   ├── whisper_engine.py      # faster-whisper + mlx-whisper backend
│   ├── parakeet_engine.py     # onnxruntime + onnx-asr backend
│   ├── registry.py            # ModelRegistry
│   ├── worker.py              # SessionWorker + micro-batching
│   ├── grpc_client.py         # AudioCoreClient (gRPC subscriber)
│   ├── grpc_server.py         # TranscriptionGrpcService + BroadcastChannel
│   ├── app.py                 # FastAPI application
│   └── __init__.py            # main() entrypoint
└── tests/
```

## Proto

New proto at `services/transcription/proto/transcription/v1/transcription.proto`.
Python bindings generated from both this proto and
`shell/audio-core/proto/audio_core/v1/audio.proto` into `src/bahlily_transcription/pb/`
via `grpcio-tools`.

```proto
syntax = "proto3";
package transcription.v1;

enum Engine {
  ENGINE_UNSPECIFIED = 0;
  ENGINE_WHISPER     = 1;
  ENGINE_PARAKEET    = 2;
}

message TranscriptSegment {
  string          text             = 1;
  uint64          segment_id       = 2;
  optional float  confidence       = 3;  // null for engines that don't produce one
  bool            is_partial       = 4;
  Engine          engine           = 5;
  string          model_name       = 6;
  double          audio_start_time = 7;
  double          audio_end_time   = 8;
  optional string language         = 9;  // null for English-only engines
  string          recording_id     = 10; // routes segments to the right session
  string          trace_id         = 11; // propagated from AudioSegment.trace_id
}

message StreamTranscriptsRequest  {}
message StreamTranscriptsResponse { TranscriptSegment segment = 1; }

service TranscriptionService {
  rpc StreamTranscripts(StreamTranscriptsRequest)
      returns (stream StreamTranscriptsResponse);
}
```

`StreamTranscriptsRequest` is empty — all subscribers receive all segments from
all active recordings and filter by `recording_id` client-side, mirroring the
audio-core broadcast pattern.

## Data contracts (Pydantic)

`models.py` defines internal types used by engine and worker layers. Proto
objects are only created or consumed at the gRPC boundary (`grpc_client.py` and
`grpc_server.py`).

```python
class TranscriptResult:
    text: str
    confidence: float | None
    language: str | None
    audio_start_time: float
    audio_end_time: float

class ModelInfo:
    name: str
    engine: str
    size_bytes: int
    checksum_sha256: str
    download_url: str
    tier: str            # e.g. "high_accuracy", "balanced", "fast"

class ModelStatus(Enum):
    AVAILABLE | MISSING | DOWNLOADING | ERROR | CORRUPTED

class DownloadProgress:
    model_name: str
    engine: str
    bytes_downloaded: int
    total_bytes: int
    status: ModelStatus
```

## Engine abstraction

`engine.py` defines the Protocol all engine implementations satisfy:

```python
class TranscriptionEngine(Protocol):
    @property
    def name(self) -> str: ...
    def is_model_loaded(self) -> bool: ...
    def current_model(self) -> str | None: ...
    def load_model(self, name: str) -> None: ...
    def unload_model(self) -> None: ...
    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult: ...
```

`transcribe()` always receives a float32 NumPy array at 16 kHz mono. Resampling
from the audio-core's native rate happens in the worker before the engine is
called, using `scipy.signal.resample_poly`.

### Whisper backend (`whisper_engine.py`)

Platform-selected at `load_model()` time:

- **Apple Silicon** (`sys.platform == "darwin"` and
  `platform.machine() == "arm64"`): uses `mlx-whisper` for native Metal GPU
  acceleration.
- **All other platforms** (Linux, Windows, macOS Intel): uses `faster-whisper`
  (CTranslate2), which supports CUDA and CPU.

Confidence is derived from `avg_logprob` on the output segments (or the
equivalent field on the MLX backend).

### Parakeet backend (`parakeet_engine.py`)

Uses `onnxruntime` + `onnx-asr`. ONNX Runtime handles platform differences
internally (CPU/CUDA/CoreML execution providers). English-only: `language` is
always `None` in `TranscriptResult`. No confidence score: `confidence` is always
`None`.

### Default engine selection

Resolved in the worker at session start, unless the caller specifies an engine
explicitly via the `POST /sessions` body:

- Language explicitly set to non-English → Whisper
- Language is English or unknown → Parakeet (better WER and real-time factor for
  English)

## Model registry

YAML manifests per engine at
`src/bahlily_transcription/manifests/{engine}.yaml`:

```yaml
engine: whisper
models:
  - name: large-v3-turbo
    download_url: "https://huggingface.co/..."
    size_bytes: 1500000000
    checksum_sha256: "abc123..."
    tier: high_accuracy
  - name: medium
    download_url: "https://huggingface.co/..."
    size_bytes: 764000000
    checksum_sha256: "def456..."
    tier: balanced
```

Adding a model variant is a data change (YAML only), not a code change.

Models are stored at `~/.bahlily/models/{engine}/{name}/`, configurable via
`BAHLILY_MODELS_DIR`.

**Download flow:**

1. Check `_in_flight` set — raise `AlreadyDownloadingError` if already running.
2. Check `shutil.disk_usage()` — raise `InsufficientDiskSpaceError` if
   `free < model.size_bytes`.
3. Stream download via `httpx.AsyncClient` to a `.tmp` file, yielding
   `DownloadProgress` per 8 KB chunk. SHA-256 is computed incrementally during
   download.
4. On completion: compare digest against manifest. If mismatch → delete temp,
   set status `CORRUPTED`, raise `ChecksumError`. If match → rename to final
   path, set status `AVAILABLE`.
5. On cancel: delete temp, set status `MISSING`.

**Startup cleanup:** temp files (`.tmp`) left by a previous crash are deleted and
their models marked `MISSING`. Status dict is populated by scanning
`BAHLILY_MODELS_DIR` and verifying checksums of existing files.

**Remove guard:** `DELETE /models/{engine}/{name}` checks whether the engine
currently has this model loaded. If so, `unload_model()` is called first, then
the files are removed.

## Session worker

```
POST /sessions { engine?, model?, language? }
  → generate recording_id (UUID), start SessionWorker asyncio task
  → return { recording_id }

SessionWorker.run():
  ├── subscribe to AudioCoreClient stream
  ├── enqueue AudioSegments into asyncio.Queue
  ├── batch loop every 300 ms (or when 8 segments queued):
  │     resample if needed (scipy)
  │     → run_in_executor(engine.transcribe_batch, batch)
  │     → sort results by segment_id
  │     → emit each TranscriptSegment to BroadcastChannel
  └── on stop: drain queue (process all already-queued segments, do not wait
  │           for new segments from audio-core), wait for in-flight inference,
  │           mark completed

POST /sessions/{id}/stop
  → signal drain, await completion
  → log warning if segments_received != segments_completed
  → return { recording_id, status: "stopped", segments_transcribed }
```

**Micro-batching:** `faster-whisper` and `onnx-asr` both benefit from batched
GPU inference. The worker accumulates segments for up to 300 ms (or 8 segments,
whichever comes first) before submitting a batch to the engine.

**Ordering guarantee:** after each batch completes, results are sorted by
`segment_id` before emission, regardless of inference completion order.

**Multiple concurrent sessions:** each gets an independent `SessionWorker` with
its own queue. All workers subscribe to the same audio-core broadcast stream and
stamp their own `recording_id` onto output segments.

## gRPC layers

### `grpc_client.py` — audio-core consumer

```python
class AudioCoreClient:
    async def stream_segments(self) -> AsyncIterator[AudioSegment]:
        backoff = 1.0
        while True:
            try:
                async with grpc.aio.insecure_channel(self._addr) as channel:
                    stub = AudioServiceStub(channel)
                    backoff = 1.0
                    async for response in stub.StreamAudio(StreamAudioRequest()):
                        yield response.segment
            except grpc.aio.AioRpcError:
                await asyncio.sleep(min(backoff, 30.0))
                backoff *= 2
```

Reconnects with exponential backoff (1 s → 2 s → … → 30 s cap) if audio-core
is not yet running or the connection drops.

### `grpc_server.py` — TranscriptSegment broadcaster

Mirrors the audio-core `BroadcastStream` pattern in Python:

```python
class BroadcastChannel:
    def subscribe(self) -> asyncio.Queue[TranscriptSegment]: ...
    def unsubscribe(self, q: asyncio.Queue[TranscriptSegment]) -> None: ...
    async def publish(self, segment: TranscriptSegment) -> None:
        # put_nowait to each subscriber queue
        # QueueFull → log warning, skip for that subscriber only

class TranscriptionGrpcService:
    async def StreamTranscripts(self, request, context):
        q = self._broadcast.subscribe()
        try:
            while True:
                segment = await q.get()
                yield StreamTranscriptsResponse(segment=segment)
        finally:
            self._broadcast.unsubscribe(q)
```

Per-subscriber queue capacity: 100 (same reasoning as audio-core: ~1–2 s of
buffer at typical segment rates). A lagging subscriber is skipped with a warning
rather than blocking the pipeline.

## HTTP API

FastAPI on port 8002. `{engine}` is `whisper` or `parakeet`.

### Model management

| Method   | Path                                    | Notes                                   |
|----------|-----------------------------------------|-----------------------------------------|
| `GET`    | `/models/{engine}`                      | List all models with status             |
| `GET`    | `/models/{engine}/current`              | Currently loaded model (null if none)   |
| `POST`   | `/models/{engine}/load`                 | Body: `{name}` — blocks until loaded    |
| `POST`   | `/models/{engine}/download/{name}`      | SSE stream of `DownloadProgress` events |
| `POST`   | `/models/{engine}/download/{name}/cancel` | Cancel in-flight download             |
| `DELETE` | `/models/{engine}/{name}`               | Unload if needed, then delete files     |
| `GET`    | `/health`                               | Service status + loaded models          |

### Session management

| Method | Path                    | Notes                                         |
|--------|-------------------------|-----------------------------------------------|
| `POST` | `/sessions`             | Start session, return `{recording_id}`        |
| `POST` | `/sessions/{id}/stop`   | Drain + stop, return segment count            |
| `GET`  | `/sessions/{id}`        | Status: `started\|stopping\|stopped\|error`   |

### SSE download progress events

```
data: {"bytes_downloaded": 50000000, "total_bytes": 1500000000, "status": "downloading"}

data: {"bytes_downloaded": 1500000000, "total_bytes": 1500000000, "status": "complete"}

data: {"status": "error", "message": "checksum verification failed"}
```

Keepalive comment (`:\n\n`) every 15 s prevents proxy timeouts. A subscriber
that connects after the download finishes receives an immediate `complete` event.

## Error handling

All errors extend `BahlilyError` from `bahlily-logging` and are registered in
`error-catalog.yaml`.

| Code                                    | Trigger                               | HTTP |
|-----------------------------------------|---------------------------------------|------|
| `TRANSCRIPTION_MODEL_NOT_LOADED`        | Session started, no model loaded      | 409  |
| `TRANSCRIPTION_AUDIO_TOO_SHORT`         | Segment < 0.5 s                       | —    |
| `TRANSCRIPTION_ENGINE_FAILED`           | Inference exhausted retries           | —    |
| `TRANSCRIPTION_UNSUPPORTED_LANGUAGE`    | Parakeet called with non-English      | 422  |
| `TRANSCRIPTION_MODEL_NOT_FOUND`         | Name not in manifest                  | 404  |
| `TRANSCRIPTION_ALREADY_DOWNLOADING`     | Concurrent download for same model    | 409  |
| `TRANSCRIPTION_INSUFFICIENT_DISK`       | Disk too full before download starts  | 422  |
| `TRANSCRIPTION_CHECKSUM_FAILED`         | SHA-256 mismatch after download       | —    |

`TRANSCRIPTION_AUDIO_TOO_SHORT`, `TRANSCRIPTION_ENGINE_FAILED`, and
`TRANSCRIPTION_CHECKSUM_FAILED` do not map to HTTP status codes because they
surface as typed events or status updates rather than request responses.

**Per-segment retry** uses `stamina`:

```python
@stamina.retry(on=EngineFailedError, attempts=3, wait_initial=1.0, wait_max=4.0)
async def _transcribe_with_retry(engine, audio, language): ...
```

On exhausted retries, an error `TranscriptSegment` is emitted (`text=""`,
`confidence=None`, `is_partial=False`) — never a silent drop. `stamina`
integrates with `structlog` automatically, logging each retry attempt.

**Per-segment timeout:** 60 s for CPU, 30 s for GPU, configurable via
`TRANSCRIPTION_SEGMENT_TIMEOUT_S`. These are initial values to be calibrated
against real benchmark data.

## Dependencies

Runtime:

```toml
dependencies = [
    "grpcio>=1.83.0",
    "fastapi>=0.140.13",
    "uvicorn[standard]>=0.51.0",
    "httpx>=0.28.1",
    "sse-starlette>=3.4.6",
    "stamina>=26.1.0",
    "pyyaml>=6.0.3",
    "pydantic>=2.13.4",
    "numpy>=2.0",
    "scipy>=1.18.0",
    "bahlily-logging>=0.1.0",
    "structlog>=24.1",
    # Whisper backends — platform-selected:
    "faster-whisper>=1.2.1; sys_platform != 'darwin' or platform_machine != 'arm64'",
    "mlx-whisper>=0.4.3;   sys_platform == 'darwin' and platform_machine == 'arm64'",
    # Parakeet:
    "onnxruntime>=1.28.0",
    "onnx-asr>=0.12.0",
]
```

Dev:

```toml
[dependency-groups]
dev = [
    "ruff>=0.8", "pytest>=8", "mypy>=1.13",
    "grpcio-tools>=1.83.0",   # proto codegen
    "respx>=0.23.1",          # httpx mock for download tests
    "types-pyyaml>=6.0",
]
```

All licenses: MIT, BSD-3-Clause, or Apache-2.0 — permissive, no copyleft.

## Testing

**Unit tests** (`tests/`):

- **Engine Protocol** — `FakeEngine` implementing `TranscriptionEngine`,
  verifying the interface is complete and type-correct.
- **Model registry** — httpx mocked via `respx`: progress yielded correctly,
  checksum mismatch → `CORRUPTED` status, cancel cleans up temp file,
  concurrent download rejected, disk space check triggers before download.
- **Worker micro-batching** — inject segments with controlled timestamps, verify
  batch window (≤300 ms) and max size (≤8), verify output is sorted by
  `segment_id` even when inference completes out of order.
- **Worker retry** — `FakeEngine` that raises `EngineFailedError` on the first
  two calls then succeeds; verify three attempts occurred and the result is
  emitted. Separate case: fails all three → error segment emitted, not silent
  drop. Use `stamina.testing.suppress()` where retries should not run.
- **BroadcastChannel** — multiple subscribers each receive all segments; one
  subscriber's `QueueFull` does not stall others.
- **HTTP endpoints** — `TestClient` covering all endpoints including SSE event
  format, keepalive comment, late-subscriber immediate-complete, and all
  4xx/409/422 error codes.

**Integration tests** (tagged `@pytest.mark.integration`, skipped in CI by
default):

- `FakeAudioCoreServer` (in-process gRPC server) → worker → broadcast →
  assert `TranscriptSegment` output with real `FakeEngine`.
- `WhisperEngine` with the `tiny` model on a fixed 5 s audio fixture; assert
  output is non-empty and segment IDs are ordered.
- `ParakeetEngine` on the same fixture; assert `confidence=None` and
  `language=None`.

**Benchmark tests** (tagged `@pytest.mark.benchmark`, run manually only):

WER and latency comparison across engines and platforms (macOS Metal, NVIDIA
CUDA, CPU-only) on a fixed golden-set of meeting recordings. Results written to
a file for comparison across runs. Not part of CI.
