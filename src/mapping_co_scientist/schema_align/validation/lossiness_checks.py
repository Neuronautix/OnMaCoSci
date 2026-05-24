from __future__ import annotations
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import FieldMappingHypothesis
from mapping_co_scientist.schema_align.models.lossiness_report import LossyMapping, LossinessReport
from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation


def build_lossiness_report(
    hypotheses: list[FieldMappingHypothesis],
    pipeline_run_id: str,
    total_source_fields: int,
) -> LossinessReport:
    lossy: list[LossyMapping] = []
    ambiguous: list[str] = []

    # Track unique source paths (hypotheses include top-k candidates per source field)
    # A source field is "mapped" if at least one non-UNMAPPED hypothesis exists for it
    # A source field is "unmapped" if ALL hypotheses are UNMAPPED (or there are none)
    by_source: dict[str, list[FieldMappingHypothesis]] = {}
    for h in hypotheses:
        key = h.source_path or "__constant__"
        by_source.setdefault(key, []).append(h)

    mapped_sources: set[str] = set()
    unmapped_sources: set[str] = set()

    for source_path, hyps in by_source.items():
        if source_path == "__constant__":
            # Constant assignments have no real source field; skip for coverage counting
            continue

        non_unmapped = [h for h in hyps if h.mapping_operation != MappingOperation.UNMAPPED]
        if non_unmapped:
            mapped_sources.add(source_path)
            # Check the top-ranked hypothesis for lossiness and ambiguity
            top = sorted(non_unmapped, key=lambda x: x.confidence, reverse=True)[0]
            if top.information_loss and top.information_loss_description:
                lossy.append(LossyMapping(
                    source_path=source_path,
                    target_path=top.target_path,
                    operation=top.mapping_operation,
                    loss_type="context_loss",
                    description=top.information_loss_description,
                    severity="warning",
                ))
            if top.confidence < 0.50:
                ambiguous.append(source_path)
        else:
            unmapped_sources.add(source_path)
            lossy.append(LossyMapping(
                source_path=source_path,
                target_path=None,
                operation=MappingOperation.UNMAPPED,
                loss_type="unmapped_field",
                description=f"No target path found for '{source_path}'",
                severity="warning",
            ))

    return LossinessReport(
        pipeline_run_id=pipeline_run_id,
        total_source_fields=total_source_fields,
        mapped_fields=len(mapped_sources),
        unmapped_fields=len(unmapped_sources),
        lossy_mappings=lossy,
        ambiguous_fields=list(set(ambiguous)),
    )
