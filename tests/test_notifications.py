from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from risk_agent_platform import notifications as notifications_module
from risk_agent_platform import run_scenario
from risk_agent_platform.config import Settings
from risk_agent_platform.notifications import (
    NotificationDecisionRef,
    NotificationDeltaRef,
    NotificationEngine,
    NotificationEvent,
    NotificationFindingRef,
    PortfolioDeadlineConflictRef,
    PortfolioOwnerGapRef,
    _idempotency_key,
    build_scenario_event,
    dispatch_portfolio_notifications,
    dispatch_scenario_notifications,
)
from risk_agent_platform.run_scenario import execute_scenario
from risk_agent_platform.schemas import AgentFinding, AgentTaskResult, DecisionItem, RiskEvent, ScenarioDelta


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")


def _write_rules(path: Path, rules: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(rule) for rule in rules) + "\n", encoding="utf-8")


def _default_rules() -> list[dict]:
    return [
        {
            "rule_id": "R-SCORE",
            "description": "test",
            "enabled": True,
            "trigger": "risk_score_threshold",
            "params": {"min_risk_score": 70},
            "channels": ["webhook"],
            "severity": "high",
        },
        {
            "rule_id": "R-REVIEW",
            "description": "test",
            "enabled": True,
            "trigger": "review_required_decision",
            "params": {},
            "channels": ["webhook"],
            "severity": "high",
        },
        {
            "rule_id": "R-DELTA",
            "description": "test",
            "enabled": True,
            "trigger": "delta_changes",
            "params": {"min_changes": 1},
            "channels": ["webhook"],
            "severity": "medium",
        },
        {
            "rule_id": "R-OWNER-GAP",
            "description": "test",
            "enabled": True,
            "trigger": "portfolio_owner_gap",
            "params": {},
            "channels": ["webhook"],
            "severity": "high",
        },
        {
            "rule_id": "R-DEADLINE",
            "description": "test",
            "enabled": True,
            "trigger": "portfolio_deadline_conflict",
            "params": {},
            "channels": ["webhook"],
            "severity": "medium",
        },
        {
            "rule_id": "R-COMPLETED",
            "description": "test",
            "enabled": False,
            "trigger": "scenario_completed",
            "params": {},
            "channels": ["webhook"],
            "severity": "info",
        },
    ]


def _scenario_event(**overrides) -> NotificationEvent:
    base = dict(event_type="scenario_completed", scenario_id="scenario_notify_001", trace_id="trace-1", run_id="run-1")
    base.update(overrides)
    return NotificationEvent(**base)


# --- Rule evaluation ---------------------------------------------------------------------


def test_risk_score_threshold_fires_once_per_qualifying_finding(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(
        findings=[
            NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=85, summary="high exposure"),
            NotificationFindingRef(agent_name="legal-risk-agent", risk_score=40, summary="low exposure"),
            NotificationFindingRef(agent_name="procurement-risk-agent", risk_score=70, summary="threshold exposure"),
        ]
    )
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    score_messages = [m for m in messages if m.rule_id == "R-SCORE"]
    assert len(score_messages) == 2
    assert {m.target_id for m in score_messages} == {"treasury-risk-agent", "procurement-risk-agent"}


def test_risk_score_below_threshold_fires_nothing(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(findings=[NotificationFindingRef(agent_name="legal-risk-agent", risk_score=50)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    assert not [m for m in messages if m.rule_id == "R-SCORE"]


def test_review_required_decision_fires(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(
        decisions=[
            NotificationDecisionRef(decision_id="d1", decision="Confirm payment route.", owner="Treasury", review_required=True),
            NotificationDecisionRef(decision_id="d2", decision="Log for records.", owner="Legal", review_required=False),
        ]
    )
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    review_messages = [m for m in messages if m.rule_id == "R-REVIEW"]
    assert len(review_messages) == 1
    assert review_messages[0].target_id == "d1"


def test_delta_changes_fires_when_changes_present(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(
        delta=NotificationDeltaRef(run_id="run-2", previous_run_id="run-1", baseline=False, evidence_added_count=1)
    )
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    delta_messages = [m for m in messages if m.rule_id == "R-DELTA"]
    assert len(delta_messages) == 1
    assert delta_messages[0].target_id == "run-2"


def test_delta_baseline_does_not_fire(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(delta=NotificationDeltaRef(run_id="run-1", baseline=True))
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    assert not [m for m in messages if m.rule_id == "R-DELTA"]


def test_portfolio_owner_gap_and_deadline_conflict_fire(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = NotificationEvent(
        event_type="portfolio_summary",
        scenario_id="portfolio_001",
        run_id="portfolio_001",
        owner_gaps=[
            PortfolioOwnerGapRef(
                group_id="sanctions_review",
                missing_owners=["Legal"],
                required_owners=["Legal"],
                owners=["Treasury"],
                scenario_ids=["s1"],
            )
        ],
        deadline_conflicts=[
            PortfolioDeadlineConflictRef(
                group_id="payment_execution",
                owners=["Treasury", "CFO"],
                deadlines=["2026-08-01", "2026-08-05"],
                scenario_ids=["s1", "s2"],
            )
        ],
    )
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    owner_gap_messages = [m for m in messages if m.rule_id == "R-OWNER-GAP"]
    deadline_messages = [m for m in messages if m.rule_id == "R-DEADLINE"]
    assert len(owner_gap_messages) == 1
    assert owner_gap_messages[0].target_id == "sanctions_review"
    assert len(deadline_messages) == 1
    assert deadline_messages[0].target_id == "payment_execution"


def test_disabled_rule_never_fires(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event()
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    assert not [m for m in messages if m.rule_id == "R-COMPLETED"]


# --- Idempotency --------------------------------------------------------------------------


def test_evaluating_same_event_twice_in_one_dispatch_does_not_duplicate(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=90)])
    engine = NotificationEngine(settings)
    first = engine.evaluate(event)
    second = engine.evaluate(event)
    assert len(first) == 1
    assert second == []


def test_idempotency_key_stable_across_instances_for_identical_inputs():
    key1 = _idempotency_key("RULE-1", "scenario_001", "run_001", "target_a")
    key2 = _idempotency_key("RULE-1", "scenario_001", "run_001", "target_a")
    assert key1 == key2
    key3 = _idempotency_key("RULE-1", "scenario_001", "run_001", "target_b")
    assert key1 != key3


# --- New rule without code change ----------------------------------------------------------


def test_new_rule_appended_to_jsonl_fires_without_code_change(tmp_path):
    settings = _settings(tmp_path)
    rules_path = settings.data_dir / "notification_rules.jsonl"
    _write_rules(rules_path, _default_rules())
    with rules_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "rule_id": "R-SCORE-STRICT",
                    "description": "stricter score threshold appended as a new JSONL line",
                    "enabled": True,
                    "trigger": "risk_score_threshold",
                    "params": {"min_risk_score": 95},
                    "channels": ["webhook"],
                    "severity": "critical",
                }
            )
            + "\n"
        )
    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=97)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    strict_messages = [m for m in messages if m.rule_id == "R-SCORE-STRICT"]
    assert len(strict_messages) == 1
    assert strict_messages[0].severity == "critical"


# --- Retry / failure ------------------------------------------------------------------------


def test_webhook_retry_exhausts_and_records_failure(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings = replace(
        settings,
        notifications=replace(settings.notifications, webhook_url="http://example.invalid/hook", retry_max_attempts=3, retry_base_delay_seconds=0.0),
    )
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())

    call_count = {"n": 0}

    def _always_fail(url, payload, timeout_seconds=10.0):
        call_count["n"] += 1
        raise ConnectionError("simulated webhook outage")

    monkeypatch.setattr(notifications_module, "send_http_post_json", _always_fail)

    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=90)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    outcomes = engine.dispatch(messages)

    assert call_count["n"] == 4  # 1 initial attempt + 3 retries
    failed_outcomes = [o for o in outcomes if o.status == "failed"]
    assert len(failed_outcomes) == 1
    assert failed_outcomes[0].attempts == 4

    failures_path = tmp_path / "outputs" / event.scenario_id / "notification_failures.json"
    assert failures_path.exists()
    failures = json.loads(failures_path.read_text(encoding="utf-8"))["failures"]
    assert len(failures) == 1
    assert failures[0]["attempts"] == 4
    assert "simulated webhook outage" in failures[0]["error"]


def test_scenario_execution_still_succeeds_when_notifications_fail(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings = replace(
        settings,
        notifications=replace(settings.notifications, webhook_url="http://example.invalid/hook", retry_max_attempts=1, retry_base_delay_seconds=0.0),
    )

    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())

    def _always_fail(url, payload, timeout_seconds=10.0):
        raise ConnectionError("simulated webhook outage")

    monkeypatch.setattr(notifications_module, "send_http_post_json", _always_fail)

    class _FakeOrchestrator:
        def run_task(self, request):
            event = RiskEvent.model_validate(request.task.inputs["risk_event"])
            output_dir = settings.project_root / "outputs" / event.scenario_id
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "decision_queue.json").write_text(
                json.dumps({"decisions": [DecisionItem(
                    decision_id="d1",
                    decision="Confirm payment route.",
                    owner="Treasury",
                    deadline="2026-08-01",
                    rationale="r",
                    options=["a", "b"],
                    risk_if_delayed="high",
                    review_required=True,
                    priority=1,
                ).model_dump(mode="json")]}),
                encoding="utf-8",
            )
            finding = AgentFinding(
                agent_name="treasury-risk-agent",
                mode="treasury",
                summary="s",
                risk_score=90,
                rationale="r",
                metadata={"findings": [
                    {"agent_name": "treasury-risk-agent", "risk_score": 90, "review_required": True, "summary": "s"}
                ]},
            )
            return AgentTaskResult(
                task_id=request.task.task_id,
                trace_id=request.task.trace_id,
                agent_name="orchestrator-agent",
                status="completed",
                finding=finding,
            )

    monkeypatch.setattr(run_scenario, "create_orchestrator_service", lambda *_a, **_k: _FakeOrchestrator())

    event = RiskEvent(
        scenario_id="scenario_notify_failure_001",
        client_id="demo_client",
        title="Sanctions escalation review",
        risk_type="geopolitical_sanctions",
        description="A sanctions escalation may affect supplier payments.",
        event_date=date(2026, 7, 1),
        urgency="high",
    )

    result, output_dir = execute_scenario(settings, event, embedded_services=False)

    assert result.status == "completed"
    failures_path = output_dir / "notification_failures.json"
    assert failures_path.exists()


# --- Sanitization ---------------------------------------------------------------------------


def test_confidential_values_are_redacted_from_payload(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(
        findings=[
            NotificationFindingRef(
                agent_name="treasury-risk-agent",
                risk_score=90,
                summary="INV-88213 exceeds materiality threshold of 123456.78",
            )
        ]
    )
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    assert len(messages) == 1
    payload_text = " ".join(messages[0].body) + messages[0].title
    assert "INV-88213" not in payload_text
    assert "123456.78" not in payload_text
    assert "invoice" in payload_text.lower()


def test_build_scenario_event_reads_decisions_from_output_dir(tmp_path):
    settings = _settings(tmp_path)
    output_dir = settings.project_root / "outputs" / "scenario_notify_002"
    output_dir.mkdir(parents=True)
    (output_dir / "decision_queue.json").write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "decision_id": "d1",
                        "decision": "Confirm payment route via SUP-4471.",
                        "owner": "Treasury",
                        "deadline": "2026-08-01",
                        "rationale": "r",
                        "options": ["a", "b"],
                        "risk_if_delayed": "high",
                        "review_required": True,
                        "priority": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    event = RiskEvent(
        scenario_id="scenario_notify_002",
        client_id="demo_client",
        title="Sanctions escalation review",
        risk_type="geopolitical_sanctions",
        description="A sanctions escalation may affect supplier payments.",
        event_date=date(2026, 7, 1),
        urgency="high",
    )
    result = AgentTaskResult(
        task_id="t1",
        trace_id="trace-1",
        agent_name="orchestrator-agent",
        status="completed",
        finding=AgentFinding(agent_name="orchestrator-agent", mode="orchestrator", summary="s", rationale="r"),
    )
    notification_event = build_scenario_event(settings, event, result, None)
    assert notification_event.decisions[0].decision_id == "d1"
    assert notification_event.decisions[0].review_required is True


# --- Unconfigured channels -------------------------------------------------------------------


def test_unconfigured_channel_is_recorded_as_skipped(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=95)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    outcomes = engine.dispatch(messages)
    assert outcomes
    assert all(o.status == "skipped:channel_unconfigured" for o in outcomes)

    notifications_path = tmp_path / "outputs" / event.scenario_id / "notifications.json"
    assert notifications_path.exists()
    logged = json.loads(notifications_path.read_text(encoding="utf-8"))["entries"]
    assert len(logged) == len(messages)


# --- Channel transports -----------------------------------------------------------------------


def test_webhook_channel_sends_via_stubbed_transport(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings = replace(settings, notifications=replace(settings.notifications, webhook_url="http://example.invalid/hook"))
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())

    calls = []

    def _fake_post(url, payload, timeout_seconds=10.0):
        calls.append((url, payload))

    monkeypatch.setattr(notifications_module, "send_http_post_json", _fake_post)

    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=95)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    outcomes = engine.dispatch(messages)

    assert len(calls) == 1
    assert calls[0][0] == "http://example.invalid/hook"
    assert calls[0][1]["idempotency_key"] == messages[0].idempotency_key
    assert all(o.status == "sent" for o in outcomes)


def test_slack_channel_sends_via_stubbed_transport(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings = replace(settings, notifications=replace(settings.notifications, slack_webhook_url="http://example.invalid/slack"))
    _write_rules(
        settings.data_dir / "notification_rules.jsonl",
        [
            {
                "rule_id": "R-SCORE-SLACK",
                "description": "test",
                "enabled": True,
                "trigger": "risk_score_threshold",
                "params": {"min_risk_score": 70},
                "channels": ["slack"],
                "severity": "high",
            }
        ],
    )

    calls = []
    monkeypatch.setattr(notifications_module, "send_http_post_json", lambda url, payload, timeout_seconds=10.0: calls.append((url, payload)))

    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=95)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    outcomes = engine.dispatch(messages)

    assert len(calls) == 1
    assert calls[0][0] == "http://example.invalid/slack"
    assert "text" in calls[0][1]
    assert all(o.status == "sent" for o in outcomes)


def test_smtp_channel_sends_via_stubbed_client(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings = replace(
        settings,
        notifications=replace(
            settings.notifications,
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_from="alerts@example.com",
            smtp_to=["risk-team@example.com"],
        ),
    )
    _write_rules(
        settings.data_dir / "notification_rules.jsonl",
        [
            {
                "rule_id": "R-SCORE-SMTP",
                "description": "test",
                "enabled": True,
                "trigger": "risk_score_threshold",
                "params": {"min_risk_score": 70},
                "channels": ["smtp"],
                "severity": "high",
            }
        ],
    )

    calls = []
    monkeypatch.setattr(
        notifications_module,
        "send_smtp_message",
        lambda host, port, sender, recipients, subject, body: calls.append((host, port, sender, recipients, subject, body)),
    )

    event = _scenario_event(findings=[NotificationFindingRef(agent_name="treasury-risk-agent", risk_score=95)])
    engine = NotificationEngine(settings)
    messages = engine.evaluate(event)
    outcomes = engine.dispatch(messages)

    assert len(calls) == 1
    host, port, sender, recipients, subject, body = calls[0]
    assert host == "smtp.example.invalid"
    assert sender == "alerts@example.com"
    assert recipients == ["risk-team@example.com"]
    assert all(o.status == "sent" for o in outcomes)


def test_dispatch_scenario_notifications_skips_non_completed_status(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    event = RiskEvent(
        scenario_id="scenario_notify_003",
        client_id="demo_client",
        title="Sanctions escalation review",
        risk_type="geopolitical_sanctions",
        description="A sanctions escalation may affect supplier payments.",
        event_date=date(2026, 7, 1),
        urgency="high",
    )
    result = AgentTaskResult(task_id="t1", trace_id="trace-1", agent_name="orchestrator-agent", status="failed")
    outcomes = dispatch_scenario_notifications(settings, event, result, None)
    assert outcomes == []


def test_dispatch_portfolio_notifications_never_raises_on_bad_input(tmp_path):
    settings = _settings(tmp_path)
    _write_rules(settings.data_dir / "notification_rules.jsonl", _default_rules())
    outcomes = dispatch_portfolio_notifications(settings, "portfolio_broken", {"decision_conflicts": "not-a-list"})
    assert outcomes == []
