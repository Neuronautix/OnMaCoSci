from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mapping_co_scientist.ontology_align.agents.ontology_source_profiler import OntologySourceProfilerAgent
from mapping_co_scientist.ontology_align.agents.ontology_target_profiler import OntologyTargetProfilerAgent
from mapping_co_scientist.ontology_align.agents.semantic_candidate_generator import SemanticCandidateGeneratorAgent
from mapping_co_scientist.ontology_align.agents.ontology_adversarial_reviewer import OntologyAdversarialReviewerAgent
from mapping_co_scientist.ontology_align.agents.term_gap_agent import TermGapAgent
from mapping_co_scientist.ontology_align.agents.ontology_validation_agent import OntologyValidationAgent
from mapping_co_scientist.ontology_align.exporters.sssom_exporter import export_sssom
from mapping_co_scientist.ontology_align.exporters.ontology_review_report import OntologyReviewReport
from mapping_co_scientist.shared.io.common_serialization import write_json
from mapping_co_scientist.shared.debate import run_debate

logger = logging.getLogger(__name__)


def run_ontology_alignment_pipeline(
    source_path: Path,
    ontology_path: Path,
    output_dir: Path,
    pipeline_run_id: str | None = None,
    top_k: int = 3,
    verbose: bool = False,
    ledger_path: Path | None = None,
    use_llm: bool = False,
    llm_model: str | None = None,
) -> dict[str, Any]:
    if verbose:
        logging.basicConfig(level=logging.INFO)

    run_id = pipeline_run_id or f"oa-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Ontology Alignment Pipeline === run_id=%s", run_id)

    # Load review ledger to skip already-decided entities
    decided_source_ids: set[str] = set()
    if ledger_path:
        from mapping_co_scientist.shared.persistence.review_ledger import load_ledger
        ledger = load_ledger(ledger_path)
        decided_source_ids = {d.source_id for d in ledger.decisions}
        logger.info("Ledger loaded: %d decided source entities will be skipped", len(decided_source_ids))

    source_agent = OntologySourceProfilerAgent()
    target_agent = OntologyTargetProfilerAgent()
    source_entities = source_agent.profile(source_path)
    ontology_terms = target_agent.profile(ontology_path)

    # Filter out already-decided entities
    if decided_source_ids:
        source_entities = [e for e in source_entities if e.entity_id not in decided_source_ids]
        logger.info("After ledger filter: %d source entities remain", len(source_entities))

    logger.info("Source: %d entities, Ontology: %d terms", len(source_entities), len(ontology_terms))

    # Stage 2: Candidate generation (lexical or LLM-backed)
    if use_llm:
        from mapping_co_scientist.ontology_align.agents.llm_candidate_generator import LLMOntologyCandidateGenerator
        from mapping_co_scientist.shared.llm.claude_provider import ClaudeProvider
        from mapping_co_scientist.shared.llm.cost_tracker import CostTracker
        tracker = CostTracker()
        provider = ClaudeProvider(model=llm_model, cost_tracker=tracker)
        generator = LLMOntologyCandidateGenerator(llm=provider, top_k=top_k, pipeline_run_id=run_id)
        logger.info("Using LLM candidate generator (%s)", provider.model_name)
    else:
        generator = SemanticCandidateGeneratorAgent(top_k=top_k, pipeline_run_id=run_id)

    hypotheses = generator.generate(source_entities, ontology_terms)

    adversarial = OntologyAdversarialReviewerAgent()
    adv_results = adversarial.review_all(hypotheses)

    validator = OntologyValidationAgent()
    hypotheses = validator.validate_all(hypotheses)

    gap_agent = TermGapAgent()
    term_gaps = gap_agent.identify_gaps(source_entities, hypotheses)

    # Stage: Three-agent debate (Elo ranking)
    by_source: dict[str, list] = {}
    for h in hypotheses:
        by_source.setdefault(h.source_concept.entity_id, []).append(h)
    debate_report = run_debate(
        hypotheses_by_source=by_source,
        run_type="ontology_align",
        adversarial_results=adv_results,
        run_id=run_id,
    )

    # Write outputs
    candidates_path = output_dir / "ontology_mapping_candidates.json"
    sssom_path = output_dir / "ontology_mapping_candidates.sssom.tsv"
    report_path = output_dir / "ontology_review_report.md"
    gaps_path = output_dir / "term_gap_proposals.json"
    debate_path = output_dir / "debate_report.json"

    write_json([h.model_dump(mode="json") for h in hypotheses], candidates_path)
    export_sssom(hypotheses, sssom_path, pipeline_run_id=run_id)

    report = OntologyReviewReport(pipeline_run_id=run_id)
    report.write(report_path, hypotheses=hypotheses, adversarial_results=adv_results, term_gaps=term_gaps)

    write_json([g.model_dump(mode="json") for g in term_gaps], gaps_path)
    write_json(debate_report.model_dump(mode="json"), debate_path)

    summary: dict[str, Any] = {
        "pipeline_run_id": run_id,
        "source_entities": len(source_entities),
        "ontology_terms": len(ontology_terms),
        "hypotheses_generated": len(hypotheses),
        "term_gaps_identified": len(term_gaps),
        "debate": {
            "rank_inversions": debate_report.consistency.rank_inversions,
            "collisions": debate_report.consistency.collisions,
            "tier_1_items": sum(1 for e in debate_report.entity_results if e.tier == 1),
            "tier_2_items": sum(1 for e in debate_report.entity_results if e.tier == 2),
            "tier_3_items": sum(1 for e in debate_report.entity_results if e.tier == 3),
        },
        "outputs": {
            "candidates_json": str(candidates_path),
            "sssom_tsv": str(sssom_path),
            "review_report_md": str(report_path),
            "term_gap_proposals_json": str(gaps_path),
            "debate_report_json": str(debate_path),
        },
    }

    if use_llm and "tracker" in dir():
        summary["llm_usage"] = tracker.summary()

    logger.info("Pipeline complete: %s", summary)
    return summary
