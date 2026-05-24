from __future__ import annotations
import logging
import re
import unicodedata
import uuid
from datetime import datetime
from mapping_co_scientist.shared.agents.base_agent import BaseAgent
from mapping_co_scientist.shared.models.evidence import Evidence, Provenance
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity
from mapping_co_scientist.schema_align.models.field_mapping_hypothesis import (
    FieldMappingHypothesis, CardinalityRelation
)
from mapping_co_scientist.schema_align.models.transformation_rule import (
    MappingOperation, TransformationRule
)

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz as _fuzz
    def _sim(a: str, b: str) -> float:
        return _fuzz.WRatio(a, b) / 100.0
except ImportError:
    import difflib
    def _sim(a: str, b: str) -> float:  # type: ignore[misc]
        return difflib.SequenceMatcher(None, a, b).ratio()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).strip().lower()
    s = re.sub(r"[_\-\.\s]+", " ", s)
    # Remove common suffixes that don't add meaning
    s = re.sub(r"\b(id|identifier|code|val|value)\b", "", s).strip()
    return re.sub(r"\s+", " ", s).strip()


class FieldCandidateGeneratorAgent(BaseAgent):
    """Generates FieldMappingHypothesis candidates using lexical field matching.

    This agent understands schema-level transformations:
    - field renaming
    - path nesting
    - unit-aware matching (e.g. Weight_g -> bodyWeight.value + unit="g")
    - constant assignment for derived fields
    - information loss detection
    """

    def __init__(self, top_k: int = 3, pipeline_run_id: str | None = None):
        self.top_k = top_k
        self.pipeline_run_id = pipeline_run_id

    @property
    def agent_name(self) -> str:
        return "FieldCandidateGenerator"

    def generate(
        self,
        source_fields: list[SchemaEntity],
        target_fields: list[SchemaEntity],
    ) -> list[FieldMappingHypothesis]:
        all_hyps: list[FieldMappingHypothesis] = []

        for src in source_fields:
            hyps = self._generate_for_field(src, target_fields)
            all_hyps.extend(hyps)

        # Also generate constant assignment hypotheses for target fields
        # that require units from source unit-bearing fields
        unit_hyps = self._generate_unit_constant_hypotheses(source_fields, target_fields)
        all_hyps.extend(unit_hyps)

        self.log_step(f"Generated {len(all_hyps)} field mapping hypotheses")
        return all_hyps

    def _generate_for_field(
        self,
        src: SchemaEntity,
        target_fields: list[SchemaEntity],
    ) -> list[FieldMappingHypothesis]:
        norm_src = _norm(src.label)

        scored: list[tuple[SchemaEntity, float]] = []
        for tgt in target_fields:
            # Skip unit fields (those will be handled separately)
            if tgt.path.endswith(".unit"):
                continue
            norm_tgt = _norm(tgt.label)
            score = _sim(norm_src, norm_tgt)
            scored.append((tgt, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: self.top_k]

        hypotheses = []
        for i, (tgt, score) in enumerate(top):
            if score < 0.25:
                continue
            hyp = self._build_hypothesis(src, tgt, score, rank=i + 1)
            hypotheses.append(hyp)

        return hypotheses

    def _generate_unit_constant_hypotheses(
        self,
        source_fields: list[SchemaEntity],
        target_fields: list[SchemaEntity],
    ) -> list[FieldMappingHypothesis]:
        """Generate constant-assignment hypotheses for unit fields derived from source column names."""
        hyps = []
        unit_targets = [t for t in target_fields if t.path.endswith(".unit")]

        for ut in unit_targets:
            # Find source field that has a unit inferred from its column name
            # e.g. target "measurements.bodyWeight.unit" matches source "Weight_g" -> unit = "g"
            base_path = ut.path[:-5]  # remove ".unit"
            for src in source_fields:
                if src.unit and _sim(_norm(base_path.split(".")[-1]), _norm(src.label)) > 0.40:
                    rule = TransformationRule(
                        rule_id=f"rule-{uuid.uuid4().hex[:8]}",
                        source_path=None,
                        target_path=ut.path,
                        operation=MappingOperation.CONSTANT_ASSIGNMENT,
                        constant_value=src.unit,
                        notes=f"Unit '{src.unit}' inferred from source column name '{src.path}'",
                    )
                    hyp = FieldMappingHypothesis(
                        mapping_id=f"sa-const-{ut.path}-{src.path}".replace(":", "_").replace(".", "_"),
                        source_path=None,
                        target_path=ut.path,
                        mapping_operation=MappingOperation.CONSTANT_ASSIGNMENT,
                        source_datatype=None,
                        target_datatype="string",
                        confidence=0.80,
                        transformation_required=False,
                        transformation_rule=rule,
                        evidence=[Evidence(
                            evidence_type="unit_inference",
                            description=f"Unit '{src.unit}' inferred from source column name '{src.path}'",
                            score=0.80,
                            source="FieldCandidateGenerator",
                        )],
                        provenance=Provenance(
                            created_by="FieldCandidateGenerator",
                            created_at=datetime.utcnow().isoformat(),
                            method="unit_constant_inference_v1",
                            pipeline_run_id=self.pipeline_run_id,
                        ),
                    )
                    hyps.append(hyp)
                    break
        return hyps

    def _build_hypothesis(
        self,
        src: SchemaEntity,
        tgt: SchemaEntity,
        score: float,
        rank: int,
    ) -> FieldMappingHypothesis:
        mapping_id = f"sa-{src.path}-{tgt.path}".replace(":", "_").replace(".", "_").replace("/", "_")

        operation = self._infer_operation(src, tgt, score)
        transformation_required = operation not in (
            MappingOperation.DIRECT_COPY, MappingOperation.RENAME, MappingOperation.NESTED_PATH
        )

        evidence = [Evidence(
            evidence_type="lexical_similarity",
            description=f"Field '{src.label}' matched '{tgt.label}' with score {score:.3f}",
            score=score,
            source="FieldCandidateGenerator",
        )]

        counter_evidence = []
        warnings = []

        # Datatype mismatch
        dt_mismatch = self._check_datatype_mismatch(src, tgt)
        if dt_mismatch:
            warnings.append(dt_mismatch)
            counter_evidence.append(Evidence(
                evidence_type="datatype_mismatch",
                description=dt_mismatch,
                source="FieldCandidateGenerator",
            ))

        # Information loss detection
        info_loss, loss_desc = self._check_information_loss(src, tgt)

        # Unit conversion
        unit_conv = None
        if src.unit and tgt.unit and src.unit != tgt.unit:
            unit_conv = f"{src.unit} -> {tgt.unit}"
            warnings.append(f"Unit conversion required: {unit_conv}")

        # Build transformation rule
        rule = TransformationRule(
            rule_id=f"rule-{uuid.uuid4().hex[:8]}",
            source_path=src.path,
            target_path=tgt.path,
            operation=operation,
            datatype_from=src.datatype,
            datatype_to=tgt.datatype,
            unit_from=src.unit,
            unit_to=tgt.unit,
            information_loss=info_loss,
            information_loss_description=loss_desc,
        )

        return FieldMappingHypothesis(
            mapping_id=mapping_id,
            source_path=src.path,
            target_path=tgt.path,
            mapping_operation=operation,
            confidence=score,
            source_datatype=src.datatype,
            target_datatype=tgt.datatype,
            transformation_required=transformation_required,
            unit_conversion=unit_conv,
            information_loss=info_loss,
            information_loss_description=loss_desc,
            warnings=warnings,
            evidence=evidence,
            counter_evidence=counter_evidence,
            transformation_rule=rule,
            rank=rank,
            cardinality_relation=CardinalityRelation(
                source_cardinality="0..1",
                target_cardinality="0..1",
            ),
            provenance=Provenance(
                created_by="FieldCandidateGenerator",
                created_at=datetime.utcnow().isoformat(),
                method="lexical_field_matching_v1",
                pipeline_run_id=self.pipeline_run_id,
            ),
        )

    def _infer_operation(self, src: SchemaEntity, tgt: SchemaEntity, score: float) -> MappingOperation:
        if score < 0.30:
            return MappingOperation.UNMAPPED
        # Nested path (source is flat, target has nesting)
        if "." in tgt.path and "." not in src.path:
            return MappingOperation.NESTED_PATH
        # Datatype conversion needed
        if src.datatype != tgt.datatype and src.datatype is not None and tgt.datatype is not None:
            return MappingOperation.DATATYPE_CONVERSION
        # Same label, same type
        if score >= 0.85:
            return MappingOperation.DIRECT_COPY
        return MappingOperation.RENAME

    def _check_datatype_mismatch(self, src: SchemaEntity, tgt: SchemaEntity) -> str | None:
        if src.datatype is None or tgt.datatype is None:
            return None
        if src.datatype == tgt.datatype:
            return None
        # number/integer are compatible
        if {src.datatype, tgt.datatype} <= {"number", "integer"}:
            return None
        return f"Datatype mismatch: source={src.datatype}, target={tgt.datatype}. Conversion required."

    def _check_information_loss(self, src: SchemaEntity, tgt: SchemaEntity) -> tuple[bool, str | None]:
        if src.required and not tgt.required:
            return False, None  # Not a loss, target is more permissive
        # If source has more enumeration values than target
        if src.enumeration and tgt.enumeration:
            extra = set(src.enumeration) - set(tgt.enumeration)
            if extra:
                return True, f"Source has enum values not in target: {extra}"
        return False, None
