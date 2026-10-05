# AI Guardrails for Structured JSON

**An evaluation harness and Streamlit dashboard for checking whether model outputs match a schema—and whether their values are correct.**

[Demo walkthrough](DEMO.md) · [Detailed methodology](TECHNICAL_NOTES.md)

## The problem it addresses

An automation can fail because an LLM returns invalid JSON, misses a required field, or supplies a valid-looking but wrong value. This project makes those differences visible and measures what retries can repair.

## What it demonstrates

- Pydantic schemas for incident and bug reports.
- Guardrails AI validation compared with a strict Pydantic baseline.
- Bounded reask loops after invalid outputs.
- Failure categories, first-pass and final validation rates, field accuracy, and correctness.
- CSV output and a Streamlit interface for inspecting results.
- Deterministic simulated model profiles for offline demos; optional real-model access through LiteLLM.

## Run locally

```bash
git clone https://github.com/ahsaan-10/AI-Guardrails-JSON.git
cd AI-Guardrails-JSON
python -m venv .venv
```

Activate the environment (`.venv\Scripts\Activate.ps1` on Windows, `source .venv/bin/activate` on macOS/Linux), then:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The repository records compatibility with Python 3.12 and pins Guardrails AI to `0.10.2`. For a minimal CLI evaluation that does not install Guardrails or Streamlit:

```bash
python -m pip install pydantic
python run_eval.py eval --engine builtin --models strong,medium,weak
```

## Run an evaluation or demo

```bash
python run_eval.py eval --engine guardrails --models strong,medium,weak
python run_eval.py demo --engine guardrails
python run_eval.py eval --engine builtin --models strong,medium,weak --csv results_builtin.csv
```

Real-model evaluations additionally require `litellm` and the chosen provider's key. Use `--reps` to collect repeated observations rather than treating one response as a stable benchmark.

## How to interpret results

The bundled strong, medium, and weak profiles are **simulated models**, not a comparison of commercial LLMs. Schema validation tests structure; semantic correctness is checked separately against task ground truth. Passing a schema after a retry does not prove that the answer is correct.

See [TECHNICAL_NOTES.md](TECHNICAL_NOTES.md) for the original recorded results, metric definitions, and validator differences. Those recorded runs were not rerun during this documentation update.

## Repository map

```text
app.py            Streamlit dashboard
run_eval.py       Evaluation and demo CLI
schemas.py        Task schemas, ground truth, and test cases
engines.py        Guardrails and Pydantic validators
models.py         Mock and optional real-model adapters
harness.py        Retry loop, aggregation, and CSV export
failure_modes.py  Failure classification
DEMO.md           Guided demonstration
```

## A short walkthrough

Run the weak-profile demo, show a structural failure repaired by a retry, then show a schema-valid response with an incorrect value. This is the project's clearest example of why validation and evaluation need separate checks.
