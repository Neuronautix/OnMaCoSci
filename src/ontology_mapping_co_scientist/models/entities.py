"""Pydantic models for source entities and ontology terms.

This module defines the two primary entity types that participate in an
ontology mapping: a :class:`SourceEntity` representing a field or concept
extracted from an upstream data source (CSV column, OpenAPI parameter,
JSON Schema property, etc.), and an :class:`OntologyTerm` representing a
term that lives inside a formal ontology.

Both models are intentionally light-weight value objects — they carry the
raw facts needed by the mapping pipeline and do *not* contain any mapping
logic themselves.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SourceEntity(BaseModel):
    """A single field or concept extracted from a source data artefact.

    A ``SourceEntity`` is the *left-hand side* of an ontology mapping: it
    represents something from the real world that a data producer is
    already capturing (e.g. the CSV column ``animal.strain``) and that we
    want to link to a well-defined ontology term.

    Attributes:
        entity_id: A globally unique identifier for this entity within the
            pipeline run, following the convention
            ``<source_type>:<field_path>``, e.g. ``"csv:animal.strain"``.
        label: Human-readable name of the entity, typically derived from
            the column header, property name, or parameter label.
        description: Optional free-text description scraped from the source
            artefact (e.g. a CSV header comment, OpenAPI ``description``
            field, or JSON Schema ``description`` annotation).
        datatype: The primitive data type declared in the source artefact,
            e.g. ``"string"``, ``"number"``, ``"boolean"``, ``"integer"``,
            ``"array"``.  ``None`` when the source does not declare a type.
        examples: A list of representative example values for this entity,
            used by scoring agents to infer semantic meaning when label and
            description are insufficient.
        source_file: Path or URL of the originating artefact, e.g.
            ``"data/animals.csv"`` or
            ``"https://api.example.com/openapi.json"``.
        source_type: The kind of artefact this entity was extracted from.
            Well-known values: ``"csv"``, ``"openapi"``, ``"json_schema"``,
            ``"database_column"``.
        extra_context: An open-ended dictionary for any additional
            metadata that a specific extractor agent may want to attach
            (e.g. ``{"units": "kg", "nullable": true}``).
    """

    entity_id: str = Field(
        ...,
        description=(
            "Unique identifier for this entity within the pipeline run, "
            "e.g. 'csv:animal.strain'."
        ),
    )
    label: str = Field(
        ...,
        description="Human-readable name derived from the source artefact.",
    )
    description: str | None = Field(
        default=None,
        description="Optional free-text description from the source artefact.",
    )
    datatype: str | None = Field(
        default=None,
        description=(
            "Primitive data type declared in the source, e.g. 'string', "
            "'number', 'boolean'.  None when not declared."
        ),
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Representative sample values that help infer semantic meaning.",
    )
    source_file: str | None = Field(
        default=None,
        description="Path or URL of the originating data artefact.",
    )
    source_type: str = Field(
        ...,
        description=(
            "Kind of artefact this entity was extracted from, "
            "e.g. 'csv', 'openapi', 'json_schema'."
        ),
    )
    extra_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional metadata attached by the extractor agent.",
    )

    model_config = {"frozen": False, "extra": "forbid"}

    def __str__(self) -> str:
        """Return a concise string representation."""
        parts = [f"SourceEntity(id={self.entity_id!r}, label={self.label!r}"]
        if self.datatype:
            parts.append(f", datatype={self.datatype!r}")
        parts.append(")")
        return "".join(parts)


class OntologyTerm(BaseModel):
    """A single term from a formal ontology.

    An ``OntologyTerm`` is the *right-hand side* of an ontology mapping: it
    represents a well-defined concept whose semantics are governed by an
    ontology (OWL, OBO, SKOS, etc.).

    Attributes:
        term_id: The canonical identifier for this term, either in CURIE
            form (e.g. ``"mbo:GeneticBackground"``) or as a full IRI
            (e.g. ``"http://purl.obolibrary.org/obo/MBO_0001234"``).
        label: The preferred label (``rdfs:label`` or ``skos:prefLabel``)
            of the term.
        definition: The formal definition of the term, typically the value
            of the ``IAO:0000115`` annotation or ``skos:definition``.
        synonyms: A list of alternative labels, including exact synonyms,
            broad synonyms, and narrow synonyms as recorded in the ontology.
        parent_terms: CURIEs or IRIs of direct super-classes or broader
            concepts (``rdfs:subClassOf`` or ``skos:broader``).  Used by
            agents to reason about term granularity.
        term_type: The logical type of this term within its ontology.
            Typical values: ``"class"``, ``"property"``, ``"individual"``,
            ``"annotation_property"``.
        ontology_id: Short identifier of the source ontology, e.g.
            ``"mbo"``, ``"ncit"``, ``"hp"``, ``"chebi"``.
        ontology_source: URL or file path from which this term was loaded,
            e.g. ``"http://purl.obolibrary.org/obo/mbo.owl"`` or a local
            OBO/JSON path.
        extra_context: An open-ended dictionary for additional term
            metadata such as ``{"deprecated": false, "in_subset": ["slim"]}``.
    """

    term_id: str = Field(
        ...,
        description=(
            "Canonical identifier in CURIE or IRI form, "
            "e.g. 'mbo:GeneticBackground' or "
            "'http://purl.obolibrary.org/obo/MBO_0001234'."
        ),
    )
    label: str = Field(
        ...,
        description="Preferred label of the term (rdfs:label or skos:prefLabel).",
    )
    definition: str | None = Field(
        default=None,
        description=(
            "Formal definition (IAO:0000115 or skos:definition).  "
            "None when not present in the ontology."
        ),
    )
    synonyms: list[str] = Field(
        default_factory=list,
        description="Alternative labels including exact, broad, and narrow synonyms.",
    )
    parent_terms: list[str] = Field(
        default_factory=list,
        description=(
            "CURIEs or IRIs of direct superclasses or broader concepts "
            "(rdfs:subClassOf / skos:broader)."
        ),
    )
    term_type: str = Field(
        ...,
        description=(
            "Logical type of this term, e.g. 'class', 'property', 'individual'."
        ),
    )
    ontology_id: str = Field(
        ...,
        description=(
            "Short identifier for the source ontology, e.g. 'mbo', 'ncit', 'hp'."
        ),
    )
    ontology_source: str | None = Field(
        default=None,
        description="URL or file path from which this term was loaded.",
    )
    extra_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional term metadata (e.g. subset memberships).",
    )

    model_config = {"frozen": False, "extra": "forbid"}

    def __str__(self) -> str:
        """Return a concise string representation."""
        return (
            f"OntologyTerm(id={self.term_id!r}, label={self.label!r}, "
            f"ontology={self.ontology_id!r})"
        )
