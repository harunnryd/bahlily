from __future__ import annotations

from bahlily_transcription.diarize_engine import DiarizationTurn
from bahlily_transcription.models import TranscriptSegmentSchema


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speakers(
    segments: list[TranscriptSegmentSchema], turns: list[DiarizationTurn]
) -> list[TranscriptSegmentSchema]:
    labeled: list[TranscriptSegmentSchema] = []
    for segment in segments:
        best_label: str | None = None
        best_overlap = 0.0
        for turn in turns:
            overlap = _overlap(
                segment.audio_start_time, segment.audio_end_time, turn.start, turn.end
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = turn.speaker_label
        labeled.append(segment.model_copy(update={"speaker_cluster_label": best_label}))
    return labeled
