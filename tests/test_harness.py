"""Offline tests: failure classification and the end-to-end evaluation harness.

These use only the built-in Pydantic engine and the simulated models, so they
need no API keys and no Guardrails install.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from failure_modes import classify  # noqa: E402
from harness import run_eval, summarize  # noqa: E402
from schemas import IncidentReport  # noqa: E402

VALID = {
    "incident_id": "INC-4521",
    "title": "Checkout outage",
    "affected_service": "payments",
    "severity": "high",
    "impacted_users": 1200,
    "resolved": False,
}


def _raw(**overrides):
    data = {**VALID, **overrides}
    return json.dumps({k: v for k, v in data.items() if v is not None})


@pytest.mark.parametrize(
    "raw, expected",
    [
        (_raw(), "valid"),
        ("not json at all", "invalid_json"),
        ("[1, 2, 3]", "not_object"),
        (_raw(severity=None), "missing_field"),
        (_raw(confidence=0.9), "extra_field"),
        (_raw(severity="catastrophic"), "wrong_type"),
        (_raw(impacted_users=-5), "wrong_type"),
        (_raw(affected_service="search"), "semantic_error"),
    ],
)
def test_classify_failure_modes(raw, expected):
    mode, _ = classify(raw, IncidentReport, {"affected_service": "payments"})
    assert mode == expected


def test_retries_repair_structure_for_every_simulated_model():
    records = run_eval(["strong", "medium", "weak"], ["incident", "bug"], "builtin", 1, 1)
    _, rows = summarize(records)
    assert len(rows) == 3
    for row in rows:
        assert row["final_pass"] == 100.0
        assert row["final_pass"] >= row["first_pass"]


def test_schema_valid_does_not_imply_correct():
    records = run_eval(["strong"], ["incident", "bug"], "builtin", 1, 1)
    _, rows = summarize(records)
    strong = rows[0]
    assert strong["first_pass"] == 100.0
    assert strong["fully_correct"] < 100.0
