"""
Demonstrates the LLM adversarial reviewer.
Runs on the PK study example. If ANTHROPIC_API_KEY is set, uses Claude.
Otherwise shows heuristic fallback with a clear message.

Usage:
    python scripts/demo_llm_reviewer.py
    ANTHROPIC_API_KEY=sk-... python scripts/demo_llm_reviewer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from any directory without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.agents.llm_adversarial_reviewer import (
    LLMAdversarialReviewerAgent,
)
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
)


def _make_hypothesis(
    mapping_id: str,
    source_label: str,
    source_id: str,
    source_desc: str | None,
    source_datatype: str,
    source_examples: list[str],
    target_id: str,
    target_label: str,
    target_def: str | None,
    predicate: MappingPredicate,
    confidence: float,
) -> MappingHypothesis:
    """Helper to build a sample MappingHypothesis inline."""
    source = SourceEntity(
        entity_id=source_id,
        label=source_label,
        description=source_desc,
        datatype=source_datatype,
        examples=source_examples,
        source_file="examples/source_csv/pk_study_metadata.csv",
        source_type="csv",
    )
    target = OntologyTerm(
        term_id=target_id,
        label=target_label,
        definition=target_def,
        synonyms=[],
        term_type="class",
        ontology_id="CHEBI",
    )
    provenance = Provenance(
        created_by="demo_script",
        created_at="2026-05-21T00:00:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id="demo-run-001",
    )
    evidence = [
        Evidence(
            evidence_type="lexical_similarity",
            description=f"Label similarity between '{source_label}' and '{target_label}'",
            score=confidence,
            source="LexicalScoringAgent",
        )
    ]
    return MappingHypothesis(
        mapping_id=mapping_id,
        source_entity=source,
        target_entity=target,
        predicate=predicate,
        confidence=confidence,
        evidence=evidence,
        provenance=provenance,
    )


def build_sample_hypotheses() -> list[MappingHypothesis]:
    """Build three representative PK-study mapping hypotheses for the demo."""
    return [
        # 1. Straightforward exact match: dose in mg/kg — high confidence
        _make_hypothesis(
            mapping_id="demo-map-001",
            source_label="dose_mg_kg",
            source_id="csv:pk.dose_mg_kg",
            source_desc="Dose administered to the animal in mg per kg body weight",
            source_datatype="number",
            source_examples=["10", "30", "100"],
            target_id="CHEBI:23888",
            target_label="drug dose",
            target_def=(
                "The quantity of a drug or other substance given to an organism "
                "at one time or in specified intervals."
            ),
            predicate=MappingPredicate.EXACT_MATCH,
            confidence=0.91,
        ),
        # 2. Close match with moderate confidence: species field
        _make_hypothesis(
            mapping_id="demo-map-002",
            source_label="species",
            source_id="csv:pk.species",
            source_desc="Species of the experimental animal",
            source_datatype="string",
            source_examples=["Mus musculus", "Rattus norvegicus"],
            target_id="NCBITAXON:10090",
            target_label="Mus musculus",
            target_def="The house mouse, commonly used as a model organism in research.",
            predicate=MappingPredicate.CLOSE_MATCH,
            confidence=0.67,
        ),
        # 3. Weak exact match: short label, low confidence — adversarial reviewer
        # should flag both the exactMatch claim and the weak similarity
        _make_hypothesis(
            mapping_id="demo-map-003",
            source_label="AUC",
            source_id="csv:pk.AUC",
            source_desc=None,  # no description — reviewer should flag missing examples
            source_datatype="number",
            source_examples=[],  # no examples
            target_id="PATO:0001421",
            target_label="area",
            target_def=None,  # no definition — reviewer should flag this too
            predicate=MappingPredicate.EXACT_MATCH,
            confidence=0.42,
        ),
    ]


def main() -> None:
    """Run the demo."""
    print()
    print("=" * 65)
    print("  LLM Adversarial Reviewer — Demo")
    print("=" * 65)

    # Instantiate the reviewer (auto-detects API key)
    reviewer = LLMAdversarialReviewerAgent.from_env()

    mode = "LLM (Claude)" if reviewer.llm_client is not None else "Heuristic fallback"
    print(f"  Mode: {mode}")
    if reviewer.llm_client is not None:
        print(f"  Model: {reviewer.model}")
    else:
        print()
        print(
            "  NOTE: No ANTHROPIC_API_KEY found (or 'anthropic' package not installed)."
        )
        print(
            "  To use LLM mode: ANTHROPIC_API_KEY=sk-ant-... python scripts/demo_llm_reviewer.py"
        )
    print("=" * 65)

    hypotheses = build_sample_hypotheses()
    print(f"\nReviewing {len(hypotheses)} sample PK-study mapping hypotheses...\n")

    results = reviewer.review_all(hypotheses)

    for hypothesis, result in zip(hypotheses, results):
        print("-" * 65)
        print(f"Hypothesis : {hypothesis.mapping_id}")
        print(f"Mapping    : {hypothesis.source_entity.label!r}")
        print(f"           : --[{hypothesis.predicate.value}]-->")
        print(f"           : {hypothesis.target_entity.term_id} ({hypothesis.target_entity.label!r})")
        print(f"Confidence : {hypothesis.confidence:.2f}")
        print(f"Severity   : {result.overall_severity}")
        print(f"Recommend  : {result.recommendation}")

        if result.flags:
            print(f"Flags ({len(result.flags)}):")
            for flag in result.flags:
                print(f"  [{flag.severity.upper():6}] {flag.flag_type}")
                # Wrap description at 60 chars for readability
                desc = flag.description
                while len(desc) > 60:
                    cut = desc[:60].rfind(" ")
                    if cut == -1:
                        cut = 60
                    print(f"           {desc[:cut]}")
                    desc = desc[cut:].strip()
                if desc:
                    print(f"           {desc}")
        else:
            print("Flags      : none (mapping appears sound)")
        print()

    print("=" * 65)
    print("  Demo complete.")
    print("=" * 65)
    print()


if __name__ == "__main__":
    main()
