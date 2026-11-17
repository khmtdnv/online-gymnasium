"""Координаты и последовательность не допускают неявных преобразований."""

from uuid import uuid4

import pytest


def batch_data(**changes):
    return {
        "batch_id": str(uuid4()),
        "sequence": 1,
        "stroke_id": str(uuid4()),
        "points": [{"x": 0.2, "y": 0.5}],
        "finished": True,
    } | changes


def test_batch_contract_rejects_bad_points_sequence_and_extra_identity():
    import json

    from pen_service.contracts import StrokeBatch

    assert StrokeBatch.model_validate_json(json.dumps(batch_data())).sequence == 1
    for change in (
        {"sequence": True},
        {"sequence": "1"},
        {"points": []},
        {"points": [{"x": -0.1, "y": 0.5}]},
        {"points": [{"x": 0.5, "y": float("inf")}]},
        {"points": [{"x": 0.5, "y": 0.5}] * 65},
        {"student_id": str(uuid4())},
    ):
        with pytest.raises(ValueError):
            StrokeBatch.model_validate_json(json.dumps(batch_data(**change)))
