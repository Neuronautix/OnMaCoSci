"""Orchestrator agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`OrchestratorAgent`, the top-level agent that
coordinates the full ontology mapping pipeline from source profiling through
to human review packet generation and output export.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ontology_mapping_co_scientist.agents.adversarial_reviewer import (
    AdversarialReviewerAgent,
)
from ontology_mapping_co_scientist.agents.candidate_generator import (
    CandidateGeneratorAgent,
)
from ontology_mapping_co_scientist.agents.human_review import HumanReviewAgent
from ontology_mapping_co_scientist.agents.ontology_profiler import OntologyProfilerAgent
from ontology_mapping_co_scientist.agents.ranking_agent import RankingAgent
from ontology_mapping_co_scientist.agents.source_profiler import SourceProfilerAgent
from ontology_mapping_co_scientist.agents.validation_agent import ValidationAgent

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """Controls the full mapping pipeline workflow, coordinating all specialist agents."""

    def __init__(self) -> None:
        """Instantiate all sub-agents used by the pipeline."""
        self.source_profiler = SourceProfilerAgent()
        self.ontology_profiler = OntologyProfilerAgent()
        self.candidate_generator = CandidateGeneratorAgent()
        self.adversarial_reviewer = AdversarialReviewerAgent()
        self.validation_agent = ValidationAgent()
        self.ranking_agent = RankingAgent()
        self.human_review_agent = HumanReviewAgent()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        source_filepath: str | Path,
        ontology_filepath: str | Path,
        output_dir: str | Path,
        pipeline_run_id: str | None = None,
    ) -> dict:
        """Execute the full ontology mapping pipeline.

        Pipeline steps:

        1. **Source profiling** — load and profile source entities from the
           input file (CSV or OpenAPI/JSON).
        2. **Ontology loading** — load and index ontology terms from the
           ontology profile file.
        3. **Candidate generation** — generate mapping hypotheses using
           lexical similarity.
        4. **Adversarial review** — review all hypotheses for issues and
           weaknesses.
        5. **Apply adversarial flags** — merge review findings back into
           hypotheses as counter-evidence and warnings.
        6. **Validation** — run consistency and quality checks on all
           hypotheses.
        7. **Ranking** — rank competing hypotheses per source entity.
        8. **Human review preparation** — prepare structured review packets
           for human experts.
        9. **JSON export** — write hypotheses to ``<output_dir>/hypotheses.json``.
        10. **SSSOM TSV export** — write SSSOM-formatted TSV to
            ``<output_dir>/mappings.sssom.tsv``.
        11. **Markdown report** — generate a Markdown summary report at
            ``<output_dir>/report.md``.

        Args:
            source_filepath: Path to the source schema file (CSV or OpenAPI JSON).
            ontology_filepath: Path to the ontology profile file (YAML or JSON).
            output_dir: Directory where output files will be written.  Created
                if it does not already exist.
            pipeline_run_id: Optional identifier for this pipeline run.  A
                UUID4 string is generated automatically if not provided.

        Returns:
            A summary dict with the following keys:

            * ``pipeline_run_id`` (*str*) — the run identifier used.
            * ``source_entities_count`` (*int*) — number of source entities profiled.
            * ``ontology_terms_count`` (*int*) — number of ontology terms loaded.
            * ``total_hypotheses`` (*int*) — total mapping hypotheses generated.
            * ``validation_summary`` (*dict*) — output of
              :meth:`~.ValidationAgent.generate_validation_summary`.
            * ``output_files`` (*dict*) — absolute paths of the three output files:
              ``json``, ``tsv``, and ``markdown``.
        """
        run_start = datetime.now(tz=timezone.utc)

        if pipeline_run_id is None:
            pipeline_run_id = str(uuid.uuid4())
        logger.info(
            "=== Pipeline run %s started at %s ===",
            pipeline_run_id,
            run_start.isoformat(),
        )

        source_filepath = Path(source_filepath)
        ontology_filepath = Path(ontology_filepath)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Output directory: %s", output_dir)

        # ------------------------------------------------------------------
        # Step 1: Profile source entities
        # ------------------------------------------------------------------
        logger.info("[Step 1/11] Profiling source entities from: %s", source_filepath)
        source_entities = self.source_profiler.profile_auto(source_filepath)
        source_summary = self.source_profiler.summarize(source_entities)
        logger.info(
            "Source profiling complete: %d entities (missing descriptions: %d).",
            source_summary["total"],
            source_summary["missing_descriptions"],
        )

        # ------------------------------------------------------------------
        # Step 2: Load ontology profile
        # ------------------------------------------------------------------
        logger.info("[Step 2/11] Loading ontology profile from: %s", ontology_filepath)
        ontology_terms = self.ontology_profiler.load_profile(ontology_filepath)
        onto_summary = self.ontology_profiler.summarize()
        logger.info(
            "Ontology loading complete: %d terms, ontologies=%s.",
            onto_summary["total_terms"],
            onto_summary["ontology_ids"],
        )

        # ------------------------------------------------------------------
        # Step 3: Generate candidates
        # ------------------------------------------------------------------
        logger.info("[Step 3/11] Generating mapping candidates.")
        hypotheses = self.candidate_generator.generate_candidates(
            source_entities=source_entities,
            ontology_terms=ontology_terms,
            pipeline_run_id=pipeline_run_id,
        )
        logger.info("Candidate generation complete: %d hypotheses.", len(hypotheses))

        # ------------------------------------------------------------------
        # Step 4: Adversarial review
        # ------------------------------------------------------------------
        logger.info("[Step 4/11] Running adversarial review.")
        adv_results = self.adversarial_reviewer.review_all(hypotheses)
        adv_results_index = {r.mapping_id: r for r in adv_results}

        # ------------------------------------------------------------------
        # Step 5: Apply adversarial flags back to hypotheses
        # ------------------------------------------------------------------
        logger.info("[Step 5/11] Applying adversarial flags to hypotheses.")
        hypotheses = self.adversarial_reviewer.apply_flags_to_hypotheses(
            hypotheses, adv_results
        )

        # ------------------------------------------------------------------
        # Step 6: Validate
        # ------------------------------------------------------------------
        logger.info("[Step 6/11] Validating hypotheses.")
        hypotheses = self.validation_agent.validate_all(hypotheses)
        validation_summary = self.validation_agent.generate_validation_summary(hypotheses)

        # ------------------------------------------------------------------
        # Step 7: Rank
        # ------------------------------------------------------------------
        logger.info("[Step 7/11] Ranking hypotheses.")
        hypotheses = self.ranking_agent.rank_hypotheses(hypotheses, adv_results_index)

        # ------------------------------------------------------------------
        # Step 8: Prepare human review packets
        # ------------------------------------------------------------------
        logger.info("[Step 8/11] Preparing human review packets.")
        review_packets = self.human_review_agent.prepare_all_packets(
            hypotheses, adv_results_index
        )
        logger.info("Prepared %d review packets.", len(review_packets))

        # ------------------------------------------------------------------
        # Step 9: Export JSON
        # ------------------------------------------------------------------
        json_path = output_dir / "hypotheses.json"
        logger.info("[Step 9/11] Exporting hypotheses to JSON: %s", json_path)
        json_path = self._export_json(hypotheses, review_packets, json_path, pipeline_run_id)

        # ------------------------------------------------------------------
        # Step 10: Export SSSOM TSV
        # ------------------------------------------------------------------
        tsv_path = output_dir / "mappings.sssom.tsv"
        logger.info("[Step 10/11] Exporting SSSOM TSV: %s", tsv_path)
        tsv_path = self._export_sssom_tsv(hypotheses, tsv_path)

        # ------------------------------------------------------------------
        # Step 10b: Export fully SSSOM-compliant TSV
        # ------------------------------------------------------------------
        sssom_compliant_stem = tsv_path.stem  # e.g. "mappings.sssom"
        sssom_compliant_path = output_dir / f"{sssom_compliant_stem}_sssom_compliant.tsv"
        logger.info(
            "[Step 10b] Exporting SSSOM-compliant TSV: %s", sssom_compliant_path
        )
        sssom_compliant_path = self._export_sssom_compliant(
            hypotheses, sssom_compliant_path, pipeline_run_id
        )

        # ------------------------------------------------------------------
        # Step 11: Generate Markdown report
        # ------------------------------------------------------------------
        md_path = output_dir / "report.md"
        logger.info("[Step 11/11] Generating Markdown report: %s", md_path)
        md_path = self._generate_markdown_report(
            hypotheses=hypotheses,
            review_packets=review_packets,
            validation_summary=validation_summary,
            pipeline_run_id=pipeline_run_id,
            run_start=run_start,
            output_path=md_path,
        )

        run_end = datetime.now(tz=timezone.utc)
        duration = (run_end - run_start).total_seconds()
        logger.info(
            "=== Pipeline run %s completed in %.2fs ===",
            pipeline_run_id,
            duration,
        )

        return {
            "pipeline_run_id": pipeline_run_id,
            "source_entities_count": len(source_entities),
            "ontology_terms_count": len(ontology_terms),
            "total_hypotheses": len(hypotheses),
            "validation_summary": validation_summary,
            "output_files": {
                "json": str(json_path),
                "tsv": str(tsv_path),
                "sssom_compliant": str(sssom_compliant_path),
                "markdown": str(md_path),
            },
        }

    # ------------------------------------------------------------------
    # Private export helpers
    # ------------------------------------------------------------------

    def _export_json(
        self,
        hypotheses: list,
        review_packets: list[dict],
        output_path: Path,
        pipeline_run_id: str,
    ) -> Path:
        """Export hypotheses and review packets to a JSON file.

        Attempts to use
        :func:`~ontology_mapping_co_scientist.exporters.export_to_json` if
        available; falls back to a built-in serialisation otherwise.

        Args:
            hypotheses: List of :class:`~.MappingHypothesis` objects.
            review_packets: Pre-built list of review packet dicts.
            output_path: Destination file path.
            pipeline_run_id: Run identifier included in the output envelope.

        Returns:
            The resolved output path.
        """
        try:
            from ontology_mapping_co_scientist.exporters import export_to_json

            export_to_json(hypotheses, output_path)
        except ImportError:
            logger.debug("exporters.export_to_json not available; using fallback JSON export.")
            payload = {
                "pipeline_run_id": pipeline_run_id,
                "hypotheses": [h.model_dump() for h in hypotheses],
                "review_packets": review_packets,
            }
            with output_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)

        logger.debug("JSON export written to: %s", output_path)
        return output_path

    def _export_sssom_tsv(
        self,
        hypotheses: list,
        output_path: Path,
    ) -> Path:
        """Export hypotheses to an SSSOM-compatible TSV file.

        Attempts to use
        :func:`~ontology_mapping_co_scientist.exporters.export_to_sssom_tsv` if
        available; falls back to a built-in minimal SSSOM serialisation otherwise.

        SSSOM column set used:
        ``subject_id``, ``subject_label``, ``predicate_id``,
        ``object_id``, ``object_label``, ``mapping_justification``,
        ``confidence``, ``mapping_provider``, ``comment``.

        Args:
            hypotheses: List of :class:`~.MappingHypothesis` objects.
            output_path: Destination file path.

        Returns:
            The resolved output path.
        """
        try:
            from ontology_mapping_co_scientist.exporters import export_to_sssom_tsv

            export_to_sssom_tsv(hypotheses, output_path)
        except ImportError:
            logger.debug(
                "exporters.export_to_sssom_tsv not available; using fallback SSSOM export."
            )
            self._write_sssom_tsv_fallback(hypotheses, output_path)

        logger.debug("SSSOM TSV export written to: %s", output_path)
        return output_path

    def _export_sssom_compliant(
        self,
        hypotheses: list,
        output_path: Path,
        pipeline_run_id: str,
    ) -> Path:
        """Export hypotheses to a fully SSSOM-compliant TSV file.

        Uses :func:`~ontology_mapping_co_scientist.io.sssom_exporter.export_to_sssom`
        to produce a file that includes a proper YAML metadata block and full
        SKOS predicate URIs.

        Args:
            hypotheses: List of :class:`~.MappingHypothesis` objects.
            output_path: Destination file path.
            pipeline_run_id: The pipeline run identifier, used as the mapping
                set ID when individual hypotheses do not carry one.

        Returns:
            The resolved output path.
        """
        try:
            from ontology_mapping_co_scientist.io.exporters import export_to_sssom_compliant

            export_to_sssom_compliant(
                hypotheses,
                output_path,
                mapping_set_id=pipeline_run_id,
            )
        except ImportError:
            logger.warning(
                "export_to_sssom_compliant not available; skipping compliant export."
            )

        logger.debug("SSSOM-compliant TSV written to: %s", output_path)
        return output_path

    def _write_sssom_tsv_fallback(self, hypotheses: list, output_path: Path) -> None:
        """Write a minimal SSSOM TSV using only stdlib.

        Args:
            hypotheses: List of :class:`~.MappingHypothesis` objects.
            output_path: Destination file path.
        """
        import csv

        columns = [
            "subject_id",
            "subject_label",
            "predicate_id",
            "object_id",
            "object_label",
            "mapping_justification",
            "confidence",
            "mapping_provider",
            "comment",
        ]

        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t")
            writer.writeheader()
            for h in hypotheses:
                # Derive mapping justification from evidence types
                ev_types = ", ".join(
                    e.evidence_type for e in h.evidence
                ) or "semapv:UnspecifiedMatching"
                writer.writerow(
                    {
                        "subject_id": h.source_entity.entity_id,
                        "subject_label": h.source_entity.label,
                        "predicate_id": h.predicate.value,
                        "object_id": h.target_entity.term_id,
                        "object_label": h.target_entity.label,
                        "mapping_justification": ev_types,
                        "confidence": f"{h.confidence:.4f}",
                        "mapping_provider": h.provenance.created_by,
                        "comment": "; ".join(h.warnings) if h.warnings else "",
                    }
                )

    def _generate_markdown_report(
        self,
        hypotheses: list,
        review_packets: list[dict],
        validation_summary: dict,
        pipeline_run_id: str,
        run_start: datetime,
        output_path: Path,
    ) -> Path:
        """Generate a Markdown summary report.

        Attempts to use
        :func:`~ontology_mapping_co_scientist.reports.markdown_report.generate_markdown_report`
        if available; falls back to a built-in Markdown generator otherwise.

        Args:
            hypotheses: List of :class:`~.MappingHypothesis` objects.
            review_packets: Pre-built list of review packet dicts.
            validation_summary: Output of
                :meth:`~.ValidationAgent.generate_validation_summary`.
            pipeline_run_id: The pipeline run identifier.
            run_start: UTC datetime when the pipeline run started.
            output_path: Destination file path.

        Returns:
            The resolved output path.
        """
        try:
            from ontology_mapping_co_scientist.reports.markdown_report import (
                generate_markdown_report,
            )

            generate_markdown_report(
                hypotheses=hypotheses,
                review_packets=review_packets,
                validation_summary=validation_summary,
                pipeline_run_id=pipeline_run_id,
                output_path=output_path,
            )
        except ImportError:
            logger.debug(
                "reports.markdown_report not available; using fallback Markdown export."
            )
            self._write_markdown_fallback(
                hypotheses=hypotheses,
                review_packets=review_packets,
                validation_summary=validation_summary,
                pipeline_run_id=pipeline_run_id,
                run_start=run_start,
                output_path=output_path,
            )

        logger.debug("Markdown report written to: %s", output_path)
        return output_path

    def _write_markdown_fallback(
        self,
        hypotheses: list,
        review_packets: list[dict],
        validation_summary: dict,
        pipeline_run_id: str,
        run_start: datetime,
        output_path: Path,
    ) -> None:
        """Write a minimal Markdown report using only stdlib.

        Args:
            hypotheses: List of :class:`~.MappingHypothesis` objects.
            review_packets: Pre-built list of review packet dicts.
            validation_summary: Validation summary dict.
            pipeline_run_id: The pipeline run identifier.
            run_start: UTC datetime when the pipeline run started.
            output_path: Destination file path.
        """
        lines: list[str] = [
            "# Ontology Mapping Co-Scientist — Pipeline Report",
            "",
            f"**Pipeline Run ID:** `{pipeline_run_id}`  ",
            f"**Generated:** {run_start.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "---",
            "",
            "## Validation Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total hypotheses | {validation_summary.get('total', 0)} |",
            f"| Passed | {validation_summary.get('passed', 0)} |",
            f"| Warnings | {validation_summary.get('warnings', 0)} |",
            f"| Failed | {validation_summary.get('failed', 0)} |",
            f"| No-mapping | {validation_summary.get('no_mapping_count', 0)} |",
            f"| Exact match | {validation_summary.get('exact_match_count', 0)} |",
            f"| High confidence (≥0.8) | {validation_summary.get('high_confidence_count', 0)} |",
            "",
            "---",
            "",
            "## Top Mappings by Source Entity",
            "",
        ]

        for packet in review_packets:
            entity_label = packet.get("source_entity_label", packet.get("source_entity_id", ""))
            top = packet.get("top_mapping")
            action = packet.get("suggested_action") or {}
            warnings = packet.get("all_warnings", [])

            lines.append(f"### {entity_label}")
            lines.append("")

            if top:
                lines.append(f"- **Target:** `{top['target_entity']['term_id']}` — {top['target_entity']['label']}")
                lines.append(f"- **Predicate:** `{top['predicate']}`")
                lines.append(f"- **Confidence:** {top['confidence']:.3f}")
                lines.append(f"- **Validation status:** {top.get('validation_status', 'unknown')}")
                if action:
                    lines.append(f"- **Suggested action:** `{action.get('action', '')}` — {action.get('reason', '')}")
            else:
                lines.append("_No mapping found._")

            if warnings:
                lines.append("")
                lines.append("**Warnings:**")
                for w in warnings[:5]:  # cap at 5 to keep report readable
                    lines.append(f"- {w}")

            lines.append("")

        content = "\n".join(lines)
        output_path.write_text(content, encoding="utf-8")
