from __future__ import annotations

import json
import os
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from risk_agent_platform.api.jobs import JobRecord
from risk_agent_platform.config import Settings
from risk_agent_platform.ui_server import build_ui_state, create_ui_app


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=Path.cwd() / "data")


def _write_ui_fixture(tmp_path: Path, scenario_id: str = "scenario_ui_test", *, optional: bool = True) -> None:
    output_dir = tmp_path / "outputs" / scenario_id
    output_dir.mkdir(parents=True)
    static_dir = tmp_path / "docs" / "ui_mockups"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text("<html><body>decision cockpit</body></html>", encoding="utf-8")

    (output_dir / "trace_metadata.json").write_text(
        json.dumps({"trace_id": "trace-ui-001", "scenario_id": scenario_id}),
        encoding="utf-8",
    )
    (output_dir / "decision_queue.json").write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "decision_id": "decision-001",
                        "decision": "Confirm high-risk payment route.",
                        "owner": "CFO / Legal",
                        "deadline": "24 hours",
                        "rationale": "Payment and sanctions findings require accountable review.",
                        "options": ["Proceed", "Hold"],
                        "evidence_ids": ["ev-001"],
                        "risk_if_delayed": "Payment and supply exposure may increase.",
                        "review_required": True,
                        "priority": 1,
                    },
                    {
                        "decision_id": "decision-002",
                        "decision": "Prepare an alternative supply route.",
                        "owner": "Procurement",
                        "deadline": "48 hours",
                        "rationale": "Continuity options should be prepared.",
                        "options": ["Prepare"],
                        "evidence_ids": [],
                        "risk_if_delayed": "Continuity options may narrow.",
                        "review_required": True,
                        "priority": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    if not optional:
        return

    (output_dir / "evidence_summary.json").write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "evidence_id": "ev-001",
                        "source_title": "Treasury source",
                        "source_domain": "home.treasury.gov",
                        "source_url": "https://home.treasury.gov/example",
                        "summary": "A sanctions update supports payment screening.",
                        "raw_snippet": "SECRET_RAW_SNIPPET_MUST_NOT_LEAK",
                        "reliability": "high",
                        "client_relevance": "high",
                        "confidence": "medium",
                        "supports": ["sanctions"],
                        "contradicts": ["legacy bank response"],
                        "used_by_agents": ["source-intelligence-agent"],
                        "retrieved_at": "2026-07-09T12:00:00Z",
                    },
                    {
                        "evidence_id": "ev-not-linked",
                        "source_title": "Unlinked source",
                        "source_domain": "example.com",
                        "reliability": "low",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "assumptions_and_unknowns.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "agent_name": "treasury-risk-agent",
                        "risk_score": 64,
                        "confidence": "medium",
                        "assumptions": ["Pending payments proxy near-term exposure."],
                        "unknowns": ["Confirm correspondent bank status."],
                        "metadata": {"confidential_terms": "SECRET_METADATA_MUST_NOT_LEAK"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "final_brief.md").write_text(
        "\n".join(
            [
                "# Executive Brief: Payment and sanctions response",
                "- **client_context**: Registered RiskScenario and 5 suppliers in Neo4j; affected candidates: 3.",
                "- **treasury**: Payment exposure count=1 amount=2400000.0.",
                "- **legal**: Legal review found 5 contracts with sanctions or force majeure clauses.",
            ]
        ),
        encoding="utf-8",
    )
    discovery_dir = tmp_path / "outputs" / "risk_discovery"
    discovery_dir.mkdir(parents=True, exist_ok=True)
    (discovery_dir / f"{scenario_id}.json").write_text(
        json.dumps(
            {
                "request": {
                    "event_title": "Iran war escalation affecting payments",
                    "event_description": "War escalation may disrupt payments and supply routes.",
                    "scope": {"client_id": "fujifilm_dummy", "scope_name": "Executive"},
                    "countries": ["Iran"],
                },
                "selected_event": {
                    "scenario_id": scenario_id,
                    "client_id": "fujifilm_dummy",
                    "title": "Sanctions compliance breach via payment channels",
                    "risk_type": "Compliance",
                    "countries": ["Iran"],
                    "risk_themes": ["payment", "sanctions"],
                    "affected_categories": ["Treasury", "Legal"],
                    "description": "Payment route may create sanctions exposure.",
                    "event_date": "2026-07-09",
                    "urgency": "high",
                },
                "selected_candidates": [
                    {
                        "title": "Sanctions compliance breach via payment channels",
                        "risk_type": "Compliance",
                        "description": "Payment route may create sanctions exposure.",
                        "urgency": "high",
                        "relevance_score": 90,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_ui_state_projects_real_outputs_without_raw_fields(tmp_path: Path) -> None:
    scenario_id = "scenario_ui_test"
    _write_ui_fixture(tmp_path, scenario_id)

    state = build_ui_state(_settings(tmp_path), scenario_id=scenario_id)

    assert state["source"] == "backend"
    assert state["trace_id"] == "trace-ui-001"
    assert state["event"]["title"] == "Iran war escalation affecting payments"
    assert state["metrics"]["payment_exposure_display"] == "2,400,000"
    assert state["risk_tree"]["scenarios"][0]["agents"] == ["Source", "Treasury", "Legal", "Red Team"]
    assert len(state["decisions"]) == 2
    assert state["decision"]["state"] == "pending"
    assert "approve" in state["decision"]["allowed_actions"]
    assert state["risk_assessment"] == {
        "risk_score": 64,
        "confidence": "medium",
        "source_agent": "treasury-risk-agent",
    }
    assert state["contradiction_count"] == 1
    assert [item["evidence_id"] for item in state["evidence"]] == ["ev-001"]
    serialized = json.dumps(state)
    assert "SECRET_RAW_SNIPPET_MUST_NOT_LEAK" not in serialized
    assert "SECRET_METADATA_MUST_NOT_LEAK" not in serialized


def test_ui_app_serves_static_and_platform_routes_same_origin(tmp_path: Path) -> None:
    scenario_id = "scenario_ui_test"
    _write_ui_fixture(tmp_path, scenario_id)
    app = create_ui_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/jobs").json() == {"jobs": []}
        assert client.get("/", follow_redirects=False).headers["location"] == "/ui/"
        assert client.get("/ui/").status_code == 200
        state = client.get(f"/api/ui/state?scenario_id={scenario_id}")
        assert state.status_code == 200
        assert state.json()["scenario_id"] == scenario_id
        assert client.post("/api/ui/runs", json={"scenario_id": scenario_id}).status_code == 404


def test_decision_action_is_reflected_in_ui_state(tmp_path: Path) -> None:
    scenario_id = "scenario_ui_action"
    _write_ui_fixture(tmp_path, scenario_id)
    app = create_ui_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        action = client.post(
            f"/v1/scenarios/{scenario_id}/decisions/decision-001/actions",
            json={"action": "approve", "actor": "reviewer", "reason": "review complete"},
        )
        assert action.status_code == 201
        refreshed = client.get(f"/api/ui/state?scenario_id={scenario_id}").json()
        approved = next(item for item in refreshed["decisions"] if item["decision_id"] == "decision-001")
        assert approved["state"] == "approved"
        assert approved["allowed_actions"] == []
        assert refreshed["decision"]["decision_id"] == "decision-002"
        assert refreshed["evidence"] == []
        queue_item = next(item for item in refreshed["scenario_queue"] if item["scenario_id"] == scenario_id)
        assert queue_item["state"] == "pending"
        assert queue_item["owner"] == "Procurement"
        assert refreshed["activity"][0]["label"] == "承認"
        assert refreshed["activity"][0]["decision_id"] == "decision-001"
        assert refreshed["activity"][0]["decision_title"] == "Confirm high-risk payment route."
        assert refreshed["activity"][0]["detail"] == "review complete"
        assert refreshed["activity"][0]["reason"] == "review complete"

        duplicate = client.post(
            f"/v1/scenarios/{scenario_id}/decisions/decision-001/actions",
            json={"action": "approve", "actor": "reviewer", "reason": "duplicate"},
        )
        assert duplicate.status_code == 409

        reassign = client.post(
            f"/v1/scenarios/{scenario_id}/decisions/decision-002/actions",
            json={"action": "reassign", "actor": "reviewer", "new_owner": "COO"},
        )
        assert reassign.status_code == 201
        refreshed = client.get(f"/api/ui/state?scenario_id={scenario_id}").json()
        second = next(item for item in refreshed["decisions"] if item["decision_id"] == "decision-002")
        assert second["effective_owner"] == "COO"
        queue_item = next(item for item in refreshed["scenario_queue"] if item["scenario_id"] == scenario_id)
        assert queue_item["owner"] == "COO"


def test_ui_state_does_not_fabricate_missing_optional_data(tmp_path: Path) -> None:
    scenario_id = "scenario_ui_sparse"
    _write_ui_fixture(tmp_path, scenario_id, optional=False)

    state = build_ui_state(_settings(tmp_path), scenario_id=scenario_id)

    assert state["metrics"]["payment_exposure"] is None
    assert state["metrics"]["contracts_reviewed"] is None
    assert state["risk_tree"]["scenarios"] == []
    assert state["evidence"] == []
    assert state["risk_assessment"]["risk_score"] is None
    assert "2,400,000" not in json.dumps(state)


def test_ui_state_reconstructs_direct_rerun_event_from_job(tmp_path: Path) -> None:
    scenario_id = "scenario_ui_rerun_20260710"
    _write_ui_fixture(tmp_path, scenario_id, optional=False)
    event = {
        "scenario_id": scenario_id,
        "client_id": "fujifilm_dummy",
        "title": "Versioned sanctions rerun",
        "risk_type": "Compliance",
        "countries": ["Iran"],
        "risk_themes": ["sanctions"],
        "affected_categories": ["Treasury"],
        "description": "Re-evaluate the scenario without inheriting the prior decision identity.",
        "event_date": "2026-07-10",
        "urgency": "high",
    }
    job = JobRecord(
        job_id="job-rerun",
        job_type="scenario",
        status="completed",
        trace_id="trace-rerun",
        request_payload={"event": event, "embedded_services": True},
        result_summary={"scenario_id": scenario_id},
        error_message=None,
        created_at="2026-07-10T00:00:00+00:00",
        started_at="2026-07-10T00:00:01+00:00",
        finished_at="2026-07-10T00:00:02+00:00",
    )

    state = build_ui_state(_settings(tmp_path), scenario_id=scenario_id, jobs=[job])

    assert state["event"]["title"] == "Versioned sanctions rerun"
    assert state["event_payload"] == event
    assert state["can_rerun"] is True


def test_latest_scenario_is_selected_without_hard_coded_preference(tmp_path: Path) -> None:
    _write_ui_fixture(tmp_path, "scenario_older", optional=False)
    _write_ui_fixture(tmp_path, "scenario_newer", optional=False)
    older = tmp_path / "outputs" / "scenario_older"
    newer = tmp_path / "outputs" / "scenario_newer"
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    state = build_ui_state(_settings(tmp_path))

    assert state["scenario_id"] == "scenario_newer"


class _ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ui_hooks: set[str] = set()
        self.actions: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("data-ui"):
            self.ui_hooks.add(str(values["data-ui"]))
        if values.get("data-decision-action"):
            self.actions.add(str(values["data-decision-action"]))


def test_static_decision_cockpit_contract() -> None:
    parser = _ContractParser()
    parser.feed((Path.cwd() / "docs" / "ui_mockups" / "index.html").read_text(encoding="utf-8"))

    assert {
        "scenario-queue",
        "selected-decision",
        "decision-state",
        "evidence-list",
        "decision-history",
    } <= parser.ui_hooks
    assert parser.actions == {"approve", "hold", "request_recheck", "reassign"}
    html = (Path.cwd() / "docs" / "ui_mockups" / "index.html").read_text(encoding="utf-8")
    assert 'value="Executive Reviewer"' not in html
    assert 'data-ui="rerun-submit"' in html
    assert 'data-ui="risk-score-label"' in html
    script = (Path.cwd() / "docs" / "ui_mockups" / "app.js").read_text(encoding="utf-8")
    assert 'toggleAttribute("inert", inactive)' in script
    assert "Api.submitScenario(Store.data.event_payload" in script
    assert 'item.review_required ? "人間レビュー" : "レビュー不要"' in script
    assert "function trapDrawerFocus(event)" in script
    assert "drawerFocusableElements(drawer)[0]" in script
    assert html.count("data-close-dialog") == 4
