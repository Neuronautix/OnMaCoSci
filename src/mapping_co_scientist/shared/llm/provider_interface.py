from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProviderInterface(ABC):
    @abstractmethod
    def complete(self, messages: list[LLMMessage], system: str = "", max_tokens: int = 1024) -> LLMResponse: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
