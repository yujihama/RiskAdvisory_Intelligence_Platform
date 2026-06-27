from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from risk_agent_platform.config import Settings
from risk_agent_platform.final_agents import create_embedded_a2a_apps, create_orchestrator_service, new_root_task
from risk_agent_platform.schemas import AgentTaskRequest, RiskEvent
from risk_agent_platform.stores.neo4j_store import Neo4jStore
from risk_agent_platform.stores.qdrant_store import QdrantStore


def test_final_embedded_e2e_with_mocked_tavily_and_dummy_client_data(tmp_path, monkeypatch):
    root = Path.cwd()
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setattr(
        "risk_agent_platform.deepagent_runtime.DeepAgentRunner.synthesize",
        lambda self, prompt, max_chars=600: f"{self.agent_name} synthesized",
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
    assert (output_dir / "final_brief.md").exists()
    assert (output_dir / "decision_queue.json").exists()
    assert (output_dir / "evidence_summary.json").exists()
    assert (output_dir / "red_team_review.md").exists()
    assert (output_dir / "assumptions_and_unknowns.json").exists()
    assert (output_dir / "trace_metadata.json").exists()

    queue = json.loads((output_dir / "decision_queue.json").read_text(encoding="utf-8"))
    assert queue["decisions"][0]["decision_id"] == "scenario_test_final_e2e_decision_001"
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
