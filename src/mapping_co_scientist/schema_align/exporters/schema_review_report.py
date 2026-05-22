from __future__ import annotations
from pathlib import Path
from mapping_co_scientist.shared.reports.markdown_report_base import MarkdownReportBase
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.lossiness_report import LossinessReport
from mapping_co_scientist.shared.models.review import AdversarialReviewResult
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation


class SchemaReviewReport(MarkdownReportBase):
    def generate(
        self,
        hypotheses: list[FieldMappingHypothesis] | None = None,
        adversarial_results: dict[str, AdversarialReviewResult] | None = None,
        lossiness_report: LossinessReport | None = None,
        **kwargs,
    ) -> str:
        hypotheses = hypotheses or []
        adversarial_results = adversarial_results or {}

        lines = []
        lines.append("# Schema Alignment Review Report\n")
        lines.append(f"**Pipeline Run**: {self.pipeline_run_id}")
        lines.append(f"**Generated**: {self.generated_at}")
        lines.append(f"**Total field mappings**: {len(hypotheses)}\n")

        if lossiness_report:
            lines.append(f"**Coverage**: {lossiness_report.coverage_pct:.1f}% "
                        f"({lossiness_report.mapped_fields}/{lossiness_report.total_source_fields} fields)")
            lines.append(f"**Unmapped fields**: {lossiness_report.unmapped_fields}\n")

        lines.append("---\n")
        lines.append("## Field Mappings\n")

        # Group by source path (take top-ranked per source)
        by_source: dict[str, list[FieldMappingHypothesis]] = {}
        for h in hypotheses:
            key = h.source_path or "<constant>"
            by_source.setdefault(key, []).append(h)

        for source_path, hyps in sorted(by_source.items()):
            top = sorted(hyps, key=lambda x: x.confidence, reverse=True)[0]

            lines.append(f"### `{source_path}` -> `{top.target_path}`\n")
            lines.append(f"- **Operation**: `{top.mapping_operation}`")
            lines.append(f"- **Confidence**: {top.confidence:.2f}")
            lines.append(f"- **Validation**: {top.validation_status}")

            if top.source_datatype or top.target_datatype:
                lines.append(f"- **Types**: {top.source_datatype} -> {top.target_datatype}")

            if top.unit_conversion:
                lines.append(f"- **Unit conversion**: {top.unit_conversion}")

            if top.transformation_rule and top.transformation_rule.constant_value is not None:
                lines.append(f"- **Constant value**: `{top.transformation_rule.constant_value}`")

            if top.information_loss:
                lines.append(f"\n**[INFORMATION LOSS]** {top.information_loss_description}")

            if top.warnings:
                lines.append("\n**Warnings:**")
                for w in top.warnings:
                    lines.append(f"- {w}")

            adv = adversarial_results.get(top.mapping_id)
            if adv and adv.flags:
                lines.append(f"\n**Adversarial Review**: {adv.overall_severity} -- {adv.recommendation}")
                for flag in adv.flags:
                    lines.append(f"- [{flag.severity}] {flag.flag_type}: {flag.description}")

            lines.append("")
            lines.append("---\n")

        if lossiness_report and lossiness_report.lossy_mappings:
            lines.append("## Information Loss Summary\n")
            for loss in lossiness_report.lossy_mappings:
                lines.append(f"- **{loss.source_path}**: [{loss.loss_type}] {loss.description}")
            lines.append("")

        return "\n".join(lines)
