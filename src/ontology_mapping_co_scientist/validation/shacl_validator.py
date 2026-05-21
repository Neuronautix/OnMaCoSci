"""
SHACL validation for mapping hypotheses.
Validates that proposed mappings do not violate SHACL shapes constraints.
Requires: pyshacl (pip install pyshacl), rdflib

Both are optional dependencies — graceful ImportError if missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingHypothesis

if TYPE_CHECKING:
    import rdflib

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

try:
    import pyshacl
    import rdflib as _rdflib

    HAS_SHACL = True
except ImportError:
    HAS_SHACL = False

# ---------------------------------------------------------------------------
# Namespace constants (used even when rdflib is absent, as plain strings)
# ---------------------------------------------------------------------------

_OMCS_NS = "https://w3id.org/omcs/mapping#"
_SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
_XSD_NS = "http://www.w3.org/2001/XMLSchema#"
_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class SHACLValidationResult(BaseModel):
    """Result of a SHACL validation for a single mapping hypothesis."""

    mapping_id: str
    conforms: bool
    violation_messages: list[str] = Field(default_factory=list)
    shapes_used: str | None = None  # path to shapes graph

    model_config = {"frozen": False}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class SHACLValidator:
    """
    Validates mapping hypotheses against a SHACL shapes graph.

    Usage::

        validator = SHACLValidator("examples/shacl/preclinical_shapes.ttl")
        results = validator.validate_hypotheses(hypotheses)

    If ``shapes_graph_path`` is ``None``, all hypotheses are returned as
    conformant (no shapes to validate against).

    Both ``pyshacl`` and ``rdflib`` are optional; when either is absent and a
    ``shapes_graph_path`` is given, an :class:`ImportError` is raised at
    construction time.
    """

    def __init__(self, shapes_graph_path: str | Path | None = None) -> None:
        if not HAS_SHACL and shapes_graph_path is not None:
            raise ImportError(
                "pyshacl and rdflib are required for SHACL validation. "
                "pip install pyshacl rdflib"
            )
        self.shapes_graph_path = Path(shapes_graph_path) if shapes_graph_path else None
        self._shapes_graph: rdflib.Graph | None = None  # lazy load

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_shapes(self) -> rdflib.Graph | None:
        """Load SHACL shapes graph from file. Returns None if no path set."""
        if self.shapes_graph_path is None:
            return None
        if self._shapes_graph is not None:
            return self._shapes_graph
        graph = _rdflib.Graph()
        graph.parse(str(self.shapes_graph_path))
        self._shapes_graph = graph
        return graph

    def hypothesis_to_rdf(self, hypothesis: MappingHypothesis) -> rdflib.Graph:
        """
        Converts one MappingHypothesis to a minimal RDF graph for SHACL validation.

        Creates triples::

            <mapping_id>       rdf:type                omcs:MappingHypothesis
            <mapping_id>       omcs:sourceEntity        <source_entity_id>
            <mapping_id>       omcs:targetEntity        <target_entity_id>
            <mapping_id>       skos:mappingRelation     <predicate_uri>
            <mapping_id>       omcs:confidence          "0.85"^^xsd:decimal
            <source_entity_id> omcs:datatype            "number"
            <source_entity_id> omcs:sourceType          "csv"
        """
        g = _rdflib.Graph()

        omcs = _rdflib.Namespace(_OMCS_NS)
        skos = _rdflib.Namespace(_SKOS_NS)
        xsd = _rdflib.Namespace(_XSD_NS)
        rdf = _rdflib.Namespace(_RDF_NS)

        # Build URIs
        mapping_uri = _rdflib.URIRef(f"{_OMCS_NS}{hypothesis.mapping_id}")
        source_uri = _rdflib.URIRef(f"{_OMCS_NS}{hypothesis.source_entity.entity_id}")
        target_uri = _rdflib.URIRef(f"{_OMCS_NS}{hypothesis.target_entity.term_id}")

        # Map predicate value to URI
        predicate_str = str(hypothesis.predicate.value)
        # Convert "skos:exactMatch" -> "http://www.w3.org/2004/02/skos/core#exactMatch"
        if predicate_str.startswith("skos:"):
            local = predicate_str.split("skos:")[1]
            predicate_uri = _rdflib.URIRef(f"{_SKOS_NS}{local}")
        elif predicate_str.startswith("custom:"):
            local = predicate_str.split("custom:")[1]
            predicate_uri = _rdflib.URIRef(f"{_OMCS_NS}{local}")
        else:
            predicate_uri = _rdflib.URIRef(predicate_str)

        # Mapping hypothesis triples
        g.add((mapping_uri, rdf.type, omcs.MappingHypothesis))
        g.add((mapping_uri, omcs.sourceEntity, source_uri))
        g.add((mapping_uri, omcs.targetEntity, target_uri))
        g.add((mapping_uri, skos.mappingRelation, predicate_uri))
        g.add((
            mapping_uri,
            omcs.confidence,
            _rdflib.Literal(
                str(hypothesis.confidence),
                datatype=xsd.decimal,
            ),
        ))

        # Source entity triples
        if hypothesis.source_entity.datatype:
            g.add((
                source_uri,
                omcs.datatype,
                _rdflib.Literal(hypothesis.source_entity.datatype),
            ))
        g.add((
            source_uri,
            omcs.sourceType,
            _rdflib.Literal(hypothesis.source_entity.source_type),
        ))

        return g

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate_hypothesis(self, hypothesis: MappingHypothesis) -> SHACLValidationResult:
        """
        Validates a single hypothesis against the shapes graph.

        If no shapes graph is loaded, returns a conformant result immediately.

        Args:
            hypothesis: The mapping hypothesis to validate.

        Returns:
            A :class:`SHACLValidationResult` for the hypothesis.
        """
        shapes_path_str = str(self.shapes_graph_path) if self.shapes_graph_path else None

        if self.shapes_graph_path is None or not HAS_SHACL:
            return SHACLValidationResult(
                mapping_id=hypothesis.mapping_id,
                conforms=True,
                violation_messages=[],
                shapes_used=None,
            )

        shapes_graph = self._load_shapes()
        data_graph = self.hypothesis_to_rdf(hypothesis)

        conforms, results_graph, results_text = pyshacl.validate(
            data_graph,
            shacl_graph=shapes_graph,
            inference="rdfs",
            abort_on_first=False,
        )

        violation_messages: list[str] = []
        if not conforms:
            # Parse violation messages from results text
            for line in (results_text or "").splitlines():
                line = line.strip()
                if line and not line.startswith("Validation") and not line.startswith("---"):
                    violation_messages.append(line)

        return SHACLValidationResult(
            mapping_id=hypothesis.mapping_id,
            conforms=bool(conforms),
            violation_messages=violation_messages,
            shapes_used=shapes_path_str,
        )

    def validate_hypotheses(
        self, hypotheses: list[MappingHypothesis]
    ) -> list[SHACLValidationResult]:
        """Validate all hypotheses and return one result per hypothesis.

        Args:
            hypotheses: The list of mapping hypotheses to validate.

        Returns:
            A list of :class:`SHACLValidationResult` objects.
        """
        return [self.validate_hypothesis(h) for h in hypotheses]
