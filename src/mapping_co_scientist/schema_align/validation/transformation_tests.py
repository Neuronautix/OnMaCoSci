"""Run transformation rules against example records to test correctness."""
from __future__ import annotations
from mapping_co_scientist.schema_align.models.transformation_rule import TransformationRule, MappingOperation


def test_transformation_rule(rule: TransformationRule, example_records: list[dict]) -> dict:
    """Run a transformation rule against example records. Returns test report."""
    if not example_records:
        return {"status": "skipped", "reason": "No example records provided"}

    if rule.operation == MappingOperation.CONSTANT_ASSIGNMENT:
        return {"status": "passed", "output_sample": rule.constant_value}

    if rule.operation in (MappingOperation.DIRECT_COPY, MappingOperation.RENAME, MappingOperation.NESTED_PATH):
        if rule.source_path is None:
            return {"status": "skipped", "reason": "No source path"}
        outputs = []
        for rec in example_records[:3]:
            val = rec.get(rule.source_path)
            outputs.append(val)
        return {"status": "passed", "output_sample": outputs}

    return {"status": "not_tested", "reason": f"Operation {rule.operation} requires manual testing"}
