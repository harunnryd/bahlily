from typing import Any, ClassVar

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeToolCallingModel(GenericFakeChatModel):
    _llm_type: ClassVar[str] = "anthropic-chat"
    _last_result: BaseMessage | None = None

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            result = super()._generate(messages, stop, run_manager, **kwargs)
            self._last_result = result.generations[0].message
            return result
        except StopIteration:
            if self._last_result is not None:
                return ChatResult(generations=[ChatGeneration(message=self._last_result)])
            raise


def tool_call_message(tool_name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name=tool_name, args=args, id=f"call-{tool_name}")],
    )
