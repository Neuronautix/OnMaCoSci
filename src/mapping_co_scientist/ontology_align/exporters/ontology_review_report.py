from __future__ import annotations
from datetime import datetime
from pathlib import Path
from mapping_co_scientist.shared.reports.markdown_report_base import MarkdownReportBase
from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
    OntologyMappingHypothesis, OntologyRelation
)
from mapping_co_scientist.ontology_align.models.term_gap_proposal import TermGapProposal
from mapping_co_scientist.shared.models.review import AdversarialReviewResult


class OntologyReviewReport(MarkdownReportBase):
    def generate(
        self,
        hypotheses: list[OntologyMappingHypothesis] | None = None,
        adversarial_results: dict[str, AdversarialReviewResult] | None = None,
        term_gaps: list[TermGapProposal] | None = None,
        **kwargs,
    ) -> str:
        hypotheses = hypotheses or []
        adversarial_results = adversarial_results or {}
        term_gaps = term_gaps or []

        lines = []
        lines.append(f"# Ontology Alignment Review Report\n")
        lines.append(f"**Pipeline Run**: {self.pipeline_run_id}")
        lines.append(f"**Generated**: {self.generated_at}\n")
        lines.append(f"**Total hypotheses**: {len(hypotheses)}")
        lines.append(f"**Term gap proposals**: {len(term_gaps)}\n")
        lines.append("---\n")

        by_source: dict[str, list[OntologyMappingHypothesis]] = {}
        for h in hypotheses:
            key = h.source_concept.entity_id
            by_source.setdefault(key, []).append(h)

        lines.append("## Mapping Candidates\n")
        for source_id, hyps in by_source.items():
            hyps_sorted = sorted(hyps, key=lambda x: x.confidence, reverse=True)
            top = hyps_sorted[0]

            lines.append(f"### `{source_id}` → `{top.target_ontology_entity.label}`\n")
            lines.append(f"- **Relation**: `{top.ontology_relation}`")
            lines.append(f"- **Confidence**: {top.confidence:.2f}")
            lines.append(f"- **Source type**: {top.source_entity_type}")
            lines.append(f"- **Target type**: {top.target_entity_type}")
            lines.append(f"- **Validation**: {top.validation_status}\n")

            if top.semantic_warnings:
                lines.append("**Semantic Warnings:**")
                for w in top.semantic_warnings:
                    lines.append(f"- [{w.severity.upper()}] {w.description}")
                lines.append("")

            adv = adversarial_results.get(top.mapping_id)
            if adv and adv.flags:
                lines.append(f"**Adversarial Review**: {adv.overall_severity} severity — {adv.recommendation}")
                for flag in adv.flags:
                    lines.append(f"- [{flag.severity}] **{flag.flag_type}**: {flag.description}")
                lines.append("")

            if len(hyps_sorted) > 1:
                lines.append("**Alternative candidates:**")
                for alt in hyps_sorted[1:]:
                    lines.append(
                        f"- `{alt.target_ontology_entity.term_id}` "
                        f"({alt.ontology_relation}, conf={alt.confidence:.2f})"
                    )
                lines.append("")

            lines.append("---\n")

        if term_gaps:
            lines.append("## Term Gap Proposals\n")
            lines.append("The following source concepts had no suitable ontology mapping:\n")
            for gap in term_gaps:
                lines.append(f"### `{gap.source_concept_label}`")
                lines.append(f"- **Proposed term**: {gap.proposed_term_label}")
                lines.append(f"- **Rationale**: {gap.rationale}")
                lines.append(f"- **Definition stub**: {gap.proposed_term_definition}\n")

        return "\n".join(lines)
