from __future__ import annotations

from bahlily_transcription.diarize_engine import DiarizationTurn
from bahlily_transcription.merge import assign_speakers
from bahlily_transcription.models import TranscriptSegmentSchema


def _segment(segment_id: int, start: float, end: float) -> TranscriptSegmentSchema:
    return TranscriptSegmentSchema(
        text="text",
        segment_id=segment_id,
        is_partial=False,
        engine="whisper",
        model_name="tiny",
        audio_start_time=start,
        audio_end_time=end,
        recording_id="m1",
        trace_id="t1",
    )


def test_segment_fully_inside_one_turn_gets_that_turns_label() -> None:
    segments = [_segment(0, 1.0, 2.0)]
    turns = [DiarizationTurn(start=0.0, end=5.0, speaker_label="Speaker 1")]

    result = assign_speakers(segments, turns)

    assert result[0].speaker_cluster_label == "Speaker 1"


def test_segment_spanning_a_speaker_change_gets_the_larger_overlap_label() -> None:
    segments = [_segment(0, 0.0, 4.0)]
    turns = [
        DiarizationTurn(start=0.0, end=1.0, speaker_label="Speaker 1"),
        DiarizationTurn(start=1.0, end=4.0, speaker_label="Speaker 2"),
    ]

    result = assign_speakers(segments, turns)

    assert result[0].speaker_cluster_label == "Speaker 2"


def test_segment_with_no_diarization_coverage_keeps_label_none() -> None:
    segments = [_segment(0, 10.0, 11.0)]
    turns = [DiarizationTurn(start=0.0, end=1.0, speaker_label="Speaker 1")]

    result = assign_speakers(segments, turns)

    assert result[0].speaker_cluster_label is None


def test_assign_speakers_does_not_mutate_the_input_segments() -> None:
    segments = [_segment(0, 1.0, 2.0)]
    turns = [DiarizationTurn(start=0.0, end=5.0, speaker_label="Speaker 1")]

    assign_speakers(segments, turns)

    assert segments[0].speaker_cluster_label is None
