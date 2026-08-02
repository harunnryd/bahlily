from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from bahlily_transcription.diarize_engine import (
    DiarizationResult,
    DiarizationTurn,
    DiarizeEngine,
    _select_device,
)
from bahlily_transcription.errors import TranscriptionDiarizationUnavailableError


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
