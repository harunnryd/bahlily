from __future__ import annotations

import pytest
from deepeval import assert_test  # type: ignore[attr-defined]
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from bahlily_orchestration.models import SummarizeRequest
from bahlily_orchestration.summarize import summarize
from bahlily_orchestration.template_loader import load_template

from .golden_transcripts import GOLDEN_TRANSCRIPTS, GoldenTranscript
from .judge_model import LangChainJudgeModel


@pytest.fixture(scope="module")
def correctness_metric() -> GEval:
    return GEval(
        name="Correctness",
        criteria=(
            "Determine if the summary covers all expected key points listed in the expected output "
            "and reflects only facts present in the transcript, without inventing names, dates, or "
            "decisions. Penalize summaries that omit key points from the expected output."
        ),
        evaluation_steps=[
            "Check that every key point in the expected output appears in the actual summary.",
            "Penalize any key points from the expected output that are missing from the summary.",
            "Verify every claim in the summary is grounded in a fact present in the transcript.",
            "Penalize any names, dates, or decisions in the summary not present in the transcript.",
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        threshold=0.7,
        model=LangChainJudgeModel(),
    )


@pytest.mark.parametrize("golden", GOLDEN_TRANSCRIPTS, ids=lambda g: g.name)
def test_summary_covers_expected_key_points(
    golden: GoldenTranscript, correctness_metric: GEval
) -> None:
    request = SummarizeRequest(
        segments=golden.segments,
        template=load_template("general"),
        provider="ollama",
        model="qwen2.5:7b",
    )
    response = summarize(request)

    transcript_text = "\n".join(f"[{s.speaker}] {s.text}" for s in golden.segments)
    test_case = LLMTestCase(
        input=transcript_text,
        actual_output=f"{response.summary.overview}\n" + "\n".join(response.summary.key_points),
        expected_output="\n".join(golden.expected_key_points),
    )
    assert_test(test_case, [correctness_metric])
