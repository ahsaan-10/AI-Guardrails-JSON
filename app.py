"""
Visual dashboard for "Guardrails for Structured Outputs".

A local Streamlit UI that makes the existing, tested harness *visible*: it shows
how an AI's JSON output is validated against a strict schema, retried ("reasked")
on failure, and where schema validation alone is not enough.

This file is ADDITIVE. It imports and calls the existing modules and never
reimplements their validation logic:

    schemas.py        -> TASKS, CASE_IDS, IncidentReport, BugReport, PROFILES
    models.py         -> make_model
    engines.py        -> get_validator   (builtin / guardrails, one interface)
    failure_modes.py  -> classify        (engine-independent taxonomy)
    harness.py        -> run_eval, summarize

Run it with:   streamlit run app.py
The original CLI (`python run_eval.py ...`) is untouched.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd
import streamlit as st

try:
    import altair as alt

    HAVE_ALT = True
except Exception:  # pragma: no cover - altair ships with streamlit, but be safe
    HAVE_ALT = False

# --- Existing project modules (the source of truth; only imported, never changed)
from schemas import TASKS, CASE_IDS, IncidentReport, BugReport, PROFILES
from models import make_model
from engines import get_validator
from failure_modes import classify
from harness import run_eval, summarize

# --- Is the real Guardrails library importable? (engines.py imports it lazily,
#     so the app loads fine without it; we only need to know for the UI default.)
try:
    import guardrails as _gr

    GUARDRAILS_AVAILABLE = True
    try:
        from importlib.metadata import version as _pkg_version

        GUARDRAILS_VERSION = _pkg_version("guardrails-ai")
    except Exception:
        GUARDRAILS_VERSION = getattr(_gr, "__version__", "installed")
except Exception:
    GUARDRAILS_AVAILABLE = False
    GUARDRAILS_VERSION = None


# --------------------------------------------------------------------------- #
# Constants / look & feel
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Guardrails for Structured Outputs",
                   page_icon="🛡️", layout="wide")

ALL_MODELS = ["mock-strong", "mock-medium", "mock-weak"]

# Color convention used throughout:
#   green  = passes schema validation
#   red    = fails schema validation
#   amber  = schema-valid but the *value* is wrong (semantic)
GREEN = "#2e7d32"
LIGHT_GREEN = "#66bb6a"
AMBER = "#f9a825"

# Failure-mode taxonomy (matches failure_modes.classify / harness.print_summary).
MODE_ORDER = [
    "valid", "invalid_json", "not_object", "missing_field",
    "wrong_type", "extra_field", "semantic_error",
]
MODE_COLORS = {
    "valid": GREEN,            # the only "good" mode -> green
    "invalid_json": "#8e0000",
    "not_object": "#c62828",
    "missing_field": "#ef6c00",
    "wrong_type": "#f57f17",
    "extra_field": "#ad1457",
    "semantic_error": AMBER,   # schema-valid but wrong -> amber
}

CASE_DESC = {
    "valid": "valid — correct output",
    "invalid_json": "invalid_json — not JSON at all",
    "not_object": "not_object — a JSON array, not an object",
    "missing": "missing — a required field is absent",
    "wrong_type": "wrong_type — a field has the wrong type",
    "extra": "extra — an unexpected / hallucinated field",
    "semantic": "semantic — schema-valid but a wrong value",
}

TASK_LABEL = {"incident": "incident report", "bug": "bug report"}


# --------------------------------------------------------------------------- #
# Helpers (additive — drive the EXISTING engines/models, record per attempt)
# --------------------------------------------------------------------------- #
def _walk_base_messages(spec: dict) -> list[dict]:
    """Mirror harness._base_messages so the walkthrough drives the model with the
    same prompt the CLI uses. (MockModel ignores these, but we keep the call
    signature faithful to the real reask loop in harness.run_case.)"""
    schema = json.dumps(spec["model_cls"].model_json_schema(), indent=2)
    return [
        {"role": "system",
         "content": ("You output ONLY a single JSON object matching this schema. "
                     "No prose, no markdown fences.\n" + schema)},
        {"role": "user", "content": spec["prompt"]},
    ]


def run_walkthrough(engine: str, model_name: str, task: str,
                    case_id: str, num_reasks: int) -> dict:
    """Run one (model, task, case) through the SAME attempt -> validate -> reask
    loop as harness.run_case, but record every attempt so the UI can show it.

    Uses get_validator(...) + make_model(...) only; nothing in the existing
    modules is modified.
    """
    spec = TASKS[task]
    model_cls = spec["model_cls"]
    gt_check = spec["gt_check"]

    model = make_model(model_name)
    validator = get_validator(engine, model_cls)
    base_messages = _walk_base_messages(spec)

    attempts: list[dict] = []
    error_msg = None
    verdict = None
    for i in range(num_reasks + 1):
        raw = model.generate(task, case_id, i, base_messages, error_msg)
        verdict = validator.validate(raw)

        # Did the engine accept the output but silently drop keys from it?
        # (Guardrails does this for hallucinated/extra fields — finding #1.)
        dropped: list[str] = []
        if verdict.passed and verdict.parsed is not None:
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    dropped = [k for k in obj if k not in verdict.parsed]
            except Exception:
                pass

        attempts.append({
            "i": i,
            "label": "First attempt" if i == 0 else f"Reask #{i}",
            "raw": raw,
            "passed": bool(verdict.passed),
            "error": verdict.error,
            "parsed": verdict.parsed,
            "dropped": dropped,
        })
        if verdict.passed:
            break
        error_msg = verdict.error

    # Separate ground-truth (semantic) check on the FINAL validated output.
    parsed_final = verdict.parsed
    gt_rows = []
    gt_all_match = parsed_final is not None
    for key, expected in gt_check.items():
        actual = parsed_final.get(key) if parsed_final is not None else None
        match = parsed_final is not None and str(actual) == str(expected)
        if not match:
            gt_all_match = False
        gt_rows.append({"field": key, "expected": expected,
                        "got": actual, "match": match})

    # Engine-independent taxonomy label for the first attempt.
    first_mode = classify(attempts[0]["raw"], model_cls, gt_check)[0]

    return {
        "attempts": attempts,
        "final_passed": bool(verdict.passed),
        "reasks_used": attempts[-1]["i"],
        "gt_rows": gt_rows,
        "gt_all_match": gt_all_match,
        "first_mode": first_mode,
        "prompt": spec["prompt"],
    }


def _render_raw(raw: str) -> None:
    """Pretty-print the model output as JSON when possible, else as plain text."""
    try:
        obj = json.loads(raw)
        st.code(json.dumps(obj, indent=2), language="json")
    except Exception:
        st.code(raw, language="text")


def _metric_compare_chart(rows: list[dict]):
    """Grouped bars: first-pass % vs final % vs fully-correct %, per model."""
    order = ["first-pass %", "final %", "fully-correct %"]
    colors = [LIGHT_GREEN, GREEN, AMBER]
    data = []
    for row in rows:
        data.append({"model": row["model"], "metric": "first-pass %",
                     "value": round(row["first_pass"], 1)})
        data.append({"model": row["model"], "metric": "final %",
                     "value": round(row["final_pass"], 1)})
        data.append({"model": row["model"], "metric": "fully-correct %",
                     "value": round(row["fully_correct"], 1)})
    df = pd.DataFrame(data)

    if not HAVE_ALT:
        st.bar_chart(df.pivot(index="model", columns="metric", values="value")[order])
        return

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("model:N", title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("metric:N", sort=order),
            y=alt.Y("value:Q", title="percent", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("metric:N", sort=order,
                            scale=alt.Scale(domain=order, range=colors),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("model:N"), alt.Tooltip("metric:N"),
                     alt.Tooltip("value:Q", format=".1f", title="value")],
        )
        .properties(height=340)
    )
    st.altair_chart(chart, width="stretch")


def _failure_mode_chart(records, models_list: list[str]):
    """Stacked bars of first-attempt failure-mode counts, per model."""
    data = []
    for m in models_list:
        rs = [r for r in records if r.model == m]
        for mode in MODE_ORDER:
            data.append({"model": m, "mode": mode,
                         "count": sum(1 for r in rs if r.first_mode == mode)})
    df = pd.DataFrame(data)

    if not HAVE_ALT:
        st.bar_chart(df.pivot(index="model", columns="mode", values="count")[MODE_ORDER])
        return

    df = df[df["count"] > 0]
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("model:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count:Q", title="first-attempt count"),
            color=alt.Color("mode:N", sort=MODE_ORDER,
                            scale=alt.Scale(domain=MODE_ORDER,
                                            range=[MODE_COLORS[m] for m in MODE_ORDER]),
                            legend=alt.Legend(title="failure mode")),
            tooltip=["model:N", "mode:N", "count:Q"],
        )
        .properties(height=340)
    )
    st.altair_chart(chart, width="stretch")


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("🛡️ Guardrails for Structured Outputs")
st.caption(
    "Force an AI into a strict JSON schema, **reask** it when it fails, and see "
    "exactly where it goes wrong — fully offline, no API key."
)

if GUARDRAILS_AVAILABLE:
    st.success(
        f"Guardrails AI engine available (guardrails-ai {GUARDRAILS_VERSION}). "
        "Validation runs offline via `guard.parse(..., num_reasks=0)` — no network call.",
        icon="✅",
    )
else:
    st.warning(
        "guardrails-ai is **not installed**, so the *guardrails* engine is "
        "unavailable. The dashboard runs on the **builtin** engine (strict "
        "Pydantic). Run `pip install guardrails-ai==0.10.2` to enable it.",
        icon="⚠️",
    )

st.markdown(
    f"<span style='color:{GREEN};font-weight:600'>● green</span> = passes schema &nbsp;·&nbsp; "
    f"<span style='color:#c62828;font-weight:600'>● red</span> = fails schema &nbsp;·&nbsp; "
    f"<span style='color:{AMBER};font-weight:600'>● amber</span> = schema-valid but wrong value",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Sidebar controls
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("⚙️ Evaluation")

    engine_options = ["guardrails", "builtin"] if GUARDRAILS_AVAILABLE else ["builtin"]
    engine = st.selectbox(
        "engine", engine_options, index=0,
        help="guardrails = the real library's verdict. builtin = strict Pydantic "
             "(json.loads + model_validate). Same interface, different leniency.",
    )

    models_selected = st.multiselect(
        "models (simulated base models)", ALL_MODELS, default=ALL_MODELS,
        help="Illustrative, deterministic mock profiles — NOT measurements of real "
             "models. strong rarely fails; weak fails almost everything first.",
    )
    # keep a stable strong -> medium -> weak order regardless of click order
    models_selected = [m for m in ALL_MODELS if m in models_selected]

    task_choice = st.radio("task", ["both", "incident", "bug"], index=0, horizontal=True)
    tasks = ["incident", "bug"] if task_choice == "both" else [task_choice]

    num_reasks = st.slider("num_reasks (max retries per case)", 0, 3, 1)

    run_clicked = st.button("▶ Run evaluation", type="primary", width="stretch")

    st.divider()
    st.caption(
        "Mock profiles are illustrative stand-ins so the demo is offline and "
        "deterministic. Swap in real models via the CLI "
        "(`run_eval.py eval --models gpt-4o-mini`)."
    )

# Run the evaluation (store in session_state so results survive other interactions).
if run_clicked:
    if not models_selected:
        st.sidebar.error("Pick at least one model.")
    else:
        with st.spinner("Running evaluation…"):
            records = run_eval(models_selected, tasks, engine, num_reasks, 1)
        st.session_state["eval"] = {
            "records": records,
            "engine": engine,
            "models": models_selected,
            "tasks": tasks,
            "num_reasks": num_reasks,
        }


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #
tab_results, tab_walk, tab_schema, tab_findings = st.tabs(
    ["📊 Results", "🔁 Reask walkthrough", "🧩 Schemas", "💡 What this shows"]
)


# ----- 1. Results ---------------------------------------------------------- #
with tab_results:
    state = st.session_state.get("eval")
    if not state:
        st.info("Choose an engine, models, task and reask budget in the sidebar, "
                "then press **▶ Run evaluation**.")
    else:
        records = state["records"]
        models_list, rows = summarize(records)
        st.caption(
            f"engine = **{state['engine']}**  ·  tasks = **{', '.join(state['tasks'])}**  ·  "
            f"num_reasks = **{state['num_reasks']}**  ·  N = **{len(records) // max(len(models_list), 1)}** "
            f"cases per model"
        )

        st.subheader("Per-model metrics")
        for row in rows:
            with st.container(border=True):
                st.markdown(f"#### {row['model']}")
                c = st.columns(5)
                c[0].metric("first-pass %", f"{row['first_pass']:.1f}",
                            help="schema-valid on the FIRST attempt, before any reask")
                c[1].metric("final %", f"{row['final_pass']:.1f}",
                            help="schema-valid after up to num_reasks reasks")
                c[2].metric("mean reasks", f"{row['mean_reasks']:.2f}",
                            help="average reasks used per case")
                c[3].metric("field-acc %", f"{row['field_acc']:.1f}",
                            help="per-field agreement with the prompt's ground truth")
                c[4].metric("fully-correct %", f"{row['fully_correct']:.1f}",
                            help="schema-valid AND every ground-truth field matches")

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Schema vs. correctness")
            st.caption("The gap between **final %** (green) and **fully-correct %** "
                       "(amber) is finding #3: schema-valid ≠ correct.")
            _metric_compare_chart(rows)
        with col_b:
            st.subheader("First-attempt failure modes")
            st.caption("How each model's first attempts break down. Computed by the "
                       "independent classifier on the raw text — engine-independent.")
            _failure_mode_chart(records, models_list)

        with st.expander("Full metrics table & raw per-case records"):
            summary_df = pd.DataFrame([
                {"model": r["model"], "N": r["n"],
                 "first-pass %": round(r["first_pass"], 1),
                 "final %": round(r["final_pass"], 1),
                 "mean reasks": round(r["mean_reasks"], 2),
                 "field-acc %": round(r["field_acc"], 1),
                 "fully-correct %": round(r["fully_correct"], 1)}
                for r in rows
            ])
            st.dataframe(summary_df, width="stretch", hide_index=True)

            recs_df = pd.DataFrame([asdict(r) for r in records])
            st.dataframe(recs_df, width="stretch", hide_index=True)
            st.download_button(
                "⬇ Download per-case records (CSV)",
                recs_df.to_csv(index=False).encode("utf-8"),
                file_name="dashboard_results.csv", mime="text/csv",
            )


# ----- 2. Reask walkthrough ------------------------------------------------ #
with tab_walk:
    st.subheader("Step through one case, attempt by attempt")
    st.caption("Pick a model, task and failure case, then watch the loop: "
               "raw output → schema verdict → reask → final.")

    cc = st.columns([1, 1, 2, 1])
    with cc[0]:
        w_model = st.selectbox("model", ALL_MODELS,
                               index=ALL_MODELS.index("mock-weak"), key="w_model")
    with cc[1]:
        w_task = st.selectbox("task", ["incident", "bug"],
                              format_func=lambda t: TASK_LABEL[t], key="w_task")
    with cc[2]:
        w_case = st.selectbox("case", CASE_IDS, format_func=lambda c: CASE_DESC[c],
                              index=CASE_IDS.index("invalid_json"), key="w_case")
    with cc[3]:
        w_reasks = st.slider("num_reasks", 0, 3, 1, key="w_reasks")

    if engine == "guardrails":
        st.caption("Engine: **guardrails** — watch the *extra* case (silent field-drop) "
                   "and *bug · wrong_type* (`\"maybe\"`→`true` coercion).")
    else:
        st.caption("Engine: **builtin** (strict Pydantic). The Guardrails-specific "
                   "leniencies (silent drop, type coercion) won't appear here.")

    st.info("💡 **mock-weak** deliberately fails every structural case on the first "
            "attempt, so it's the best model to watch the reask loop. strong/medium "
            "emit valid JSON for most cases.")

    result = run_walkthrough(engine, w_model, w_task, w_case, w_reasks)

    with st.expander("Prompt the model was given"):
        st.write(result["prompt"])

    st.caption(f"Failure-mode taxonomy for the first attempt "
               f"(engine-independent): **{result['first_mode']}**")

    # Each attempt as a card.
    for idx, a in enumerate(result["attempts"]):
        with st.container(border=True):
            st.markdown(f"**{a['label']}** · model output")
            _render_raw(a["raw"])
            if a["passed"]:
                st.success("✅ PASS — the output satisfies the schema")
                if a["dropped"]:
                    st.warning(
                        "Guardrails accepted the output but **silently dropped** "
                        + ", ".join(f"`{k}`" for k in a["dropped"])
                        + " — the schema sets `additionalProperties: false`, yet it "
                        "was not flagged. (Finding #1.)"
                    )
            else:
                st.error(f"❌ FAIL — {a['error']}")
        # narration between a failed attempt and the next reask
        if not a["passed"] and idx < len(result["attempts"]) - 1:
            st.caption("↳ feeding the error back to the model and reasking…")

    # Final result + the SEPARATE ground-truth (semantic) check.
    st.markdown("#### Final result")
    if result["final_passed"] and result["gt_all_match"]:
        st.success(f"✅ Schema-valid after {result['reasks_used']} reask(s), and every "
                   "ground-truth field matches.")
    elif result["final_passed"] and not result["gt_all_match"]:
        st.warning("⚠️ **schema-valid ≠ correct** — the schema check **passes** "
                   "(green), but the separate **ground-truth** check finds a wrong "
                   "value (amber). A reask can't fix this: the schema already passes. "
                   "(Finding #3.)")
    else:
        st.error(f"❌ Still fails the schema after {result['reasks_used']} reask(s).")

    st.markdown("**Ground-truth check** (values the prompt pins down):")
    gt_disp = pd.DataFrame([
        {"field": r["field"], "expected": str(r["expected"]),
         "model gave": "—" if r["got"] is None else str(r["got"]),
         "ground-truth": "✓ match" if r["match"] else "✗ WRONG"}
        for r in result["gt_rows"]
    ])
    st.dataframe(gt_disp, width="stretch", hide_index=True)


# ----- 3. Schemas ---------------------------------------------------------- #
with tab_schema:
    st.subheader("The two strict JSON schemas")
    st.caption("Generated from the Pydantic models via `Model.model_json_schema()`. "
               "`extra=\"forbid\"` becomes `additionalProperties: false`.")
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**IncidentReport**")
        st.json(IncidentReport.model_json_schema())
    with sc2:
        st.markdown("**BugReport**")
        st.json(BugReport.model_json_schema())


# ----- 4. What this shows / findings --------------------------------------- #
with tab_findings:
    st.subheader("What this shows")
    st.markdown(
        "The library forces an LLM's response into a strict Pydantic JSON schema "
        "and **reasks** on failure. Three findings — observed by actually running "
        "the harness on **guardrails-ai 0.10.2** — are the interesting part."
    )

    with st.container(border=True):
        st.markdown(
            "#### 1 · Extra / hallucinated fields vanish silently\n"
            "When the model invents a field that isn't in the schema (e.g. "
            "`root_cause`), Guardrails still calls the output **valid** and quietly "
            "deletes that field — even though the schema says "
            "`additionalProperties: false`. Strict Pydantic (`extra=\"forbid\"`) "
            "**rejects** the same output. So a hallucinated field never reaches your "
            "code, but you also never learn it was there.  \n"
            "➡️ *Walkthrough: the **extra** case on the guardrails engine.*"
        )
    with st.container(border=True):
        st.markdown(
            "#### 2 · Loose values get coerced\n"
            "Guardrails accepts `\"is_regression\": \"maybe\"` for a boolean and "
            "stores it as `True`; strict Pydantic rejects it. A garbage value can be "
            "silently turned into a plausible-looking one.  \n"
            "➡️ *Walkthrough: the **wrong_type** case on the bug task.*"
        )
    with st.container(border=True):
        st.markdown(
            "#### 3 · Schema-valid ≠ correct\n"
            "The **semantic** case is perfectly schema-valid but has one wrong value "
            "(`affected_service: auth-service` instead of `payments-api`). Both "
            "engines **pass** it, so reasking cannot help — the schema already "
            "passes. That is why a **separate ground-truth check** exists.  \n"
            "➡️ *Walkthrough: the **semantic** case — schema goes green, ground-truth "
            "goes amber.*"
        )

    st.info(
        "Leniencies #1 and #2 explain why the **guardrails** engine shows higher "
        "first-pass rates and fewer reasks than strict **builtin** Pydantic on the "
        "*same* model outputs — flip the engine in the sidebar, rerun, and compare."
    )
    st.caption(
        "Scope: the strong / medium / weak profiles are **illustrative, "
        "deterministic** stand-ins so the demo runs offline with no API key — not "
        "measurements of real models. The headline pass/fail is the validator's own "
        "verdict; the failure-mode label is separate post-hoc analysis of the raw text."
    )
