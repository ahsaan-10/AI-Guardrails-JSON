# Demo Runbook — Guardrails for Structured Outputs

Everything below runs **fully offline, with no API key**. Two ways to run it:
a visual **dashboard** (best for the showcase) and the original **command line**.

---

## 0. One-time setup in VS Code

1. Open the `guardrails_demo` folder in VS Code (**File → Open Folder…**).
2. If VS Code offers to **install recommended extensions** (Python / Pylance), accept.
3. The Python interpreter is already pointed at this project's `.venv` (Python 3.12).
   If the bottom status bar doesn't show `.venv`, press `Ctrl+Shift+P` →
   **Python: Select Interpreter** → choose the one under `.\.venv\Scripts\python.exe`.

> The packages are already installed. To reinstall if ever needed:
> **Terminal → Run Task… → "Reinstall requirements"**.

---

## 1. How to run it

### A) Visual dashboard  ← use this for the demo
Pick any one:
- **Terminal → Run Task… → "Run dashboard (Streamlit)"**, or
- **Run and Debug** panel → **"Streamlit: dashboard (app.py)"** → press **F5**, or
- terminal: `.\.venv\Scripts\streamlit.exe run app.py`

⏱️ **The FIRST launch takes ~20–30 seconds** (it loads the guardrails library) — this is
normal, it is not stuck. When ready, the terminal prints **http://localhost:8501** —
click it. Later launches are fast.

### B) Command line (the "under the hood" view)
- **Run and Debug** → **"run_eval: demo (guardrails)"** (F5) — step-by-step fail → reask → pass.
- **Run and Debug** → **"run_eval: eval (guardrails, all models)"** — the full scoreboard.
- or terminal: `python run_eval.py demo`  /  `python run_eval.py eval`

---

## 2. Suggested 3–4 minute showcase

1. **Open the dashboard.** "This forces an AI's answer into a strict JSON schema,
   retries it when it fails, and measures how well it does — fully offline."
2. **📊 Results tab → ▶ Run evaluation** (engine *guardrails*, all 3 models).
   - Cards: the *weak* model passes only **50%** first try but **100%** after one reask.
   - Left chart: the amber **fully-correct %** bars sit *below* the green **final %** bars →
     *passing the schema is not the same as being correct.*
3. **🔁 Reask walkthrough tab** → model **mock-weak**, case **invalid_json**:
   watch **❌ FAIL → reask → ✅ PASS**.
4. Change the case to **semantic**: the schema check goes **green (PASS)** but a separate
   ground-truth check goes **amber** — `affected_service` is `auth-service` instead of
   `payments-api`. "A reask can't fix this; the schema already passes."
5. **💡 What this shows tab** → read out the three findings.

---

## 3. The three headline findings (your talking points)

1. **Extra fields vanish silently.** Guardrails accepts a hallucinated field (e.g.
   `root_cause`) as *valid* and quietly drops it; strict Pydantic *rejects* it.
2. **Loose values get coerced.** Guardrails turns `"is_regression": "maybe"` into `true`;
   strict Pydantic *rejects* it.
3. **Schema-valid ≠ correct.** A schema-valid answer can still hold a wrong value, and a
   reask cannot fix it — so you need a separate ground-truth check.

> These leniencies are why the **guardrails** engine shows higher pass rates than the
> strict **builtin** engine on the *same* outputs. Flip the engine in the sidebar and rerun
> to show the difference live.

---

## 4. Likely instructor questions → where to point

| Question | Answer / where to show it |
|---|---|
| How do you force JSON? | `Guard.for_pydantic` in `engines.py`; the schemas in `schemas.py` (or the **🧩 Schemas** tab). |
| What happens on failure? | The reask loop in `harness.py`, shown live in the **🔁 walkthrough** tab. |
| How do you know it worked? | The metric cards + the failure-mode chart. |
| Why not just `json.loads`? | Switch engine to **builtin** and rerun — first-pass rates drop (medium 78.6% → 57.1%, weak 50% → 28.6%). |
| Biggest limitation? | Finding #3: schema-valid ≠ correct. |
| Are these real model numbers? | No — strong/medium/weak are **illustrative, deterministic mocks** so the demo is offline and repeatable. Swap in a real model via the CLI. |

---

## 5. If something misbehaves

- **Dashboard looks stuck right after launch** → it's loading the library; wait ~30s.
- **`streamlit` not recognized** in a plain terminal → use the **Run Task** or **F5** config
  (they call the venv directly), or run `.\.venv\Scripts\streamlit.exe run app.py`.
- **Port 8501 already in use** → `.\.venv\Scripts\streamlit.exe run app.py --server.port 8502`.
- **Stop the dashboard** → click in its terminal and press `Ctrl+C`.
