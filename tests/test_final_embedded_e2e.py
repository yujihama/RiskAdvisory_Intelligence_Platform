from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from risk_agent_platform.config import Settings
from risk_agent_platform.final_agents import create_embedded_a2a_apps, create_orchestrator_service, new_root_task
from risk_agent_platform.schemas import AgentTaskRequest, AnalysisPlan, DecisionSynthesisOutput, RiskEvent, SourceQueryPlan
from risk_agent_platform.stores.neo4j_store import Neo4jStore
from risk_agent_platform.stores.qdrant_store import QdrantStore


def test_final_embedded_e2e_with_mocked_tavily_and_dummy_client_data(tmp_path, monkeypatch):
    root = Path.cwd()
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    monkeypatch.setattr(
        "risk_agent_platform.deepagent_runtime.DeepAgentRunner.synthesize",
        lambda self, prompt, max_chars=600: f"{self.agent_name} synthesized",
    )
    monkeypatch.setattr(
        "risk_agent_platform.deepagent_runtime.DeepAgentRunner.synthesize_structured",
        _fake_structured_output,
    )
    monkeypatch.setattr("risk_agent_platform.mcp_servers.factory.TavilyClient", _FakeTavilyClient)

    shutil.copytree(root / "data" / "clients", tmp_path / "data" / "clients")
    shutil.copytree(root / "data" / "expert_knowledge", tmp_path / "data" / "expert_knowledge")
    shutil.copytree(root / "config", tmp_path / "config")

    settings = replace(Settings.load(root), project_root=tmp_path, data_dir=tmp_path / "data")
    _skip_if_stores_unavailable(settings)

    event = RiskEvent(
        scenario_id="scenario_test_final_e2e",
        client_id="demo_client",
        title="Potential sanctions escalation affecting critical supplier payments",
        risk_type="geopolitical_sanctions",
        countries=["Noveria"],
        risk_themes=["sanctions", "payment_disruption", "supplier_resilience"],
        affected_categories=["critical_components", "cross_border_payments"],
        description="A sanctions escalation signal may affect supplier payments and contract performance.",
        event_date=date(2026, 6, 27),
        urgency="high",
    )

    embedded_apps = create_embedded_a2a_apps(settings, embedded_mcp=True)
    orchestrator = create_orchestrator_service(settings, embedded_apps=embedded_apps)
    result = orchestrator.run_task(AgentTaskRequest(task=new_root_task(event)))

    output_dir = tmp_path / "outputs" / event.scenario_id
    assert result.status == "completed"
    assert result.finding is not None
    assert result.finding.metadata["analysis_plan"]["fallback_used"] is False
    findings_by_agent = {item["agent_name"]: item for item in result.finding.metadata["findings"]}
    assert findings_by_agent["source-intelligence-agent"]["metadata"]["queries"]
    assert findings_by_agent["source-intelligence-agent"]["metadata"]["extracted_urls"]
    assert findings_by_agent["expert-as-code-agent"]["metadata"]["knowledge_application_finding"]["similar_case_ids"]
    assert findings_by_agent["evidence-redteam-agent"]["metadata"]["decision_queue_written"] is False
    assert "issue_exploration" in findings_by_agent["treasury-risk-agent"]["metadata"]
    assert (output_dir / "final_brief.md").exists()
    assert (output_dir / "decision_queue.json").exists()
    assert (output_dir / "evidence_summary.json").exists()
    assert (output_dir / "red_team_review.md").exists()
    assert (output_dir / "assumptions_and_unknowns.json").exists()
    assert (output_dir / "trace_metadata.json").exists()

    queue = json.loads((output_dir / "decision_queue.json").read_text(encoding="utf-8"))
    assert queue["decisions"][0]["decision_id"].startswith("scenario_test_final_e2e_decision_001_")
    assert len(queue["decisions"][0]["decision_id"].rsplit("_", 1)[-1]) == 12
    assert queue["decisions"][0]["expert_knowledge_ids"]

    evidence = json.loads((output_dir / "evidence_summary.json").read_text(encoding="utf-8"))
    assert evidence["evidence"][0]["source_type"] == "web"
    assert evidence["evidence"][0]["client_id"] == "demo_client"

    qdrant_hits = QdrantStore(settings).search("evidence_chunks", query=event.title, filters={"scenario_id": event.scenario_id})
    assert qdrant_hits

    store = Neo4jStore(settings)
    try:
        affected = store.find_affected_assets(event.scenario_id)
        assert affected
    finally:
        store.close()


class _FakeTavilyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, **_kwargs):
        return {
            "results": [
                {
                    "url": "https://example.test/sanctions-update",
                    "title": "Official sanctions update",
                    "content": "Authorities announced additional sanctions screening requirements affecting payments.",
                },
                {
                    "url": "https://example.test/payment-routes",
                    "title": "Payment route disruption",
                    "content": "Banks reported increased review of cross-border payments in the affected region.",
                },
            ]
        }

    def extract(self, urls: list[str]):
        return {
            "results": [
                {
                    "url": url,
                    "raw_content": f"Extracted authoritative detail for {url}.",
                }
                for url in urls
            ]
        }


def _fake_structured_output(self, _prompt, output_model, **_kwargs):
    if output_model is SourceQueryPlan:
        return SourceQueryPlan(
            queries=[
                "Noveria sanctions payment disruption official source",
                "Noveria supplier continuity logistics disruption official source",
            ],
            rationale="Test query plan.",
        )
    if output_model is AnalysisPlan:
        return AnalysisPlan(
            selected_agents=[
                "client-context-agent",
                "source-intelligence-agent",
                "treasury-risk-agent",
                "legal-risk-agent",
                "expert-as-code-agent",
                "evidence-redteam-agent",
            ],
            rationale="Test analysis plan.",
        )
    if output_model is DecisionSynthesisOutput:
        evidence_ids = _json_line_value(_prompt, "available_evidence_ids") or ["scenario_test_final_e2e_tavily_001"]
        expert_ids = _json_line_value(_prompt, "available_expert_knowledge_ids") or []
        return DecisionSynthesisOutput(
            decision="Decide whether to hold or reroute supplier payments under legal and treasury controls.",
            owner="Treasury / Legal",
            deadline="48 hours",
            deadline_rationale="Mocked structured decision uses payment and sanctions evidence without immediate execution proof.",
            deadline_signals=["test:payment_sanctions_evidence"],
            rationale="Test structured decision synthesis output.",
            options=["Proceed after screening", "Hold pending legal review", "Prepare approved alternate route"],
            cited_evidence_ids=evidence_ids[:1],
            cited_expert_knowledge_ids=expert_ids[:1],
            risk_if_delayed="Delayed ownership may worsen payment, sanctions, and supplier continuity exposure.",
            review_required=True,
            priority=2,
        )
    return output_model()


def _json_line_value(prompt: str, key: str):
    for line in prompt.splitlines():
        if line.startswith(f"{key}="):
            return json.loads(line.split("=", 1)[1])
    return None


def _skip_if_stores_unavailable(settings: Settings) -> None:
    if not settings.openrouter.api_key:
        pytest.skip("OPENROUTER_API_KEY is required to construct DeepAgent-backed services")
    try:
        QdrantStore(settings).ensure_collections()
        store = Neo4jStore(settings)
        try:
            store.ping()
        finally:
            store.close()
    except Exception as exc:
        pytest.skip(f"Qdrant/Neo4j integration services are unavailable: {exc}")
