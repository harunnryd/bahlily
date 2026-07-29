from collections.abc import Iterator
from typing import Any, ClassVar, cast

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.tool import ToolCall


class FakeToolCallingModel(GenericFakeChatModel):
    _llm_type: ClassVar[str] = "anthropic-chat"
    _last_response: BaseMessage | None = None

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            result = super()._generate(messages, stop, run_manager, **kwargs)
            self._last_response = result.generations[0].message
            return result
        except StopIteration:
            if self._last_response is not None:
                return self._generate(messages, stop, run_manager, **kwargs)
            raise


@pytest.fixture
def make_fake_model() -> Any:
    def _make(responses: list[BaseMessage]) -> FakeToolCallingModel:
        return FakeToolCallingModel(messages=cast(Iterator[AIMessage], iter(responses)))

    return _make


def tool_call_message(tool_name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name=tool_name, args=args, id=f"call-{tool_name}")],
    )
