from __future__ import annotations

from dataclasses import dataclass

from bahlily_orchestration.models import TranscriptSegment


@dataclass(frozen=True)
class GoldenTranscript:
    name: str
    segments: list[TranscriptSegment]
    expected_key_points: list[str]


GOLDEN_TRANSCRIPTS: list[GoldenTranscript] = [
    GoldenTranscript(
        name="standup-ship-friday",
        segments=[
            TranscriptSegment(
                text="Let's make sure we ship the report by Friday.",
                segment_id=0,
                speaker="Alice",
            ),
            TranscriptSegment(
                text="Agreed, I'll draft it and send it to you by Thursday for review.",
                segment_id=1,
                speaker="Bob",
            ),
            TranscriptSegment(
                text="Sounds good. Let's also sync on the Q3 roadmap next week.",
                segment_id=2,
                speaker="Alice",
            ),
        ],
        expected_key_points=[
            "report ships Friday",
            "Bob drafts by Thursday",
            "Q3 roadmap sync next week",
        ],
    ),
    GoldenTranscript(
        name="sales-call-pricing-objection",
        segments=[
            TranscriptSegment(
                text="Our main concern is the price point compared to your competitor.",
                segment_id=0,
                speaker="Prospect",
            ),
            TranscriptSegment(
                text="I understand. We can offer a discounted annual plan if you commit today.",
                segment_id=1,
                speaker="Sales Rep",
            ),
            TranscriptSegment(
                text="Let me discuss internally and get back to you by end of week.",
                segment_id=2,
                speaker="Prospect",
            ),
        ],
        expected_key_points=[
            "price objection raised",
            "discounted annual plan offered",
            "prospect follows up by end of week",
        ],
    ),
]
