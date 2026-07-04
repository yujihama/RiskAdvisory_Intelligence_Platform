from __future__ import annotations

import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from risk_agent_platform.api import runner as api_runner
from risk_agent_platform.api.app import create_app, default_job_db_path
from risk_agent_platform.api.jobs import JobStore
from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import AgentError, AgentTaskResult, RiskEvent


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.load(Path.cwd()), project_root=tmp_path, data_dir=tmp_path / "data")


def _wait_for_status(client: TestClient, job_id: str, target_statuses: set[str], timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in target_statuses:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {target_statuses} in time; last={last}")


def test_healthz(tmp_path):
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_discovery_job_lifecycle_completes(tmp_path, monkeypatch):
    scenario_id = "scenario_test_api_001"

    def _fake_execute_discovery_job(settings, request, options):
        return {
            "discovery_status": "completed",
            "selected_candidate_count": 1,
            "rejected_candidate_count": 0,
            "fallback_used": False,
            "discovery_confidence": "agent_recorded_candidates",
            "selected_scenario_id": scenario_id,
            "selected_scenario_ids": [scenario_id],
            "discovery_output": str(settings.project_root / "outputs" / "risk_discovery" / f"{scenario_id}.json"),
            "analysis_status": "skipped",
            "records": [],
            "analysis_count": 0,
            "portfolio_summary_json": None,
            "portfolio_summary_md": None,
        }

    monkeypatch.setattr(api_runner, "execute_discovery_job", _fake_execute_discovery_job)

    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.post(
            "/v1/discoveries",
            json={
                "event_title": "Test event",
                "client_id": "demo_client",
                "scope_type": "company",
                "scope_name": "Demo Company",
                "run_analysis": True,
            },
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert job_id

        final = _wait_for_status(client, job_id, {"completed", "failed"})

    assert final["status"] == "completed"
    assert final["job_type"] == "discovery"
    assert final["trace_id"]
    assert final["started_at"] is not None
    assert final["finished_at"] is not None
    assert final["result"]["selected_scenario_id"] == scenario_id
    assert final["result"]["scenario_ids"] == [scenario_id]
    assert final["error"] is None


def test_discovery_job_failure_path_is_sanitized(tmp_path, monkeypatch):
    def _raising_execute_discovery_job(settings, request, options):
        raise RuntimeError("boom while calling the orchestrator")

    monkeypatch.setattr(api_runner, "execute_discovery_job", _raising_execute_discovery_job)

    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.post(
            "/v1/discoveries",
            json={"event_title": "Failing event", "client_id": "demo_client"},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        final = _wait_for_status(client, job_id, {"completed", "failed"})

    assert final["status"] == "failed"
    assert final["error"] is not None
    assert "boom while calling the orchestrator" in final["error"]
    body_text = client.get(f"/v1/jobs/{job_id}").text
    assert "Traceback" not in body_text
    assert "traceback" not in body_text.lower()


def test_scenario_job_lifecycle_completes(tmp_path, monkeypatch):
    scenario_id = "scenario_test_api_scenario_001"

    def _fake_execute_scenario_job(settings, event, *, embedded_services):
        output_dir = settings.project_root / "outputs" / event.scenario_id
        result = AgentTaskResult(
            task_id="t1",
            trace_id="trace-fake-001",
            agent_name="orchestrator-agent",
            status="completed",
        )
        return result, output_dir

    monkeypatch.setattr(api_runner, "execute_scenario_job", _fake_execute_scenario_job)

    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    event = RiskEvent(
        scenario_id=scenario_id,
        client_id="demo_client",
        title="Test scenario",
        risk_type="geopolitical_sanctions",
        description="Test description",
        event_date=date(2026, 7, 1),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/scenarios",
            json={"event": event.model_dump(mode="json")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        final = _wait_for_status(client, job_id, {"completed", "failed"})

    assert final["status"] == "completed"
    assert final["result"]["scenario_id"] == scenario_id
    assert final["result"]["trace_id"] == "trace-fake-001"


def test_scenario_job_marks_failed_on_agent_error(tmp_path, monkeypatch):
    def _fake_execute_scenario_job(settings, event, *, embedded_services):
        output_dir = settings.project_root / "outputs" / event.scenario_id
        result = AgentTaskResult(
            task_id="t1",
            trace_id="trace-fake-002",
            agent_name="orchestrator-agent",
            status="failed",
            error=AgentError(code="upstream_error", message="downstream agent unavailable"),
        )
        return result, output_dir

    monkeypatch.setattr(api_runner, "execute_scenario_job", _fake_execute_scenario_job)

    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    event = RiskEvent(
        scenario_id="scenario_test_api_scenario_002",
        client_id="demo_client",
        title="Test scenario",
        risk_type="geopolitical_sanctions",
        description="Test description",
        event_date=date(2026, 7, 1),
    )
    with TestClient(app) as client:
        response = client.post("/v1/scenarios", json={"event": event.model_dump(mode="json")})
        job_id = response.json()["job_id"]
        final = _wait_for_status(client, job_id, {"completed", "failed"})

    assert final["status"] == "failed"
    assert "upstream_error" in final["error"]
    assert "downstream agent unavailable" in final["error"]


def test_orphan_job_is_recovered_as_failed_on_startup(tmp_path):
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    store.create_job("job_orphan_001", "discovery", "trace-orphan-001", {"event_title": "x"})
    store.mark_working("job_orphan_001")
    store.close()

    app = create_app(_settings(tmp_path), job_db_path=db_path)
    with TestClient(app) as client:
        response = client.get("/v1/jobs/job_orphan_001")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "orphaned_by_restart"


def test_job_list_filters_by_status(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_runner,
        "execute_discovery_job",
        lambda settings, request, options: {
            "discovery_status": "completed",
            "selected_candidate_count": 0,
            "rejected_candidate_count": 0,
            "fallback_used": False,
            "discovery_confidence": "",
            "selected_scenario_id": "",
            "selected_scenario_ids": [],
            "discovery_output": "",
            "analysis_status": "skipped:no_selected_event",
            "records": [],
            "analysis_count": 0,
            "portfolio_summary_json": None,
            "portfolio_summary_md": None,
        },
    )
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.post("/v1/discoveries", json={"event_title": "Event", "client_id": "demo_client"})
        job_id = response.json()["job_id"]
        _wait_for_status(client, job_id, {"completed", "failed"})

        completed = client.get("/v1/jobs", params={"status": "completed"}).json()["jobs"]
        failed = client.get("/v1/jobs", params={"status": "failed"}).json()["jobs"]
        all_jobs = client.get("/v1/jobs").json()["jobs"]

    assert any(job["job_id"] == job_id for job in completed)
    assert not any(job["job_id"] == job_id for job in failed)
    assert any(job["job_id"] == job_id for job in all_jobs)


def test_missing_required_fields_returns_422(tmp_path):
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.post("/v1/discoveries", json={"event_description": "no title or client id"})
    assert response.status_code == 422


def test_scenario_request_requires_exactly_one_source(tmp_path):
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.post("/v1/scenarios", json={})
    assert response.status_code == 422


def test_artifact_listing_and_fetch(tmp_path):
    scenario_id = "scenario_artifact_test"
    scenario_dir = tmp_path / "outputs" / scenario_id
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "final_brief.md").write_text("# Brief\ncontent", encoding="utf-8")
    (scenario_dir / "decision_queue.json").write_text('{"decisions": []}', encoding="utf-8")

    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        listing = client.get(f"/v1/scenarios/{scenario_id}/artifacts")
        assert listing.status_code == 200
        names = listing.json()["artifacts"]
        assert "final_brief.md" in names
        assert "decision_queue.json" in names

        brief = client.get(f"/v1/scenarios/{scenario_id}/artifacts/final_brief.md")
        assert brief.status_code == 200
        assert brief.headers["content-type"].startswith("text/markdown")
        assert "content" in brief.text

        queue = client.get(f"/v1/scenarios/{scenario_id}/artifacts/decision_queue.json")
        assert queue.status_code == 200
        assert queue.headers["content-type"].startswith("application/json")
        assert queue.json() == {"decisions": []}


def test_artifact_path_traversal_is_rejected(tmp_path):
    scenario_id = "scenario_artifact_traversal"
    scenario_dir = tmp_path / "outputs" / scenario_id
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "final_brief.md").write_text("secret", encoding="utf-8")
    outside_secret = tmp_path / "outside_secret.txt"
    outside_secret.write_text("do not serve me", encoding="utf-8")

    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        traversal = client.get(f"/v1/scenarios/{scenario_id}/artifacts/../../outside_secret.txt")
        assert traversal.status_code in (400, 404)

        absolute = client.get(f"/v1/scenarios/{scenario_id}/artifacts/%2Fetc%2Fpasswd")
        assert absolute.status_code in (400, 404)

        unknown = client.get(f"/v1/scenarios/{scenario_id}/artifacts/not_a_real_artifact.json")
        assert unknown.status_code == 404


def test_artifact_listing_for_unknown_scenario_is_404(tmp_path):
    app = create_app(_settings(tmp_path), job_db_path=tmp_path / "jobs.sqlite3")
    with TestClient(app) as client:
        response = client.get("/v1/scenarios/no_such_scenario/artifacts")
    assert response.status_code == 404


def test_default_job_db_path_respects_env_override(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.delenv("PLATFORM_API_JOB_DB", raising=False)
    assert default_job_db_path(settings) == tmp_path / "outputs" / "api_jobs.sqlite3"

    override_path = tmp_path / "custom" / "jobs.sqlite3"
    monkeypatch.setenv("PLATFORM_API_JOB_DB", str(override_path))
    assert default_job_db_path(settings) == override_path
