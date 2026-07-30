# Transcription Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `bahlily-transcription` Python service that receives VAD-filtered
audio from the Rust audio core over gRPC, transcribes via Whisper or Parakeet,
and broadcasts `TranscriptSegment` messages over a second gRPC stream.

**Architecture:** Single asyncio process. `AudioCoreClient` subscribes to audio-core's
`StreamAudio` gRPC. `SessionWorker` micro-batches segments (300 ms / 8 segments),
runs inference in a `ThreadPoolExecutor`, and publishes results to a
`BroadcastChannel`. `TranscriptionGrpcService` streams from that channel to gRPC
subscribers. `FastAPI` exposes model management and session lifecycle over HTTP.

**Tech Stack:** Python 3.12, FastAPI, grpcio 1.83, grpcio-tools, httpx, sse-starlette,
stamina, faster-whisper (non-Apple-Silicon) / mlx-whisper (Apple Silicon),
onnxruntime + onnx-asr (Parakeet), scipy, numpy, pydantic, structlog,
bahlily-logging, respx (tests).

## Global Constraints

- Python ≥ 3.12; `from __future__ import annotations` in every file.
- `mypy --strict` must pass. All public functions annotated. No `Any` unless
  unavoidable with third-party stubs.
- `ruff format` + `ruff check` must pass before every commit.
- All runtime deps: MIT, BSD-3-Clause, or Apache-2.0 — no copyleft.
- Working directory for all `uv` commands: `services/transcription/`.
- Conventional commit messages: `feat(transcription): ...`, `fix(transcription): ...`,
  `test(transcription): ...`, `chore(transcription): ...`.
- Every new error code must be added to `error-catalog.yaml` in the repo root.
- Tests live in `services/transcription/tests/`. Run with `uv run pytest`.
- Proto-generated files live in `src/bahlily_transcription/pb/` and are
  regenerated via `scripts/gen_proto.sh` — never edit generated files by hand.

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Dependencies, tool config |
| `proto/transcription/v1/transcription.proto` | TranscriptSegment gRPC contract |
| `scripts/gen_proto.sh` | Regenerate pb/ from both protos |
| `src/bahlily_transcription/pb/` | Generated gRPC bindings (both protos) |
| `src/bahlily_transcription/models.py` | Pydantic/dataclass data contracts |
| `src/bahlily_transcription/errors.py` | BahlilyError subclasses |
| `src/bahlily_transcription/engine.py` | TranscriptionEngine Protocol |
| `src/bahlily_transcription/whisper_engine.py` | Whisper backend (faster-whisper / mlx-whisper) |
| `src/bahlily_transcription/parakeet_engine.py` | Parakeet backend (onnxruntime + onnx-asr) |
| `src/bahlily_transcription/manifests/whisper.yaml` | Whisper model catalog |
| `src/bahlily_transcription/manifests/parakeet.yaml` | Parakeet model catalog |
| `src/bahlily_transcription/registry.py` | ModelRegistry (download, verify, status) |
| `src/bahlily_transcription/grpc_server.py` | BroadcastChannel + TranscriptionGrpcService |
| `src/bahlily_transcription/grpc_client.py` | AudioCoreClient (gRPC subscriber) |
| `src/bahlily_transcription/worker.py` | SessionWorker + micro-batching |
| `src/bahlily_transcription/app.py` | FastAPI app (HTTP management + SSE) |
| `src/bahlily_transcription/__init__.py` | `main()` entrypoint |
| `tests/conftest.py` | FakeEngine, FakeAudioCoreServer shared fixtures |
| `tests/test_models.py` | Data contract validation tests |
| `tests/test_engine_protocol.py` | Protocol conformance via FakeEngine |
| `tests/test_whisper_engine.py` | WhisperEngine with mocked library |
| `tests/test_parakeet_engine.py` | ParakeetEngine with mocked library |
| `tests/test_registry.py` | ModelRegistry with respx + tmp_path |
| `tests/test_grpc_server.py` | BroadcastChannel + gRPC server |
| `tests/test_grpc_client.py` | AudioCoreClient with FakeAudioCoreServer |
| `tests/test_worker.py` | SessionWorker: batching, ordering, retry |
| `tests/test_app.py` | FastAPI TestClient: all endpoints |
| `tests/test_smoke.py` | Replace existing placeholder |

---

## Task 1: Project skeleton + proto codegen

**Files:**
- Modify: `services/transcription/pyproject.toml`
- Create: `services/transcription/proto/transcription/v1/transcription.proto`
- Create: `services/transcription/scripts/gen_proto.sh`
- Create: `services/transcription/src/bahlily_transcription/pb/` (directory, populated by script)

**Interfaces:**
- Produces: `bahlily_transcription.pb.audio_core.v1.audio_pb2.AudioSegment`,
  `bahlily_transcription.pb.audio_core.v1.audio_pb2_grpc.AudioServiceStub`,
  `bahlily_transcription.pb.transcription.v1.transcription_pb2.TranscriptSegment`,
  `bahlily_transcription.pb.transcription.v1.transcription_pb2_grpc.TranscriptionServiceServicer`

- [ ] **Step 1: Replace pyproject.toml**

```toml
[project]
name = "bahlily-transcription"
version = "0.1.0"
description = "Whisper + Parakeet transcription service"
authors = [{ name = "Harun", email = "harun.sigmawaveai@gmail.com" }]
requires-python = ">=3.12"
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
    "structlog>=24.1",
    "bahlily-logging>=0.1.0",
    "faster-whisper>=1.2.1; sys_platform != 'darwin' or platform_machine != 'arm64'",
    "mlx-whisper>=0.4.3;   sys_platform == 'darwin' and platform_machine == 'arm64'",
    "onnxruntime>=1.28.0",
    "onnx-asr>=0.12.0",
]

[tool.uv.sources]
bahlily-logging = { path = "../../packages/bahlily-logging" }

[project.scripts]
bahlily-transcription = "bahlily_transcription:main"

[build-system]
requires = ["uv_build>=0.11.7,<0.12.0"]
build-backend = "uv_build"

[dependency-groups]
dev = [
    "ruff>=0.8",
    "pytest>=8",
    "mypy>=1.13",
    "grpcio-tools>=1.83.0",
    "respx>=0.23.1",
    "types-pyyaml>=6.0",
    "pytest-asyncio>=0.23",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create proto file**

Create `proto/transcription/v1/transcription.proto`:

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
  optional float  confidence       = 3;
  bool            is_partial       = 4;
  Engine          engine           = 5;
  string          model_name       = 6;
  double          audio_start_time = 7;
  double          audio_end_time   = 8;
  optional string language         = 9;
  string          recording_id     = 10;
  string          trace_id         = 11;
}

message StreamTranscriptsRequest  {}
message StreamTranscriptsResponse { TranscriptSegment segment = 1; }

service TranscriptionService {
  rpc StreamTranscripts(StreamTranscriptsRequest)
      returns (stream StreamTranscriptsResponse);
}
```

- [ ] **Step 3: Create codegen script**

Create `scripts/gen_proto.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf src/bahlily_transcription/pb
mkdir -p src/bahlily_transcription/pb

uv run python -m grpc_tools.protoc \
  -I proto \
  -I ../../shell/audio-core/proto \
  --python_out=src/bahlily_transcription/pb \
  --grpc_python_out=src/bahlily_transcription/pb \
  --pyi_out=src/bahlily_transcription/pb \
  proto/transcription/v1/transcription.proto \
  ../../shell/audio-core/proto/audio_core/v1/audio.proto

# Create __init__.py in every generated subdirectory
find src/bahlily_transcription/pb -type d -exec touch {}/__init__.py \;

echo "proto codegen complete"
```

```bash
chmod +x scripts/gen_proto.sh
```

- [ ] **Step 4: Install deps and run codegen**

```bash
uv sync
bash scripts/gen_proto.sh
```

Verify the following files exist:
- `src/bahlily_transcription/pb/transcription/v1/transcription_pb2.py`
- `src/bahlily_transcription/pb/transcription/v1/transcription_pb2_grpc.py`
- `src/bahlily_transcription/pb/audio_core/v1/audio_pb2.py`
- `src/bahlily_transcription/pb/audio_core/v1/audio_pb2_grpc.py`

- [ ] **Step 5: Verify import works**

```bash
uv run python -c "
from bahlily_transcription.pb.audio_core.v1 import audio_pb2
from bahlily_transcription.pb.transcription.v1 import transcription_pb2
print('imports ok')
"
```

Expected output: `imports ok`

- [ ] **Step 6: Commit**

```bash
git add services/transcription/pyproject.toml \
        services/transcription/proto/ \
        services/transcription/scripts/ \
        services/transcription/src/bahlily_transcription/pb/ \
        services/transcription/uv.lock
git commit -m "chore(transcription): add deps, proto, and codegen script"
```

---

## Task 2: Data contracts + error taxonomy

**Files:**
- Create: `services/transcription/src/bahlily_transcription/models.py`
- Create: `services/transcription/src/bahlily_transcription/errors.py`
- Modify: `error-catalog.yaml` (repo root)
- Create: `services/transcription/tests/__init__.py`
- Create: `services/transcription/tests/test_models.py`

**Interfaces:**
- Produces:
  - `TranscriptResult(text, confidence, language, audio_start_time, audio_end_time)`
  - `ModelInfo(name, engine, size_bytes, checksum_sha256, download_url, tier)`
  - `ModelStatus` enum: `AVAILABLE | MISSING | DOWNLOADING | ERROR | CORRUPTED`
  - `DownloadProgress(model_name, engine, bytes_downloaded, total_bytes, status)`
  - `TranscriptionModelNotLoadedError`, `TranscriptionAudioTooShortError`,
    `TranscriptionEngineFailedError`, `TranscriptionUnsupportedLanguageError`,
    `TranscriptionModelNotFoundError`, `TranscriptionAlreadyDownloadingError`,
    `TranscriptionInsufficientDiskError`, `TranscriptionChecksumFailedError`

- [ ] **Step 1: Write failing tests**

Create `tests/__init__.py` (empty).

Create `tests/test_models.py`:

```python
from __future__ import annotations
import pytest
from bahlily_transcription.models import (
    DownloadProgress,
    ModelInfo,
    ModelStatus,
    TranscriptResult,
)
from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionModelNotFoundError,
    TranscriptionModelNotLoadedError,
)


def test_transcript_result_is_frozen() -> None:
    r = TranscriptResult(
        text="hello",
        confidence=0.9,
        language="en",
        audio_start_time=0.0,
        audio_end_time=2.5,
    )
    with pytest.raises(Exception):
        r.text = "changed"  # type: ignore[misc]


def test_model_status_values_exist() -> None:
    assert ModelStatus.AVAILABLE.value == "available"
    assert ModelStatus.MISSING.value == "missing"
    assert ModelStatus.DOWNLOADING.value == "downloading"
    assert ModelStatus.ERROR.value == "error"
    assert ModelStatus.CORRUPTED.value == "corrupted"


def test_download_progress_is_frozen() -> None:
    p = DownloadProgress(
        model_name="large-v3-turbo",
        engine="whisper",
        bytes_downloaded=500,
        total_bytes=1000,
        status=ModelStatus.DOWNLOADING,
    )
    with pytest.raises(Exception):
        p.bytes_downloaded = 600  # type: ignore[misc]


def test_error_codes_are_set() -> None:
    assert TranscriptionModelNotLoadedError("whisper").code == "TRANSCRIPTION_MODEL_NOT_LOADED"
    assert TranscriptionModelNotFoundError("bad-name").code == "TRANSCRIPTION_MODEL_NOT_FOUND"
    assert TranscriptionAlreadyDownloadingError("large-v3").code == "TRANSCRIPTION_ALREADY_DOWNLOADING"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'bahlily_transcription.models'`

- [ ] **Step 3: Create models.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    confidence: float | None
    language: str | None
    audio_start_time: float
    audio_end_time: float


@dataclass(frozen=True)
class ModelInfo:
    name: str
    engine: str
    size_bytes: int
    checksum_sha256: str
    download_url: str
    tier: str


class ModelStatus(Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    ERROR = "error"
    CORRUPTED = "corrupted"


@dataclass(frozen=True)
class DownloadProgress:
    model_name: str
    engine: str
    bytes_downloaded: int
    total_bytes: int
    status: ModelStatus
```

- [ ] **Step 4: Create errors.py**

```python
from __future__ import annotations

from bahlily_logging.errors import BahlilyError


class TranscriptionModelNotLoadedError(BahlilyError):
    def __init__(self, engine: str) -> None:
        super().__init__(f"{engine} has no model loaded", code="TRANSCRIPTION_MODEL_NOT_LOADED")


class TranscriptionAudioTooShortError(BahlilyError):
    def __init__(self, duration_s: float) -> None:
        super().__init__(
            f"audio segment too short ({duration_s:.2f}s < 0.5s)",
            code="TRANSCRIPTION_AUDIO_TOO_SHORT",
        )


class TranscriptionEngineFailedError(BahlilyError):
    def __init__(self, engine: str, reason: str) -> None:
        super().__init__(f"{engine} inference failed: {reason}", code="TRANSCRIPTION_ENGINE_FAILED")


class TranscriptionUnsupportedLanguageError(BahlilyError):
    def __init__(self, language: str, engine: str) -> None:
        super().__init__(
            f"{engine} does not support language '{language}'",
            code="TRANSCRIPTION_UNSUPPORTED_LANGUAGE",
        )


class TranscriptionModelNotFoundError(BahlilyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"model '{name}' not found in manifest", code="TRANSCRIPTION_MODEL_NOT_FOUND")


class TranscriptionAlreadyDownloadingError(BahlilyError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"model '{name}' is already downloading",
            code="TRANSCRIPTION_ALREADY_DOWNLOADING",
        )


class TranscriptionInsufficientDiskError(BahlilyError):
    def __init__(self, needed: int, free: int) -> None:
        super().__init__(
            f"need {needed} bytes but only {free} free",
            code="TRANSCRIPTION_INSUFFICIENT_DISK",
        )


class TranscriptionChecksumFailedError(BahlilyError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"checksum verification failed for '{name}'",
            code="TRANSCRIPTION_CHECKSUM_FAILED",
        )
```

- [ ] **Step 5: Add error codes to error-catalog.yaml** (repo root)

Append these entries to `error-catalog.yaml`:

```yaml
- code: TRANSCRIPTION_MODEL_NOT_LOADED
  domain: transcription
  severity: error
  description: A transcription session was started but no model has been loaded into the requested engine.
- code: TRANSCRIPTION_AUDIO_TOO_SHORT
  domain: transcription
  severity: warn
  description: An audio segment shorter than 0.5 s was submitted for transcription; it was skipped.
- code: TRANSCRIPTION_ENGINE_FAILED
  domain: transcription
  severity: error
  description: The transcription engine raised an error during inference and exhausted its retry budget.
- code: TRANSCRIPTION_UNSUPPORTED_LANGUAGE
  domain: transcription
  severity: error
  description: Parakeet was requested for a non-English language it does not support.
- code: TRANSCRIPTION_MODEL_NOT_FOUND
  domain: transcription
  severity: error
  description: The requested model name does not appear in the engine manifest.
- code: TRANSCRIPTION_ALREADY_DOWNLOADING
  domain: transcription
  severity: warn
  description: A download was requested for a model that is already being downloaded.
- code: TRANSCRIPTION_INSUFFICIENT_DISK
  domain: transcription
  severity: error
  description: Not enough free disk space to download the requested model.
- code: TRANSCRIPTION_CHECKSUM_FAILED
  domain: transcription
  severity: error
  description: SHA-256 verification of a downloaded model file failed; the file has been removed.
```

Also remove the placeholder entry:
```yaml
- code: TRANSCRIPTION_RESERVED
  ...
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
uv run pytest tests/test_models.py -v
```

- [ ] **Step 7: Run mypy**

```bash
uv run mypy .
```

Expected: `Success: no issues found`

- [ ] **Step 8: Commit**

```bash
git add services/transcription/src/bahlily_transcription/models.py \
        services/transcription/src/bahlily_transcription/errors.py \
        services/transcription/tests/ \
        error-catalog.yaml
git commit -m "feat(transcription): add data contracts, errors, and catalog entries"
```

---

## Task 3: Engine Protocol + FakeEngine

**Files:**
- Create: `services/transcription/src/bahlily_transcription/engine.py`
- Create: `services/transcription/tests/conftest.py`
- Create: `services/transcription/tests/test_engine_protocol.py`

**Interfaces:**
- Consumes: `TranscriptResult` from `models.py`
- Produces:
  - `TranscriptionEngine` Protocol (runtime_checkable)
  - `FakeEngine` (in conftest.py, available to all tests as a fixture)
  - `TranscriptionEngine.name: str` property
  - `TranscriptionEngine.is_model_loaded() -> bool`
  - `TranscriptionEngine.current_model() -> str | None`
  - `TranscriptionEngine.load_model(name: str) -> None`
  - `TranscriptionEngine.unload_model() -> None`
  - `TranscriptionEngine.transcribe(audio: np.ndarray, language: str | None) -> TranscriptResult`
  - `TranscriptionEngine.transcribe_batch(audios: list[np.ndarray], language: str | None) -> list[TranscriptResult]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_engine_protocol.py`:

```python
from __future__ import annotations
import numpy as np
import pytest
from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.models import TranscriptResult


def test_fake_engine_satisfies_protocol(fake_engine: TranscriptionEngine) -> None:
    assert isinstance(fake_engine, TranscriptionEngine)


def test_fake_engine_not_loaded_initially(fake_engine: TranscriptionEngine) -> None:
    assert fake_engine.is_model_loaded() is False
    assert fake_engine.current_model() is None


def test_fake_engine_load_and_unload(fake_engine: TranscriptionEngine) -> None:
    fake_engine.load_model("test-model")
    assert fake_engine.is_model_loaded() is True
    assert fake_engine.current_model() == "test-model"
    fake_engine.unload_model()
    assert fake_engine.is_model_loaded() is False


def test_fake_engine_transcribe_returns_result(fake_engine: TranscriptionEngine) -> None:
    fake_engine.load_model("test-model")
    audio = np.zeros(16000, dtype=np.float32)
    result = fake_engine.transcribe(audio, language="en")
    assert isinstance(result, TranscriptResult)
    assert result.text == "fake transcription"


def test_fake_engine_transcribe_batch(fake_engine: TranscriptionEngine) -> None:
    fake_engine.load_model("test-model")
    audios = [np.zeros(16000, dtype=np.float32) for _ in range(3)]
    results = fake_engine.transcribe_batch(audios, language="en")
    assert len(results) == 3
    assert all(isinstance(r, TranscriptResult) for r in results)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_engine_protocol.py -v
```

- [ ] **Step 3: Create engine.py**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from bahlily_transcription.models import TranscriptResult


@runtime_checkable
class TranscriptionEngine(Protocol):
    @property
    def name(self) -> str: ...

    def is_model_loaded(self) -> bool: ...

    def current_model(self) -> str | None: ...

    def load_model(self, name: str) -> None: ...

    def unload_model(self) -> None: ...

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult: ...

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
```

- [ ] **Step 4: Create tests/conftest.py with FakeEngine**

```python
from __future__ import annotations

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.models import TranscriptResult


class FakeEngine:
    """Implements TranscriptionEngine for use in tests. No real models loaded."""

    _name = "fake"
    _loaded: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._loaded is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        self._loaded = name

    def unload_model(self) -> None:
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        duration = len(audio) / 16000.0
        return TranscriptResult(
            text="fake transcription",
            confidence=0.95,
            language=language or "en",
            audio_start_time=0.0,
            audio_end_time=duration,
        )

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]


@pytest.fixture
def fake_engine() -> TranscriptionEngine:
    return FakeEngine()  # type: ignore[return-value]
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/test_engine_protocol.py -v
```

- [ ] **Step 6: Commit**

```bash
git add services/transcription/src/bahlily_transcription/engine.py \
        services/transcription/tests/conftest.py \
        services/transcription/tests/test_engine_protocol.py
git commit -m "feat(transcription): add TranscriptionEngine protocol and FakeEngine"
```

---

## Task 4: Whisper engine

**Files:**
- Create: `services/transcription/src/bahlily_transcription/whisper_engine.py`
- Create: `services/transcription/tests/test_whisper_engine.py`

**Interfaces:**
- Consumes: `TranscriptionEngine` Protocol, `TranscriptResult`, `TranscriptionEngineFailedError`
- Produces: `WhisperEngine(models_dir: Path)` — implements `TranscriptionEngine`

- [ ] **Step 1: Write failing tests**

Create `tests/test_whisper_engine.py`:

```python
from __future__ import annotations

import platform
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.whisper_engine import WhisperEngine


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "whisper"
    d.mkdir(parents=True)
    return d


def _mock_faster_whisper_segment(text: str, start: float, end: float) -> MagicMock:
    seg = MagicMock()
    seg.text = text
    seg.start = start
    seg.end = end
    seg.avg_logprob = -0.15
    return seg


def test_whisper_engine_satisfies_protocol(models_dir: Path) -> None:
    engine = WhisperEngine(models_dir=models_dir)
    assert isinstance(engine, TranscriptionEngine)


def test_whisper_not_loaded_initially(models_dir: Path) -> None:
    engine = WhisperEngine(models_dir=models_dir)
    assert engine.is_model_loaded() is False
    assert engine.current_model() is None


def test_whisper_load_sets_state(models_dir: Path) -> None:
    mock_model = MagicMock()
    with patch("bahlily_transcription.whisper_engine._is_apple_silicon", return_value=False), \
         patch("bahlily_transcription.whisper_engine.WhisperModel", return_value=mock_model):
        engine = WhisperEngine(models_dir=models_dir)
        engine.load_model("tiny")
    assert engine.is_model_loaded() is True
    assert engine.current_model() == "tiny"


def test_whisper_transcribe_returns_joined_text(models_dir: Path) -> None:
    seg1 = _mock_faster_whisper_segment("hello", 0.0, 1.0)
    seg2 = _mock_faster_whisper_segment(" world", 1.0, 2.0)
    mock_info = MagicMock()
    mock_info.language = "en"
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([seg1, seg2], mock_info)

    with patch("bahlily_transcription.whisper_engine._is_apple_silicon", return_value=False), \
         patch("bahlily_transcription.whisper_engine.WhisperModel", return_value=mock_model):
        engine = WhisperEngine(models_dir=models_dir)
        engine.load_model("tiny")
        audio = np.zeros(32000, dtype=np.float32)
        result = engine.transcribe(audio, language=None)

    assert result.text == "hello world"
    assert result.audio_start_time == 0.0
    assert result.audio_end_time == 2.0
    assert result.language == "en"


def test_whisper_unload_clears_state(models_dir: Path) -> None:
    mock_model = MagicMock()
    with patch("bahlily_transcription.whisper_engine._is_apple_silicon", return_value=False), \
         patch("bahlily_transcription.whisper_engine.WhisperModel", return_value=mock_model):
        engine = WhisperEngine(models_dir=models_dir)
        engine.load_model("tiny")
        engine.unload_model()
    assert engine.is_model_loaded() is False
    assert engine.current_model() is None
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_whisper_engine.py -v
```

- [ ] **Step 3: Create whisper_engine.py**

```python
from __future__ import annotations

import platform
import sys
from pathlib import Path

import numpy as np

from bahlily_transcription.errors import TranscriptionEngineFailedError
from bahlily_transcription.models import TranscriptResult


def _is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


# Lazy imports to avoid import errors on platforms without the library installed.
# WhisperModel and mlx_whisper are imported at load_model() time.
if not _is_apple_silicon():
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]
else:
    WhisperModel = None  # type: ignore[assignment,misc]


class WhisperEngine:
    """Whisper transcription backend. Uses mlx-whisper on Apple Silicon,
    faster-whisper on all other platforms."""

    _name = "whisper"

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir
        self._model: object | None = None
        self._loaded: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._model is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        model_path = str(self._models_dir / name)
        if _is_apple_silicon():
            import mlx_whisper  # type: ignore[import-untyped]
            # mlx_whisper uses the model path directly at transcribe time.
            self._model = mlx_whisper
            self._mlx_model_path = model_path
        else:
            self._model = WhisperModel(model_path, device="auto", compute_type="auto")
        self._loaded = name

    def unload_model(self) -> None:
        self._model = None
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        if self._model is None:
            raise TranscriptionEngineFailedError("whisper", "model not loaded")

        try:
            if _is_apple_silicon():
                import mlx_whisper  # type: ignore[import-untyped]
                result = mlx_whisper.transcribe(
                    audio,
                    path_or_hf_repo=self._mlx_model_path,  # type: ignore[attr-defined]
                    language=language,
                )
                text = result["text"].strip()
                segments = result.get("segments", [])
                start = segments[0]["start"] if segments else 0.0
                end = segments[-1]["end"] if segments else float(len(audio)) / 16000.0
                detected_language = result.get("language", language)
                confidence = None
            else:
                segments_iter, info = self._model.transcribe(  # type: ignore[union-attr]
                    audio, language=language
                )
                segments = list(segments_iter)
                text = "".join(s.text for s in segments).strip()
                start = segments[0].start if segments else 0.0
                end = segments[-1].end if segments else float(len(audio)) / 16000.0
                detected_language = info.language
                logprobs = [s.avg_logprob for s in segments if hasattr(s, "avg_logprob")]
                confidence = float(sum(logprobs) / len(logprobs)) if logprobs else None
        except Exception as exc:
            raise TranscriptionEngineFailedError("whisper", str(exc)) from exc

        return TranscriptResult(
            text=text,
            confidence=confidence,
            language=detected_language,
            audio_start_time=start,
            audio_end_time=end,
        )

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_whisper_engine.py -v
```

- [ ] **Step 5: Run mypy**

```bash
uv run mypy .
```

- [ ] **Step 6: Commit**

```bash
git add services/transcription/src/bahlily_transcription/whisper_engine.py \
        services/transcription/tests/test_whisper_engine.py
git commit -m "feat(transcription): add WhisperEngine (faster-whisper + mlx-whisper)"
```

---

## Task 5: Parakeet engine

**Files:**
- Create: `services/transcription/src/bahlily_transcription/parakeet_engine.py`
- Create: `services/transcription/tests/test_parakeet_engine.py`

**Interfaces:**
- Consumes: `TranscriptionEngine` Protocol, `TranscriptResult`, `TranscriptionUnsupportedLanguageError`, `TranscriptionEngineFailedError`
- Produces: `ParakeetEngine(models_dir: Path)` — implements `TranscriptionEngine`
  - `confidence` is always `None` (Parakeet does not produce it)
  - `language` is always `None` (English-only, not detected)
  - Raises `TranscriptionUnsupportedLanguageError` if `language` is not `None` and not `"en"`

- [ ] **Step 1: Write failing tests**

Create `tests/test_parakeet_engine.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.errors import TranscriptionUnsupportedLanguageError
from bahlily_transcription.parakeet_engine import ParakeetEngine


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "parakeet"
    d.mkdir(parents=True)
    return d


def test_parakeet_satisfies_protocol(models_dir: Path) -> None:
    engine = ParakeetEngine(models_dir=models_dir)
    assert isinstance(engine, TranscriptionEngine)


def test_parakeet_not_loaded_initially(models_dir: Path) -> None:
    engine = ParakeetEngine(models_dir=models_dir)
    assert engine.is_model_loaded() is False


def test_parakeet_transcribe_returns_no_confidence_no_language(models_dir: Path) -> None:
    mock_pipeline = MagicMock()
    mock_pipeline.transcribe.return_value = {"text": "hello world"}

    with patch("bahlily_transcription.parakeet_engine.ASRPipeline", return_value=mock_pipeline):
        engine = ParakeetEngine(models_dir=models_dir)
        engine.load_model("parakeet-tdt-1.1b")
        audio = np.zeros(16000, dtype=np.float32)
        result = engine.transcribe(audio, language=None)

    assert result.text == "hello world"
    assert result.confidence is None
    assert result.language is None


def test_parakeet_rejects_non_english(models_dir: Path) -> None:
    mock_pipeline = MagicMock()
    with patch("bahlily_transcription.parakeet_engine.ASRPipeline", return_value=mock_pipeline):
        engine = ParakeetEngine(models_dir=models_dir)
        engine.load_model("parakeet-tdt-1.1b")
        with pytest.raises(TranscriptionUnsupportedLanguageError):
            engine.transcribe(np.zeros(16000, dtype=np.float32), language="fr")
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_parakeet_engine.py -v
```

- [ ] **Step 3: Create parakeet_engine.py**

```python
from __future__ import annotations

from pathlib import Path

import numpy as np

from bahlily_transcription.errors import (
    TranscriptionEngineFailedError,
    TranscriptionUnsupportedLanguageError,
)
from bahlily_transcription.models import TranscriptResult

try:
    from onnx_asr import ASRPipeline  # type: ignore[import-untyped]
except ImportError:
    ASRPipeline = None  # type: ignore[assignment,misc]


class ParakeetEngine:
    """Parakeet transcription backend via onnx-asr. English-only.
    Does not produce confidence scores."""

    _name = "parakeet"

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir
        self._pipeline: object | None = None
        self._loaded: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_model_loaded(self) -> bool:
        return self._pipeline is not None

    def current_model(self) -> str | None:
        return self._loaded

    def load_model(self, name: str) -> None:
        model_path = str(self._models_dir / name)
        self._pipeline = ASRPipeline(model_path)
        self._loaded = name

    def unload_model(self) -> None:
        self._pipeline = None
        self._loaded = None

    def transcribe(self, audio: np.ndarray, language: str | None) -> TranscriptResult:
        if self._pipeline is None:
            raise TranscriptionEngineFailedError("parakeet", "model not loaded")
        if language is not None and language != "en":
            raise TranscriptionUnsupportedLanguageError(language, "parakeet")

        duration = float(len(audio)) / 16000.0
        try:
            result = self._pipeline.transcribe(audio)  # type: ignore[union-attr]
            text = result["text"].strip() if isinstance(result, dict) else str(result).strip()
        except Exception as exc:
            raise TranscriptionEngineFailedError("parakeet", str(exc)) from exc

        return TranscriptResult(
            text=text,
            confidence=None,
            language=None,
            audio_start_time=0.0,
            audio_end_time=duration,
        )

    def transcribe_batch(
        self, audios: list[np.ndarray], language: str | None
    ) -> list[TranscriptResult]:
        return [self.transcribe(audio, language) for audio in audios]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_parakeet_engine.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/transcription/src/bahlily_transcription/parakeet_engine.py \
        services/transcription/tests/test_parakeet_engine.py
git commit -m "feat(transcription): add ParakeetEngine (onnxruntime + onnx-asr)"
```

---

## Task 6: Model registry

**Files:**
- Create: `services/transcription/src/bahlily_transcription/manifests/whisper.yaml`
- Create: `services/transcription/src/bahlily_transcription/manifests/parakeet.yaml`
- Create: `services/transcription/src/bahlily_transcription/registry.py`
- Create: `services/transcription/tests/test_registry.py`

**Interfaces:**
- Consumes: `ModelInfo`, `ModelStatus`, `DownloadProgress`, all `Transcription*Error` types
- Produces: `ModelRegistry(engine: str, models_dir: Path, manifests_dir: Path)`
  - `list_models() -> list[ModelInfo]`
  - `get_status(name: str) -> ModelStatus`
  - `async download(name: str) -> AsyncIterator[DownloadProgress]`
  - `cancel_download(name: str) -> None`
  - `remove(name: str, engine_instance: TranscriptionEngine | None) -> None`

- [ ] **Step 1: Create manifest YAML files**

Create `src/bahlily_transcription/manifests/whisper.yaml`:

```yaml
engine: whisper
models:
  - name: large-v3-turbo
    # faster-whisper CTranslate2 format — tarball of model directory
    # URL and checksum: compute SHA256 after downloading from HuggingFace
    # Hub repo: Systran/faster-whisper-large-v3-turbo (non-Apple-Silicon)
    # Hub repo: mlx-community/whisper-large-v3-turbo (Apple Silicon)
    download_url: "https://huggingface.co/Systran/faster-whisper-large-v3-turbo/resolve/main/model.bin"
    size_bytes: 1628614656
    # Replace with actual SHA256 of model.bin after first download:
    checksum_sha256: "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD"
    tier: high_accuracy
  - name: medium
    download_url: "https://huggingface.co/Systran/faster-whisper-medium/resolve/main/model.bin"
    size_bytes: 764014080
    checksum_sha256: "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD"
    tier: balanced
  - name: tiny
    download_url: "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin"
    size_bytes: 75968000
    checksum_sha256: "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD"
    tier: fast
```

Create `src/bahlily_transcription/manifests/parakeet.yaml`:

```yaml
engine: parakeet
models:
  - name: parakeet-tdt-1.1b
    download_url: "https://huggingface.co/nvidia/parakeet-tdt-1.1b/resolve/main/parakeet-tdt-1.1b.onnx"
    size_bytes: 4400000000
    checksum_sha256: "REPLACE_WITH_ACTUAL_SHA256_AFTER_DOWNLOAD"
    tier: high_accuracy
```

> **Note for implementer:** The `checksum_sha256` values are placeholders. After
> downloading each model file once, compute its SHA256 with
> `sha256sum <file>` (Linux/macOS) and replace the placeholder value in the YAML.
> The download URLs above are for the primary model binary; verify they are current
> against the HuggingFace repositories before release.

- [ ] **Step 2: Write failing tests**

Create `tests/test_registry.py`:

```python
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import ModelStatus
from bahlily_transcription.registry import ModelRegistry


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models"
    d.mkdir()
    return d


@pytest.fixture
def manifests_dir() -> Path:
    from importlib import resources
    return Path(str(resources.files("bahlily_transcription") / "manifests"))


@pytest.fixture
def registry(models_dir: Path, manifests_dir: Path) -> ModelRegistry:
    return ModelRegistry(engine="whisper", models_dir=models_dir, manifests_dir=manifests_dir)


def test_list_models_returns_all_manifest_entries(registry: ModelRegistry) -> None:
    models = registry.list_models()
    names = {m.name for m in models}
    assert "large-v3-turbo" in names
    assert "tiny" in names


def test_status_missing_when_not_downloaded(registry: ModelRegistry) -> None:
    assert registry.get_status("tiny") == ModelStatus.MISSING


def test_status_available_after_model_dir_created(
    registry: ModelRegistry, models_dir: Path
) -> None:
    model_dir = models_dir / "tiny"
    model_dir.mkdir()
    # Write a sentinel file with a known checksum
    model_file = model_dir / "model.bin"
    content = b"fake model data"
    model_file.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    # Patch the manifest checksum to match
    with patch.object(registry, "_get_model_info") as mock_info:
        mock_info.return_value = MagicMock(checksum_sha256=checksum)
        registry._refresh_status("tiny")
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


def test_model_not_found_raises(registry: ModelRegistry) -> None:
    with pytest.raises(TranscriptionModelNotFoundError):
        registry.get_status("nonexistent-model")


@pytest.mark.asyncio
async def test_download_yields_progress_and_verifies_checksum(
    registry: ModelRegistry, models_dir: Path
) -> None:
    content = b"fake model content " * 100
    expected_checksum = hashlib.sha256(content).hexdigest()

    # Patch the manifest to use our fake URL and checksum
    tiny_info = MagicMock()
    tiny_info.name = "tiny"
    tiny_info.download_url = "https://fake.host/model.bin"
    tiny_info.size_bytes = len(content)
    tiny_info.checksum_sha256 = expected_checksum
    tiny_info.tier = "fast"

    with patch.object(registry, "_get_model_info", return_value=tiny_info), \
         respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        events = []
        async for progress in registry.download("tiny"):
            events.append(progress)

    assert events[-1].status == ModelStatus.AVAILABLE
    assert registry.get_status("tiny") == ModelStatus.AVAILABLE


@pytest.mark.asyncio
async def test_download_sets_corrupted_on_checksum_mismatch(
    registry: ModelRegistry, models_dir: Path
) -> None:
    content = b"corrupted content"
    tiny_info = MagicMock()
    tiny_info.name = "tiny"
    tiny_info.download_url = "https://fake.host/model.bin"
    tiny_info.size_bytes = len(content)
    tiny_info.checksum_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
    tiny_info.tier = "fast"

    with patch.object(registry, "_get_model_info", return_value=tiny_info), \
         respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        with pytest.raises(TranscriptionChecksumFailedError):
            async for _ in registry.download("tiny"):
                pass

    assert registry.get_status("tiny") == ModelStatus.CORRUPTED


@pytest.mark.asyncio
async def test_concurrent_download_rejected(registry: ModelRegistry) -> None:
    content = b"x" * 1000
    info = MagicMock()
    info.name = "tiny"
    info.download_url = "https://fake.host/model.bin"
    info.size_bytes = len(content)
    info.checksum_sha256 = hashlib.sha256(content).hexdigest()

    with patch.object(registry, "_get_model_info", return_value=info), \
         respx.mock:
        respx.get("https://fake.host/model.bin").mock(
            return_value=httpx.Response(200, content=content)
        )
        registry._in_flight.add("tiny")
        with pytest.raises(TranscriptionAlreadyDownloadingError):
            async for _ in registry.download("tiny"):
                pass
        registry._in_flight.discard("tiny")
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
uv run pytest tests/test_registry.py -v
```

- [ ] **Step 4: Create registry.py**

```python
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import AsyncIterator

import httpx
import yaml

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
)
from bahlily_transcription.models import DownloadProgress, ModelInfo, ModelStatus

_CHUNK_SIZE = 8 * 1024  # 8 KB


class ModelRegistry:
    def __init__(self, engine: str, models_dir: Path, manifests_dir: Path) -> None:
        self._engine = engine
        self._models_dir = models_dir / engine
        self._models_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir = manifests_dir
        self._status: dict[str, ModelStatus] = {}
        self._in_flight: set[str] = set()
        self._load_manifest()
        self._scan_existing()

    # --- public API ---

    def list_models(self) -> list[ModelInfo]:
        return list(self._manifest.values())

    def get_status(self, name: str) -> ModelStatus:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        return self._status.get(name, ModelStatus.MISSING)

    async def download(self, name: str) -> AsyncIterator[DownloadProgress]:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        if name in self._in_flight:
            raise TranscriptionAlreadyDownloadingError(name)

        info = self._manifest[name]
        free = shutil.disk_usage(self._models_dir).free
        if free < info.size_bytes:
            raise TranscriptionInsufficientDiskError(info.size_bytes, free)

        self._in_flight.add(name)
        self._status[name] = ModelStatus.DOWNLOADING
        model_dir = self._models_dir / name
        model_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = model_dir / "model.bin.tmp"
        sha256 = hashlib.sha256()
        bytes_downloaded = 0

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", info.download_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                        tmp_path.write_bytes(
                            tmp_path.read_bytes() + chunk if tmp_path.exists() else chunk
                        )
                        sha256.update(chunk)
                        bytes_downloaded += len(chunk)
                        yield DownloadProgress(
                            model_name=name,
                            engine=self._engine,
                            bytes_downloaded=bytes_downloaded,
                            total_bytes=info.size_bytes,
                            status=ModelStatus.DOWNLOADING,
                        )

            if sha256.hexdigest() != info.checksum_sha256:
                tmp_path.unlink(missing_ok=True)
                self._status[name] = ModelStatus.CORRUPTED
                raise TranscriptionChecksumFailedError(name)

            final_path = model_dir / "model.bin"
            tmp_path.rename(final_path)
            self._status[name] = ModelStatus.AVAILABLE
            yield DownloadProgress(
                model_name=name,
                engine=self._engine,
                bytes_downloaded=bytes_downloaded,
                total_bytes=info.size_bytes,
                status=ModelStatus.AVAILABLE,
            )
        except TranscriptionChecksumFailedError:
            raise
        except Exception:
            tmp_path.unlink(missing_ok=True)
            self._status[name] = ModelStatus.ERROR
            raise
        finally:
            self._in_flight.discard(name)

    def cancel_download(self, name: str) -> None:
        self._in_flight.discard(name)
        tmp = self._models_dir / name / "model.bin.tmp"
        tmp.unlink(missing_ok=True)
        self._status[name] = ModelStatus.MISSING

    def remove(self, name: str, loaded_name: str | None = None) -> None:
        if name not in self._manifest:
            raise TranscriptionModelNotFoundError(name)
        model_dir = self._models_dir / name
        if model_dir.exists():
            shutil.rmtree(model_dir)
        self._status[name] = ModelStatus.MISSING

    # --- internal helpers ---

    def _load_manifest(self) -> None:
        manifest_path = self._manifests_dir / f"{self._engine}.yaml"
        with manifest_path.open() as f:
            data = yaml.safe_load(f)
        self._manifest: dict[str, ModelInfo] = {
            m["name"]: ModelInfo(
                name=m["name"],
                engine=self._engine,
                size_bytes=m["size_bytes"],
                checksum_sha256=m["checksum_sha256"],
                download_url=m["download_url"],
                tier=m["tier"],
            )
            for m in data["models"]
        }

    def _scan_existing(self) -> None:
        for name in self._manifest:
            model_path = self._models_dir / name / "model.bin"
            tmp_path = self._models_dir / name / "model.bin.tmp"
            if tmp_path.exists():
                tmp_path.unlink()
                self._status[name] = ModelStatus.MISSING
            elif model_path.exists():
                self._status[name] = ModelStatus.AVAILABLE
            else:
                self._status[name] = ModelStatus.MISSING

    def _refresh_status(self, name: str) -> None:
        model_path = self._models_dir / name / "model.bin"
        if model_path.exists():
            self._status[name] = ModelStatus.AVAILABLE
        else:
            self._status[name] = ModelStatus.MISSING

    def _get_model_info(self, name: str) -> ModelInfo:
        return self._manifest[name]
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/test_registry.py -v
```

- [ ] **Step 6: Commit**

```bash
git add services/transcription/src/bahlily_transcription/manifests/ \
        services/transcription/src/bahlily_transcription/registry.py \
        services/transcription/tests/test_registry.py
git commit -m "feat(transcription): add model registry with async download and checksum verification"
```

---

## Task 7: BroadcastChannel + gRPC server

**Files:**
- Create: `services/transcription/src/bahlily_transcription/grpc_server.py`
- Create: `services/transcription/tests/test_grpc_server.py`

**Interfaces:**
- Consumes: `transcription_pb2.TranscriptSegment`, `transcription_pb2_grpc.TranscriptionServiceServicer`
- Produces:
  - `BroadcastChannel` — `subscribe() -> asyncio.Queue`, `unsubscribe(q)`, `async publish(segment)`
  - `TranscriptionGrpcService(broadcast: BroadcastChannel)` — implements gRPC servicer
  - `async serve(broadcast: BroadcastChannel, port: int) -> None` — starts gRPC server

- [ ] **Step 1: Write failing tests**

Create `tests/test_grpc_server.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.pb.transcription.v1.transcription_pb2 import TranscriptSegment


def _make_segment(segment_id: int, text: str = "hello") -> TranscriptSegment:
    seg = TranscriptSegment()
    seg.segment_id = segment_id
    seg.text = text
    seg.recording_id = "rec-1"
    return seg


@pytest.mark.asyncio
async def test_single_subscriber_receives_published_segment() -> None:
    channel = BroadcastChannel(capacity=10)
    q = channel.subscribe()
    seg = _make_segment(1)
    await channel.publish(seg)
    received = q.get_nowait()
    assert received.segment_id == 1


@pytest.mark.asyncio
async def test_two_subscribers_each_receive_segment() -> None:
    channel = BroadcastChannel(capacity=10)
    q1 = channel.subscribe()
    q2 = channel.subscribe()
    await channel.publish(_make_segment(2))
    assert q1.get_nowait().segment_id == 2
    assert q2.get_nowait().segment_id == 2


@pytest.mark.asyncio
async def test_full_queue_skips_that_subscriber_only() -> None:
    channel = BroadcastChannel(capacity=1)
    q_full = channel.subscribe()
    q_ok = channel.subscribe()
    # Fill q_full
    await channel.publish(_make_segment(1))
    # This publish should skip q_full (full) but reach q_ok
    await channel.publish(_make_segment(2))
    assert q_ok.qsize() == 2
    # q_full only has the first message
    assert q_full.qsize() == 1


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving() -> None:
    channel = BroadcastChannel(capacity=10)
    q = channel.subscribe()
    channel.unsubscribe(q)
    await channel.publish(_make_segment(3))
    assert q.empty()
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_grpc_server.py -v
```

- [ ] **Step 3: Create grpc_server.py**

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import grpc.aio
import structlog

from bahlily_transcription.pb.transcription.v1 import transcription_pb2, transcription_pb2_grpc

_log = structlog.get_logger()

_BROADCAST_CAPACITY = 100


class BroadcastChannel:
    def __init__(self, capacity: int = _BROADCAST_CAPACITY) -> None:
        self._capacity = capacity
        self._subscribers: list[asyncio.Queue[transcription_pb2.TranscriptSegment]] = []

    def subscribe(self) -> asyncio.Queue[transcription_pb2.TranscriptSegment]:
        q: asyncio.Queue[transcription_pb2.TranscriptSegment] = asyncio.Queue(
            maxsize=self._capacity
        )
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[transcription_pb2.TranscriptSegment]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, segment: transcription_pb2.TranscriptSegment) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(segment)
            except asyncio.QueueFull:
                _log.warning(
                    "transcript_broadcast_lagged",
                    code="AUDIO_STREAM_LAGGED",
                    recording_id=segment.recording_id,
                )


class TranscriptionGrpcService(transcription_pb2_grpc.TranscriptionServiceServicer):
    def __init__(self, broadcast: BroadcastChannel) -> None:
        self._broadcast = broadcast

    async def StreamTranscripts(
        self,
        request: transcription_pb2.StreamTranscriptsRequest,
        context: grpc.aio.ServicerContext[
            transcription_pb2.StreamTranscriptsRequest,
            transcription_pb2.StreamTranscriptsResponse,
        ],
    ) -> AsyncIterator[transcription_pb2.StreamTranscriptsResponse]:
        q = self._broadcast.subscribe()
        try:
            while True:
                segment = await q.get()
                yield transcription_pb2.StreamTranscriptsResponse(segment=segment)
        finally:
            self._broadcast.unsubscribe(q)


async def serve(broadcast: BroadcastChannel, port: int) -> None:
    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(
        TranscriptionGrpcService(broadcast), server
    )
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    _log.info("transcription_grpc_server_started", port=port)
    await server.wait_for_termination()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_grpc_server.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/transcription/src/bahlily_transcription/grpc_server.py \
        services/transcription/tests/test_grpc_server.py
git commit -m "feat(transcription): add BroadcastChannel and TranscriptionGrpcService"
```

---

## Task 8: gRPC client (audio-core subscriber)

**Files:**
- Create: `services/transcription/src/bahlily_transcription/grpc_client.py`
- Create: `services/transcription/tests/test_grpc_client.py`

**Interfaces:**
- Consumes: `audio_pb2.AudioSegment`, `audio_pb2_grpc.AudioServiceStub`
- Produces: `AudioCoreClient(addr: str)` with `async stream_segments() -> AsyncIterator[audio_pb2.AudioSegment]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_grpc_client.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import grpc.aio
import pytest

from bahlily_transcription.grpc_client import AudioCoreClient
from bahlily_transcription.pb.audio_core.v1 import audio_pb2, audio_pb2_grpc


def _make_audio_segment(segment_id: int) -> audio_pb2.AudioSegment:
    seg = audio_pb2.AudioSegment()
    seg.segment_id = segment_id
    seg.sample_rate = 16000
    seg.device_type = audio_pb2.DEVICE_TYPE_MICROPHONE
    seg.trace_id = "test-trace"
    return seg


class FakeAudioCoreServicer(audio_pb2_grpc.AudioServiceServicer):
    def __init__(self, segments: list[audio_pb2.AudioSegment]) -> None:
        self._segments = segments

    async def StreamAudio(
        self,
        request: audio_pb2.StreamAudioRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[audio_pb2.StreamAudioResponse]:
        for seg in self._segments:
            yield audio_pb2.StreamAudioResponse(segment=seg)


@pytest.fixture
async def fake_server(unused_tcp_port: int) -> AsyncIterator[str]:
    segments = [_make_audio_segment(i) for i in range(3)]
    server = grpc.aio.server()
    audio_pb2_grpc.add_AudioServiceServicer_to_server(FakeAudioCoreServicer(segments), server)
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()
    yield f"localhost:{unused_tcp_port}"
    await server.stop(grace=0)


@pytest.mark.asyncio
async def test_client_receives_segments_from_server(fake_server: str) -> None:
    client = AudioCoreClient(addr=fake_server)
    received = []
    async for seg in client.stream_segments():
        received.append(seg.segment_id)
        if len(received) == 3:
            break
    assert received == [0, 1, 2]
```

> **Note:** `unused_tcp_port` fixture requires `pytest-asyncio`. Add
> `pytest-asyncio>=0.23` to dev deps if not already present (it is in Task 1).
> For `unused_tcp_port`, use `pytest-asyncio`'s built-in or implement a simple
> fixture in conftest.py:
> ```python
> @pytest.fixture
> def unused_tcp_port() -> int:
>     import socket
>     with socket.socket() as s:
>         s.bind(("", 0))
>         return s.getsockname()[1]
> ```

Add the above `unused_tcp_port` fixture to `tests/conftest.py`.

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_grpc_client.py -v
```

- [ ] **Step 3: Create grpc_client.py**

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import grpc.aio
import structlog

from bahlily_transcription.pb.audio_core.v1 import audio_pb2, audio_pb2_grpc

_log = structlog.get_logger()


class AudioCoreClient:
    def __init__(self, addr: str = "localhost:50051") -> None:
        self._addr = addr

    async def stream_segments(self) -> AsyncIterator[audio_pb2.AudioSegment]:
        backoff = 1.0
        while True:
            try:
                async with grpc.aio.insecure_channel(self._addr) as channel:
                    stub = audio_pb2_grpc.AudioServiceStub(channel)
                    backoff = 1.0
                    async for response in stub.StreamAudio(audio_pb2.StreamAudioRequest()):
                        yield response.segment
            except grpc.aio.AioRpcError as exc:
                _log.warning(
                    "audio_core_connection_lost",
                    addr=self._addr,
                    backoff_s=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(min(backoff, 30.0))
                backoff *= 2
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_grpc_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/transcription/src/bahlily_transcription/grpc_client.py \
        services/transcription/tests/test_grpc_client.py \
        services/transcription/tests/conftest.py
git commit -m "feat(transcription): add AudioCoreClient with exponential backoff reconnect"
```

---

## Task 9: Session worker

**Files:**
- Create: `services/transcription/src/bahlily_transcription/worker.py`
- Create: `services/transcription/tests/test_worker.py`

**Interfaces:**
- Consumes: `TranscriptionEngine`, `BroadcastChannel`, `audio_pb2.AudioSegment`,
  `TranscriptResult`, `TranscriptionAudioTooShortError`, `TranscriptionEngineFailedError`,
  `stamina`
- Produces: `SessionWorker(recording_id, engine, broadcast, executor)` with
  - `async run(audio_stream: AsyncIterator[audio_pb2.AudioSegment]) -> None`
  - `async stop() -> int` — drains queue, returns `segments_transcribed`
  - `segments_received: int`
  - `segments_transcribed: int`

- [ ] **Step 1: Write failing tests**

Create `tests/test_worker.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.pb.audio_core.v1 import audio_pb2
from bahlily_transcription.pb.transcription.v1.transcription_pb2 import TranscriptSegment
from bahlily_transcription.worker import SessionWorker


def _make_audio_segment(segment_id: int, sample_rate: int = 16000) -> audio_pb2.AudioSegment:
    seg = audio_pb2.AudioSegment()
    seg.segment_id = segment_id
    seg.sample_rate = sample_rate
    # 1 second of audio at 16 kHz
    seg.data.extend([0.0] * 16000)
    seg.trace_id = "trace-1"
    return seg


async def _stream_segments(
    segments: list[audio_pb2.AudioSegment],
) -> AsyncIterator[audio_pb2.AudioSegment]:
    for seg in segments:
        yield seg


@pytest.mark.asyncio
async def test_worker_transcribes_segments_in_order(fake_engine) -> None:  # type: ignore[no-untyped-def]
    fake_engine.load_model("test-model")
    broadcast = BroadcastChannel(capacity=50)
    q = broadcast.subscribe()
    executor = ThreadPoolExecutor(max_workers=1)

    worker = SessionWorker(
        recording_id="rec-1",
        engine=fake_engine,
        broadcast=broadcast,
        executor=executor,
        batch_window_s=0.05,  # short window for tests
        max_batch_size=4,
    )

    segments = [_make_audio_segment(i) for i in range(3)]
    task = asyncio.create_task(worker.run(_stream_segments(segments)))
    await asyncio.sleep(0.3)
    await worker.stop()
    await task

    received_ids = []
    while not q.empty():
        seg: TranscriptSegment = q.get_nowait()
        received_ids.append(seg.segment_id)

    assert received_ids == sorted(received_ids)
    assert worker.segments_transcribed == 3


@pytest.mark.asyncio
async def test_worker_resamples_non_16k_audio(fake_engine) -> None:  # type: ignore[no-untyped-def]
    fake_engine.load_model("test-model")
    broadcast = BroadcastChannel(capacity=50)
    q = broadcast.subscribe()
    executor = ThreadPoolExecutor(max_workers=1)

    worker = SessionWorker(
        recording_id="rec-1",
        engine=fake_engine,
        broadcast=broadcast,
        executor=executor,
        batch_window_s=0.05,
        max_batch_size=4,
    )

    seg = _make_audio_segment(0, sample_rate=44100)
    seg.data.extend([0.0] * (44100 - 16000))  # pad to 44100 samples

    task = asyncio.create_task(worker.run(_stream_segments([seg])))
    await asyncio.sleep(0.3)
    await worker.stop()
    await task

    assert not q.empty()
    result = q.get_nowait()
    assert result.segment_id == 0


@pytest.mark.asyncio
async def test_worker_emits_error_segment_after_engine_exhaustion() -> None:
    import stamina

    class AlwaysFailEngine:
        _name = "fake"
        _loaded: str | None = "test"

        @property
        def name(self) -> str:
            return self._name

        def is_model_loaded(self) -> bool:
            return True

        def current_model(self) -> str | None:
            return self._loaded

        def load_model(self, name: str) -> None:
            self._loaded = name

        def unload_model(self) -> None:
            self._loaded = None

        def transcribe(self, audio: np.ndarray, language: str | None) -> None:  # type: ignore[override]
            from bahlily_transcription.errors import TranscriptionEngineFailedError
            raise TranscriptionEngineFailedError("fake", "always fails")

        def transcribe_batch(self, audios: list[np.ndarray], language: str | None) -> list[None]:  # type: ignore[override]
            return [self.transcribe(a, language) for a in audios]

    broadcast = BroadcastChannel(capacity=50)
    q = broadcast.subscribe()
    executor = ThreadPoolExecutor(max_workers=1)
    engine = AlwaysFailEngine()

    worker = SessionWorker(
        recording_id="rec-1",
        engine=engine,  # type: ignore[arg-type]
        broadcast=broadcast,
        executor=executor,
        batch_window_s=0.05,
        max_batch_size=4,
    )

    with stamina.testing.suppress():
        task = asyncio.create_task(worker.run(_stream_segments([_make_audio_segment(0)])))
        await asyncio.sleep(0.3)
        await worker.stop()
        await task

    result = q.get_nowait()
    # Error segment has empty text
    assert result.text == ""
    assert not result.is_partial
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_worker.py -v
```

- [ ] **Step 3: Create worker.py**

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import scipy.signal
import stamina
import structlog

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.errors import TranscriptionEngineFailedError
from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.pb.audio_core.v1 import audio_pb2
from bahlily_transcription.pb.transcription.v1 import transcription_pb2

_log = structlog.get_logger()
_TARGET_SAMPLE_RATE = 16000
_MIN_AUDIO_DURATION_S = 0.5


class SessionWorker:
    def __init__(
        self,
        recording_id: str,
        engine: TranscriptionEngine,
        broadcast: BroadcastChannel,
        executor: ThreadPoolExecutor,
        batch_window_s: float = 0.3,
        max_batch_size: int = 8,
    ) -> None:
        self._recording_id = recording_id
        self._engine = engine
        self._broadcast = broadcast
        self._executor = executor
        self._batch_window_s = batch_window_s
        self._max_batch_size = max_batch_size
        self._queue: asyncio.Queue[audio_pb2.AudioSegment] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self.segments_received = 0
        self.segments_transcribed = 0

    async def run(self, audio_stream: AsyncIterator[audio_pb2.AudioSegment]) -> None:
        ingest_task = asyncio.create_task(self._ingest(audio_stream))
        batch_task = asyncio.create_task(self._batch_loop())
        await asyncio.gather(ingest_task, batch_task, return_exceptions=True)

    async def stop(self) -> int:
        self._stop_event.set()
        return self.segments_transcribed

    async def _ingest(self, stream: AsyncIterator[audio_pb2.AudioSegment]) -> None:
        async for seg in stream:
            self.segments_received += 1
            await self._queue.put(seg)

    async def _batch_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set() or not self._queue.empty():
            batch: list[audio_pb2.AudioSegment] = []
            deadline = loop.time() + self._batch_window_s
            while loop.time() < deadline and len(batch) < self._max_batch_size:
                try:
                    seg = self._queue.get_nowait()
                    batch.append(seg)
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.01)

            if not batch:
                continue

            audios = [self._to_numpy(seg) for seg in batch]
            segment_ids = [seg.segment_id for seg in batch]

            try:
                results = await self._transcribe_with_retry(audios)
            except TranscriptionEngineFailedError:
                results = None

            if results is None:
                for seg_id in segment_ids:
                    await self._emit_error(seg_id)
            else:
                pairs = sorted(zip(segment_ids, results), key=lambda x: x[0])
                for seg_id, result in pairs:
                    seg_proto = self._result_to_proto(seg_id, result, batch)
                    await self._broadcast.publish(seg_proto)
                    self.segments_transcribed += 1

    @stamina.retry(
        on=TranscriptionEngineFailedError,
        attempts=3,
        wait_initial=1.0,
        wait_max=4.0,
    )
    async def _transcribe_with_retry(
        self, audios: list[np.ndarray]
    ) -> list[object]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._engine.transcribe_batch,
            audios,
            None,
        )

    async def _emit_error(self, segment_id: int) -> None:
        _log.warning(
            "transcription_segment_failed",
            code="TRANSCRIPTION_ENGINE_FAILED",
            recording_id=self._recording_id,
            segment_id=segment_id,
        )
        seg = transcription_pb2.TranscriptSegment()
        seg.segment_id = segment_id
        seg.text = ""
        seg.is_partial = False
        seg.recording_id = self._recording_id
        await self._broadcast.publish(seg)

    def _to_numpy(self, seg: audio_pb2.AudioSegment) -> np.ndarray:
        audio = np.array(seg.data, dtype=np.float32)
        if seg.sample_rate != _TARGET_SAMPLE_RATE:
            audio = scipy.signal.resample_poly(
                audio,
                up=_TARGET_SAMPLE_RATE,
                down=seg.sample_rate,
            ).astype(np.float32)
        return audio

    def _result_to_proto(
        self,
        segment_id: int,
        result: object,
        batch: list[audio_pb2.AudioSegment],
    ) -> transcription_pb2.TranscriptSegment:
        from bahlily_transcription.models import TranscriptResult
        r = result  # type: ignore[assignment]
        seg_proto = transcription_pb2.TranscriptSegment()
        seg_proto.segment_id = segment_id
        seg_proto.recording_id = self._recording_id
        seg_proto.is_partial = False
        if isinstance(r, TranscriptResult):
            seg_proto.text = r.text
            seg_proto.audio_start_time = r.audio_start_time
            seg_proto.audio_end_time = r.audio_end_time
            if r.confidence is not None:
                seg_proto.confidence = r.confidence
            if r.language is not None:
                seg_proto.language = r.language
        # Propagate trace_id from the corresponding AudioSegment
        for orig_seg in batch:
            if orig_seg.segment_id == segment_id:
                seg_proto.trace_id = orig_seg.trace_id
                break
        return seg_proto
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_worker.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/transcription/src/bahlily_transcription/worker.py \
        services/transcription/tests/test_worker.py
git commit -m "feat(transcription): add SessionWorker with micro-batching and stamina retry"
```

---

## Task 10: FastAPI HTTP app

**Files:**
- Create: `services/transcription/src/bahlily_transcription/app.py`
- Create: `services/transcription/tests/test_app.py`

**Interfaces:**
- Consumes: `ModelRegistry`, `SessionWorker`, `BroadcastChannel`, `WhisperEngine`,
  `ParakeetEngine`, `ModelStatus`, all `Transcription*Error` types, `sse_starlette`
- Produces: `app: FastAPI` — all endpoints listed in the spec

- [ ] **Step 1: Write failing tests**

Create `tests/test_app.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from bahlily_transcription.app import app
    return TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_models_whisper_returns_entries(client: TestClient) -> None:
    response = client.get("/models/whisper")
    assert response.status_code == 200
    names = {m["name"] for m in response.json()}
    assert "large-v3-turbo" in names


def test_list_models_invalid_engine_returns_404(client: TestClient) -> None:
    response = client.get("/models/nonexistent")
    assert response.status_code == 404


def test_load_model_calls_engine(client: TestClient) -> None:
    with patch("bahlily_transcription.app._whisper_engine") as mock_engine:
        mock_engine.load_model = MagicMock()
        response = client.post("/models/whisper/load", json={"name": "tiny"})
    assert response.status_code == 200


def test_post_session_returns_recording_id(client: TestClient) -> None:
    with patch("bahlily_transcription.app._whisper_engine") as mock_engine, \
         patch("bahlily_transcription.app._start_worker_task"):
        mock_engine.is_model_loaded.return_value = True
        mock_engine.current_model.return_value = "tiny"
        response = client.post("/sessions", json={"engine": "whisper", "language": "fr"})
    assert response.status_code == 200
    assert "recording_id" in response.json()


def test_post_session_auto_selects_parakeet_for_english(client: TestClient) -> None:
    with patch("bahlily_transcription.app._parakeet_engine") as mock_engine, \
         patch("bahlily_transcription.app._start_worker_task"):
        mock_engine.is_model_loaded.return_value = True
        mock_engine.current_model.return_value = "parakeet-tdt-1.1b"
        response = client.post("/sessions", json={"language": "en"})
    assert response.status_code == 200


def test_post_session_no_model_returns_409(client: TestClient) -> None:
    with patch("bahlily_transcription.app._whisper_engine") as mock_engine:
        mock_engine.is_model_loaded.return_value = False
        response = client.post("/sessions", json={"engine": "whisper"})
    assert response.status_code == 409
    assert response.json()["code"] == "TRANSCRIPTION_MODEL_NOT_LOADED"


def test_get_session_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/sessions/nonexistent-id")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_app.py -v
```

- [ ] **Step 3: Create app.py**

```python
from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path
from typing import Literal

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from bahlily_transcription.errors import (
    TranscriptionAlreadyDownloadingError,
    TranscriptionChecksumFailedError,
    TranscriptionEngineFailedError,
    TranscriptionInsufficientDiskError,
    TranscriptionModelNotFoundError,
    TranscriptionModelNotLoadedError,
    TranscriptionUnsupportedLanguageError,
)
from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.models import ModelStatus
from bahlily_transcription.parakeet_engine import ParakeetEngine
from bahlily_transcription.registry import ModelRegistry
from bahlily_transcription.whisper_engine import WhisperEngine
from bahlily_transcription.worker import SessionWorker

_log = structlog.get_logger()

_MODELS_DIR = Path(os.environ.get("BAHLILY_MODELS_DIR", Path.home() / ".bahlily" / "models"))
_MANIFESTS_DIR = Path(str(resources.files("bahlily_transcription") / "manifests"))

_whisper_engine = WhisperEngine(models_dir=_MODELS_DIR / "whisper")
_parakeet_engine = ParakeetEngine(models_dir=_MODELS_DIR / "parakeet")
_whisper_registry = ModelRegistry("whisper", _MODELS_DIR, _MANIFESTS_DIR)
_parakeet_registry = ModelRegistry("parakeet", _MODELS_DIR, _MANIFESTS_DIR)
_broadcast = BroadcastChannel()
_executor = ThreadPoolExecutor(max_workers=4)
_sessions: dict[str, dict[str, object]] = {}

app = FastAPI(title="bahlily-transcription")

_ENGINES = {"whisper": (_whisper_engine, _whisper_registry),
            "parakeet": (_parakeet_engine, _parakeet_registry)}

_ERROR_STATUS: dict[type[Exception], int] = {
    TranscriptionModelNotLoadedError: 409,
    TranscriptionModelNotFoundError: 404,
    TranscriptionAlreadyDownloadingError: 409,
    TranscriptionInsufficientDiskError: 422,
    TranscriptionUnsupportedLanguageError: 422,
}


@app.exception_handler(TranscriptionModelNotLoadedError)
@app.exception_handler(TranscriptionModelNotFoundError)
@app.exception_handler(TranscriptionAlreadyDownloadingError)
@app.exception_handler(TranscriptionInsufficientDiskError)
@app.exception_handler(TranscriptionUnsupportedLanguageError)
async def _error_handler(request: Request, exc: Exception) -> JSONResponse:
    status = _ERROR_STATUS[type(exc)]
    return JSONResponse(status_code=status, content={"code": exc.code, "message": str(exc)})  # type: ignore[attr-defined]


# --- Health ---

@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "engines": {
            "whisper": {
                "loaded": _whisper_engine.is_model_loaded(),
                "model": _whisper_engine.current_model(),
            },
            "parakeet": {
                "loaded": _parakeet_engine.is_model_loaded(),
                "model": _parakeet_engine.current_model(),
            },
        },
    }


# --- Models ---

@app.get("/models/{engine}")
def list_models(engine: str) -> list[dict[str, object]]:
    if engine not in _ENGINES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = _ENGINES[engine]
    models = registry.list_models()
    return [
        {
            "name": m.name,
            "engine": m.engine,
            "tier": m.tier,
            "size_bytes": m.size_bytes,
            "status": registry.get_status(m.name).value,
        }
        for m in models
    ]


@app.get("/models/{engine}/current")
def current_model(engine: str) -> dict[str, str | None]:
    if engine not in _ENGINES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, _ = _ENGINES[engine]
    return {"model": eng.current_model()}


class LoadModelRequest(BaseModel):
    name: str


@app.post("/models/{engine}/load")
def load_model(engine: str, req: LoadModelRequest) -> dict[str, str]:
    if engine not in _ENGINES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, _ = _ENGINES[engine]
    eng.load_model(req.name)
    return {"engine": engine, "model": req.name, "status": "loaded"}


@app.post("/models/{engine}/download/{name}")
async def download_model(engine: str, name: str, request: Request) -> EventSourceResponse:
    if engine not in _ENGINES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = _ENGINES[engine]

    async def _event_generator() -> object:
        async for progress in registry.download(name):
            yield {
                "data": f'{{"model_name":"{progress.model_name}",'
                        f'"bytes_downloaded":{progress.bytes_downloaded},'
                        f'"total_bytes":{progress.total_bytes},'
                        f'"status":"{progress.status.value}"}}',
            }

    return EventSourceResponse(_event_generator(), ping=15)


@app.post("/models/{engine}/download/{name}/cancel")
def cancel_download(engine: str, name: str) -> dict[str, str]:
    if engine not in _ENGINES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    _, registry = _ENGINES[engine]
    registry.cancel_download(name)
    return {"status": "cancelled"}


@app.delete("/models/{engine}/{name}")
def remove_model(engine: str, name: str) -> dict[str, str]:
    if engine not in _ENGINES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown engine '{engine}'")
    eng, registry = _ENGINES[engine]
    loaded = eng.current_model()
    if loaded == name:
        eng.unload_model()
    registry.remove(name)
    return {"status": "removed"}


# --- Sessions ---

class StartSessionRequest(BaseModel):
    engine: str | None = None
    model: str | None = None
    language: str | None = None


def _select_engine(req: StartSessionRequest) -> tuple[WhisperEngine | ParakeetEngine, str]:
    if req.engine == "whisper" or (req.language and req.language != "en"):
        eng = _whisper_engine
        name = "whisper"
    else:
        eng = _parakeet_engine
        name = "parakeet"
    if not eng.is_model_loaded():
        raise TranscriptionModelNotLoadedError(name)
    return eng, name


def _start_worker_task(
    recording_id: str,
    engine: WhisperEngine | ParakeetEngine,
    language: str | None,
) -> None:
    from bahlily_transcription.grpc_client import AudioCoreClient
    client = AudioCoreClient(
        addr=os.environ.get("AUDIO_CORE_GRPC_ADDR", "localhost:50051")
    )
    worker = SessionWorker(
        recording_id=recording_id,
        engine=engine,  # type: ignore[arg-type]
        broadcast=_broadcast,
        executor=_executor,
    )
    _sessions[recording_id] = {"status": "started", "worker": worker}

    async def _run() -> None:
        await worker.run(client.stream_segments())

    asyncio.create_task(_run())


@app.post("/sessions")
async def start_session(req: StartSessionRequest) -> dict[str, str]:
    engine, _ = _select_engine(req)
    recording_id = str(uuid.uuid4())
    _start_worker_task(recording_id, engine, req.language)
    return {"recording_id": recording_id, "status": "started"}


@app.post("/sessions/{recording_id}/stop")
async def stop_session(recording_id: str) -> dict[str, object]:
    if recording_id not in _sessions:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="session not found")
    session = _sessions[recording_id]
    worker: SessionWorker = session["worker"]  # type: ignore[assignment]
    session["status"] = "stopping"
    transcribed = await worker.stop()
    session["status"] = "stopped"
    return {"recording_id": recording_id, "status": "stopped", "segments_transcribed": transcribed}


@app.get("/sessions/{recording_id}")
def get_session(recording_id: str) -> dict[str, object]:
    if recording_id not in _sessions:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="session not found")
    session = _sessions[recording_id]
    return {"recording_id": recording_id, "status": session["status"]}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_app.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/transcription/src/bahlily_transcription/app.py \
        services/transcription/tests/test_app.py
git commit -m "feat(transcription): add FastAPI app with model management and session endpoints"
```

---

## Task 11: Service wiring + smoke test

**Files:**
- Modify: `services/transcription/src/bahlily_transcription/__init__.py`
- Modify: `services/transcription/tests/test_smoke.py`

**Interfaces:**
- Consumes: `app` from `app.py`, `serve` from `grpc_server.py`, `BroadcastChannel`
- Produces: `main()` — starts both FastAPI (uvicorn) and gRPC server concurrently

- [ ] **Step 1: Write failing test**

Replace `tests/test_smoke.py`:

```python
from __future__ import annotations

from unittest.mock import patch, MagicMock

from bahlily_transcription import main
from bahlily_transcription.app import app


def test_app_has_correct_title() -> None:
    assert app.title == "bahlily-transcription"


def test_main_starts_uvicorn_with_expected_args() -> None:
    with patch("bahlily_transcription.uvicorn") as mock_uvicorn, \
         patch("bahlily_transcription.asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock()
        main()
    # uvicorn.run is called or asyncio.run is called with the startup coroutine
    assert mock_asyncio.run.called or mock_uvicorn.run.called
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
uv run pytest tests/test_smoke.py -v
```

- [ ] **Step 3: Update __init__.py**

```python
from __future__ import annotations

import asyncio
import os

import uvicorn


def main() -> None:
    grpc_port = int(os.environ.get("TRANSCRIPTION_GRPC_PORT", "50052"))
    http_port = int(os.environ.get("TRANSCRIPTION_HTTP_PORT", "8002"))

    async def _serve_all() -> None:
        from bahlily_transcription.app import app, _broadcast
        from bahlily_transcription.grpc_server import serve as grpc_serve

        config = uvicorn.Config(app, host="0.0.0.0", port=http_port, log_level="info")
        server = uvicorn.Server(config)

        await asyncio.gather(
            server.serve(),
            grpc_serve(_broadcast, grpc_port),
        )

    asyncio.run(_serve_all())
```

- [ ] **Step 4: Run all tests — expect PASS**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Run mypy**

```bash
uv run mypy .
```

Expected: `Success: no issues found`

- [ ] **Step 6: Run ruff**

```bash
uv run ruff format . && uv run ruff check .
```

- [ ] **Step 7: Commit**

```bash
git add services/transcription/src/bahlily_transcription/__init__.py \
        services/transcription/tests/test_smoke.py
git commit -m "feat(transcription): wire uvicorn and gRPC server into main() entrypoint"
```

- [ ] **Step 8: Open PR**

```bash
git push origin feat/transcription-service
gh pr create \
  --base main \
  --title "feat: implement transcription service" \
  --body "Phase 2 of the roadmap. Whisper + Parakeet transcription service with gRPC in/out, model registry, SSE download progress, and session management."
```
