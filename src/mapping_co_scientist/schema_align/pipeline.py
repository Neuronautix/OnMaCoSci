from __future__ import annotations
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mapping_co_scientist.schema_align.agents.source_schema_profiler import SourceSchemaProfilerAgent
from mapping_co_scientist.schema_align.agents.target_schema_profiler import TargetSchemaProfilerAgent
from mapping_co_scientist.schema_align.agents.field_candidate_generator import FieldCandidateGeneratorAgent
from mapping_co_scientist.schema_align.agents.schema_adversarial_reviewer import SchemaAdversarialReviewerAgent
from mapping_co_scientist.schema_align.agents.mapping_rule_generator import MappingRuleGeneratorAgent
from mapping_co_scientist.schema_align.agents.schema_validation_agent import SchemaValidationAgent
from mapping_co_scientist.schema_align.exporters.generic_mapping_exporter import export_mapping_spec
from mapping_co_scientist.schema_align.exporters.transformation_spec_exporter import export_transformation_rules
from mapping_co_scientist.schema_align.exporters.schema_review_report import SchemaReviewReport
from mapping_co_scientist.schema_align.validation.lossiness_checks import build_lossiness_report
from mapping_co_scientist.shared.io.common_serialization import write_json
from mapping_co_scientist.shared.debate import run_debate

logger = logging.getLogger(__name__)


def run_schema_alignment_pipeline(
    source_path: Path,
    target_schema_path: Path,
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

    run_id = pipeline_run_id or f"sa-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Schema Alignment Pipeline === run_id=%s", run_id)

    # Load review ledger to skip already-decided fields
    decided_source_paths: set[str] = set()
    if ledger_path:
        from mapping_co_scientist.shared.persistence.review_ledger import load_ledger
        ledger = load_ledger(ledger_path)
        decided_source_paths = {d.source_id for d in ledger.decisions}
        logger.info("Ledger loaded: %d decided source fields will be skipped", len(decided_source_paths))

    # Stage 1: Profile source and target schemas
    source_agent = SourceSchemaProfilerAgent()
    target_agent = TargetSchemaProfilerAgent()
    source_fields = source_agent.profile(source_path)
    target_fields = target_agent.profile(target_schema_path)

    # Filter out already-decided fields
    if decided_source_paths:
        source_fields = [f for f in source_fields if f.source_path not in decided_source_paths]
        logger.info("After ledger filter: %d source fields remain", len(source_fields))

    logger.info("Source: %d fields, Target: %d fields", len(source_fields), len(target_fields))

    # Stage 2: Generate field mapping candidates (lexical or LLM-backed)
    if use_llm:
        from mapping_co_scientist.schema_align.agents.llm_field_generator import LLMSchemaFieldGenerator
        from mapping_co_scientist.shared.llm.claude_provider import ClaudeProvider
        from mapping_co_scientist.shared.llm.cost_tracker import CostTracker
        tracker = CostTracker()
        provider = ClaudeProvider(model=llm_model, cost_tracker=tracker)
        generator = LLMSchemaFieldGenerator(llm=provider, top_k=top_k, pipeline_run_id=run_id)
        logger.info("Using LLM field generator (%s)", provider.model_name)
    else:
        generator = FieldCandidateGeneratorAgent(top_k=top_k, pipeline_run_id=run_id)

    hypotheses = generator.generate(source_fields, target_fields)

    # Stage 3: Adversarial review
    adversarial = SchemaAdversarialReviewerAgent()
    adv_results = adversarial.review_all(hypotheses)

    # Stage 4: Validation
    validator = SchemaValidationAgent()
    hypotheses = validator.validate_all(hypotheses)

    # Stage 5: Lossiness analysis
    loss_report = build_lossiness_report(hypotheses, run_id, len(source_fields))

    # Stage 6: Generate transformation rules
    rule_gen = MappingRuleGeneratorAgent()
    rules = rule_gen.generate_rules(hypotheses)

    # Stage 7: Three-agent debate (Elo ranking)
    by_source: dict[str, list] = {}
    for h in hypotheses:
        key = h.source_path or f"__const_{h.target_path}"
        by_source.setdefault(key, []).append(h)
    debate_report = run_debate(
        hypotheses_by_source=by_source,
        run_type="schema_align",
        adversarial_results=adv_results,
        run_id=run_id,
    )

    # Stage 8: Export
    candidates_path = output_dir / "field_mapping_candidates.json"
    mapping_spec_path = output_dir / "approved_mapping_spec.yaml"
    rules_path = output_dir / "transformation_rules.json"
    report_path = output_dir / "transformation_validation_report.md"
    unmapped_path = output_dir / "unmapped_fields_report.md"
    loss_path = output_dir / "information_loss_report.md"
    debate_path = output_dir / "debate_report.json"

    write_json([h.model_dump(mode="json") for h in hypotheses], candidates_path)
    export_mapping_spec(hypotheses, mapping_spec_path, pipeline_run_id=run_id)
    export_transformation_rules(rules, rules_path)

    report = SchemaReviewReport(pipeline_run_id=run_id)
    report.write(report_path, hypotheses=hypotheses, adversarial_results=adv_results, lossiness_report=loss_report)

    # Unmapped fields report
    from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation
    unmapped = [h for h in hypotheses if h.mapping_operation == MappingOperation.UNMAPPED]
    _write_unmapped_report(unmapped_path, unmapped, source_fields, target_fields)

    # Info loss report
    write_json(loss_report.model_dump(mode="json"), loss_path.with_suffix(".json"))
    _write_loss_report(loss_path, loss_report)

    write_json(debate_report.model_dump(mode="json"), debate_path)

    summary: dict[str, Any] = {
        "pipeline_run_id": run_id,
        "source_fields": len(source_fields),
        "target_fields": len(target_fields),
        "hypotheses_generated": len(hypotheses),
        "transformation_rules": len(rules),
        "unmapped_fields": loss_report.unmapped_fields,
        "coverage_pct": round(loss_report.coverage_pct, 1),
        "debate": {
            "rank_inversions": debate_report.consistency.rank_inversions,
            "collisions": debate_report.consistency.collisions,
            "tier_1_items": sum(1 for e in debate_report.entity_results if e.tier == 1),
            "tier_2_items": sum(1 for e in debate_report.entity_results if e.tier == 2),
            "tier_3_items": sum(1 for e in debate_report.entity_results if e.tier == 3),
        },
        "outputs": {
            "candidates_json": str(candidates_path),
            "mapping_spec_yaml": str(mapping_spec_path),
            "transformation_rules_json": str(rules_path),
            "validation_report_md": str(report_path),
            "unmapped_report_md": str(unmapped_path),
            "loss_report_json": str(loss_path.with_suffix(".json")),
            "debate_report_json": str(debate_path),
        },
    }

    if use_llm and "tracker" in dir():
        summary["llm_usage"] = tracker.summary()

    logger.info("Pipeline complete: %s", summary)
    return summary


def _write_unmapped_report(path: Path, unmapped, source_fields, target_fields) -> None:
    lines = ["# Unmapped Fields Report\n"]
    if not unmapped:
        lines.append("All source fields were mapped to at least one target field.\n")
    else:
        lines.append(f"{len(unmapped)} source field(s) could not be mapped:\n")
        for h in unmapped:
            lines.append(f"- `{h.source_path}`: {h.warnings[0] if h.warnings else 'No suitable target found'}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_loss_report(path: Path, report: LossinessReport) -> None:
    lines = [
        "# Information Loss Report\n",
        f"**Coverage**: {report.coverage_pct:.1f}%",
        f"**Mapped**: {report.mapped_fields} / {report.total_source_fields}",
        f"**Unmapped**: {report.unmapped_fields}\n",
    ]
    if report.lossy_mappings:
        lines.append("## Lossy Mappings\n")
        for loss in report.lossy_mappings:
            lines.append(f"- [{loss.severity.upper()}] `{loss.source_path}`: {loss.description}")
    if report.ambiguous_fields:
        lines.append("\n## Ambiguous Fields\n")
        for field in report.ambiguous_fields:
            lines.append(f"- `{field}`")
    path.write_text("\n".join(lines), encoding="utf-8")


# Import for _write_loss_report type annotation
from mapping_co_scientist.schema_align.models.lossiness_report import LossinessReport  # noqa: E402
