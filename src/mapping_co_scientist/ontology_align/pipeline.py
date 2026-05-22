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

logger = logging.getLogger(__name__)


def run_ontology_alignment_pipeline(
    source_path: Path,
    ontology_path: Path,
    output_dir: Path,
    pipeline_run_id: str | None = None,
    top_k: int = 3,
    verbose: bool = False,
) -> dict[str, Any]:
    if verbose:
        logging.basicConfig(level=logging.INFO)

    run_id = pipeline_run_id or f"oa-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Ontology Alignment Pipeline === run_id=%s", run_id)

    source_agent = OntologySourceProfilerAgent()
    target_agent = OntologyTargetProfilerAgent()
    source_entities = source_agent.profile(source_path)
    ontology_terms = target_agent.profile(ontology_path)

    logger.info("Source: %d entities, Ontology: %d terms", len(source_entities), len(ontology_terms))

    generator = SemanticCandidateGeneratorAgent(top_k=top_k, pipeline_run_id=run_id)
    hypotheses = generator.generate(source_entities, ontology_terms)

    adversarial = OntologyAdversarialReviewerAgent()
    adv_results = adversarial.review_all(hypotheses)

    validator = OntologyValidationAgent()
    hypotheses = validator.validate_all(hypotheses)

    gap_agent = TermGapAgent()
    term_gaps = gap_agent.identify_gaps(source_entities, hypotheses)

    candidates_path = output_dir / "ontology_mapping_candidates.json"
    sssom_path = output_dir / "ontology_mapping_candidates.sssom.tsv"
    report_path = output_dir / "ontology_review_report.md"
    gaps_path = output_dir / "term_gap_proposals.json"

    write_json([h.model_dump(mode="json") for h in hypotheses], candidates_path)
    export_sssom(hypotheses, sssom_path, pipeline_run_id=run_id)

    report = OntologyReviewReport(pipeline_run_id=run_id)
    report.write(report_path, hypotheses=hypotheses, adversarial_results=adv_results, term_gaps=term_gaps)

    write_json([g.model_dump(mode="json") for g in term_gaps], gaps_path)

    summary = {
        "pipeline_run_id": run_id,
        "source_entities": len(source_entities),
        "ontology_terms": len(ontology_terms),
        "hypotheses_generated": len(hypotheses),
        "term_gaps_identified": len(term_gaps),
        "outputs": {
            "candidates_json": str(candidates_path),
            "sssom_tsv": str(sssom_path),
            "review_report_md": str(report_path),
            "term_gap_proposals_json": str(gaps_path),
        },
    }
    logger.info("Pipeline complete: %s", summary)
    return summary
