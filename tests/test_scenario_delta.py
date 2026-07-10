from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from risk_agent_platform import delta as delta_module
from risk_agent_platform import run_scenario
from risk_agent_platform.api.app import create_app
from risk_agent_platform.config import Settings
from risk_agent_platform.delta import (
    RunSnapshot,
    SnapshotEvidence,
    SnapshotFinding,
    compute_delta,
    evaluate_recheck_conditions,
    render_delta_summary,
)
from risk_agent_platform.run_scenario import execute_scenario
from risk_agent_platform.schemas import (
    AgentFinding,
    AgentTaskResult,
    AssumptionItem,
    DecisionItem,
    RiskEvent,
    ScenarioDelta,
    UnknownItem,
    now_utc,
)


def _decision(decision_id: str, decision: str, owner: str, deadline: str, priority: int, review_required: bool) -> DecisionItem:
    return DecisionItem(
        decision_id=decision_id,
        decision=decision,
        owner=owner,
        deadline=deadline,
        rationale="test rationale",
        options=["option a", "option b"],
        risk_if_delayed="high",
        review_required=review_required,
        priority=priority,
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


def test_compute_delta_detects_evidence_score_decision_and_unknown_changes():
    previous = RunSnapshot(
        scenario_id="scenario_delta_unit_001",
        run_id="run_001",
        trace_id="trace-1",
        evidence=[SnapshotEvidence(evidence_id="ev-1"), SnapshotEvidence(evidence_id="ev-2")],
        findings=[
            SnapshotFinding(agent_name="treasury-risk-agent", risk_score=40),
            SnapshotFinding(agent_name="legal-risk-agent", risk_score=60),
        ],
        decisions=[
            _decision("d1", "Confirm payment route.", "Treasury", "2026-08-01", 1, True),
            _decision("d2", "Review sanctions clause.", "Legal", "2026-08-02", 2, False),
        ],
        unknowns=[UnknownItem(id="u1", scenario_id="scenario_delta_unit_001", description="Bank confirmation pending")],
    )
    current = RunSnapshot(
        scenario_id="scenario_delta_unit_001",
        run_id="run_002",
        trace_id="trace-2",
        evidence=[SnapshotEvidence(evidence_id="ev-2"), SnapshotEvidence(evidence_id="ev-3")],
        findings=[
            SnapshotFinding(agent_name="treasury-risk-agent", risk_score=70),
            SnapshotFinding(agent_name="legal-risk-agent", risk_score=45),
        ],
        decisions=[
            _decision("d1", "Confirm payment route.", "CFO", "2026-08-01", 1, True),
            _decision("d3", "Engage alternate supplier.", "Procurement", "2026-08-05", 3, False),
        ],
        unknowns=[],
    )

    delta = compute_delta(previous, current)

    assert delta.baseline is False
    assert delta.previous_run_id == "run_001"
    assert delta.evidence_added == ["ev-3"]
    assert delta.evidence_removed == ["ev-1"]

    scores = {change.agent_name: (change.previous_score, change.current_score) for change in delta.score_changes}
    assert scores["treasury-risk-agent"] == (40, 70)
    assert scores["legal-risk-agent"] == (60, 45)

    by_type: dict[str, list[str]] = {}
    for change in delta.decision_changes:
        by_type.setdefault(change.change_type, []).append(change.decision_id)
    assert by_type.get("added") == ["d3"]
    assert by_type.get("removed") == ["d2"]
    assert by_type.get("modified") == ["d1"]
    modified = next(change for change in delta.decision_changes if change.decision_id == "d1")
    assert "owner" in modified.changed_fields

    assert delta.unknown_resolutions == ["Bank confirmation pending"]


def test_compute_delta_treats_content_fingerprint_as_decision_revision() -> None:
    scenario_id = "scenario_delta_revision"
    previous = RunSnapshot(
        scenario_id=scenario_id,
        run_id="run_001",
        trace_id="trace-1",
        decisions=[
            _decision(
                f"{scenario_id}_decision_001_aaaaaaaaaaaa",
                "Confirm the original payment route.",
                "Treasury",
                "24 hours",
                1,
                True,
            )
        ],
    )
    current = RunSnapshot(
        scenario_id=scenario_id,
        run_id="run_002",
        trace_id="trace-2",
        decisions=[
            _decision(
                f"{scenario_id}_decision_001_bbbbbbbbbbbb",
                "Hold and reroute the payment.",
                "CFO",
                "24 hours",
                1,
                True,
            )
        ],
    )

    delta = compute_delta(previous, current)

    assert [change.change_type for change in delta.decision_changes] == ["modified"]
    change = delta.decision_changes[0]
    assert change.decision_id == f"{scenario_id}_decision_001_bbbbbbbbbbbb"
    assert {"decision", "owner"} <= set(change.changed_fields)


def test_compute_delta_is_baseline_with_no_previous_snapshot():
    current = RunSnapshot(scenario_id="scenario_delta_unit_002", run_id="run_001", trace_id="trace-1")

    delta = compute_delta(None, current)

    assert delta.baseline is True
    assert delta.previous_run_id is None
    assert delta.evidence_added == []
    assert delta.evidence_removed == []
    assert delta.score_changes == []
    assert delta.decision_changes == []
    assert delta.assumption_expirations == []
    assert delta.unknown_resolutions == []


def test_compute_delta_flags_expired_assumptions():
    now = now_utc()
    past = now - timedelta(days=1)
    previous = RunSnapshot(scenario_id="scenario_delta_unit_003", run_id="run_001", trace_id="trace-1")
    current = RunSnapshot(
        scenario_id="scenario_delta_unit_003",
        run_id="run_002",
        trace_id="trace-2",
        assumptions=[
            AssumptionItem(
                id="a1",
                scenario_id="scenario_delta_unit_003",
                description="Pending payments are used as near-term liquidity exposure.",
                expires_at=past,
            )
        ],
    )

    delta = compute_delta(previous, current, now=now)

    assert "Pending payments are used as near-term liquidity exposure." in delta.assumption_expirations


def test_evaluate_recheck_conditions_maps_known_signals_and_flags_free_text():
    delta = ScenarioDelta(
        scenario_id="scenario_delta_unit_004",
        run_id="run_002",
        previous_run_id="run_001",
        evidence_added=["ev-3"],
        score_changes=[],
        decision_changes=[],
    )
    conditions = [
        "Re-check if new evidence emerges about the sanctions list.",
        "Escalate to specialists if the treasury risk score materially changes.",
        "Confirm whether the CFO personally approved the mitigation plan.",
    ]

    evaluations = evaluate_recheck_conditions(conditions, delta)

    by_condition = {evaluation.condition: evaluation for evaluation in evaluations}
    assert by_condition[conditions[0]].status == "fired"
    assert by_condition[conditions[1]].status == "not_fired"
    assert by_condition[conditions[2]].status == "not_evaluable"
    assert by_condition[conditions[2]].rationale == "no deterministic signal mapping"


def test_render_delta_summary_states_no_changes_detected():
    event = _event("scenario_delta_unit_005")
    delta = ScenarioDelta(scenario_id="scenario_delta_unit_005", run_id="run_002", previous_run_id="run_001", baseline=False)

    text = render_delta_summary(event, delta)

    assert "No changes detected" in text


def test_render_delta_summary_baseline_is_explicit():
    event = _event("scenario_delta_unit_006")
    delta = ScenarioDelta(scenario_id="scenario_delta_unit_006", run_id="run_001", previous_run_id=None, baseline=True)

    text = render_delta_summary(event, delta)

    assert "Baseline: `True`" in text
    assert "first recorded run" in text


def test_record_scenario_delta_degrades_on_failure(tmp_path, monkeypatch):
    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")
    event = _event("scenario_delta_degrade_001")
    result = AgentTaskResult(
        task_id="t1",
        trace_id="trace-1",
        agent_name="orchestrator-agent",
        status="completed",
        finding=AgentFinding(agent_name="orchestrator-agent", mode="orchestrator", summary="s", rationale="r"),
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom during snapshot build")

    monkeypatch.setattr(delta_module, "_build_snapshot", _raise)

    produced = delta_module.record_scenario_delta(settings, event, result)

    assert produced is not None
    assert produced.degraded is True
    assert "boom during snapshot build" in (produced.degraded_reason or "")

    deltas_dir = tmp_path / "outputs" / event.scenario_id / "deltas"
    delta_files = list(deltas_dir.glob("*.json"))
    summary_files = list(deltas_dir.glob("*_summary.md"))
    assert len(delta_files) == 1
    assert len(summary_files) == 1
    assert "Degraded" in summary_files[0].read_text(encoding="utf-8")

    runs_dir = tmp_path / "outputs" / event.scenario_id / "runs"
    assert not runs_dir.exists() or not list(runs_dir.glob("*.json"))


def test_record_scenario_delta_skips_non_completed_runs(tmp_path):
    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")
    event = _event("scenario_delta_skip_001")
    result = AgentTaskResult(task_id="t1", trace_id="trace-1", agent_name="orchestrator-agent", status="failed")

    produced = delta_module.record_scenario_delta(settings, event, result)

    assert produced is None
    assert not (tmp_path / "outputs" / event.scenario_id).exists()


class _FakeOrchestrator:
    def __init__(self, settings: Settings, run_data: dict, received_inputs: list[dict]) -> None:
        self.settings = settings
        self.run_data = run_data
        self.received_inputs = received_inputs

    def run_task(self, request):
        event = RiskEvent.model_validate(request.task.inputs["risk_event"])
        self.received_inputs.append(dict(request.task.inputs))
        output_dir = self.settings.project_root / "outputs" / event.scenario_id
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence_summary.json").write_text(
            json.dumps({"evidence": self.run_data["evidence"]}, ensure_ascii=False), encoding="utf-8"
        )
        (output_dir / "decision_queue.json").write_text(
            json.dumps({"decisions": self.run_data["decisions"]}, ensure_ascii=False), encoding="utf-8"
        )
        finding = AgentFinding(
            agent_name="orchestrator-agent",
            mode="orchestrator",
            summary="fake orchestration run",
            rationale="fake orchestration run for delta ledger testing",
            review_required=True,
            metadata={
                "analysis_plan": {"recheck_conditions": self.run_data.get("recheck_conditions", [])},
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


def test_execute_scenario_records_delta_across_two_runs(tmp_path, monkeypatch):
    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")
    event = _event("scenario_delta_integration_001")

    first_run = {
        "evidence": [{"evidence_id": "ev-1", "reliability": "medium", "confidence": "medium"}],
        "decisions": [
            _decision("d1", "Confirm payment route.", "Treasury", "2026-08-01", 1, True).model_dump(mode="json"),
        ],
        "findings": [
            {
                "agent_name": "treasury-risk-agent",
                "mode": "treasury",
                "summary": "s",
                "risk_score": 40,
                "confidence": "medium",
                "evidence_ids": [],
                "assumptions": [],
                "unknowns": [],
                "recommended_actions": [],
                "review_required": True,
                "rationale": "r",
                "metadata": {},
            }
        ],
        "recheck_conditions": ["Re-check if new evidence about the sanctions list appears."],
    }
    second_run = {
        "evidence": [
            {"evidence_id": "ev-1", "reliability": "medium", "confidence": "medium"},
            {"evidence_id": "ev-2", "reliability": "high", "confidence": "high"},
        ],
        "decisions": [
            _decision("d1", "Confirm payment route.", "CFO", "2026-08-01", 1, True).model_dump(mode="json"),
        ],
        "findings": [
            {
                "agent_name": "treasury-risk-agent",
                "mode": "treasury",
                "summary": "s",
                "risk_score": 75,
                "confidence": "medium",
                "evidence_ids": [],
                "assumptions": [],
                "unknowns": [],
                "recommended_actions": [],
                "review_required": True,
                "rationale": "r",
                "metadata": {},
            }
        ],
        "recheck_conditions": [],
    }

    received_inputs: list[dict] = []
    run_state = {"data": first_run}

    def _fake_create_orchestrator_service(_settings, embedded_apps=None):
        return _FakeOrchestrator(settings, run_state["data"], received_inputs)

    monkeypatch.setattr(run_scenario, "create_orchestrator_service", _fake_create_orchestrator_service)

    result1, output_dir = execute_scenario(settings, event, embedded_services=False)
    assert result1.status == "completed"

    run_state["data"] = second_run
    result2, _ = execute_scenario(settings, event, embedded_services=False)
    assert result2.status == "completed"

    assert received_inputs[0]["previous_recheck_conditions"] == []
    assert received_inputs[1]["previous_recheck_conditions"] == ["Re-check if new evidence about the sanctions list appears."]

    delta_files = sorted((output_dir / "deltas").glob("*.json"))
    assert len(delta_files) == 2
    first_delta = json.loads(delta_files[0].read_text(encoding="utf-8"))
    second_delta = json.loads(delta_files[1].read_text(encoding="utf-8"))

    assert first_delta["baseline"] is True
    assert second_delta["baseline"] is False
    assert second_delta["evidence_added"] == ["ev-2"]
    assert any(change["agent_name"] == "treasury-risk-agent" for change in second_delta["score_changes"])
    modified_decisions = [change for change in second_delta["decision_changes"] if change["change_type"] == "modified"]
    assert modified_decisions and "owner" in modified_decisions[0]["changed_fields"]
    assert any(evaluation["status"] == "fired" for evaluation in second_delta["recheck_triggers_fired"])

    summary_files = sorted((output_dir / "deltas").glob("*_summary.md"))
    assert len(summary_files) == 2
    assert "first recorded run" in summary_files[0].read_text(encoding="utf-8")


def test_delta_artifacts_are_listed_and_fetchable(tmp_path):
    scenario_id = "scenario_delta_api_001"
    deltas_dir = tmp_path / "outputs" / scenario_id / "deltas"
    deltas_dir.mkdir(parents=True)
    (deltas_dir / "run_001.json").write_text(
        json.dumps({"scenario_id": scenario_id, "run_id": "run_001", "baseline": True}), encoding="utf-8"
    )
    (deltas_dir / "run_001_summary.md").write_text(
        "# Scenario Delta Summary\n\nThis is the first recorded run for this scenario; no prior run exists for comparison.\n",
        encoding="utf-8",
    )

    settings = replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")
    app = create_app(settings, job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        listing = client.get(f"/v1/scenarios/{scenario_id}/artifacts")
        assert listing.status_code == 200
        names = listing.json()["artifacts"]
        assert "deltas/run_001.json" in names
        assert "deltas/run_001_summary.md" in names

        delta_json = client.get(f"/v1/scenarios/{scenario_id}/artifacts/deltas/run_001.json")
        assert delta_json.status_code == 200
        assert delta_json.headers["content-type"].startswith("application/json")
        assert delta_json.json()["baseline"] is True

        delta_md = client.get(f"/v1/scenarios/{scenario_id}/artifacts/deltas/run_001_summary.md")
        assert delta_md.status_code == 200
        assert delta_md.headers["content-type"].startswith("text/markdown")
        assert "first recorded run" in delta_md.text
