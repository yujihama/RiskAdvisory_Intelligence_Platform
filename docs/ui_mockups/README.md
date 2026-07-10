# Risk Intelligence Decision Cockpit

This folder contains the responsive Decision Cockpit served by the unified UI and Platform API process.

Run it from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m risk_agent_platform.ui_server --host 127.0.0.1 --port 8300
```

Open:

```text
http://127.0.0.1:8300/ui/
```

Use a specific analyzed scenario:

```text
http://127.0.0.1:8300/ui/?scenario_id=<scenario_id>
```

## Runtime boundary

`risk_agent_platform.ui_server` extends the real Platform API FastAPI application instead of running a mock lifecycle. The same process exposes:

- `GET /api/ui/state` for the read-only cockpit projection.
- `POST /v1/scenarios` and `GET /v1/jobs/{job_id}` for real analysis jobs.
- `POST /v1/scenarios/{scenario_id}/decisions/{decision_id}/actions` for append-only Decision Log actions.
- `GET /v1/scenarios/{scenario_id}/decision-log` for folded decision state and history.
- `GET /ui/` for the static frontend.

The UI displays only values present in generated artifacts or the Platform API. Missing values are shown as unset rather than replaced with demo numbers.

Re-analysis keeps the same scenario lineage so existing delta snapshots and `request_recheck` conditions are evaluated on the next run. A changed synthesized recommendation receives a content-fingerprinted Decision revision ID and starts pending; an unchanged recommendation retains its existing folded state.

## Files

- `index.html`: semantic application shell and interaction surfaces.
- `app.css`: desktop, tablet, and mobile layout.
- `app.js`: API client, state projection, rendering, decisions, drawers, dialogs, and job polling.
- `decision-cockpit-reference.png`: selected ImageGen visual target used for design QA.
- `vendor/tabler-icons/`: pinned Tabler Icons webfont assets and license.

The selected visual target is implemented as one primary Decision Cockpit rather than the previous six disconnected mock screens. The core flow is:

1. Choose a scenario from the prioritized queue.
2. Review the selected decision, actual risk score, uncertainty, and linked evidence.
3. Approve, hold, request re-evaluation, or reassign ownership.
4. Verify the append-only decision history.
5. Optionally submit a real scenario re-analysis job and monitor its terminal state.
