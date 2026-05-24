from __future__ import annotations
from mapping_co_scientist.shared.llm.provider_interface import LLMProviderInterface, LLMMessage, LLMResponse


class MockLLMProvider(LLMProviderInterface):
    """Deterministic mock for testing without an API key."""

    def __init__(self, default_response: str = "MOCK: No specific response configured."):
        self._default = default_response
        self._rules: list[tuple[str, str]] = []

    def add_rule(self, keyword: str, response: str) -> None:
        self._rules.append((keyword, response))

    def complete(self, messages: list[LLMMessage], system: str = "", max_tokens: int = 1024) -> LLMResponse:
        combined = " ".join(m.content for m in messages) + " " + system
        for keyword, response in self._rules:
            if keyword.lower() in combined.lower():
                return LLMResponse(content=response, model="mock", input_tokens=0, output_tokens=0)
        return LLMResponse(content=self._default, model="mock", input_tokens=0, output_tokens=0)

    @property
    def model_name(self) -> str:
        return "mock"
