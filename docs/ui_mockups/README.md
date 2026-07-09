# Risk Advisory Intelligence Platform UI Mockups

This folder contains static UI mockups for the planned service UI.

Open `index.html` directly in a browser. The mock has six screens:

- Executive start / manual analysis
- Real-time signal canvas placeholder
- Autonomous analysis live view
- Recommendation rationale view
- Executive result view
- Proof stack / evidence provenance view

To connect the mock to local backend outputs, serve it through the UI backend:

```powershell
$env:PYTHONPATH = "src"
python -m risk_agent_platform.ui_server --host 127.0.0.1 --port 8300
```

Then open:

```text
http://127.0.0.1:8300/ui/#live
```

When opened through `file://`, the mock remains static and does not call the backend.

The current version is an executive-oriented mockup. It intentionally reduces operational detail and presents the analysis as:

- Decision focus
- Recommendation
- Three key reasons
- Human review gate
- Minimal proof stack

The live analysis screen now focuses on one primary UI direction:

- Risk Scenario Tree: one event branching into multiple risk scenarios, each with a neural-style agent analysis network

The mock is intentionally static. It uses the current CLI outputs and trace shape as the product model:

- `risk-agent-platform discover-risks`
- `risk-agent-platform run-scenario`
- `outputs/<scenario_id>/final_brief.md`
- `outputs/<scenario_id>/decision_queue.json`
- `outputs/<scenario_id>/evidence_summary.json`
- `outputs/<scenario_id>/trace_metadata.json`
- `outputs/_traces/<trace_id>.jsonl`

Current embedded scenario data comes from:

- `outputs/scenario_discovered_fujifilm_dummy_iran_war_escalation_affecting_fujifilm_executive_management_disc_`

`concept-executive-green.png` is the generated visual concept used for the executive green redesign. `concept-board.png` is the earlier operational dashboard concept.
