#!/usr/bin/env python3
"""
CLI for the Guardrails-for-Structured-Outputs demo.

Examples
--------
# Offline, deterministic comparison across three simulated base models:
python run_eval.py eval --engine guardrails --models strong,medium,weak

# Same, using only the pydantic baseline (no guardrails-ai needed):
python run_eval.py eval --engine builtin --models strong,medium,weak

# 2-3 minute live walkthrough (raw output -> verdict -> reask -> final):
python run_eval.py demo --engine guardrails

# With a real model (needs `pip install litellm` + an API key):
python run_eval.py eval --engine guardrails --models gpt-4o-mini --reps 5
python run_eval.py native --model gpt-4o-mini      # let Guardrails reask itself
"""

from __future__ import annotations

import argparse
import sys

from harness import print_summary, run_case, run_eval, write_csv
from schemas import TASKS


def cmd_eval(args):
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    tasks = list(TASKS) if args.task == "all" else [args.task]
    records = run_eval(models, tasks, args.engine, args.num_reasks, args.reps)
    print(f"\nengine={args.engine}  models={models}  tasks={tasks}  "
          f"num_reasks={args.num_reasks}  reps={args.reps}")
    print_summary(records)
    write_csv(records, args.csv)
    print(f"per-case rows written to {args.csv}")


def cmd_demo(args):
    """Walk through three illustrative cases on the weak model, verbosely."""
    from engines import get_validator
    from models import make_model

    model = make_model("weak")
    task = args.task if args.task != "all" else "incident"
    validator = get_validator(args.engine, TASKS[task]["model_cls"])

    cases = [
        ("invalid_json", "Model returns prose instead of JSON"),
        ("missing", "Model omits a required field (severity / priority)"),
        ("wrong_type", "Model uses the wrong type for a field"),
        ("semantic", "Model returns SCHEMA-VALID json with a wrong value"),
    ]
    print(f"\n# Live demo  (engine={args.engine}, model={model.name}, task={task}, "
          f"num_reasks={args.num_reasks})")
    for case_id, desc in cases:
        print(f"\n## {case_id}: {desc}")
        run_case(model, validator, task, case_id, 0, args.num_reasks, verbose=True)
    print("Takeaway: the guard catches structural failures and reask fixes them;")
    print("the 'semantic' case passes the schema yet is wrong -> needs a separate")
    print("ground-truth/semantic check, not just schema validation.\n")


def cmd_native(args):
    """Let Guardrails call the LLM and reask by itself (real model required)."""
    from engines import native_guardrails_run

    task = args.task if args.task != "all" else "incident"
    spec = TASKS[task]
    try:
        outcome = native_guardrails_run(
            spec["model_cls"], spec["prompt"], args.model, args.num_reasks
        )
    except Exception as e:
        print(f"native run failed: {type(e).__name__}: {e}")
        print("This path needs guardrails-ai + the provider API key in your env.")
        sys.exit(1)
    print("validation_passed:", getattr(outcome, "validation_passed", None))
    print("validated_output :", getattr(outcome, "validated_output", None))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--engine", choices=["guardrails", "builtin"],
                        default="guardrails", help="validation engine")
    common.add_argument("--task", choices=["all", *TASKS.keys()], default="all")
    common.add_argument("--num-reasks", dest="num_reasks", type=int, default=1,
                        help="max reasks per case")

    pe = sub.add_parser("eval", parents=[common], help="run the full evaluation")
    pe.add_argument("--models", default="strong,medium,weak",
                    help="comma-separated mock profiles (strong/medium/weak) "
                         "and/or real LiteLLM model strings")
    pe.add_argument("--reps", type=int, default=1,
                    help="repetitions per case (use >1 for real, nondeterministic models)")
    pe.add_argument("--csv", default="results.csv")
    pe.set_defaults(func=cmd_eval)

    pd = sub.add_parser("demo", parents=[common], help="verbose walkthrough")
    pd.set_defaults(func=cmd_demo)

    pn = sub.add_parser("native", parents=[common],
                        help="Guardrails reasks the LLM itself (real model)")
    pn.add_argument("--model", default="gpt-4o-mini")
    pn.set_defaults(func=cmd_native)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
