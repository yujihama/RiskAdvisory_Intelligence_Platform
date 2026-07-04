from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from risk_agent_platform import run_discovery, run_scenario
from risk_agent_platform.api.app import create_app
from risk_agent_platform.config import Settings
from risk_agent_platform.decision_log import DecisionLogStore
from risk_agent_platform.delta import load_previous_recheck_conditions
from risk_agent_platform.schemas import AgentFinding, AgentTaskResult, DecisionItem, RiskEvent


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")


def _decision(decision_id: str, **overrides) -> DecisionItem:
    fields = {
        "decision_id": decision_id,
        "decision": f"Decide on {decision_id}",
        "owner": "Treasury",
        "deadline": "2026-08-01",
        "rationale": "test rationale",
        "options": ["option a", "option b"],
        "risk_if_delayed": "high",
        "review_required": False,
        "priority": 1,
    }
    fields.update(overrides)
    return DecisionItem(**fields)


def _write_decision_queue(tmp_path: Path, scenario_id: str, decision_ids: list[str]) -> None:
    output_dir = tmp_path / "outputs" / scenario_id
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions = [_decision(decision_id).model_dump(mode="json") for decision_id in decision_ids]
    (output_dir / "decision_queue.json").write_text(
        json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8"
    )


def _event(scenario_id: str) -> RiskEvent:
    return RiskEvent(
        scenario_id=scenario_id,
        client_id="demo_client",
        title="Sanctions escalation review",
        risk_type="geopolitical_sanctions",
        description="A sanctions escalation may affect supplier payments.",
        event_date=date(2026, 7, 1),
        urgency="high",
    )


def _post_action(client: TestClient, scenario_id: str, decision_id: str, **body):
    return client.post(f"/v1/scenarios/{scenario_id}/decisions/{decision_id}/actions", json=body)


# --- API-level state machine tests -----------------------------------------------------------


def test_all_five_action_types_recorded_with_correct_states(tmp_path):
    scenario_id = "scenario_decision_log_001"
    _write_decision_queue(tmp_path, scenario_id, ["d_approve", "d_reject", "d_hold", "d_recheck", "d_reassign"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        approve = _post_action(client, scenario_id, "d_approve", action="approve", actor="alice")
        assert approve.status_code == 201
        body = approve.json()
        assert body["prev_state"] == "pending"
        assert body["new_state"] == "approved"
        assert body["action"] == "approve"
        assert body["actor"] == "alice"

        reject = _post_action(client, scenario_id, "d_reject", action="reject", actor="bob", reason="not viable")
        assert reject.status_code == 201
        body = reject.json()
        assert body["prev_state"] == "pending"
        assert body["new_state"] == "rejected"
        assert body["reason"] == "not viable"

        hold = _post_action(client, scenario_id, "d_hold", action="hold", actor="carol", reason="need more evidence")
        assert hold.status_code == 201
        body = hold.json()
        assert body["prev_state"] == "pending"
        assert body["new_state"] == "held"
        assert body["reason"] == "need more evidence"

        recheck = _post_action(client, scenario_id, "d_recheck", action="request_recheck", actor="dave")
        assert recheck.status_code == 201
        body = recheck.json()
        assert body["prev_state"] == "pending"
        assert body["new_state"] == "recheck_requested"

        reassign = _post_action(
            client, scenario_id, "d_reassign", action="reassign", actor="erin", new_owner="Legal"
        )
        assert reassign.status_code == 201
        body = reassign.json()
        assert body["prev_state"] == "pending"
        assert body["new_state"] == "pending"
        assert body["new_owner"] == "Legal"


def test_reason_required_for_hold_and_reject(tmp_path):
    scenario_id = "scenario_decision_log_002"
    _write_decision_queue(tmp_path, scenario_id, ["d1", "d2"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        hold_without_reason = _post_action(client, scenario_id, "d1", action="hold", actor="alice")
        assert hold_without_reason.status_code == 422

        reject_without_reason = _post_action(client, scenario_id, "d2", action="reject", actor="alice")
        assert reject_without_reason.status_code == 422


def test_new_owner_required_for_reassign(tmp_path):
    scenario_id = "scenario_decision_log_003"
    _write_decision_queue(tmp_path, scenario_id, ["d1"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        response = _post_action(client, scenario_id, "d1", action="reassign", actor="alice")
        assert response.status_code == 422


def test_terminal_states_reject_all_further_actions(tmp_path):
    scenario_id = "scenario_decision_log_004"
    _write_decision_queue(tmp_path, scenario_id, ["d_approved_twice", "d_hold_after_approved", "d_after_rejected"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        first_approve = _post_action(client, scenario_id, "d_approved_twice", action="approve", actor="alice")
        assert first_approve.status_code == 201
        second_approve = _post_action(client, scenario_id, "d_approved_twice", action="approve", actor="alice")
        assert second_approve.status_code == 409

        approve = _post_action(client, scenario_id, "d_hold_after_approved", action="approve", actor="alice")
        assert approve.status_code == 201
        hold_after_approve = _post_action(
            client, scenario_id, "d_hold_after_approved", action="hold", actor="alice", reason="wait"
        )
        assert hold_after_approve.status_code == 409

        reject = _post_action(client, scenario_id, "d_after_rejected", action="reject", actor="alice", reason="no")
        assert reject.status_code == 201
        for action, kwargs in [
            ("approve", {}),
            ("hold", {"reason": "x"}),
            ("request_recheck", {}),
            ("reassign", {"new_owner": "Legal"}),
        ]:
            response = _post_action(client, scenario_id, "d_after_rejected", action=action, actor="alice", **kwargs)
            assert response.status_code == 409, f"{action} after rejected should be 409"


def test_unknown_decision_id_is_404(tmp_path):
    scenario_id = "scenario_decision_log_005"
    _write_decision_queue(tmp_path, scenario_id, ["d1"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        response = _post_action(client, scenario_id, "does_not_exist", action="approve", actor="alice")
        assert response.status_code == 404


def test_unknown_scenario_is_404(tmp_path):
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        response = _post_action(client, "no_such_scenario", "d1", action="approve", actor="alice")
        assert response.status_code == 404

        log_response = client.get("/v1/scenarios/no_such_scenario/decision-log")
        assert log_response.status_code == 404


def test_append_only_no_mutation_endpoints(tmp_path):
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    log_paths = {
        route.path: route.methods
        for route in app.routes
        if getattr(route, "path", "").endswith("/actions") or getattr(route, "path", "").endswith("/decision-log")
    }
    for path, methods in log_paths.items():
        assert "PUT" not in methods, f"{path} must not support PUT"
        assert "PATCH" not in methods, f"{path} must not support PATCH"
        assert "DELETE" not in methods, f"{path} must not support DELETE"
    assert any(path.endswith("/actions") for path in log_paths)
    assert any(path.endswith("/decision-log") for path in log_paths)


def test_two_sequential_actions_produce_two_jsonl_lines_first_unchanged(tmp_path):
    scenario_id = "scenario_decision_log_006"
    _write_decision_queue(tmp_path, scenario_id, ["d1"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        hold = _post_action(client, scenario_id, "d1", action="hold", actor="alice", reason="need info")
        assert hold.status_code == 201

        log_path = tmp_path / "outputs" / scenario_id / "decision_log.jsonl"
        lines_after_first = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines_after_first) == 1
        first_line_snapshot = lines_after_first[0]

        approve = _post_action(client, scenario_id, "d1", action="approve", actor="bob")
        assert approve.status_code == 201

        lines_after_second = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines_after_second) == 2
        assert lines_after_second[0] == first_line_snapshot


def test_chronological_retrieval_with_actor_reason_and_states(tmp_path):
    scenario_id = "scenario_decision_log_007"
    _write_decision_queue(tmp_path, scenario_id, ["d1", "d2"])
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")

    with TestClient(app) as client:
        _post_action(client, scenario_id, "d1", action="hold", actor="alice", reason="need more evidence")
        _post_action(client, scenario_id, "d1", action="approve", actor="bob")
        _post_action(client, scenario_id, "d2", action="reject", actor="carol", reason="out of scope")

        response = client.get(f"/v1/scenarios/{scenario_id}/decision-log")
        assert response.status_code == 200
        body = response.json()

    actions = body["actions"]
    assert [a["decision_id"] for a in actions] == ["d1", "d1", "d2"]
    assert actions[0]["actor"] == "alice"
    assert actions[0]["reason"] == "need more evidence"
    assert actions[0]["prev_state"] == "pending"
    assert actions[0]["new_state"] == "held"
    assert actions[1]["actor"] == "bob"
    assert actions[1]["prev_state"] == "held"
    assert actions[1]["new_state"] == "approved"
    assert actions[2]["actor"] == "carol"
    assert actions[2]["reason"] == "out of scope"

    assert body["states"] == {"d1": "approved", "d2": "rejected"}
    assert body["summary"]["counts"]["approved"] == 1
    assert body["summary"]["counts"]["rejected"] == 1
    assert body["summary"]["total_decisions"] == 2


# --- F2 integration: request_recheck feeds the next run's delta ------------------------------


def test_request_recheck_condition_is_included_in_load_previous_recheck_conditions(tmp_path):
    scenario_id = "scenario_decision_log_recheck_001"
    _write_decision_queue(tmp_path, scenario_id, ["d1"])
    settings = _settings(tmp_path)
    store = DecisionLogStore(settings)
    store.append_action(scenario_id, "d1", action="request_recheck", actor="alice", reason="confirm sanctions list")

    conditions = load_previous_recheck_conditions(settings, scenario_id)

    assert any(
        condition.startswith("decision_recheck_requested: d1") and "confirm sanctions list" in condition
        for condition in conditions
    )


class _FakeOrchestrator:
    """Mirrors final_agents.py's real behavior of merging `previous_recheck_conditions` into the
    finding's own `analysis_plan.recheck_conditions` (see `_with_previous_recheck_conditions`), so
    a condition injected as input in run N becomes part of run N's *own* snapshot and is therefore
    evaluated against the delta between run N and run N+1 -- exactly like any other recheck
    condition established by a domain agent."""

    def __init__(self, settings: Settings, run_data: dict, received_inputs: list[dict]) -> None:
        self.settings = settings
        self.run_data = run_data
        self.received_inputs = received_inputs

    def run_task(self, request):
        event = RiskEvent.model_validate(request.task.inputs["risk_event"])
        previous_recheck_conditions = list(request.task.inputs.get("previous_recheck_conditions") or [])
        self.received_inputs.append(dict(request.task.inputs))
        output_dir = self.settings.project_root / "outputs" / event.scenario_id
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence_summary.json").write_text(
            json.dumps({"evidence": self.run_data["evidence"]}, ensure_ascii=False), encoding="utf-8"
        )
        (output_dir / "decision_queue.json").write_text(
            json.dumps({"decisions": self.run_data["decisions"]}, ensure_ascii=False), encoding="utf-8"
        )
        own_recheck_conditions = list(self.run_data.get("recheck_conditions", []))
        for condition in previous_recheck_conditions:
            if condition not in own_recheck_conditions:
                own_recheck_conditions.append(condition)
        finding = AgentFinding(
            agent_name="orchestrator-agent",
            mode="orchestrator",
            summary="fake orchestration run",
            rationale="fake orchestration run for decision log recheck testing",
            review_required=True,
            metadata={
                "analysis_plan": {"recheck_conditions": own_recheck_conditions},
                "findings": self.run_data["findings"],
            },
        )
        return AgentTaskResult(
            task_id=request.task.task_id,
            trace_id=request.task.trace_id,
            agent_name="orchestrator-agent",
            status="completed",
            finding=finding,
        )


def _finding_entry(risk_score: int) -> dict:
    return {
        "agent_name": "treasury-risk-agent",
        "mode": "treasury",
        "summary": "s",
        "risk_score": risk_score,
        "confidence": "medium",
        "evidence_ids": [],
        "assumptions": [],
        "unknowns": [],
        "recommended_actions": [],
        "review_required": True,
        "rationale": "r",
        "metadata": {},
    }


def test_request_recheck_action_shows_up_in_next_run_delta_triggers(tmp_path, monkeypatch):
    """A human's request_recheck action feeds the synthetic condition into the orchestrator's next
    run (like any other recheck condition established by a domain agent); the condition then fires
    in the delta of the run *after that* once the associated decision actually changes, matching how
    ordinary recheck_conditions are evaluated one run later than when they are established (see
    test_scenario_delta.py's test_execute_scenario_records_delta_across_two_runs)."""
    settings = _settings(tmp_path)
    scenario_id = "scenario_decision_log_recheck_002"
    event = _event(scenario_id)

    run1_decision = _decision("d1", owner="Treasury").model_dump(mode="json")
    run2_decision = _decision("d1", owner="Treasury").model_dump(mode="json")
    run3_decision = _decision("d1", owner="CFO").model_dump(mode="json")  # triggers a decision_changes entry

    received_inputs: list[dict] = []
    run_state: dict = {"data": {}}

    def _fake_create_orchestrator_service(_settings, embedded_apps=None):
        return _FakeOrchestrator(settings, run_state["data"], received_inputs)

    monkeypatch.setattr(run_scenario, "create_orchestrator_service", _fake_create_orchestrator_service)

    def _set_run(decision: dict, risk_score: int) -> None:
        run_state["data"] = {
            "evidence": [{"evidence_id": "ev-1", "reliability": "medium", "confidence": "medium"}],
            "decisions": [decision],
            "findings": [_finding_entry(risk_score)],
            "recheck_conditions": [],
        }

    _set_run(run1_decision, 40)
    result1, output_dir = run_scenario.execute_scenario(settings, event, embedded_services=False)
    assert result1.status == "completed"

    # A human requests a recheck on "d1" after seeing the first run's output.
    store = DecisionLogStore(settings)
    store.append_action(
        scenario_id, "d1", action="request_recheck", actor="reviewer", reason="confirm updated sanctions list"
    )

    _set_run(run2_decision, 40)
    result2, _ = run_scenario.execute_scenario(settings, event, embedded_services=False)
    assert result2.status == "completed"
    assert any(
        "decision_recheck_requested: d1" in condition for condition in received_inputs[1]["previous_recheck_conditions"]
    )

    _set_run(run3_decision, 40)
    result3, _ = run_scenario.execute_scenario(settings, event, embedded_services=False)
    assert result3.status == "completed"

    delta_files = sorted((output_dir / "deltas").glob("*.json"))
    assert len(delta_files) == 3
    third_delta = json.loads(delta_files[2].read_text(encoding="utf-8"))
    assert third_delta["decision_changes"]  # owner change makes this a real decision_changes entry
    fired_conditions = [
        evaluation["condition"] for evaluation in third_delta["recheck_triggers_fired"] if evaluation["status"] == "fired"
    ]
    assert any("decision_recheck_requested: d1" in condition for condition in fired_conditions)


# --- Portfolio aggregation --------------------------------------------------------------------


def test_portfolio_summary_includes_decision_log_summary(tmp_path):
    from risk_agent_platform.schemas import DiscoveredRisk, RiskDiscoveryRequest, RiskDiscoveryResult, RiskDiscoveryScope

    scenario_id = "scenario_decision_log_portfolio_001"
    event = _event(scenario_id)
    _write_decision_queue(tmp_path, scenario_id, ["d1", "d2", "d3"])
    settings = _settings(tmp_path)
    store = DecisionLogStore(settings)
    store.append_action(scenario_id, "d1", action="approve", actor="alice")
    store.append_action(scenario_id, "d2", action="hold", actor="bob", reason="waiting on legal review")
    # d3 has no log entries -> counts as pending.

    request = RiskDiscoveryRequest(
        event_title="Iran war escalation",
        event_description="Shipping and payments may be disrupted.",
        countries=["Iran"],
        max_risks=3,
        scope=RiskDiscoveryScope(client_id="demo_client", scope_type="company", scope_name="Demo Company"),
    )
    result = RiskDiscoveryResult(
        request=request,
        selected_candidates=[
            DiscoveredRisk(
                candidate_id="DISC-001",
                title=event.title,
                risk_type=event.risk_type,
                description=event.description,
                relevance_score=90,
                rationale="test",
                selected_for_analysis=True,
            )
        ],
        selected_event=event,
        selected_events=[event],
    )
    records = [
        {
            "scenario_id": event.scenario_id,
            "title": event.title,
            "risk_type": event.risk_type,
            "risk_themes": event.risk_themes,
            "urgency": event.urgency,
            "status": "completed",
            "trace_id": "trace-001",
            "output_dir": str(tmp_path / "outputs" / event.scenario_id),
            "decision_count": 3,
            "decisions": [],
            "evidence_count": 0,
            "evidence_domains": [],
            "orchestrator_finding": {"review_required": False},
            "decision_log_summary": store.state_summary(scenario_id),
        }
    ]

    paths = run_discovery._write_portfolio_summary(settings, result, records)
    summary = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    rollup = summary["portfolio_overview"]["decision_log_summary"]

    assert rollup["total_decisions"] == 3
    assert rollup["counts"]["approved"] == 1
    assert rollup["counts"]["held"] == 1
    assert rollup["counts"]["pending"] == 1
    assert rollup["held_reasons"]["d2"] == ["waiting on legal review"]


def test_decision_log_artifact_is_listed_and_fetchable(tmp_path):
    scenario_id = "scenario_decision_log_artifact_001"
    _write_decision_queue(tmp_path, scenario_id, ["d1"])
    settings = _settings(tmp_path)
    DecisionLogStore(settings).append_action(scenario_id, "d1", action="approve", actor="alice")

    app = create_app(settings, job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        listing = client.get(f"/v1/scenarios/{scenario_id}/artifacts")
        assert listing.status_code == 200
        assert "decision_log.jsonl" in listing.json()["artifacts"]

        fetched = client.get(f"/v1/scenarios/{scenario_id}/artifacts/decision_log.jsonl")
        assert fetched.status_code == 200
        assert fetched.headers["content-type"].startswith("application/x-ndjson")
        line = json.loads(fetched.text.strip().splitlines()[0])
        assert line["decision_id"] == "d1"
        assert line["action"] == "approve"
