# Guardrails for Structured Outputs (JSON & Forms)

A small, runnable evaluation harness for **Project #6**: use Guardrails AI to
force LLM responses into a strict JSON schema, then *measure* how well different
"base models" comply — and where schema validation alone is not enough.

This is the project that is easiest to demo quickly, because:

- the library does the heavy lifting (schema -> validation -> reask), so there
  is almost no infrastructure to build or deploy;
- the result is **objective** — output either parses and matches the schema or
  it does not.
- it runs **fully offline and deterministically** here (no API key, no network),
  so a live demo can't be derailed by a flaky connection.

Everything below has been run and verified against `guardrails-ai==0.10.2`,
`pydantic==2.13`, Python 3.12.

---

## What it demonstrates

1. Defining a strict schema as a Pydantic model and turning it into a Guardrails
   `Guard` (`Guard.for_pydantic(...)`).
2. Validating model output against that schema and, on failure, **reasking** the
   model up to *N* times.
3. A clean **failure-mode taxonomy** (invalid JSON, not-an-object, missing field,
   wrong type, extra/hallucinated field, semantic error) and per-mode counts.
4. A **comparison across simulated base models** of different quality (strong /
   medium / weak) on two tasks (an incident report and a bug report).
5. Two real, measurable ways Guardrails' default validation differs from strict
   Pydantic — discovered by actually running the harness (see *Findings*).
6. The headline lesson: **schema-valid ≠ correct.** A reask fixes structure, not
   meaning.

---

## Install

The harness and the built-in engine need only Pydantic:

```bash
pip install pydantic
```

For the Guardrails engine (recommended — it's the point of the project):

```bash
pip install guardrails-ai          # tested on 0.10.2
```

LiteLLM is optional and only needed to evaluate real (non-mock) models:

```bash
pip install litellm
```

---

## Quickstart

Offline comparison across three simulated base models, using Guardrails:

```bash
python run_eval.py eval --engine guardrails --models strong,medium,weak
```

The same evaluation using only the strict-Pydantic baseline (no guardrails-ai
required):

```bash
python run_eval.py eval --engine builtin --models strong,medium,weak
```

A 2–3 minute live walkthrough — raw output → verdict → reask → final — on the
weak model:

```bash
python run_eval.py demo --engine guardrails
```

Run a single task, or change the reask budget:

```bash
python run_eval.py eval --engine guardrails --task bug --num-reasks 2
```

Per-case results are written to `results.csv`.

### Using a real model

Both `eval` and `native` accept real LiteLLM model strings once `litellm` is
installed and the relevant key is set (e.g. `OPENAI_API_KEY`):

```bash
# our harness drives the reask loop, validating each attempt with Guardrails:
python run_eval.py eval --engine guardrails --models gpt-4o-mini --reps 5

# let Guardrails call the LLM and reask entirely by itself:
python run_eval.py native --model gpt-4o-mini
```

Use `--reps > 1` for real models, since they are non-deterministic (the mock
models are deterministic, so reps add nothing there).

---

## Files

| File | Purpose |
|------|---------|
| `schemas.py` | The two Pydantic schemas, the ground truth for each prompt, the 7-case test battery, and the mock-model quality profiles. |
| `engines.py` | The two validators behind one `Verdict` interface: `GuardrailsValidator` (real library) and `BuiltinValidator` (strict Pydantic). Also `native_guardrails_run`. |
| `models.py` | Model adapters: deterministic `MockModel` (profiles) and optional `RealModel` (LiteLLM). |
| `failure_modes.py` | Engine-independent classifier that labels *why* an output failed. |
| `harness.py` | The reask loop, metric aggregation, table printing, CSV export. |
| `run_eval.py` | CLI: `eval`, `demo`, `native`. |
| `results.csv`, `results_builtin.csv` | Saved per-case outputs from the two engines. |

---

## Metrics

For each model (aggregated over both tasks and all seven cases):

- **first-pass %** — share of outputs that pass schema validation on the *first*
  attempt (no reask).
- **final %** — share that pass after up to `num_reasks` reasks.
- **reasks** — mean number of reasks used per case.
- **field-acc %** — per-field agreement with the prompt's ground truth, over the
  fields whose values the prompt pins down (the *semantic* check).
- **correct %** — share of cases that are schema-valid **and** match ground
  truth on every checked field.

A separate table reports the **first-attempt failure-mode distribution**.

---

## Verified results

`--engine guardrails`, both tasks, `--num-reasks 1` (N = 14 cases per model):

| model | first-pass % | final % | reasks | field-acc % | correct % |
|-------|-----:|-----:|-----:|-----:|-----:|
| mock-strong | 100.0 | 100.0 | 0.00 | 96.8 | 85.7 |
| mock-medium |  78.6 | 100.0 | 0.21 | 100.0 | 100.0 |
| mock-weak   |  50.0 | 100.0 | 0.50 | 96.8 | 85.7 |

`--engine builtin` (strict Pydantic) on the *same* model outputs:

| model | first-pass % | final % | reasks | field-acc % | correct % |
|-------|-----:|-----:|-----:|-----:|-----:|
| mock-strong | 100.0 | 100.0 | 0.00 | 96.8 | 85.7 |
| mock-medium |  57.1 | 100.0 | 0.43 | 100.0 | 100.0 |
| mock-weak   |  28.6 | 100.0 | 0.71 | 96.8 | 85.7 |

First-attempt failure modes (identical across engines — this table is computed
by the independent classifier on the raw text, not by the validator):

| model | valid | invalid_json | not_object | missing | wrong_type | extra | semantic |
|-------|---:|---:|---:|---:|---:|---:|---:|
| mock-strong | 12 | 0 | 0 | 0 | 0 | 0 | 2 |
| mock-medium |  8 | 0 | 0 | 2 | 2 | 2 | 0 |
| mock-weak   |  2 | 2 | 2 | 2 | 2 | 2 | 2 |

---

## Findings (observed on guardrails-ai 0.10.2)

These came out of *running* the harness, and they are the most interesting part
of the project. The two engines see identical model outputs, yet disagree.

1. **Extra/hallucinated fields are silently dropped, not flagged.** When the
   model adds an unexpected key (e.g. `root_cause`), Guardrails marks the output
   **valid** and quietly removes the key from `validated_output` — even though
   the Pydantic schema sets `additionalProperties: false`. Strict Pydantic
   (`extra="forbid"`) instead **rejects** it. So a hallucinated field never
   reaches your downstream code, but you also never learn it happened.

2. **Loose type coercion.** Guardrails accepts `"is_regression": "maybe"` for a
   boolean field and stores it as `True`; strict Pydantic rejects it. A garbage
   value can therefore be silently coerced into a plausible-looking one.

These two leniencies fully explain why the Guardrails column shows higher
first-pass rates and fewer reasks than strict Pydantic on the very same outputs
(medium 78.6% vs 57.1%, weak 50.0% vs 28.6%).

3. **Schema validity is not correctness.** The `semantic` case is perfectly
   schema-valid but has one wrong value (`affected_service` = `auth-service`
   instead of `payments-api`). Both engines **pass** it, so `correct %` stays at
   85.7% for the strong and weak models despite 100% schema validity. A reask
   cannot fix this — the schema already passes — which is why a separate
   ground-truth/semantic check exists in the harness.

---

## Honest notes about scope

- The **mock profiles are illustrative**, not measurements of real models. They
  exist so the demo is deterministic and key-free. Swap in real models with
  `--models gpt-4o-mini` (etc.) to get real numbers; the harness is identical.
- The **headline pass/fail is Guardrails' own verdict** (`validation_passed`).
  The finer failure-mode label is *post-hoc analysis* of the raw text in
  `failure_modes.py` — it is deliberately engine-independent so the taxonomy is
  comparable across engines.
- Offline, the Guardrails engine validates each attempt with
  `guard.parse(..., num_reasks=0)` (pure post-processor, no LLM call) while the
  harness orchestrates the reask loop. The `native` command instead hands the
  whole loop — LLM call and reasks — to Guardrails via `guard(model=..., num_reasks=N)`.

---

## Maps to the viva questions

- *How do you force JSON?* → `Guard.for_pydantic` + function-calling / prompt
  optimisation, shown in `engines.py`.
- *What happens on failure?* → the reask loop in `harness.py`, visible live via
  `demo`.
- *How do you know it worked?* → the metrics, and the failure-mode taxonomy.
- *Why not just `json.loads`?* → run `--engine builtin` to see exactly what the
  baseline does, then contrast with the Guardrails leniencies above.
- *Biggest limitation?* → schema-valid ≠ correct (finding #3).

---

## Team

Group project submission.

| Name | Roll No. |
|------|----------|
| S.M Ahsaan | 21B-093-CS |
| Hafiz Mohammed Harmain Meo | 21B-232-CS |
| Umar Abdul Rehman | 21B-231-CS |
| Arham Akhter | 21B-069-CS |
