"""SHACL validation adapter. Requires pyshacl (optional dependency)."""
from __future__ import annotations
from pathlib import Path


def validate_with_shacl(
    data_graph_path: Path,
    shapes_graph_path: Path,
) -> tuple[bool, str]:
    """Validate RDF data against SHACL shapes. Returns (conforms, report_text)."""
    try:
        import pyshacl  # type: ignore[import]
    except ImportError:
        return True, "pyshacl not installed; SHACL validation skipped."

    conforms, _, report_text = pyshacl.validate(
        str(data_graph_path),
        shacl_graph=str(shapes_graph_path),
        inference="rdfs",
    )
    return conforms, report_text
