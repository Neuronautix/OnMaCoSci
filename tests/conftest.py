"""Shared pytest fixtures for the ontology-mapping-co-scientist test suite.

All fixtures are session-independent and deterministic.  Fixtures that require
temporary file-system access use pytest's built-in ``tmp_path`` fixture, which
provides a fresh temporary directory per test invocation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Make the src/ layout importable without an editable install.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity
from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    Evidence,
    HumanReviewStatus,
    MappingHypothesis,
    MappingPredicate,
    Provenance,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# Entity fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_source_entity() -> SourceEntity:
    """Return a SourceEntity representing the 'strain' column from an animal CSV.

    Uses a realistic entity_id convention (``csv:<stem>.<column>``) with two
    representative mouse-strain example values.
    """
    return SourceEntity(
        entity_id="csv:animal.strain",
        label="strain",
        description="Genetic strain identifier for the animal",
        datatype="string",
        examples=["C57BL/6J", "BALB/c"],
        source_file="data/animal.csv",
        source_type="csv",
        extra_context={"column_name": "strain", "total_rows": 3},
    )


@pytest.fixture
def sample_ontology_term() -> OntologyTerm:
    """Return an OntologyTerm for 'genetic background' from a mouse background ontology.

    Includes synonyms that overlap with typical source-entity labels so that
    lexical-similarity tests have realistic data to work with.
    """
    return OntologyTerm(
        term_id="mbo:GeneticBackground",
        label="genetic background",
        definition=(
            "The genetic composition of an organism, particularly with "
            "respect to the specific combination of alleles and mutations "
            "present in the genome."
        ),
        synonyms=["strain", "mouse strain", "genetic makeup"],
        parent_terms=["mbo:BiologicalCharacteristic"],
        term_type="class",
        ontology_id="mbo",
        ontology_source="http://example.org/mbo.owl",
        extra_context={"xref": "MP:0000001"},
    )


@pytest.fixture
def sample_hypothesis(
    sample_source_entity: SourceEntity,
    sample_ontology_term: OntologyTerm,
) -> MappingHypothesis:
    """Return a MappingHypothesis with realistic values linking strain to genetic background.

    Confidence is set to 0.82 with a CLOSE_MATCH predicate to simulate a
    well-supported but not exact lexical mapping.
    """
    prov = Provenance(
        created_by="CandidateGeneratorAgent",
        created_at="2025-03-15T14:22:00Z",
        method="lexical_similarity_v1",
        pipeline_run_id="run-test-001",
    )
    evidence = [
        Evidence(
            evidence_type="lexical_similarity",
            description=(
                "Lexical similarity between 'strain' and 'genetic background': 0.82"
            ),
            score=0.82,
            source="rapidfuzz.WRatio",
        ),
        Evidence(
            evidence_type="synonym_match",
            description=(
                "Source label 'strain' matches synonym 'strain' of term mbo:GeneticBackground"
            ),
            score=0.90,
            source="synonym_lookup",
        ),
    ]
    return MappingHypothesis(
        mapping_id="map-csv_animal_strain-mbo_GeneticBackground-0",
        source_entity=sample_source_entity,
        target_entity=sample_ontology_term,
        predicate=MappingPredicate.CLOSE_MATCH,
        confidence=0.82,
        evidence=evidence,
        validation_status=ValidationStatus.PENDING,
        human_review_status=HumanReviewStatus.AWAITING_REVIEW,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# Temporary file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_csv_file(tmp_path: Path) -> Path:
    """Create a temporary CSV file with animal phenotyping columns.

    The file has four columns (animal_id, strain, sex, age_weeks) and three
    data rows with realistic values.  ``age_weeks`` contains only numeric
    values so that datatype-inference tests can verify ``"number"`` detection.

    Returns:
        Path to the created CSV file.
    """
    csv_path = tmp_path / "animals.csv"
    csv_content = (
        "animal_id,strain,sex,age_weeks\n"
        "A001,C57BL/6J,M,8\n"
        "A002,BALB/c,F,10\n"
        "A003,C57BL/6J,M,12\n"
    )
    csv_path.write_text(csv_content, encoding="utf-8")
    return csv_path


@pytest.fixture
def tmp_ontology_yaml(tmp_path: Path) -> Path:
    """Create a temporary YAML ontology profile with three representative terms.

    The profile follows the format expected by
    :func:`~ontology_mapping_co_scientist.io.ontology_profile_loader.load_ontology_profile`.
    Each term has an explicit ``extra_context: {}`` entry to satisfy the Pydantic
    validator that requires a dict (not ``None``) for that field.

    Returns:
        Path to the created YAML file.
    """
    profile: dict = {
        "ontology_id": "mbo",
        "ontology_source": "Mouse Background Ontology (test fixture)",
        "terms": [
            {
                "term_id": "mbo:MouseStrain",
                "label": "mouse strain",
                "definition": "A genetically distinct mouse lineage maintained by inbreeding.",
                "synonyms": ["strain", "genetic background", "mouse line"],
                "parent_terms": ["mbo:BiologicalCharacteristic"],
                "term_type": "class",
                "extra_context": {},
            },
            {
                "term_id": "mbo:BodyWeight",
                "label": "body weight",
                "definition": "The total measured mass of the animal at a given time point.",
                "synonyms": ["weight", "mass", "bw"],
                "parent_terms": ["mbo:Measurement"],
                "term_type": "class",
                "extra_context": {},
            },
            {
                "term_id": "mbo:BiologicalSex",
                "label": "biological sex",
                "definition": "The biological sex classification of the animal.",
                "synonyms": ["sex", "gender"],
                "parent_terms": ["mbo:BiologicalCharacteristic"],
                "term_type": "class",
                "extra_context": {},
            },
        ],
    }
    yaml_path = tmp_path / "ontology_profile.yaml"
    yaml_path.write_text(yaml.dump(profile, default_flow_style=False), encoding="utf-8")
    return yaml_path


@pytest.fixture
def tmp_openapi_json(tmp_path: Path) -> Path:
    """Create a temporary OpenAPI 3.x JSON file with one schema (Animal) and three properties.

    The ``Animal`` schema has properties: ``animal_id`` (string), ``strain``
    (string, with description and example), and ``age_weeks`` (integer).

    Returns:
        Path to the created JSON file.
    """
    spec: dict = {
        "openapi": "3.0.0",
        "info": {"title": "Animal Registry API", "version": "1.0.0"},
        "components": {
            "schemas": {
                "Animal": {
                    "type": "object",
                    "required": ["animal_id", "strain"],
                    "properties": {
                        "animal_id": {
                            "type": "string",
                            "description": "Unique identifier for the animal.",
                            "example": "A001",
                        },
                        "strain": {
                            "type": "string",
                            "description": "Genetic strain of the animal, e.g. C57BL/6J.",
                            "example": "C57BL/6J",
                        },
                        "age_weeks": {
                            "type": "integer",
                            "description": "Age of the animal in weeks at time of measurement.",
                            "example": 8,
                        },
                    },
                }
            }
        },
    }
    json_path = tmp_path / "animal_api.json"
    json_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return json_path
