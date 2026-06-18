"""
Validation engines.

Both engines expose the same tiny interface:

    validator.validate(raw_text) -> Verdict(passed, parsed, error)

so the harness can swap them freely.

  * BuiltinValidator   - json.loads + Pydantic model_validate. No third-party
                         dependency beyond pydantic. This is the "what does
                         Guardrails actually buy you" baseline, and it guarantees
                         the project runs even if guardrails-ai is not installed.

  * GuardrailsValidator- the real Guardrails AI library. Uses
                         Guard.for_pydantic(...) and guard.parse(..., num_reasks=0)
                         as a pure post-processor, so validation is offline and
                         deterministic (no LLM/network call). The headline
                         pass/fail comes straight from ValidationOutcome.

There is also `native_guardrails_run(...)`, which hands the *whole* loop to
Guardrails (`guard(model=..., num_reasks=N)`) so it calls the LLM and reasks
itself. That path needs a real model + API key and is opt-in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ValidationError


@dataclass
class Verdict:
    passed: bool
    parsed: Optional[dict]      # the validated object as a plain dict, or None
    error: Optional[str]        # short error message when not passed


def _to_plain_dict(obj) -> Optional[dict]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Built-in baseline (pydantic only)
# --------------------------------------------------------------------------- #
class BuiltinValidator:
    name = "builtin"

    def __init__(self, model_cls: type[BaseModel]):
        self.model_cls = model_cls

    def validate(self, raw: str) -> Verdict:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            return Verdict(False, None, f"invalid JSON: {e}")
        if not isinstance(data, dict):
            return Verdict(False, None, "top-level value is not a JSON object")
        try:
            self.model_cls.model_validate(data)  # honours extra='forbid'
        except ValidationError as e:
            first = e.errors()[0] if e.errors() else {}
            loc = ".".join(str(p) for p in first.get("loc", []))
            msg = first.get("msg", "validation error")
            return Verdict(False, None, f"{loc}: {msg}" if loc else msg)
        return Verdict(True, data, None)


# --------------------------------------------------------------------------- #
# Guardrails AI
# --------------------------------------------------------------------------- #
class GuardrailsValidator:
    name = "guardrails"

    def __init__(self, model_cls: type[BaseModel]):
        try:
            from guardrails import Guard
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "guardrails-ai is not installed. Run `pip install guardrails-ai`, "
                "or use --engine builtin."
            ) from e
        self.model_cls = model_cls
        # Build the guard once from the Pydantic model.
        self.guard = Guard.for_pydantic(output_class=model_cls)

    def validate(self, raw: str) -> Verdict:
        # num_reasks=0 -> pure post-processor: validate the given string only,
        # no LLM call. This is the offline, deterministic path.
        try:
            outcome = self.guard.parse(llm_output=raw, num_reasks=0)
        except Exception as e:  # guardrails can raise on e.g. array-vs-object
            return Verdict(False, None, f"{type(e).__name__}: {e}")

        passed = bool(getattr(outcome, "validation_passed", False))
        parsed = _to_plain_dict(getattr(outcome, "validated_output", None))

        error = None
        if not passed:
            error = "validation failed"
            try:
                reask = getattr(outcome, "reask", None)
                if reask is not None and getattr(reask, "fail_results", None):
                    error = reask.fail_results[0].error_message
                elif getattr(outcome, "error", None):
                    error = str(outcome.error)
            except Exception:
                pass
        return Verdict(passed, parsed if passed else None, error)


def get_validator(engine: str, model_cls: type[BaseModel]):
    if engine == "builtin":
        return BuiltinValidator(model_cls)
    if engine == "guardrails":
        return GuardrailsValidator(model_cls)
    raise ValueError(f"unknown engine: {engine!r}")


# --------------------------------------------------------------------------- #
# Native Guardrails reask loop (real model required) -- opt in
# --------------------------------------------------------------------------- #
def native_guardrails_run(model_cls, prompt: str, model_str: str, num_reasks: int):
    """
    Let Guardrails do everything: call the LLM via its LiteLLM-style `model=`
    string and reask up to `num_reasks` times. Returns the ValidationOutcome.

    Requires guardrails-ai installed and the relevant provider key in the
    environment (e.g. OPENAI_API_KEY for model_str="gpt-4o-mini").
    """
    from guardrails import Guard

    guard = Guard.for_pydantic(output_class=model_cls)
    schema = json.dumps(model_cls.model_json_schema(), indent=2)
    messages = [
        {
            "role": "system",
            "content": (
                "You output ONLY a single JSON object matching this schema. "
                "No prose, no markdown fences.\n" + schema
            ),
        },
        {"role": "user", "content": prompt},
    ]
    return guard(model=model_str, messages=messages, num_reasks=num_reasks)
