from __future__ import annotations
from dataclasses import dataclass, field
import hashlib


@dataclass
class PromptTemplate:
    name: str
    version: str
    template: str
    variables: list[str] = field(default_factory=list)

    def render(self, **kwargs: str) -> str:
        result = self.template
        for k, v in kwargs.items():
            result = result.replace(f"{{{k}}}", v)
        return result

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.template.encode()).hexdigest()[:8]


TEMPLATE_REGISTRY: dict[str, PromptTemplate] = {}


def register_template(template: PromptTemplate) -> None:
    TEMPLATE_REGISTRY[template.name] = template
