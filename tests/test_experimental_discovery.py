from __future__ import annotations

from pathlib import Path
import threading
import time

from risk_agent_platform.config import Settings
from risk_agent_platform.experimental_discovery import (
    AggregatedRiskScenarioBatch,
    AggregatedRiskScenarioDraft,
    ExperimentalCandidateBatch,
    ExperimentalRiskCandidateDraft,
    MultiLensDiscoveryExperimentResult,
    MultiLensRiskDiscoveryExperiment,
    _normalize_aggregated_scenarios,
    _raw_candidates_from_tool_input,
)
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.run_experimental_discovery import _experiment_result_to_discovery_result
from risk_agent_platform.schemas import RiskDiscoveryRequest, RiskDiscoveryScope


class _UncappedExperimentRunner:
    structured_call_count = 0
    aggregation_structured_call_count = 0
    active_synthesize_count = 0
    max_active_synthesize_count = 0
    lock = threading.Lock()

    def __init__(self, _settings, agent_name, _system_prompt, tools=None):
        self.agent_name = agent_name
        self.tools = {tool.name: tool for tool in tools or []}

    def synthesize(self, _prompt, *, max_chars=600):
        with type(self).lock:
            type(self).active_synthesize_count += 1
            type(self).max_active_synthesize_count = max(
                type(self).max_active_synthesize_count,
                type(self).active_synthesize_count,
            )
        time.sleep(0.05)
        for idx in range(4):
            self.tools["experiment_search_event_context"].invoke(
                {
                    "query": f"{self.agent_name} query {idx}",
                    "max_results": 11 + idx,
                }
            )
        self.tools["experiment_record_candidates"].invoke(
            {
                "candidates": [
                    {
                        "title": f"{self.agent_name} candidate {idx}",
                        "risk_type": "supplier_resilience",
                        "risk_themes": ["theme"],
                        "affected_categories": ["asset"],
                        "mechanism": "test mechanism",
                        "affected_asset": "test asset",
                        "time_horizon": "near term",
                        "owner": "risk owner",
                        "description": "candidate description",
                        "urgency": "high",
                        "source_refs": ["https://example.test/source"],
                        "assumptions": ["assumption"],
                        "trigger_signals": ["signal"],
                        "distinctiveness_reason": "distinct",
                        "downside_if_missed": "downside",
                        "rationale": "test rationale",
                    }
                    for idx in range(12)
                ]
            }
        )
        with type(self).lock:
            type(self).active_synthesize_count -= 1
        return f"{self.agent_name} synthesis"

    def synthesize_structured(self, _prompt, output_model, **_kwargs):
        type(self).structured_call_count += 1
        if output_model is AggregatedRiskScenarioBatch:
            type(self).aggregation_structured_call_count += 1
            batch = AggregatedRiskScenarioBatch(
                scenarios=[
                    AggregatedRiskScenarioDraft(
                        scenario_id="SCN-001",
                        title="統合集約シナリオ",
                        risk_type="legal_compliance",
                        countries=["United States"],
                        risk_themes=["aggregated_theme"],
                        affected_categories=["aggregated_asset"],
                        scenario_story="3つのレンズから統合されたシナリオ。",
                        mechanism="aggregated mechanism",
                        affected_asset="aggregated asset",
                        time_horizon="near term",
                        owner="aggregated owner",
                        severity="high",
                        likelihood="medium",
                        analysis="aggregated analysis",
                        assumptions=["aggregated assumption"],
                        trigger_signals=["aggregated trigger"],
                        early_warning_indicators=["aggregated indicator"],
                        recommended_actions=["aggregated action"],
                        source_lenses=["event_fact_visible_risk", "historical_analog_risk"],
                        source_candidate_ids=["EFVR-001", "HAR-001"],
                        source_refs=["https://example.test/structured"],
                        rationale="agent aggregated rationale",
                    )
                ],
                synthesis_observations=["aggregated by agent"],
            )
            return output_model.model_validate(batch.model_dump(mode="json"))
        batch = ExperimentalCandidateBatch(
            candidates=[
                ExperimentalRiskCandidateDraft(
                    title=f"{self.agent_name} structured candidate {idx}",
                    risk_type="legal_compliance",
                    risk_themes=["structured_theme"],
                    affected_categories=["structured_asset"],
                    mechanism="structured mechanism",
                    affected_asset="structured asset",
                    time_horizon="near term",
                    owner="structured owner",
                    description="structured candidate description",
                    urgency="high",
                    source_refs=["https://example.test/structured"],
                    assumptions=["structured assumption"],
                    trigger_signals=["structured signal"],
                    distinctiveness_reason="structured distinctiveness",
                    downside_if_missed="structured downside",
                    rationale="structured rationale",
                )
                for idx in range(5)
            ],
        )
        return output_model.model_validate(batch.model_dump(mode="json"))


def test_multi_lens_experimental_discovery_runs_without_local_caps(monkeypatch):
    _UncappedExperimentRunner.structured_call_count = 0
    _UncappedExperimentRunner.aggregation_structured_call_count = 0
    _UncappedExperimentRunner.active_synthesize_count = 0
    _UncappedExperimentRunner.max_active_synthesize_count = 0
    monkeypatch.setattr("risk_agent_platform.experimental_discovery.DeepAgentRunner", _UncappedExperimentRunner)
    search_calls = []

    def fake_call(self, server_name, tool_name, arguments=None):
        payload = arguments or {}
        if server_name == "mcp-web-search" and tool_name == "search_authoritative_sources":
            search_calls.append(payload)
            max_results = payload["max_results"]
            return {
                "query": payload["query"],
                "query_hash": f"hash-{len(search_calls)}",
                "results": [
                    {
                        "title": f"result {idx}",
                        "url": f"https://example.test/{idx}",
                        "content": "content",
                    }
                    for idx in range(max_results)
                ],
            }
        raise AssertionError(f"unexpected MCP call: {server_name}.{tool_name}")

    monkeypatch.setattr(MCPGateway, "call", fake_call)
    request = RiskDiscoveryRequest(
        event_title="Frontier LLM release restrictions",
        event_description="Public release and API access may be restricted.",
        countries=["United States"],
        max_risks=10,
        scope=RiskDiscoveryScope(
            client_id="fujifilm_dummy",
            scope_text="Enterprise AI, LLM procurement, legal compliance, and business continuity.",
        ),
    )

    result = MultiLensRiskDiscoveryExperiment(Settings.load(Path.cwd()), embedded_mcp=True).discover(request)

    assert len(result.lens_results) == 3
    assert result.metadata["web_search_count"] == 12
    assert result.metadata["candidate_count"] == 15
    assert result.metadata["aggregated_scenario_count"] == 1
    assert result.metadata["execution_mode"] == "parallel_discovery_then_agent_aggregation"
    assert result.metadata["aggregation"]["generation"] == "structured_agent_return"
    assert result.metadata["aggregation"]["response_format"] is True
    assert _UncappedExperimentRunner.structured_call_count == 4
    assert _UncappedExperimentRunner.aggregation_structured_call_count == 1
    assert _UncappedExperimentRunner.max_active_synthesize_count > 1
    assert len(search_calls) == 12
    assert {call["max_results"] for call in search_calls} == {11, 12, 13, 14}
    assert all(len(lens.web_searches) == 4 for lens in result.lens_results)
    assert all(len(lens.candidates) == 5 for lens in result.lens_results)
    assert [scenario.scenario_id for scenario in result.aggregated_scenarios] == ["SCN-001"]
    assert all(lens.metadata["candidate_generation"] == "structured_agent_return" for lens in result.lens_results)
    assert all(lens.metadata["interim_recorded_candidate_count"] == 12 for lens in result.lens_results)
    assert all(candidate.risk_type == "legal_compliance" for lens in result.lens_results for candidate in lens.candidates)
    assert all(len(search["results"]) in {11, 12, 13, 14} for lens in result.lens_results for search in lens.web_searches)


def test_recorded_candidate_json_extra_data_does_not_abort_discovery():
    candidates = _raw_candidates_from_tool_input(
        candidates_json='[{"title":"first"}] trailing model text that is not JSON'
    )

    assert candidates == [{"title": "first"}]


def test_aggregated_scenarios_convert_to_safe_risk_events_for_analysis():
    request = RiskDiscoveryRequest(
        event_title="Major escalation of war involving Iran",
        event_description="Event description",
        countries=["Iran", "Japan"],
        max_risks=10,
        scope=RiskDiscoveryScope(client_id="fujifilm_dummy", scope_text="global manufacturing"),
    )
    batch = AggregatedRiskScenarioBatch(
        scenarios=[
            AggregatedRiskScenarioDraft(
                scenario_id="EFVR-001/CSWCR-001/HAR-002",
                title="ホルムズ海峡遮断",
                risk_type="supplier_resilience",
                countries=["Iran", "Japan"],
                risk_themes=["shipping"],
                affected_categories=["logistics"],
                scenario_story="物流が遮断される。",
                analysis="生産継続に影響する。",
                severity="critical",
                likelihood="high",
                source_lenses=["event_fact_visible_risk", "causal_story_worst_case_risk"],
                rationale="aggregated rationale",
            )
        ]
    )
    result = MultiLensDiscoveryExperimentResult(
        request=request,
        lens_results=[],
        aggregated_scenarios=_normalize_aggregated_scenarios(
            [scenario.model_dump(mode="json") for scenario in batch.scenarios],
            request,
        ),
    )

    discovery_result = _experiment_result_to_discovery_result(result)

    assert len(discovery_result.selected_events) == 1
    event = discovery_result.selected_events[0]
    assert event.scenario_id == "experiment_major_escalation_of_war_involving_ir_agg_001"
    assert "/" not in event.scenario_id
    assert event.urgency == "high"
    assert "Original aggregated scenario id: EFVR-001/CSWCR-001/HAR-002" in event.description
    assert discovery_result.selected_candidates[0].selected_for_analysis is True
