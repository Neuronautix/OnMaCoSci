from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Abstract base for all pipeline agents in both tools."""

    @property
    @abstractmethod
    def agent_name(self) -> str: ...

    def log_step(self, message: str) -> None:
        import logging
        logging.getLogger(self.__class__.__module__).info("[%s] %s", self.agent_name, message)
