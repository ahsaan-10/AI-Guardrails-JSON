"""
Evaluation harness.

`run_case` runs one (model, task, case) through a reask loop:
    attempt -> validate -> if fail and reasks remain, reask -> ...
The validator's verdict drives the loop; the loop orchestration (and, for real
models, the reask feedback message) lives here.

`run_eval` sweeps models x tasks x cases x repetitions, then aggregates:
    - first-pass valid rate   : % schema-valid on attempt 0
    - final valid rate        : % schema-valid after reasks
    - mean reasks to success
    - field accuracy          : per-field match vs ground truth (semantics)
    - fully-correct rate       : schema-valid AND all ground-truth fields match
    - first-attempt failure-mode distribution
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from typing import List, Optional

from engines import get_validator
from failure_modes import classify
from schemas import CASE_IDS, TASKS


@dataclass
class Record:
    model: str
    task: str
    case: str
    rep: int
    first_pass: bool      # schema-valid on the first attempt
    final_pass: bool      # schema-valid after reasks
    reasks: int           # number of reasks performed
    first_mode: str       # failure-mode taxonomy label for the first attempt
    field_match: int      # ground-truth fields matched in the final output
    field_total: int      # ground-truth fields checked
    fully_correct: bool   # schema-valid AND all ground-truth fields match


def _base_messages(spec: dict) -> List[dict]:
    schema = json.dumps(spec["model_cls"].model_json_schema(), indent=2)
    return [
        {
            "role": "system",
            "content": (
                "You output ONLY a single JSON object matching this schema. "
                "No prose, no markdown fences.\n" + schema
            ),
        },
        {"role": "user", "content": spec["prompt"]},
    ]


def run_case(model, validator, task, case_id, rep, num_reasks, verbose=False):
    spec = TASKS[task]
    model_cls = spec["model_cls"]
    gt_check = spec["gt_check"]
    base_messages = _base_messages(spec)

    raw0: Optional[str] = None
    first_pass = False
    verdict = None
    error_msg: Optional[str] = None
    i = 0
    for i in range(num_reasks + 1):
        raw = model.generate(task, case_id, i, base_messages, error_msg)
        verdict = validator.validate(raw)
        if i == 0:
            raw0 = raw
            first_pass = bool(verdict.passed)
        if verbose:
            label = "attempt" if i == 0 else f"reask #{i}"
            status = "PASS" if verdict.passed else f"FAIL ({verdict.error})"
            preview = raw if len(raw) <= 160 else raw[:160] + "..."
            print(f"    [{label}] {status}")
            print(f"      raw: {preview}")
        if verdict.passed:
            break
        error_msg = verdict.error

    reasks_used = i  # final loop counter == number of reasks performed

    parsed_final = verdict.parsed
    field_total = len(gt_check)
    field_match = (
        sum(1 for k, v in gt_check.items() if str(parsed_final.get(k)) == str(v))
        if parsed_final is not None
        else 0
    )
    semantic_ok = parsed_final is not None and field_match == field_total
    fully_correct = bool(verdict.passed and semantic_ok)
    first_mode = classify(raw0, model_cls, gt_check)[0]

    if verbose:
        note = ""
        if verdict.passed and not semantic_ok:
            note = "  <-- schema-valid but a value contradicts the prompt"
        print(f"    final: schema_pass={bool(verdict.passed)} "
              f"field_match={field_match}/{field_total}{note}\n")

    return Record(
        model=model.name,
        task=task,
        case=case_id,
        rep=rep,
        first_pass=first_pass,
        final_pass=bool(verdict.passed),
        reasks=reasks_used,
        first_mode=first_mode,
        field_match=field_match,
        field_total=field_total,
        fully_correct=fully_correct,
    )


def run_eval(models: List[str], tasks: List[str], engine: str, num_reasks: int, reps: int):
    from models import make_model

    records: List[Record] = []
    for name in models:
        model = make_model(name)
        for task in tasks:
            validator = get_validator(engine, TASKS[task]["model_cls"])
            for case_id in CASE_IDS:
                for rep in range(reps):
                    records.append(
                        run_case(model, validator, task, case_id, rep, num_reasks)
                    )
    return records


# --------------------------------------------------------------------------- #
# Aggregation + pretty printing
# --------------------------------------------------------------------------- #
def _pct(num, den):
    return 100.0 * num / den if den else 0.0


def summarize(records: List[Record]):
    models: List[str] = []
    for r in records:
        if r.model not in models:
            models.append(r.model)

    rows = []
    for m in models:
        rs = [r for r in records if r.model == m]
        n = len(rs)
        rows.append(
            {
                "model": m,
                "n": n,
                "first_pass": _pct(sum(r.first_pass for r in rs), n),
                "final_pass": _pct(sum(r.final_pass for r in rs), n),
                "mean_reasks": (sum(r.reasks for r in rs) / n) if n else 0.0,
                "field_acc": _pct(
                    sum(r.field_match for r in rs), sum(r.field_total for r in rs)
                ),
                "fully_correct": _pct(sum(r.fully_correct for r in rs), n),
            }
        )
    return models, rows


def print_summary(records: List[Record]):
    models, rows = summarize(records)

    print("\n=== Schema-compliance & correctness (aggregated over tasks/cases) ===")
    hdr = (f"{'model':<14}{'N':>4}{'first-pass%':>13}{'final%':>9}"
           f"{'reasks':>9}{'field-acc%':>12}{'correct%':>10}")
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        print(
            f"{row['model']:<14}{row['n']:>4}{row['first_pass']:>13.1f}"
            f"{row['final_pass']:>9.1f}{row['mean_reasks']:>9.2f}"
            f"{row['field_acc']:>12.1f}{row['fully_correct']:>10.1f}"
        )

    modes = [
        "valid", "invalid_json", "not_object", "missing_field",
        "wrong_type", "extra_field", "semantic_error",
    ]
    print("\n=== First-attempt failure modes (count) ===")
    hdr2 = f"{'model':<14}" + "".join(f"{m[:11]:>13}" for m in modes)
    print(hdr2)
    print("-" * len(hdr2))
    for m in models:
        rs = [r for r in records if r.model == m]
        counts = {mode: sum(1 for r in rs if r.first_mode == mode) for mode in modes}
        print(f"{m:<14}" + "".join(f"{counts[mode]:>13}" for mode in modes))
    print()


def write_csv(records: List[Record], path: str):
    if not records:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))
