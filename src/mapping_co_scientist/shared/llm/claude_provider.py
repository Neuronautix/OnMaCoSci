from __future__ import annotations
import os

from mapping_co_scientist.shared.llm.provider_interface import (
    LLMProviderInterface,
    LLMMessage,
    LLMResponse,
)
from mapping_co_scientist.shared.llm.cost_tracker import CostTracker


class ClaudeProvider(LLMProviderInterface):
    """LLM provider backed by the Anthropic Claude API."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        try:
            import anthropic as _anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required to use ClaudeProvider. "
                "Install it with: pip install anthropic"
            ) from exc

        self._anthropic = _anthropic
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = _anthropic.Anthropic(api_key=resolved_key)
        self._model = model or self.DEFAULT_MODEL
        self._cost_tracker = cost_tracker

    @property
    def model_name(self) -> str:
        return self._model

    def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Call the Anthropic messages API and return an LLMResponse."""
        anthropic_messages = [
            {"role": m.role, "content": m.content} for m in messages
        ]

        try:
            response = self._client.messages.create(
                model=self._model,
                messages=anthropic_messages,
                system=system or self._anthropic.NOT_GIVEN,
                max_tokens=max_tokens,
            )
        except self._anthropic.APIError as exc:
            raise RuntimeError(str(exc)) from exc

        content_text = ""
        if response.content:
            first_block = response.content[0]
            # ContentBlock has a .text attribute for text blocks
            content_text = getattr(first_block, "text", str(first_block))

        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0

        if self._cost_tracker is not None:
            self._cost_tracker.record(
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                description="ClaudeProvider.complete",
            )

        return LLMResponse(
            content=content_text,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
