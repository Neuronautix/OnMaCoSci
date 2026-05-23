from __future__ import annotations

from typing import Any

from mapping_co_scientist.shared.debate.models import (
    ArgumentSide,
    DebateArgument,
    EvidenceType,
)

# Unit suffixes that suggest a numeric field carries a physical unit
_UNIT_SUFFIXES = (
    "_g", "_kg", "_mm", "_cm", "_m", "_s", "_c", "_f", "_hz",
    "_pct", "_percent",
    # also check the path ends with those strings (without underscore)
    "g", "kg", "mm", "cm", "m", "s", "hz", "pct", "percent",
)

_UNIT_SUFFIX_SET = {
    "g", "kg", "mm", "cm", "m", "s", "c", "f", "hz", "pct", "percent",
}


def _path_has_unit_suffix(path: str) -> bool:
    """Return True if path ends with a unit-like suffix."""
    stem = path.lower().rsplit(".", 1)[-1]  # handle dotted paths
    # Try underscore split
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1] in _UNIT_SUFFIX_SET:
        return True
    # The whole last segment is a unit suffix (less common)
    if stem in _UNIT_SUFFIX_SET:
        return True
    return False


def _has_unit_companion(all_hypotheses: list[Any] | None) -> bool:
    """Return True if any hypothesis in the list is a CONSTANT_ASSIGNMENT for a .unit target."""
    if not all_hypotheses:
        return False
    for h in all_hypotheses:
        op = getattr(h, "mapping_operation", None)
        target = getattr(h, "target_path", None)
        if op is not None and target is not None:
            if str(op) == "constant_assignment" and str(target).endswith(".unit"):
                return True
    return False


class HeuristicSourceAdvocate:
    """Generates Round-1 source-schema advocate arguments from heuristic rules."""

    def generate_arguments(
        self,
        hypothesis: Any,
        run_type: str,
        all_hypotheses_for_source: list[Any] | None = None,
    ) -> list[DebateArgument]:
        if run_type == "ontology_align":
            return self._ontology_args(hypothesis, run_type, all_hypotheses_for_source)
        return self._schema_args(hypothesis, run_type, all_hypotheses_for_source)

    # ------------------------------------------------------------------
    # Ontology-align heuristics
    # ------------------------------------------------------------------

    def _ontology_args(
        self,
        hyp: Any,
        run_type: str,
        all_hypotheses: list[Any] | None,
    ) -> list[DebateArgument]:
        from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
            OntologyRelation,
        )

        args: list[DebateArgument] = []
        confidence: float = hyp.confidence
        source_label: str = hyp.source_concept.label
        source_label_lower = source_label.lower()
        ontology_relation = hyp.ontology_relation
        source_entity_type: str = hyp.source_entity_type

        # 1. Ambiguity — low confidence
        if confidence < 0.60:
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.AMBIGUITY_UNRESOLVED,
                    claim=(
                        f"Lexical similarity score {confidence:.2f} may not reflect semantic "
                        f"correspondence; source field meaning in domain context is unverified."
                    ),
                    confidence=0.85,
                )
            )

        # 2. Scope FOR — narrowMatch for strain/substrain
        if ontology_relation == OntologyRelation.NARROW_MATCH and (
            "strain" in source_label_lower or "substrain" in source_label_lower
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.FOR,
                    evidence_type=EvidenceType.SCOPE_RELATIONSHIP,
                    claim=(
                        f"Source field '{source_label}' denotes a specific named line — "
                        f"a narrower concept than the general genetic background class."
                    ),
                    confidence=0.80,
                )
            )

        # 3. Scope AGAINST — exactMatch for strain
        if ontology_relation == OntologyRelation.EXACT_MATCH and "strain" in source_label_lower:
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.SCOPE_RELATIONSHIP,
                    claim=(
                        "Strain names denote specific instances, not the general concept; "
                        "skos:exactMatch overstates the relationship."
                    ),
                    confidence=0.80,
                )
            )

        # 4. Domain definition AGAINST — identifier fields
        if source_entity_type == "identifier":
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.DOMAIN_DEFINITION_MATCH,
                    claim=(
                        "Source field is an identifier recording a reference value, not the "
                        "concept itself; the mapping conflates an ID with its referent."
                    ),
                    confidence=0.75,
                )
            )

        # 5. Information loss AGAINST — error-severity semantic warnings
        semantic_warnings = getattr(hyp, "semantic_warnings", [])
        if any(
            getattr(w, "severity", None) == "error" for w in semantic_warnings
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.INFORMATION_LOSS_RISK,
                    claim=(
                        "Semantic warnings flagged during pipeline generation indicate "
                        "risk of context loss in this mapping."
                    ),
                    confidence=0.80,
                )
            )

        # 6. Missing unit companion (schema_align path — also spec'd here for completeness)
        # The spec says: when run_type is schema_align AND source_path ends with unit suffix
        # This path is schema_align only — won't fire for ontology_align.

        return args[:3]

    # ------------------------------------------------------------------
    # Schema-align heuristics
    # ------------------------------------------------------------------

    def _schema_args(
        self,
        hyp: Any,
        run_type: str,
        all_hypotheses: list[Any] | None,
    ) -> list[DebateArgument]:
        from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation

        args: list[DebateArgument] = []
        source_path: str | None = hyp.source_path
        confidence: float = hyp.confidence
        information_loss: bool = getattr(hyp, "information_loss", False)
        information_loss_description: str | None = getattr(
            hyp, "information_loss_description", None
        )
        mapping_operation = hyp.mapping_operation

        if source_path is None:
            return args

        path_lower = source_path.lower()

        # 1. Ambiguity for count/index/score/rank fields
        if any(kw in path_lower for kw in ("count", "index", "score", "rank")):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.AMBIGUITY_UNRESOLVED,
                    claim=(
                        f"Field name '{source_path}' is ambiguous — could be raw sensor count, "
                        f"derived index, or normalised score; context required before mapping "
                        f"can be safely approved."
                    ),
                    confidence=0.85,
                )
            )

        # 2. Information loss risk
        if information_loss:
            desc = information_loss_description or "Information loss detected"
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.INFORMATION_LOSS_RISK,
                    claim=(
                        f"{desc}: source values cannot round-trip through this mapping."
                    ),
                    confidence=0.90,
                )
            )

        # 3. Ambiguity — low confidence
        if confidence < 0.60:
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.AMBIGUITY_UNRESOLVED,
                    claim=(
                        f"Lexical confidence {confidence:.2f} is below 0.60; field name alone "
                        f"may not determine the correct target."
                    ),
                    confidence=0.75,
                )
            )

        # 4. Missing unit companion
        if _path_has_unit_suffix(source_path) and not _has_unit_companion(all_hypotheses):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.MISSING_UNIT_COMPANION,
                    claim=(
                        f"Source field '{source_path}' carries a unit suffix but no "
                        f"constant-assignment hypothesis exists for the companion unit field."
                    ),
                    confidence=0.90,
                )
            )

        # 5. Domain definition FOR — high-confidence, no loss, not unmapped
        if (
            confidence >= 0.80
            and not information_loss
            and mapping_operation != MappingOperation.UNMAPPED
        ):
            source_datatype: str | None = getattr(hyp, "source_datatype", None)
            dtype_str = f" ({source_datatype})" if source_datatype else ""
            args.append(
                DebateArgument(
                    round=1,
                    advocate="source",
                    side=ArgumentSide.FOR,
                    evidence_type=EvidenceType.DOMAIN_DEFINITION_MATCH,
                    claim=(
                        f"Source field '{source_path}'{dtype_str} maps cleanly to target "
                        f"with high lexical confidence."
                    ),
                    confidence=0.75,
                )
            )

        return args[:3]


class HeuristicTargetAdvocate:
    """Generates Round-1 target-schema/ontology advocate arguments from heuristic rules."""

    def generate_arguments(
        self,
        hypothesis: Any,
        run_type: str,
        all_hypotheses_for_source: list[Any] | None = None,
    ) -> list[DebateArgument]:
        if run_type == "ontology_align":
            return self._ontology_args(hypothesis)
        return self._schema_args(hypothesis)

    # ------------------------------------------------------------------
    # Ontology-align heuristics
    # ------------------------------------------------------------------

    def _ontology_args(self, hyp: Any) -> list[DebateArgument]:
        from mapping_co_scientist.ontology_align.models.ontology_mapping_hypothesis import (
            OntologyRelation,
        )

        args: list[DebateArgument] = []
        ontology_relation = hyp.ontology_relation
        source_entity_type: str = hyp.source_entity_type
        target_entity_type: str = hyp.target_entity_type
        semantic_scope_analysis: str = hyp.semantic_scope_analysis or ""

        # 1. Semantic overreach AGAINST — exactMatch
        if ontology_relation == OntologyRelation.EXACT_MATCH:
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.SEMANTIC_OVERREACH,
                    claim=(
                        "skos:exactMatch asserts full semantic interchangeability in all "
                        "contexts; lexical similarity alone is insufficient to establish this."
                    ),
                    confidence=0.90,
                    counterpoint_weakness=(
                        "If prior ontology literature documents identical extension and "
                        "intension, exactMatch may be justified."
                    ),
                )
            )

        # 2. Type incompatibility AGAINST — identifier -> class
        if source_entity_type == "identifier" and target_entity_type == "class":
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.TYPE_INCOMPATIBILITY,
                    claim=(
                        "Identifier fields reference entities; they map to annotation or data "
                        "properties, not OWL classes."
                    ),
                    confidence=0.85,
                )
            )

        # 3. Structural type mismatch AGAINST — measurement -> class
        if source_entity_type == "measurement" and target_entity_type == "class":
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.STRUCTURAL_TYPE_MATCH,
                    claim=(
                        "Measurement values map to data properties or object properties, not "
                        "OWL classes; consider hasMeasurement-style property."
                    ),
                    confidence=0.80,
                )
            )

        # 4. Scope FOR — narrowMatch/broadMatch with confirming scope analysis
        if ontology_relation in (OntologyRelation.NARROW_MATCH, OntologyRelation.BROAD_MATCH):
            scope_lower = semantic_scope_analysis.lower()
            if "narrower" in scope_lower or "specific" in scope_lower:
                args.append(
                    DebateArgument(
                        round=1,
                        advocate="target",
                        side=ArgumentSide.FOR,
                        evidence_type=EvidenceType.SCOPE_RELATIONSHIP,
                        claim=(
                            "Scope analysis confirms directional narrowMatch relationship; "
                            "target is appropriately broader."
                        ),
                        confidence=0.80,
                    )
                )
            elif not semantic_scope_analysis or scope_lower in ("", "unknown"):
                # 5. Scope AGAINST — missing scope analysis
                args.append(
                    DebateArgument(
                        round=1,
                        advocate="target",
                        side=ArgumentSide.AGAINST,
                        evidence_type=EvidenceType.SCOPE_RELATIONSHIP,
                        claim=(
                            "Scope analysis is empty or unknown; directional relationship "
                            "is unverified."
                        ),
                        confidence=0.75,
                    )
                )

        # 6. Semantic overreach AGAINST — equivalentClass/equivalentProperty
        if ontology_relation in (
            OntologyRelation.EQUIVALENT_CLASS,
            OntologyRelation.EQUIVALENT_PROPERTY,
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.SEMANTIC_OVERREACH,
                    claim=(
                        "owl:equivalentClass/Property requires formal OWL consistency evidence; "
                        "this is a very strong logical claim."
                    ),
                    confidence=0.90,
                )
            )

        return args

    # ------------------------------------------------------------------
    # Schema-align heuristics
    # ------------------------------------------------------------------

    def _schema_args(self, hyp: Any) -> list[DebateArgument]:
        from mapping_co_scientist.schema_align.models.transformation_rule import MappingOperation

        args: list[DebateArgument] = []
        source_datatype: str | None = getattr(hyp, "source_datatype", None)
        target_datatype: str | None = getattr(hyp, "target_datatype", None)
        mapping_operation = hyp.mapping_operation
        information_loss: bool = getattr(hyp, "information_loss", False)

        numeric_types = {"number", "integer"}

        # 1. Type incompatibility AGAINST — DIRECT_COPY/RENAME with mismatched types
        if (
            source_datatype
            and target_datatype
            and source_datatype != target_datatype
            and mapping_operation in (MappingOperation.DIRECT_COPY, MappingOperation.RENAME)
            and not ({source_datatype, target_datatype} <= numeric_types)
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.TYPE_INCOMPATIBILITY,
                    claim=(
                        f"DIRECT_COPY/RENAME from {source_datatype} to {target_datatype} will "
                        f"cause a runtime type error or silent coercion; operation must be "
                        f"DATATYPE_CONVERSION."
                    ),
                    confidence=0.85,
                )
            )

        # 2. Operation safety FOR — compatible types
        if (
            source_datatype
            and target_datatype
            and (
                source_datatype == target_datatype
                or ({source_datatype, target_datatype} <= numeric_types)
            )
            and mapping_operation != MappingOperation.UNMAPPED
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.FOR,
                    evidence_type=EvidenceType.OPERATION_SAFETY,
                    claim=(
                        f"Source and target datatypes are compatible; "
                        f"{mapping_operation} is operationally safe."
                    ),
                    confidence=0.80,
                )
            )

        # 3. Information loss AGAINST — loss without conversion operation
        if (
            information_loss
            and mapping_operation
            not in (
                MappingOperation.DATATYPE_CONVERSION,
                MappingOperation.UNIT_CONVERSION,
                MappingOperation.ENUMERATION_REMAPPING,
            )
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.AGAINST,
                    evidence_type=EvidenceType.INFORMATION_LOSS_RISK,
                    claim=(
                        f"Information loss is flagged but the operation is {mapping_operation}, "
                        f"not a conversion; target consumers will receive incorrect or "
                        f"truncated values."
                    ),
                    confidence=0.85,
                )
            )

        # 4. Structural type match FOR — same datatype with structural operations
        if (
            source_datatype
            and target_datatype
            and source_datatype == target_datatype
            and mapping_operation
            in (
                MappingOperation.NESTED_PATH,
                MappingOperation.DIRECT_COPY,
                MappingOperation.RENAME,
            )
        ):
            args.append(
                DebateArgument(
                    round=1,
                    advocate="target",
                    side=ArgumentSide.FOR,
                    evidence_type=EvidenceType.STRUCTURAL_TYPE_MATCH,
                    claim=(
                        f"Source ({source_datatype}) and target ({target_datatype}) share the "
                        f"same datatype; structural mapping is sound."
                    ),
                    confidence=0.75,
                )
            )

        return args
