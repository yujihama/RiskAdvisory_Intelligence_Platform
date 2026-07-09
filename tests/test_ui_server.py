from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from risk_agent_platform.config import Settings
from risk_agent_platform.ui_server import build_ui_state, create_ui_app


def test_ui_state_reads_backend_outputs(tmp_path: Path) -> None:
    scenario_id = "scenario_ui_test"
    output_dir = tmp_path / "outputs" / scenario_id
    output_dir.mkdir(parents=True)
    discovery_dir = tmp_path / "outputs" / "risk_discovery"
    discovery_dir.mkdir(parents=True)
    static_dir = tmp_path / "docs" / "ui_mockups"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<html>ui</html>", encoding="utf-8")

    (output_dir / "trace_metadata.json").write_text(
        json.dumps({"trace_id": "trace-ui-001", "scenario_id": scenario_id}),
        encoding="utf-8",
    )
    (output_dir / "decision_queue.json").write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "decision": "Confirm high-risk payment route.",
                        "owner": "CFO / Legal",
                        "deadline": "24 hours",
                        "review_required": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "evidence_summary.json").write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "evidence_id": "ev-001",
                        "source_title": "Treasury source",
                        "source_domain": "home.treasury.gov",
                        "reliability": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "final_brief.md").write_text(
        "\n".join(
            [
                "- **client_context**: Registered RiskScenario and 5 suppliers in Neo4j; affected candidates: 3.",
                "- **treasury**: Payment exposure count=1 amount=2400000.0.",
                "- **legal**: Legal review found 5 contracts with sanctions or force majeure clauses.",
                "- **expert_as_code**: Indexed expert knowledge and case bank; retrieved 204 objects and 15 similar cases.",
                "- **evidence_red_team**: Red team reviewed 5 evidence items.",
            ]
        ),
        encoding="utf-8",
    )
    (discovery_dir / f"{scenario_id}.json").write_text(
        json.dumps(
            {
                "request": {
                    "event_title": "Iran war escalation affecting FUJIFILM",
                    "event_description": "War escalation may disrupt payments and supply routes.",
                    "scope": {"client_id": "fujifilm_dummy", "scope_name": "Executive"},
                    "countries": ["Iran"],
                },
                "selected_candidates": [
                    {
                        "title": "Sanctions compliance breach via payment channels",
                        "risk_type": "Compliance",
                        "description": "Payment route may create sanctions exposure.",
                        "urgency": "high",
                        "relevance_score": 90,
                    },
                    {
                        "title": "Logistics disruption to healthcare supply chain",
                        "risk_type": "Operational",
                        "description": "Shipping routes may be disrupted.",
                        "urgency": "high",
                        "relevance_score": 85,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=Path.cwd() / "data")

    state = build_ui_state(settings, scenario_id=scenario_id)

    assert state["source"] == "backend"
    assert state["trace_id"] == "trace-ui-001"
    assert state["event"]["title"] == "Iran war escalation affecting FUJIFILM"
    assert state["metrics"]["payment_exposure_display"] == "2,400,000"
    assert state["risk_tree"]["scenarios"][0]["agents"] == ["Source", "Treasury", "Legal", "Red Team"]
    assert state["risk_tree"]["scenarios"][0]["core_label"] == "分析済"
    assert state["risk_tree"]["scenarios"][1]["agents"] == ["Context", "Source", "Procure", "Expert"]

    client = TestClient(create_ui_app(settings))
    response = client.get(f"/api/ui/state?scenario_id={scenario_id}")
    assert response.status_code == 200
    assert response.json()["scenario_id"] == scenario_id

    run_response = client.post(
        "/api/ui/runs",
        json={
            "scenario_id": scenario_id,
            "event_title": "Iran war escalation affecting FUJIFILM",
            "mode": "manual",
        },
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "running"
    assert run_payload["run_id"].startswith("ui-run-")
    assert run_payload["stages"][0]["status"] == "running"

    status_response = client.get(f"/api/ui/runs/{run_payload['run_id']}")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["scenario_id"] == scenario_id
    assert len(status_payload["stages"]) == 6
