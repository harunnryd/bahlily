from __future__ import annotations

import os

from deepeval.models.base_model import DeepEvalBaseLLM
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

_DEFAULT_JUDGE_MODEL = "ollama:qwen2.5:7b"


class LangChainJudgeModel(DeepEvalBaseLLM):  # type: ignore[misc, no-untyped-call]
    def __init__(self, provider_model: str | None = None) -> None:
        self._provider_model = provider_model or os.environ.get(
            "BAHLILY_EVAL_JUDGE_MODEL", _DEFAULT_JUDGE_MODEL
        )
        super().__init__(model=self._provider_model)

    def load_model(self, *args: object, **kwargs: object) -> BaseChatModel:  # type: ignore[override]
        return init_chat_model(self._provider_model)

    def generate(self, prompt: str, *args: object, **kwargs: object) -> str:
        model: BaseChatModel = self.model  # type: ignore[assignment]
        return str(model.invoke(prompt).content)

    async def a_generate(self, prompt: str, *args: object, **kwargs: object) -> str:
        model: BaseChatModel = self.model  # type: ignore[assignment]
        result = await model.ainvoke(prompt)
        return str(result.content)

    def get_model_name(self, *args: object, **kwargs: object) -> str:
        return self._provider_model
