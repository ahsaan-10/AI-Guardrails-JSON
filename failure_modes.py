"""
Failure-mode classifier.

This is *analysis on top of* whatever validator is used. The validator
(Guardrails or the built-in baseline) gives the headline pass/fail verdict; this
function categorises *why* a first-attempt output failed, into the taxonomy used
in the write-up and viva:

    valid          - parses, schema-valid, no extra fields, values match prompt
    invalid_json   - not parseable as JSON
    not_object     - parses but top-level is not a JSON object
    missing_field  - object missing >=1 required field
    wrong_type     - a field has the wrong type / violates a constraint or enum
    extra_field    - object has >=1 key not in the schema (possible hallucination)
    semantic_error - schema-valid, but a field value contradicts the prompt

The ordering matters: we report the first/most-fundamental problem found.
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from pydantic import BaseModel, ValidationError


def classify(
    raw: str, model_cls: type[BaseModel], gt_check: dict
) -> Tuple[str, Optional[dict]]:
    """Return (failure_mode, parsed_dict_or_None)."""
    # 1. Parseable JSON?
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "invalid_json", None

    # 2. Top-level object?
    if not isinstance(data, dict):
        return "not_object", None

    fields = model_cls.model_fields
    required = [name for name, f in fields.items() if f.is_required()]

    # 3. Missing required fields?
    if any(r not in data for r in required):
        return "missing_field", data

    # 4. Unexpected (extra) fields?
    if any(k not in fields for k in data):
        return "extra_field", data

    # 5. Wrong types / failed constraints / bad enum values?
    try:
        model_cls.model_validate(data)
    except ValidationError:
        return "wrong_type", data

    # 6. Structurally valid -> check semantics against the prompt's ground truth.
    for key, expected in gt_check.items():
        if str(data.get(key)) != str(expected):
            return "semantic_error", data

    return "valid", data
