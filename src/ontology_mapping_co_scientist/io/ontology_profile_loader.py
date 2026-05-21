"""Ontology profile loader for the Ontology Mapping Co-Scientist system.

Reads a YAML or JSON file describing a subset of ontology terms and returns a
list of :class:`OntologyTerm` objects.

Expected file format (YAML example)::

    ontology_id: "mbo"
    ontology_source: "Mouse Background Ontology"
    description: "Terms relevant to mouse phenotyping"
    terms:
      - term_id: "mbo:MouseStrain"
        label: "mouse strain"
        definition: "A genetically distinct mouse lineage."
        synonyms: ["strain", "genetic background"]
        parent_terms: ["mbo:BiologicalCharacteristic"]
        term_type: "class"
        extra_context:
          xref: "MP:0000001"

Top-level ``ontology_id`` and ``ontology_source`` are used as defaults for any
term that does not specify its own values.  All fields apart from ``term_id``
and ``label`` are optional and default to ``None`` or ``[]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml  # PyYAML – listed as a project dependency

from ontology_mapping_co_scientist.models import OntologyTerm


def _load_file(filepath: Path) -> dict[str, Any]:
    """Parse a YAML or JSON file and return the top-level dict.

    YAML is tried first (it is a strict superset of JSON, so pure JSON files
    are also handled correctly by the YAML parser).  If the file extension is
    explicitly ``.json`` the JSON stdlib parser is used directly for speed and
    stricter error messages.

    Args:
        filepath: Resolved :class:`pathlib.Path` to the input file.

    Returns:
        The parsed top-level mapping.

    Raises:
        ValueError: If the file cannot be parsed or its top level is not a dict.
    """
    suffix = filepath.suffix.lower()
    try:
        with filepath.open(encoding="utf-8") as fh:
            if suffix == ".json":
                data = json.load(fh)
            else:
                data = yaml.safe_load(fh)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot parse ontology profile {filepath}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Ontology profile must be a mapping at the top level, got "
            f"{type(data).__name__}: {filepath}"
        )
    return data  # type: ignore[return-value]


def _coerce_list(value: Any, default: list[Any] | None = None) -> list[Any]:
    """Return *value* as a list, or *default* (empty list) if absent/None."""
    if value is None:
        return default if default is not None else []
    if isinstance(value, list):
        return value
    return [value]


def load_ontology_profile(filepath: str | Path) -> list[OntologyTerm]:
    """Load an ontology profile from a YAML or JSON file.

    The file must contain a top-level key ``"terms"`` whose value is a list of
    term dicts.  An optional top-level ``"ontology_id"`` and
    ``"ontology_source"`` provide defaults applied to every term that omits
    those fields.

    Term dict keys map directly to :class:`OntologyTerm` fields:

    * ``term_id`` (str, required) – unique identifier, e.g. ``"mbo:MouseStrain"``
    * ``label`` (str, required) – human-readable name
    * ``definition`` (str, optional)
    * ``synonyms`` (list[str], optional)
    * ``parent_terms`` (list[str], optional)
    * ``term_type`` (str, optional) – e.g. ``"class"``, ``"property"``
    * ``ontology_id`` (str, optional) – overrides the file-level default
    * ``ontology_source`` (str, optional) – overrides the file-level default
    * ``extra_context`` (dict, optional) – arbitrary additional metadata

    Args:
        filepath: Path to the YAML or JSON file (``str`` or :class:`pathlib.Path`).

    Returns:
        A list of :class:`OntologyTerm` objects.  Terms with missing required
        fields (``term_id`` or ``label``) are skipped with a warning printed to
        stderr rather than raising an exception, making the loader tolerant of
        partially formed profiles.

    Raises:
        FileNotFoundError: If *filepath* does not exist.
        ValueError: If the file cannot be parsed or its structure is invalid.
    """
    import sys

    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Ontology profile not found: {filepath}")

    data = _load_file(filepath)

    # File-level defaults
    default_ontology_id: str | None = data.get("ontology_id") or None
    default_ontology_source: str | None = data.get("ontology_source") or None

    raw_terms = data.get("terms", [])
    if not isinstance(raw_terms, list):
        raise ValueError(
            f"'terms' key in ontology profile must be a list: {filepath}"
        )

    terms: list[OntologyTerm] = []

    for idx, raw in enumerate(raw_terms):
        if not isinstance(raw, dict):
            print(
                f"[ontology_profile_loader] WARNING: term at index {idx} is not a "
                f"dict – skipping ({filepath})",
                file=sys.stderr,
            )
            continue

        term_id: str | None = raw.get("term_id") or None
        label: str | None = raw.get("label") or None

        if not term_id or not label:
            print(
                f"[ontology_profile_loader] WARNING: term at index {idx} is missing "
                f"'term_id' or 'label' – skipping ({filepath})",
                file=sys.stderr,
            )
            continue

        ontology_id: str | None = raw.get("ontology_id") or default_ontology_id
        ontology_source: str | None = (
            raw.get("ontology_source") or default_ontology_source
        )

        extra_context: dict[str, Any] | None = raw.get("extra_context")
        if extra_context is not None and not isinstance(extra_context, dict):
            extra_context = {"value": extra_context}

        term = OntologyTerm(
            term_id=term_id,
            label=label,
            definition=raw.get("definition") or None,
            synonyms=_coerce_list(raw.get("synonyms")),
            parent_terms=_coerce_list(raw.get("parent_terms")),
            term_type=raw.get("term_type") or None,
            ontology_id=ontology_id,
            ontology_source=ontology_source,
            extra_context=extra_context,
        )
        terms.append(term)

    return terms
