"""
SPARQL competency question (CQ) validation for accepted mappings.

Competency questions are SPARQL ASK or SELECT queries that express requirements
that the accepted mappings must satisfy. For example:
  "For every source entity of type 'number', there must exist an accepted mapping
   to an ontology term that is a property (not a class)."

The agent constructs a small RDF graph from accepted mappings and runs CQs against it.
Requires rdflib.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingHypothesis

if TYPE_CHECKING:
    import rdflib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional rdflib import
# ---------------------------------------------------------------------------

try:
    import rdflib as _rdflib

    HAS_RDFLIB = True
except ImportError:
    HAS_RDFLIB = False

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

_OMCS_NS = "https://w3id.org/omcs/mapping#"
_SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
_XSD_NS = "http://www.w3.org/2001/XMLSchema#"
_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


# ---------------------------------------------------------------------------
# CQ models
# ---------------------------------------------------------------------------


class CompetencyQuestion(BaseModel):
    """A single SPARQL-based competency question."""

    cq_id: str
    description: str
    sparql: str  # SPARQL ASK query
    severity: str  # "error" | "warning"

    model_config = {"frozen": False}


class CQResult(BaseModel):
    """Result of running a single competency question."""

    cq_id: str
    passed: bool
    description: str
    severity: str

    model_config = {"frozen": False}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class SPARQLCompetencyAgent:
    """
    Validates accepted mappings by running SPARQL competency questions
    against an RDF graph constructed from the hypotheses.

    Built-in competency questions are defined in :attr:`BUILT_IN_CQS`.
    Additional questions can be added at construction time.

    When rdflib is not installed, all CQs are returned as failed with a
    descriptive message.
    """

    BUILT_IN_CQS: list[CompetencyQuestion] = [
        CompetencyQuestion(
            cq_id="CQ001",
            description="Every source entity has at least one mapping hypothesis",
            sparql="""
                PREFIX omcs: <https://w3id.org/omcs/mapping#>
                ASK { ?s a omcs:MappingHypothesis }
            """,
            severity="warning",
        ),
        CompetencyQuestion(
            cq_id="CQ002",
            description="No mapping has confidence above 1.0",
            sparql="""
                PREFIX omcs: <https://w3id.org/omcs/mapping#>
                PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                ASK {
                    ?m omcs:confidence ?c .
                    FILTER(?c <= 1.0)
                }
            """,
            severity="error",
        ),
    ]

    def __init__(
        self,
        extra_cqs: list[CompetencyQuestion] | None = None,
    ) -> None:
        self.cqs: list[CompetencyQuestion] = list(self.BUILT_IN_CQS) + (extra_cqs or [])

    # ------------------------------------------------------------------
    # RDF graph construction
    # ------------------------------------------------------------------

    def hypotheses_to_graph(
        self, hypotheses: list[MappingHypothesis]
    ) -> rdflib.Graph:
        """Converts hypotheses to an RDF graph for SPARQL querying.

        Each hypothesis contributes:
        - ``<mapping_id> rdf:type omcs:MappingHypothesis``
        - ``<mapping_id> omcs:sourceEntity <source_entity_id>``
        - ``<mapping_id> omcs:targetEntity <target_entity_id>``
        - ``<mapping_id> omcs:confidence "<value>"^^xsd:decimal``
        - ``<source_entity_id> omcs:datatype "<value>"``
        - ``<source_entity_id> omcs:sourceType "<value>"``

        Args:
            hypotheses: The list of mapping hypotheses.

        Returns:
            An :class:`rdflib.Graph` containing all triples.
        """
        g = _rdflib.Graph()

        omcs = _rdflib.Namespace(_OMCS_NS)
        xsd = _rdflib.Namespace(_XSD_NS)
        rdf = _rdflib.Namespace(_RDF_NS)

        for hypothesis in hypotheses:
            mapping_uri = _rdflib.URIRef(f"{_OMCS_NS}{hypothesis.mapping_id}")
            source_uri = _rdflib.URIRef(
                f"{_OMCS_NS}{hypothesis.source_entity.entity_id}"
            )
            target_uri = _rdflib.URIRef(
                f"{_OMCS_NS}{hypothesis.target_entity.term_id}"
            )

            g.add((mapping_uri, rdf.type, omcs.MappingHypothesis))
            g.add((mapping_uri, omcs.sourceEntity, source_uri))
            g.add((mapping_uri, omcs.targetEntity, target_uri))
            g.add((
                mapping_uri,
                omcs.confidence,
                _rdflib.Literal(
                    str(hypothesis.confidence),
                    datatype=xsd.decimal,
                ),
            ))

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
    # CQ execution
    # ------------------------------------------------------------------

    def run_cqs(
        self, hypotheses: list[MappingHypothesis]
    ) -> list[CQResult]:
        """Run all competency questions against a graph built from *hypotheses*.

        For each CQ, an ASK query is executed.  The CQ passes if the query
        returns ``True``.

        When rdflib is not installed, all CQs are returned as failed.

        Args:
            hypotheses: The list of mapping hypotheses to validate.

        Returns:
            A list of :class:`CQResult` objects, one per CQ.
        """
        results: list[CQResult] = []

        if not HAS_RDFLIB:
            for cq in self.cqs:
                results.append(
                    CQResult(
                        cq_id=cq.cq_id,
                        passed=False,
                        description=f"{cq.description} [rdflib not installed]",
                        severity=cq.severity,
                    )
                )
            return results

        graph = self.hypotheses_to_graph(hypotheses)

        for cq in self.cqs:
            try:
                query_result = graph.query(cq.sparql.strip())
                # ASK queries return a result object where bool(result) gives the answer
                passed = bool(query_result)
            except Exception as exc:
                logger.warning("CQ %s failed to execute: %s", cq.cq_id, exc)
                passed = False

            results.append(
                CQResult(
                    cq_id=cq.cq_id,
                    passed=passed,
                    description=cq.description,
                    severity=cq.severity,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self, results: list[CQResult]) -> dict:
        """Return a summary dict for a list of CQ results.

        Keys:
        - ``total`` — total number of CQs run.
        - ``passed`` — number of CQs that passed.
        - ``failed`` — number of CQs that failed.
        - ``errors`` — number of CQs with severity ``"error"`` that failed.
        - ``warnings`` — number of CQs with severity ``"warning"`` that failed.

        Args:
            results: The list of CQ results.

        Returns:
            A summary dictionary.
        """
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        errors = sum(1 for r in results if not r.passed and r.severity == "error")
        warnings = sum(1 for r in results if not r.passed and r.severity == "warning")
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "warnings": warnings,
        }
