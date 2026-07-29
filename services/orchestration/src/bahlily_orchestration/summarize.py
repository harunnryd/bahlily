from __future__ import annotations

import time

import structlog
from langchain.agents import create_agent
from langchain.agents.middleware import PIIMiddleware, SummarizationMiddleware
from langchain.chat_models import init_chat_model
from langgraph.errors import GraphRecursionError
from opentelemetry import trace

from bahlily_orchestration.errors import (
    StructuredOutputValidationFailedError,
    UnsupportedProviderError,
    classify_provider_exception,
)
from bahlily_orchestration.models import StructuredSummary, SummarizeRequest, SummarizeResponse
from bahlily_orchestration.prompt import build_prompt

_RECURSION_LIMIT = 8
_SUMMARIZATION_TOKEN_TRIGGER = 4000

_tracer = trace.get_tracer("bahlily.orchestration")


def summarize(request: SummarizeRequest) -> SummarizeResponse:
    with _tracer.start_as_current_span("orchestration.summarize") as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        logger = structlog.get_logger()

        logger.info(
            "summarize.started",
            provider=request.provider,
            model=request.model,
            template_name=request.template.name,
            template_version=request.template.version,
            segment_count=len(request.segments),
        )

        start = time.monotonic()
        try:
            model = init_chat_model(f"{request.provider}:{request.model}")
        except Exception as exc:
            raise UnsupportedProviderError(
                f"unsupported provider/model: {request.provider}:{request.model}"
            ) from exc

        agent = create_agent(
            model=model,
            response_format=StructuredSummary,
            middleware=[
                PIIMiddleware("email", strategy="redact", apply_to_input=True),
                PIIMiddleware(
                    "phone_number",
                    strategy="redact",
                    apply_to_input=True,
                    detector=r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                ),
                SummarizationMiddleware(
                    model=model, trigger={"tokens": _SUMMARIZATION_TOKEN_TRIGGER}
                ),
            ],
        )

        messages = build_prompt(request.segments, request.template)

        try:
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": _RECURSION_LIMIT},  # type: ignore[call-overload]
            )
        except GraphRecursionError as exc:
            logger.warning(
                "summarize.failed",
                code="ORCHESTRATION_STRUCTURED_OUTPUT_FAILED",
                provider=request.provider,
                model=request.model,
                error=str(exc),
            )
            raise StructuredOutputValidationFailedError(str(exc)) from exc
        except Exception as exc:
            classified = classify_provider_exception(exc)
            logger.warning(
                "summarize.failed",
                code=classified.code,
                provider=request.provider,
                model=request.model,
                error=str(exc),
            )
            raise classified from exc

        attempts = sum(1 for message in result["messages"] if type(message).__name__ == "AIMessage")
        duration_ms = (time.monotonic() - start) * 1000

        logger.info(
            "summarize.completed",
            provider=request.provider,
            model=request.model,
            attempts=attempts,
            duration_ms=duration_ms,
        )

        return SummarizeResponse(
            summary=result["structured_response"],
            attempts=attempts,
            provider=request.provider,
            model=request.model,
        )
