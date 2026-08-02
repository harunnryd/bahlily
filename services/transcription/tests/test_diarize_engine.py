from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from bahlily_transcription.diarize_engine import (
    DiarizationResult,
    DiarizationTurn,
    DiarizeEngine,
    _select_device,
)
from bahlily_transcription.errors import TranscriptionDiarizationUnavailableError

pytest.importorskip("pyannote.audio")


def _fake_annotation(turns: list[tuple[MagicMock, str]]) -> MagicMock:
    ann = MagicMock()
    ann.itertracks.return_value = [(seg, "_", label) for seg, label in turns]
    ann.labels.return_value = sorted({label for _, label in turns})
    return ann


def test_run_converts_pipeline_output_into_turns_and_embeddings() -> None:
    seg_1 = MagicMock(start=0.0, end=1.5)
    seg_2 = MagicMock(start=1.5, end=3.0)
    annotation = _fake_annotation([(seg_1, "SPEAKER_00"), (seg_2, "SPEAKER_01")])
    output = MagicMock(speaker_diarization=annotation, speaker_embeddings=[[0.1, 0.2], [0.3, 0.4]])
    mock_pipeline = MagicMock(return_value=output)

    with (
        patch("bahlily_transcription.diarize_engine.Pipeline") as mock_pipeline_cls,
        patch.dict(os.environ, {"BAHLILY_TRANSCRIPTION_HF_TOKEN": "test-token"}),
    ):
        mock_pipeline_cls.from_pretrained.return_value = mock_pipeline
        engine = DiarizeEngine()
        result = engine.run("recording.flac")

    assert result == DiarizationResult(
        turns=[
            DiarizationTurn(start=0.0, end=1.5, speaker_label="SPEAKER_00"),
            DiarizationTurn(start=1.5, end=3.0, speaker_label="SPEAKER_01"),
        ],
        speakers={"SPEAKER_00": [0.1, 0.2], "SPEAKER_01": [0.3, 0.4]},
    )


def test_load_raises_when_hf_token_is_missing() -> None:
    with patch.dict(os.environ, {}, clear=True):
        engine = DiarizeEngine()
        with pytest.raises(TranscriptionDiarizationUnavailableError):
            engine.load()


def test_load_raises_when_pipeline_dependency_is_missing() -> None:
    with (
        patch("bahlily_transcription.diarize_engine.Pipeline", None),
        patch.dict(os.environ, {"BAHLILY_TRANSCRIPTION_HF_TOKEN": "test-token"}),
    ):
        engine = DiarizeEngine()
        with pytest.raises(TranscriptionDiarizationUnavailableError):
            engine.load()


def test_concurrent_run_calls_load_the_pipeline_only_once() -> None:
    seg = MagicMock(start=0.0, end=1.0)
    annotation = _fake_annotation([(seg, "SPEAKER_00")])
    output = MagicMock(speaker_diarization=annotation, speaker_embeddings=None)
    mock_pipeline = MagicMock(return_value=output)

    def _slow_from_pretrained(*args: object, **kwargs: object) -> MagicMock:
        # An artificial delay makes the race window between the two threads'
        # unlocked `self._pipeline is None` checks realistic -- without the
        # lock in `run()`, both would observe `None` and both call this.
        time.sleep(0.05)
        return mock_pipeline

    with (
        patch("bahlily_transcription.diarize_engine.Pipeline") as mock_pipeline_cls,
        patch.dict(os.environ, {"BAHLILY_TRANSCRIPTION_HF_TOKEN": "test-token"}),
    ):
        mock_pipeline_cls.from_pretrained.side_effect = _slow_from_pretrained
        engine = DiarizeEngine()

        results: list[DiarizationResult] = []
        errors: list[BaseException] = []

        def _run() -> None:
            try:
                results.append(engine.run("recording.flac"))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

    assert not errors
    assert len(results) == 2
    assert mock_pipeline_cls.from_pretrained.call_count == 1


def test_select_device_prefers_cuda_then_mps_then_cpu() -> None:
    with patch("bahlily_transcription.diarize_engine.torch.cuda.is_available", return_value=True):
        assert str(_select_device()) == "cuda"
    with (
        patch("bahlily_transcription.diarize_engine.torch.cuda.is_available", return_value=False),
        patch(
            "bahlily_transcription.diarize_engine.torch.backends.mps.is_available",
            return_value=True,
        ),
    ):
        assert str(_select_device()) == "mps"
    with (
        patch("bahlily_transcription.diarize_engine.torch.cuda.is_available", return_value=False),
        patch(
            "bahlily_transcription.diarize_engine.torch.backends.mps.is_available",
            return_value=False,
        ),
    ):
        assert str(_select_device()) == "cpu"
