"""
Loads OWL ontologies and RDF graphs as ontology term profiles using rdflib.
Supports OWL/XML, Turtle, N-Triples, JSON-LD formats. Falls back gracefully
if rdflib is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import rdflib
    import rdflib.namespace
    from rdflib import Graph, URIRef
    from rdflib.namespace import OWL, RDF, RDFS, SKOS

    HAS_RDFLIB = True
except ImportError:
    HAS_RDFLIB = False

from ontology_mapping_co_scientist.models.entities import OntologyTerm

# ---------------------------------------------------------------------------
# Known CURIE prefix map (longest-prefix-first matching)
# ---------------------------------------------------------------------------

_KNOWN_PREFIXES: list[tuple[str, str]] = [
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs"),
    ("http://www.w3.org/2002/07/owl#", "owl"),
    ("http://www.w3.org/2004/02/skos/core#", "skos"),
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf"),
    ("http://purl.obolibrary.org/obo/OBI_", "obi"),
    ("http://purl.obolibrary.org/obo/UBERON_", "uberon"),
    ("http://purl.obolibrary.org/obo/CHEBI_", "chebi"),
    ("http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#", "ncit"),
    ("http://purl.obolibrary.org/obo/PATO_", "pato"),
    ("http://purl.obolibrary.org/obo/RO_", "ro"),
]


def _uri_to_curie(uri: str) -> str:
    """Convert a URI to a CURIE if a known prefix matches, else return the URI.

    Args:
        uri: A full URI string.

    Returns:
        A CURIE string (e.g. ``"obi:0000070"``) or the original URI.
    """
    for prefix_uri, prefix_name in _KNOWN_PREFIXES:
        if uri.startswith(prefix_uri):
            local = uri[len(prefix_uri):]
            return f"{prefix_name}:{local}"
    return uri


def _local_name(uri: str) -> str:
    """Extract the local name from a URI (after the last ``#`` or ``/``).

    Args:
        uri: A full URI string.

    Returns:
        The local fragment or path segment.
    """
    for sep in ("#", "/"):
        idx = uri.rfind(sep)
        if idx != -1:
            return uri[idx + 1:]
    return uri


def _best_lang_literal(graph: "rdflib.Graph", subject: "URIRef", predicate: "URIRef") -> str | None:
    """Return the best string literal for a subject/predicate pair.

    Prefers English ``@en`` literals; falls back to any literal value.

    Args:
        graph: The RDF graph.
        subject: The subject URI.
        predicate: The predicate URI.

    Returns:
        A string value, or ``None`` if no literal exists.
    """
    en_value: str | None = None
    any_value: str | None = None

    for obj in graph.objects(subject, predicate):
        obj_str = str(obj)
        lang = getattr(obj, "language", None)
        if lang and lang.startswith("en"):
            en_value = obj_str
        elif any_value is None:
            any_value = obj_str

    return en_value if en_value is not None else any_value


def _collect_literals(graph: "rdflib.Graph", subject: "URIRef", predicate: "URIRef") -> list[str]:
    """Collect all string literal values for a subject/predicate pair.

    Args:
        graph: The RDF graph.
        subject: The subject URI.
        predicate: The predicate URI.

    Returns:
        A list of string values (deduplicated, order preserved).
    """
    seen: set[str] = set()
    values: list[str] = []
    for obj in graph.objects(subject, predicate):
        s = str(obj)
        if s not in seen:
            seen.add(s)
            values.append(s)
    return values


def _detect_ontology_id(graph: "rdflib.Graph") -> str:
    """Attempt to derive a short ontology ID from the graph's ontology URI.

    Args:
        graph: The loaded RDF graph.

    Returns:
        A short identifier string (e.g. ``"obi"``), or ``"unknown"`` if
        no ontology URI can be found.
    """
    if not HAS_RDFLIB:
        return "unknown"

    for ontology_uri in graph.subjects(RDF.type, OWL.Ontology):
        uri_str = str(ontology_uri)
        # Extract last path/fragment component
        local = _local_name(uri_str).lower().rstrip("/")
        if local:
            # Strip common suffixes
            for suffix in (".owl", ".ttl", ".obo", ".rdf"):
                if local.endswith(suffix):
                    local = local[: -len(suffix)]
            return local if local else "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def detect_ontology_format(filepath: str | Path) -> str:
    """Detect the RDF serialisation format of a file.

    Checks the file extension first, then reads the first few bytes to
    identify format-specific markers.

    Args:
        filepath: Path to the RDF file.

    Returns:
        One of ``"turtle"``, ``"xml"``, ``"ntriples"``, ``"json-ld"``, or
        ``"unknown"``.
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    # Extension-based detection
    ext_map: dict[str, str] = {
        ".ttl": "turtle",
        ".turtle": "turtle",
        ".owl": "xml",
        ".rdf": "xml",
        ".xml": "xml",
        ".nt": "ntriples",
        ".ntriples": "ntriples",
        ".n3": "turtle",
        ".jsonld": "json-ld",
        ".json": "json-ld",
    }
    if ext in ext_map:
        return ext_map[ext]

    # Content-based detection (first 512 bytes)
    try:
        with filepath.open("rb") as fh:
            header = fh.read(512).lstrip()
    except OSError:
        return "unknown"

    if header.startswith(b"{") or header.startswith(b"["):
        return "json-ld"
    if b"<?xml" in header or b"<rdf:RDF" in header or b"<owl:" in header:
        return "xml"
    if header.startswith(b"@prefix") or header.startswith(b"@base") or b"a owl:" in header:
        return "turtle"
    # N-Triples lines look like: <uri> <uri> <...> .
    if header.startswith(b"<"):
        return "ntriples"

    return "unknown"


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_rdf_ontology(
    filepath_or_url: str | Path,
    ontology_id: str | None = None,
    term_types: list[str] | None = None,
    max_terms: int = 5000,
) -> list[OntologyTerm]:
    """Load an OWL/RDF ontology and return one :class:`OntologyTerm` per class/property.

    Uses rdflib to parse the file (auto-detects serialisation format).

    Extracted information per term:

    * ``term_id`` – CURIE form when a known prefix matches, else full URI.
    * ``label`` – ``rdfs:label`` (English preferred), else ``skos:prefLabel``,
      else local name from URI.
    * ``definition`` – ``skos:definition`` (English preferred), else
      ``rdfs:comment``.
    * ``synonyms`` – ``skos:altLabel`` + ``skos:hiddenLabel`` values.
    * ``parent_terms`` – direct ``rdfs:subClassOf`` values (blank nodes skipped).
    * ``term_type`` – ``"class"`` or ``"property"``.
    * ``ontology_id`` – from the *ontology_id* parameter or derived from the
      graph's ontology URI.
    * ``ontology_source`` – string form of *filepath_or_url*.
    * ``extra_context`` – ``{"domain": [...], "range": [...]}``.

    Args:
        filepath_or_url: Path or URL of the ontology file.
        ontology_id: Short identifier to use for all terms.  If ``None``,
            derived from the ontology URI in the graph.
        term_types: If provided, only terms of these types are returned
            (e.g. ``["class"]`` to exclude properties).
        max_terms: Maximum number of terms to return (default 5000).

    Returns:
        A list of :class:`OntologyTerm` objects sorted by ``term_id``.

    Raises:
        ImportError: If rdflib is not installed.
    """
    if not HAS_RDFLIB:
        raise ImportError(
            "rdflib is required for RDF/OWL loading. Install with: pip install rdflib"
        )

    source_str = str(filepath_or_url)
    graph = rdflib.Graph()
    graph.parse(source_str)

    # Derive ontology_id from graph if not provided
    if ontology_id is None:
        ontology_id = _detect_ontology_id(graph)

    terms: list[OntologyTerm] = []
    seen_ids: set[str] = set()

    # Collect class subjects
    class_subjects: set[URIRef] = set()
    for s in graph.subjects(RDF.type, OWL.Class):
        if not isinstance(s, rdflib.BNode):
            class_subjects.add(s)  # type: ignore[arg-type]

    # Collect property subjects
    property_subjects: set[URIRef] = set()
    for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty):
        for s in graph.subjects(RDF.type, prop_type):
            if not isinstance(s, rdflib.BNode):
                property_subjects.add(s)  # type: ignore[arg-type]

    def _process_subject(subject: "URIRef", term_type: str) -> OntologyTerm | None:
        uri_str = str(subject)
        term_id = _uri_to_curie(uri_str)

        if term_id in seen_ids:
            return None
        seen_ids.add(term_id)

        # Label
        label = (
            _best_lang_literal(graph, subject, RDFS.label)
            or _best_lang_literal(graph, subject, SKOS.prefLabel)
            or _local_name(uri_str)
        )

        # Definition
        definition = (
            _best_lang_literal(graph, subject, SKOS.definition)
            or _best_lang_literal(graph, subject, RDFS.comment)
        )

        # Synonyms: skos:altLabel + skos:hiddenLabel
        synonyms: list[str] = (
            _collect_literals(graph, subject, SKOS.altLabel)
            + _collect_literals(graph, subject, SKOS.hiddenLabel)
        )

        # Parent terms (direct subClassOf, skip blank nodes)
        parent_terms: list[str] = []
        for parent in graph.objects(subject, RDFS.subClassOf):
            if not isinstance(parent, rdflib.BNode):
                parent_terms.append(_uri_to_curie(str(parent)))

        # Domain and range (for properties)
        domain_values = [
            _uri_to_curie(str(d))
            for d in graph.objects(subject, RDFS.domain)
            if not isinstance(d, rdflib.BNode)
        ]
        range_values = [
            _uri_to_curie(str(r))
            for r in graph.objects(subject, RDFS.range)
            if not isinstance(r, rdflib.BNode)
        ]

        extra_context: dict[str, Any] = {
            "domain": domain_values,
            "range": range_values,
        }

        return OntologyTerm(
            term_id=term_id,
            label=label,
            definition=definition,
            synonyms=synonyms,
            parent_terms=parent_terms,
            term_type=term_type,
            ontology_id=ontology_id,
            ontology_source=source_str,
            extra_context=extra_context,
        )

    # Process classes
    if term_types is None or "class" in term_types:
        for subject in class_subjects:
            if len(terms) >= max_terms:
                break
            term = _process_subject(subject, "class")
            if term is not None:
                terms.append(term)

    # Process properties
    if term_types is None or "property" in term_types:
        for subject in property_subjects:
            if len(terms) >= max_terms:
                break
            term = _process_subject(subject, "property")
            if term is not None:
                terms.append(term)

    terms.sort(key=lambda t: t.term_id)
    return terms
