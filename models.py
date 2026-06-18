"""
Model adapters.

Both adapters expose:

    model.generate(task, case_id, attempt_idx, messages=None, error_msg=None) -> str

  * MockModel : deterministic, offline. Returns scripted outputs per (task,
                case_id, attempt). Simulates a base model of a given quality
                profile. Ignores `messages` / `error_msg`. Perfect for a viva
                demo: no keys, no network, identical every run.

  * RealModel : optional. Calls a real LLM through LiteLLM using a model string
                like "gpt-4o-mini" or "ollama/llama3". On a reask it appends the
                validation error so the model can correct itself. Requires
                `pip install litellm` and the relevant API key in the env.
"""

from __future__ import annotations

from typing import List, Optional

from schemas import build_scripts


class MockModel:
    def __init__(self, profile: str):
        if profile not in {"strong", "medium", "weak"}:
            raise ValueError(f"unknown mock profile: {profile!r}")
        self.name = f"mock-{profile}"
        self._scripts = build_scripts(profile)

    def generate(
        self,
        task: str,
        case_id: str,
        attempt_idx: int,
        messages: Optional[List[dict]] = None,
        error_msg: Optional[str] = None,
    ) -> str:
        attempts = self._scripts[task][case_id]
        idx = min(attempt_idx, len(attempts) - 1)
        return attempts[idx]


class RealModel:
    """Optional adapter backed by LiteLLM. Not used in the offline demo."""

    def __init__(self, model_str: str, temperature: float = 0.0):
        self.name = model_str
        self.model_str = model_str
        self.temperature = temperature

    def generate(
        self,
        task: str,
        case_id: str,
        attempt_idx: int,
        messages: Optional[List[dict]] = None,
        error_msg: Optional[str] = None,
    ) -> str:
        import litellm

        msgs = list(messages or [])
        if attempt_idx > 0 and error_msg:
            # Reask: tell the model what was wrong and ask it to fix the JSON.
            msgs = msgs + [
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed validation with error: "
                        f"{error_msg}. Return ONLY a corrected JSON object that "
                        "matches the schema. No prose, no markdown."
                    ),
                }
            ]
        resp = litellm.completion(
            model=self.model_str, messages=msgs, temperature=self.temperature
        )
        return resp.choices[0].message.content


def make_model(name: str):
    """`name` is a profile (strong/medium/weak) -> MockModel, else a RealModel."""
    short = name[5:] if name.startswith("mock-") else name
    if short in {"strong", "medium", "weak"}:
        return MockModel(short)
    return RealModel(name)
