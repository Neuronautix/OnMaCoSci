from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json


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


def ontology_candidate_scoring_prompt(
    source_label: str,
    source_type: str,
    source_description: str,
    candidates: list[dict],
) -> str:
    """Return a prompt asking the LLM to semantically score ontology mapping candidates.

    Each candidate dict should contain:
        term_id, label, definition, relation, lexical_score

    Response format: JSON array:
        [{"term_id": ..., "semantic_score": float, "relation": str, "rationale": str}]
    """
    candidates_json = json.dumps(candidates, indent=2)
    return (
        "You are an expert ontology mapping assistant. Your task is to evaluate candidate "
        "ontology term mappings for a source field and assign a semantic similarity score.\n\n"
        f"Source field:\n"
        f"  label: {source_label}\n"
        f"  type: {source_type}\n"
        f"  description: {source_description or '(none provided)'}\n\n"
        "Candidate ontology terms to score:\n"
        f"{candidates_json}\n\n"
        "For each candidate, evaluate how well the source field semantically matches the "
        "ontology term. Consider:\n"
        "  - Conceptual overlap (not just lexical similarity)\n"
        "  - Whether the proposed SKOS relation is appropriate\n"
        "  - Domain and scope compatibility\n\n"
        "IMPORTANT constraints on SKOS relations:\n"
        "  - Use skos:exactMatch ONLY if the concepts are definitionally equivalent (not just "
        "    lexically similar). This is rare and requires strong justification.\n"
        "  - Use skos:closeMatch for high conceptual overlap with minor scope differences.\n"
        "  - Use skos:broadMatch if the target is a broader/supertype concept.\n"
        "  - Use skos:narrowMatch if the target is a narrower/subtype concept.\n"
        "  - Use skos:relatedMatch for related but not hierarchically linked concepts.\n\n"
        "Return ONLY a JSON array (no prose, no markdown fences) with one object per candidate:\n"
        '[\n'
        '  {\n'
        '    "term_id": "<term_id from input>",\n'
        '    "semantic_score": <float 0.0-1.0>,\n'
        '    "relation": "<skos:exactMatch|skos:closeMatch|skos:broadMatch|skos:narrowMatch|skos:relatedMatch>",\n'
        '    "rationale": "<brief explanation>"\n'
        '  }\n'
        ']'
    )


def schema_field_scoring_prompt(
    source_path: str,
    source_datatype: str,
    source_description: str,
    candidates: list[dict],
) -> str:
    """Return a prompt asking the LLM to semantically score schema field mapping candidates.

    Each candidate dict should contain:
        target_path, target_datatype, operation, lexical_score

    Response format: JSON array:
        [{"target_path": ..., "semantic_score": float, "operation": str,
          "rationale": str, "valid": bool}]
    """
    candidates_json = json.dumps(candidates, indent=2)
    return (
        "You are an expert schema mapping assistant. Your task is to evaluate candidate "
        "field mappings between a source field and target schema fields.\n\n"
        f"Source field:\n"
        f"  path: {source_path}\n"
        f"  datatype: {source_datatype or '(unknown)'}\n"
        f"  description: {source_description or '(none provided)'}\n\n"
        "Candidate target fields to score:\n"
        f"{candidates_json}\n\n"
        "For each candidate, evaluate how well the source field maps to the target field. "
        "Consider:\n"
        "  - Semantic meaning (not just name similarity)\n"
        "  - Datatype compatibility\n"
        "  - Whether the proposed MappingOperation is appropriate\n\n"
        "Valid MappingOperation values:\n"
        "  direct_copy, rename, nested_path, constant_assignment, datatype_conversion,\n"
        "  unit_conversion, enumeration_remapping, concatenation, split, conditional,\n"
        "  lookup, unmapped, human_review_required\n\n"
        "Return ONLY a JSON array (no prose, no markdown fences) with one object per candidate:\n"
        '[\n'
        '  {\n'
        '    "target_path": "<target_path from input>",\n'
        '    "semantic_score": <float 0.0-1.0>,\n'
        '    "operation": "<MappingOperation value>",\n'
        '    "rationale": "<brief explanation>",\n'
        '    "valid": <true if the operation is appropriate, false if it should be flagged>\n'
        '  }\n'
        ']'
    )
