"""
Schemas, ground truth, and the test battery.

Two structured-output tasks are defined, exactly as in the project brief:
  * IncidentReport  (incident management)
  * BugReport       (bug templates)

Each task carries:
  - a Pydantic model (the strict schema we force the LLM into)
  - `gt`        : the full "correct" object for the prompt
  - `gt_check`  : the subset of fields whose values are fully determined by the
                  prompt, used for the *semantic* (ground-truth) comparison
  - `valid_json`: a model output that is structurally AND semantically correct
  - `semantic_json`: an output that is schema-valid but has one wrong value
  - `variants`  : one deliberately broken output per structural failure mode

The mock-model PROFILES below let us simulate "different base models" of
different quality, fully offline and deterministically, so a viva demo never
depends on a network call or an API key.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IncidentReport(BaseModel):
    # extra="forbid" -> the JSON schema gets additionalProperties: false, so
    # hallucinated/extra fields are a validation failure (not silently kept).
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(description="Unique incident id, e.g. INC-4521")
    title: str = Field(description="Short summary of the incident")
    affected_service: str = Field(description="Name of the affected service")
    severity: Severity = Field(description="One of: low, medium, high, critical")
    impacted_users: int = Field(ge=0, description="Estimated impacted users")
    resolved: bool = Field(description="Whether the incident is resolved")
    action_items: List[str] = Field(
        default_factory=list, description="Follow-up actions (optional)"
    )


class Priority(str, Enum):
    p0 = "P0"
    p1 = "P1"
    p2 = "P2"
    p3 = "P3"


class BugReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bug_id: str = Field(description="Unique bug id, e.g. BUG-7782")
    title: str = Field(description="Short summary of the bug")
    component: str = Field(description="Affected component / module")
    priority: Priority = Field(description="One of: P0, P1, P2, P3")
    steps_to_reproduce: List[str] = Field(description="Ordered repro steps")
    is_regression: bool = Field(description="Whether this is a regression")


# --------------------------------------------------------------------------- #
# Ground truth + the 7-case test battery per task
# --------------------------------------------------------------------------- #
# The seven cases. "valid" and "semantic" are special; the other five each
# correspond to one structural failure mode.
CASE_IDS = [
    "valid",         # correct output
    "invalid_json",  # not parseable as JSON at all
    "not_object",    # parses, but top-level is an array, not an object
    "missing",       # valid object missing a required field
    "wrong_type",    # field present but wrong type / fails a constraint
    "extra",         # valid object + an unexpected (possibly hallucinated) field
    "semantic",      # schema-valid, but one value contradicts the prompt
]


def _incident_task() -> dict:
    gt = {
        "incident_id": "INC-4521",
        "title": "Payments API returning 500 errors",
        "affected_service": "payments-api",
        "severity": "high",
        "impacted_users": 1200,
        "resolved": False,
        "action_items": ["Roll back release 4.2.1", "Notify on-call"],
    }
    # Fields whose values are pinned by the prompt -> used for semantic check.
    gt_check = {
        "incident_id": "INC-4521",
        "affected_service": "payments-api",
        "severity": "high",
        "impacted_users": 1200,
        "resolved": False,
    }
    variants = {
        "invalid_json": (
            "I checked the logs: payments-api is throwing 500s for about "
            "1200 users. Sorry, I couldn't format this as JSON."
        ),
        "not_object": json.dumps([gt]),
        "missing": json.dumps({k: v for k, v in gt.items() if k != "severity"}),
        "wrong_type": json.dumps({**gt, "impacted_users": "around twelve hundred"}),
        "extra": json.dumps({**gt, "root_cause": "suspected DNS misconfiguration"}),
    }
    return {
        "model_cls": IncidentReport,
        "prompt": (
            "Create an incident report from this note: 'payments-api has been "
            "returning HTTP 500 errors since the 4.2.1 release. ~1200 users "
            "affected. Severity high. Not yet resolved. Action items: roll back "
            "4.2.1 and notify on-call.' Incident id INC-4521."
        ),
        "gt": gt,
        "gt_check": gt_check,
        "valid_json": json.dumps(gt),
        "semantic_json": json.dumps({**gt, "affected_service": "auth-service"}),
        "variants": variants,
    }


def _bug_task() -> dict:
    gt = {
        "bug_id": "BUG-7782",
        "title": "Checkout button unresponsive on mobile",
        "component": "checkout-ui",
        "priority": "P1",
        "steps_to_reproduce": [
            "Open cart on mobile",
            "Tap Checkout",
            "Observe no response",
        ],
        "is_regression": True,
    }
    gt_check = {
        "bug_id": "BUG-7782",
        "component": "checkout-ui",
        "priority": "P1",
        "is_regression": True,
    }
    variants = {
        "invalid_json": (
            "The checkout button doesn't respond on mobile in checkout-ui. "
            "Looks like a P1 regression. (Not returning JSON.)"
        ),
        "not_object": json.dumps([gt]),
        "missing": json.dumps({k: v for k, v in gt.items() if k != "priority"}),
        "wrong_type": json.dumps({**gt, "is_regression": "maybe"}),
        "extra": json.dumps({**gt, "assigned_to": "alice"}),
    }
    return {
        "model_cls": BugReport,
        "prompt": (
            "Create a bug report from this note: 'On mobile, tapping the "
            "Checkout button in checkout-ui does nothing. Priority P1. This is a "
            "regression. Repro: open cart on mobile, tap Checkout, observe no "
            "response.' Bug id BUG-7782."
        ),
        "gt": gt,
        "gt_check": gt_check,
        "valid_json": json.dumps(gt),
        "semantic_json": json.dumps({**gt, "component": "search-service"}),
        "variants": variants,
    }


TASKS = {
    "incident": _incident_task(),
    "bug": _bug_task(),
}


# --------------------------------------------------------------------------- #
# Mock-model profiles (simulate base models of different quality)
# --------------------------------------------------------------------------- #
# fails_first   : structural cases the model gets wrong on the FIRST attempt
#                 (it then fixes them on reask).
# semantic_wrong: if "semantic" is here, the model emits a schema-valid but
#                 factually wrong value (a reask will NOT fix it, because the
#                 schema already passes -- this is the headline limitation).
PROFILES = {
    "strong": {
        "fails_first": set(),
        "semantic_wrong": {"semantic"},
    },
    "medium": {
        "fails_first": {"missing", "wrong_type", "extra"},
        "semantic_wrong": set(),
    },
    "weak": {
        "fails_first": {"invalid_json", "not_object", "missing", "wrong_type", "extra"},
        "semantic_wrong": {"semantic"},
    },
}


def build_scripts(profile: str) -> dict:
    """Return {task: {case_id: [attempt_0, attempt_1, ...]}} for a mock profile."""
    cfg = PROFILES[profile]
    fails_first = cfg["fails_first"]
    semantic_wrong = cfg["semantic_wrong"]

    scripts: dict = {}
    for task, spec in TASKS.items():
        valid = spec["valid_json"]
        semantic = spec["semantic_json"]
        variants = spec["variants"]
        case_scripts: dict = {}
        for case_id in CASE_IDS:
            if case_id == "valid":
                case_scripts[case_id] = [valid]
            elif case_id == "semantic":
                # schema-valid wrong value if this model slips semantically;
                # reask returns the same (schema already passes).
                case_scripts[case_id] = [semantic if "semantic" in semantic_wrong else valid]
            else:
                if case_id in fails_first:
                    case_scripts[case_id] = [variants[case_id], valid]  # broken -> fixed
                else:
                    case_scripts[case_id] = [valid]
        scripts[task] = case_scripts
    return scripts
