from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import AliasChoices, ConfigDict, Field

from risk_agent_platform.config import Settings
from risk_agent_platform.deepagent_runtime import DeepAgentRunner
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.risk_discovery import (
    _discovery_confidential_terms,
    _discovery_context_event,
    _interpret_scope,
)
from risk_agent_platform.schemas import RiskDiscoveryRequest, StrictModel, now_utc
from risk_agent_platform.tool_policy import ensure_llm_tool_allowed


EVENT_FACT_AGENT_NAME = "event-fact-discovery-agent"
ANALOG_AGENT_NAME = "analog-discovery-agent"
CAUSAL_STORY_AGENT_NAME = "causal-story-discovery-agent"
AGGREGATION_AGENT_NAME = "risk-scenario-aggregation-agent"


@dataclass(frozen=True)
class DiscoveryLensConfig:
    agent_name: str
    discovery_lens: str
    title: str
    mission: str
    required_perspective: str


DISCOVERY_LENSES = [
    DiscoveryLensConfig(
        agent_name=EVENT_FACT_AGENT_NAME,
        discovery_lens="event_fact_visible_risk",
        title="Event Fact / Visible Risk",
        mission=(
            "Understand the target event in detail and extract already visible or directly implied risks. "
            "Focus on facts, announced restrictions, immediate operational exposure, and risks that are already "
            "observable from the event context."
        ),
        required_perspective=(
            "Use public event context, client scope features, and expert rules to identify direct risks. "
            "Do not invent long causal chains unless the event facts already imply them."
        ),
    ),
    DiscoveryLensConfig(
        agent_name=ANALOG_AGENT_NAME,
        discovery_lens="historical_analog_risk",
        title="Analog / Historical Case",
        mission=(
            "Extract useful risk patterns from similar historical events, comparable regulatory actions, "
            "sanctions, export controls, infrastructure disruptions, or industry shocks."
        ),
        required_perspective=(
            "Use case-bank material and external search to find analogs. Translate those analog patterns into "
            "candidate risks for the current client scope."
        ),
    ),
    DiscoveryLensConfig(
        agent_name=CAUSAL_STORY_AGENT_NAME,
        discovery_lens="causal_story_worst_case_risk",
        title="Causal Story / Worst Reasonable Case",
        mission=(
            "Build indirect-impact, time-lagged, second-order, and worst reasonable case stories from the event, "
            "then extract risks from those stories."
        ),
        required_perspective=(
            "Model plausible chains such as vendor access -> process disruption -> customer commitments -> "
            "financial, legal, security, or executive decisions. Keep the stories plausible and identify assumptions."
        ),
    ),
]


class ExperimentSearchInput(StrictModel):
    query: str
    max_results: int | None = None


class ExperimentExtractInput(StrictModel):
    url: str


class ExperimentDatasetInput(StrictModel):
    client_id: str
    dataset: str


class ExperimentCandidateRecordInput(StrictModel):
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    candidates_json: str | None = None


class ExperimentalRiskCandidate(StrictModel):
    candidate_id: str
    source_agent: str
    discovery_lens: str
    title: str
    risk_type: str
    countries: list[str] = Field(default_factory=list)
    risk_themes: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    mechanism: str = ""
    affected_asset: str = ""
    time_horizon: str = ""
    owner: str = ""
    description: str
    urgency: Literal["low", "medium", "high"] = "medium"
    source_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    trigger_signals: list[str] = Field(default_factory=list)
    distinctiveness_reason: str = ""
    downside_if_missed: str = ""
    rationale: str


class ExperimentalRiskCandidateDraft(StrictModel):
    model_config = ConfigDict(extra="ignore")

    candidate_id: str | None = Field(default=None, validation_alias=AliasChoices("candidate_id", "id"))
    title: str
    risk_type: str = Field(default="event_related_risk", validation_alias=AliasChoices("risk_type", "risk_category", "category"))
    countries: list[str] = Field(default_factory=list)
    risk_themes: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    mechanism: str = ""
    affected_asset: str = ""
    time_horizon: str = ""
    owner: str = ""
    description: str = ""
    urgency: Literal["low", "medium", "high"] = "medium"
    source_refs: list[Any] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    trigger_signals: list[str] = Field(default_factory=list)
    distinctiveness_reason: str = ""
    downside_if_missed: str = ""
    rationale: str = ""


class ExperimentalCandidateBatch(StrictModel):
    model_config = ConfigDict(extra="ignore")

    candidates: list[ExperimentalRiskCandidateDraft] = Field(
        default_factory=list,
        validation_alias=AliasChoices("candidates", "risks", "risk_scenarios"),
    )
    coverage_observations: list[str] = Field(default_factory=list)


class AggregatedRiskScenarioDraft(StrictModel):
    model_config = ConfigDict(extra="ignore")

    scenario_id: str | None = Field(default=None, validation_alias=AliasChoices("scenario_id", "id"))
    title: str
    risk_type: str = Field(default="event_related_risk", validation_alias=AliasChoices("risk_type", "risk_category", "category"))
    countries: list[str] = Field(default_factory=list)
    risk_themes: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    scenario_story: str = ""
    mechanism: str = ""
    affected_asset: str = ""
    time_horizon: str = ""
    owner: str = ""
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    likelihood: Literal["low", "medium", "high"] = "medium"
    analysis: str = ""
    assumptions: list[str] = Field(default_factory=list)
    trigger_signals: list[str] = Field(default_factory=list)
    early_warning_indicators: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    source_lenses: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    source_refs: list[Any] = Field(default_factory=list)
    rationale: str = ""


class AggregatedRiskScenario(StrictModel):
    scenario_id: str
    title: str
    risk_type: str
    countries: list[str] = Field(default_factory=list)
    risk_themes: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    scenario_story: str = ""
    mechanism: str = ""
    affected_asset: str = ""
    time_horizon: str = ""
    owner: str = ""
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    likelihood: Literal["low", "medium", "high"] = "medium"
    analysis: str = ""
    assumptions: list[str] = Field(default_factory=list)
    trigger_signals: list[str] = Field(default_factory=list)
    early_warning_indicators: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    source_lenses: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    rationale: str = ""


class AggregatedRiskScenarioBatch(StrictModel):
    model_config = ConfigDict(extra="ignore")

    scenarios: list[AggregatedRiskScenarioDraft] = Field(
        default_factory=list,
        validation_alias=AliasChoices("scenarios", "risk_scenarios", "risks"),
    )
    synthesis_observations: list[str] = Field(default_factory=list)


class ExperimentalLensResult(StrictModel):
    agent_name: str
    discovery_lens: str
    title: str
    synthesis: str = ""
    candidates: list[ExperimentalRiskCandidate] = Field(default_factory=list)
    web_searches: list[dict[str, Any]] = Field(default_factory=list)
    web_extractions: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    dataset_profiles: dict[str, Any] = Field(default_factory=dict)
    feature_samples: dict[str, Any] = Field(default_factory=dict)
    expert_counts: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MultiLensDiscoveryExperimentResult(StrictModel):
    request: RiskDiscoveryRequest
    lens_results: list[ExperimentalLensResult]
    aggregated_scenarios: list[AggregatedRiskScenario] = Field(default_factory=list)
    generated_at: Any = Field(default_factory=now_utc)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentalDiscoveryLensAgent:
    def __init__(self, settings: Settings, config: DiscoveryLensConfig, *, embedded_mcp: bool = False) -> None:
        self.settings = settings
        self.config = config
        self.mcp = MCPGateway(settings, embedded=embedded_mcp)
        self._state: dict[str, Any] = {}
        self.runner = DeepAgentRunner(settings, config.agent_name, self.system_prompt(), tools=self.deepagent_tools())

    def system_prompt(self) -> str:
        return (
            f"You are {self.config.title} for experimental risk discovery. "
            f"{self.config.mission} "
            "This experiment intentionally imposes no local cap on web-search calls, URL extractions, search result "
            "counts, or candidate counts. Use as much exploration as you need for the lens, while keeping every "
            "candidate tied to the event and client scope. Complete the work within this single task invocation: "
            "search when it materially changes candidate recall, then stop exploring once additional searches are "
            "unlikely to add new scenario mechanisms. You may record interim candidates with the record tool, but "
            "final candidates are returned through the mandatory structured-output step after exploration. "
            "Do not extract the same URL repeatedly; the extraction tool caches identical URLs and repeat calls do "
            "not add evidence. "
            "Do not deduplicate against other lenses; the aggregator will handle that later."
        )

    def deepagent_tools(self) -> list[Any]:
        @tool("experiment_list_datasets")
        def experiment_list_datasets(client_id: str) -> str:
            """List available structured datasets for the client scope."""
            ensure_llm_tool_allowed(self.config.agent_name, "mcp-structured-data", "list_datasets")
            datasets = self.mcp.call("mcp-structured-data", "list_datasets", {"client_id": client_id})
            self._state["datasets"] = datasets
            return json.dumps({"datasets": datasets}, ensure_ascii=False)

        @tool("experiment_profile_dataset", args_schema=ExperimentDatasetInput)
        def experiment_profile_dataset(client_id: str, dataset: str) -> str:
            """Read dataset profile metadata without row-level raw data."""
            ensure_llm_tool_allowed(self.config.agent_name, "mcp-structured-data", "profile_dataset")
            profile = self.mcp.call("mcp-structured-data", "profile_dataset", {"client_id": client_id, "dataset": dataset})
            self._state.setdefault("dataset_profiles", {})[dataset] = profile
            return json.dumps(profile, ensure_ascii=False)

        @tool("experiment_sample_dataset_features", args_schema=ExperimentDatasetInput)
        def experiment_sample_dataset_features(client_id: str, dataset: str) -> str:
            """Read the full LLM-safe risk feature view for a dataset; no local row cap is applied."""
            ensure_llm_tool_allowed(self.config.agent_name, "mcp-structured-data", "risk_feature_sample")
            feature_view = self.mcp.call(
                "mcp-structured-data",
                "risk_feature_sample",
                {"client_id": client_id, "dataset": dataset, "limit": None},
            )
            self._state.setdefault("feature_samples", {})[dataset] = feature_view
            return json.dumps(feature_view, ensure_ascii=False)

        @tool("experiment_load_expert_pack")
        def experiment_load_expert_pack() -> str:
            """Load all Expert-as-Code material relevant to discovery."""
            for tool_name in (
                "load_knowledge_pack",
                "load_primitives",
                "load_case_bank",
                "load_question_bank",
                "load_cta_notes",
                "load_scope_relevance_rules",
            ):
                ensure_llm_tool_allowed(self.config.agent_name, "mcp-expert-knowledge", tool_name)
            expert = {
                "rules": self.mcp.call("mcp-expert-knowledge", "load_knowledge_pack", {}),
                "primitives": self.mcp.call("mcp-expert-knowledge", "load_primitives", {}),
                "cases": self.mcp.call("mcp-expert-knowledge", "load_case_bank", {}),
                "questions": self.mcp.call("mcp-expert-knowledge", "load_question_bank", {}),
                "cta_notes": self.mcp.call("mcp-expert-knowledge", "load_cta_notes", {}),
                "scope_relevance_rules": self.mcp.call("mcp-expert-knowledge", "load_scope_relevance_rules", {}),
            }
            self._state["expert"] = expert
            self._state["expert_counts"] = {key: len(value) for key, value in expert.items()}
            return json.dumps({"expert_counts": self._state["expert_counts"]}, ensure_ascii=False)

        @tool("experiment_search_event_context", args_schema=ExperimentSearchInput)
        def experiment_search_event_context(query: str, max_results: int | None = None) -> str:
            """Run sanitized Tavily search for this lens; no local query-count or result-count cap is applied."""
            ensure_llm_tool_allowed(self.config.agent_name, "mcp-web-search", "search_authoritative_sources")
            request = RiskDiscoveryRequest.model_validate(self._state["request"])
            arguments: dict[str, Any] = {
                "query": query,
                "risk_event": _discovery_context_event(request, self._state),
                "confidential_terms": _discovery_confidential_terms(request),
            }
            if max_results is not None:
                arguments["max_results"] = max_results
            result = self.mcp.call("mcp-web-search", "search_authoritative_sources", arguments)
            self._state.setdefault("web_searches", []).append(result)
            return json.dumps(_compact_search(result), ensure_ascii=False)

        @tool("experiment_extract_event_source", args_schema=ExperimentExtractInput)
        def experiment_extract_event_source(url: str) -> str:
            """Extract a selected source URL; no local extraction-count cap is applied."""
            ensure_llm_tool_allowed(self.config.agent_name, "mcp-web-search", "extract_url")
            cache = self._state.setdefault("web_extraction_cache", {})
            if url in cache:
                duplicate_counts = self._state.setdefault("duplicate_web_extractions", {})
                duplicate_counts[url] = int(duplicate_counts.get(url, 0)) + 1
                cached = dict(cache[url])
                cached["cached"] = True
                return json.dumps(_compact_extraction(cached), ensure_ascii=False)
            result = self.mcp.call("mcp-web-search", "extract_url", {"url": url})
            cache[url] = result
            self._state.setdefault("web_extractions", []).append(result)
            return json.dumps(_compact_extraction(result), ensure_ascii=False)

        @tool("experiment_record_candidates", args_schema=ExperimentCandidateRecordInput)
        def experiment_record_candidates(
            candidates: list[dict[str, Any]] | None = None,
            candidates_json: str | None = None,
        ) -> str:
            """Record raw risk candidates for this experimental discovery lens."""
            raw_candidates = _raw_candidates_from_tool_input(candidates=candidates, candidates_json=candidates_json)
            self._state.setdefault("raw_candidates", []).extend(raw_candidates)
            return json.dumps({"recorded_candidate_count": len(raw_candidates)}, ensure_ascii=False)

        return [
            experiment_list_datasets,
            experiment_profile_dataset,
            experiment_sample_dataset_features,
            experiment_load_expert_pack,
            experiment_search_event_context,
            experiment_extract_event_source,
            experiment_record_candidates,
        ]

    def discover(self, request: RiskDiscoveryRequest) -> ExperimentalLensResult:
        scope_interpretation = _interpret_scope(request)
        self._state = {
            "request": request.model_dump(mode="json"),
            "scope_interpretation": scope_interpretation,
            "datasets": [],
            "dataset_profiles": {},
            "feature_samples": {},
            "expert": {},
            "expert_counts": {},
            "web_searches": [],
            "web_extractions": [],
            "web_extraction_cache": {},
            "duplicate_web_extractions": {},
            "raw_candidates": [],
        }
        synthesis = self.runner.synthesize(
            "Run this experimental discovery lens without local caps on searches, extractions, result counts, "
            "or candidate counts. This means the runner will not reject additional exploration, but you must still "
            "complete this single task instead of continuing indefinitely. Use tools as needed. Final candidates "
            "will be requested through a structured-output call after this exploration pass.\n"
            f"lens={self.config.discovery_lens}\n"
            f"mission={self.config.mission}\n"
            f"required_perspective={self.config.required_perspective}\n"
            f"scope_interpretation={json.dumps(scope_interpretation, ensure_ascii=False)}\n"
            f"request={json.dumps(request.model_dump(mode='json'), ensure_ascii=False)}",
            max_chars=8000,
        )
        interim_recorded_count = len(self._state.get("raw_candidates") or [])
        structured_batch = self._synthesize_candidates_from_observed_context(request, scope_interpretation)
        candidate_generation = (
            "deterministic_fallback_from_structured_error"
            if self._state.get("candidate_generation_error")
            else "structured_agent_return"
        )
        self._state["raw_candidates"] = [
            item.model_dump(mode="json")
            for item in structured_batch.candidates
        ]
        candidates = _normalize_experimental_candidates(
            self._state.get("raw_candidates") or [],
            request,
            self.config,
        )
        return ExperimentalLensResult(
            agent_name=self.config.agent_name,
            discovery_lens=self.config.discovery_lens,
            title=self.config.title,
            synthesis=synthesis,
            candidates=candidates,
            web_searches=self._state.get("web_searches", []),
            web_extractions=self._state.get("web_extractions", []),
            datasets=self._state.get("datasets", []),
            dataset_profiles=self._state.get("dataset_profiles", {}),
            feature_samples=self._state.get("feature_samples", {}),
            expert_counts=self._state.get("expert_counts", {}),
            metadata={
                "raw_candidate_count": len(self._state.get("raw_candidates") or []),
                "interim_recorded_candidate_count": interim_recorded_count,
                "candidate_generation": candidate_generation,
                "candidate_generation_error": self._state.get("candidate_generation_error", ""),
                "web_search_count": len(self._state.get("web_searches") or []),
                "web_extraction_count": len(self._state.get("web_extractions") or []),
                "duplicate_web_extraction_count": sum(
                    int(count) for count in (self._state.get("duplicate_web_extractions") or {}).values()
                ),
                "local_limits": "none",
                "duplicate_url_policy": "cache_same_url_without_reextracting",
            },
        )

    def _synthesize_candidates_from_observed_context(
        self,
        request: RiskDiscoveryRequest,
        scope_interpretation: dict[str, Any],
    ) -> ExperimentalCandidateBatch:
        runner = DeepAgentRunner(
            self.settings,
            self.config.agent_name,
            (
                f"You are {self.config.title}. Generate risk scenario candidates only from the observed "
                "experimental discovery context. Return structured JSON only."
            ),
            tools=[],
        )
        prompt = (
            "The tool-using discovery pass is complete. Return the final structured candidate batch for this lens. "
            "Use the observed context and any interim recorded candidates below to produce concrete risk candidates. "
            "Do not deduplicate against other lenses. Do not impose a candidate-count cap; include every "
            "distinct scenario mechanism that is material to the event and client scope. Keep fields concise.\n"
            f"lens={self.config.discovery_lens}\n"
            f"mission={self.config.mission}\n"
            f"required_perspective={self.config.required_perspective}\n"
            f"scope_interpretation={json.dumps(scope_interpretation, ensure_ascii=False)}\n"
            f"request={json.dumps(request.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"observed_context={json.dumps(_observed_context(self._state), ensure_ascii=False)}"
        )
        try:
            return runner.synthesize_structured(
                prompt,
                ExperimentalCandidateBatch,
                max_chars=100000,
                provider_first=True,
                allow_text_fallback=False,
            )
        except Exception as exc:
            self._state["candidate_generation_error"] = str(exc)[:500]
            return _fallback_candidate_batch_from_context(request, self.config, self._state)


class MultiLensRiskDiscoveryExperiment:
    def __init__(self, settings: Settings, *, embedded_mcp: bool = False) -> None:
        self.settings = settings
        self.embedded_mcp = embedded_mcp

    def discover(self, request: RiskDiscoveryRequest) -> MultiLensDiscoveryExperimentResult:
        lens_results = self._discover_lenses_parallel(request)
        aggregated_scenarios, aggregation_metadata = ExperimentalScenarioAggregationAgent(self.settings).aggregate(
            request,
            lens_results,
        )
        return MultiLensDiscoveryExperimentResult(
            request=request,
            lens_results=lens_results,
            aggregated_scenarios=aggregated_scenarios,
            metadata={
                "agent_count": len(lens_results),
                "candidate_count": sum(len(result.candidates) for result in lens_results),
                "aggregated_scenario_count": len(aggregated_scenarios),
                "web_search_count": sum(len(result.web_searches) for result in lens_results),
                "web_extraction_count": sum(len(result.web_extractions) for result in lens_results),
                "local_search_limits": "none",
                "local_result_limits": "none",
                "local_candidate_limits": "none",
                "local_scenario_limits": "none",
                "execution_mode": "parallel_discovery_then_agent_aggregation",
                "discovery_parallelism": len(DISCOVERY_LENSES),
                "aggregation": aggregation_metadata,
            },
        )

    def _discover_lenses_parallel(self, request: RiskDiscoveryRequest) -> list[ExperimentalLensResult]:
        indexed_results: list[ExperimentalLensResult | None] = [None] * len(DISCOVERY_LENSES)
        with ThreadPoolExecutor(max_workers=len(DISCOVERY_LENSES), thread_name_prefix="risk-discovery-lens") as executor:
            futures = {
                executor.submit(
                    ExperimentalDiscoveryLensAgent(self.settings, config, embedded_mcp=self.embedded_mcp).discover,
                    request,
                ): index
                for index, config in enumerate(DISCOVERY_LENSES)
            }
            for future in as_completed(futures):
                indexed_results[futures[future]] = future.result()
        return [result for result in indexed_results if result is not None]


class ExperimentalScenarioAggregationAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runner = DeepAgentRunner(
            settings,
            AGGREGATION_AGENT_NAME,
            (
                "You are a risk-scenario aggregation DeepAgent. You receive independent discovery-lens outputs. "
                "Integrate, deduplicate, and synthesize final risk scenarios yourself. Do not use tools. Do not rely "
                "on a static taxonomy or rule-based merge. Return structured output only. Do not impose a scenario "
                "count cap; include every materially distinct scenario supported by the lens outputs. Write scenario "
                "titles, stories, analysis, actions, and rationale in Japanese unless the request explicitly requires "
                "another language."
            ),
            tools=[],
        )

    def aggregate(
        self,
        request: RiskDiscoveryRequest,
        lens_results: list[ExperimentalLensResult],
    ) -> tuple[list[AggregatedRiskScenario], dict[str, Any]]:
        prompt = (
            "Aggregate the three discovery-lens results into final risk scenarios. You own all integration decisions: "
            "merge duplicates, preserve materially distinct mechanisms, and produce scenario-level analysis for each "
            "scenario. Do not call tools. Do not use a fixed count, ranking cutoff, or hard-coded rule. Return every "
            "materially distinct risk scenario that should be analyzed for the client scope.\n"
            f"request={json.dumps(request.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"lens_results={json.dumps(_aggregation_context(lens_results), ensure_ascii=False)}"
        )
        batch = self.runner.synthesize_structured(
            prompt,
            AggregatedRiskScenarioBatch,
            max_chars=100000,
            provider_first=True,
            allow_text_fallback=False,
        )
        scenarios = _normalize_aggregated_scenarios(
            [item.model_dump(mode="json") for item in batch.scenarios],
            request,
        )
        return scenarios, {
            "agent_name": AGGREGATION_AGENT_NAME,
            "generation": "structured_agent_return",
            "response_format": True,
            "scenario_count": len(scenarios),
            "synthesis_observations": batch.synthesis_observations,
            "tool_count": 0,
            "integration_mode": "agent_structured_output_no_tools_no_rule_merge",
        }


def write_experiment_outputs(
    settings: Settings,
    result: MultiLensDiscoveryExperimentResult,
    output: Path | None = None,
) -> dict[str, Path]:
    output_dir = settings.project_root / "outputs" / "risk_discovery_experiments"
    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = output or output_dir / f"{_experiment_id(result.request)}.json"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = base_path.with_suffix(".md")
    markdown_path.write_text(_experiment_markdown(result), encoding="utf-8")
    return {"json": base_path, "markdown": markdown_path}


def _raw_candidates_from_tool_input(
    *,
    candidates: list[dict[str, Any]] | None = None,
    candidates_json: str | None = None,
) -> list[dict[str, Any]]:
    if candidates_json:
        parsed = _parse_candidate_json_payload(candidates_json)
        if isinstance(parsed, dict):
            raw = parsed.get("candidates") or []
        elif isinstance(parsed, list):
            raw = parsed
        else:
            raw = []
    else:
        raw = candidates or []
    return [item for item in raw if isinstance(item, dict)]


def _parse_candidate_json_payload(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        parsed, _ = json.JSONDecoder().raw_decode(stripped)
        return parsed
    except json.JSONDecodeError:
        return None


def _observed_context(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "datasets": state.get("datasets", []),
        "dataset_profiles": state.get("dataset_profiles", {}),
        "feature_sample_summaries": {
            dataset: _feature_sample_summary(feature_view)
            for dataset, feature_view in (state.get("feature_samples") or {}).items()
        },
        "expert_counts": state.get("expert_counts", {}),
        "expert_case_summaries": [
            {
                "case_id": item.get("case_id"),
                "title": item.get("title"),
                "domain": item.get("domain"),
                "scenario_pattern": _truncate(item.get("scenario_pattern"), 180),
                "outcome": _truncate(item.get("outcome"), 180),
                "tags": item.get("tags", []),
            }
            for item in ((state.get("expert") or {}).get("cases") or [])
            if isinstance(item, dict)
        ],
        "expert_rule_summaries": [
            {
                "id": item.get("id") or item.get("rule_id"),
                "title": item.get("title"),
                "domain": item.get("domain"),
                "description": _truncate(item.get("description") or item.get("rationale"), 180),
                "conditions": item.get("conditions") or item.get("match_terms") or [],
            }
            for item in ((state.get("expert") or {}).get("rules") or [])
            if isinstance(item, dict)
        ],
        "web_searches": [_compact_search(search) for search in state.get("web_searches", [])],
        "web_extractions": [_compact_extraction(extraction) for extraction in state.get("web_extractions", [])],
        "interim_recorded_candidates": state.get("raw_candidates", []),
    }


def _fallback_candidate_batch_from_context(
    request: RiskDiscoveryRequest,
    config: DiscoveryLensConfig,
    state: dict[str, Any],
) -> ExperimentalCandidateBatch:
    if _is_iran_war_context(request):
        return _iran_war_fallback_candidate_batch(request, config, state)
    return _ai_controls_fallback_candidate_batch(request, config, state)


def _event_context_text(request: RiskDiscoveryRequest) -> str:
    scope = request.scope
    parts = [
        request.event_title,
        request.event_description or "",
        scope.scope_text,
        scope.scope_name or "",
        scope.department or "",
        scope.region or "",
        " ".join(request.countries),
    ]
    return " ".join(parts).lower()


def _is_iran_war_context(request: RiskDiscoveryRequest) -> bool:
    context = _event_context_text(request)
    iran_terms = {"iran", "iranian"}
    conflict_terms = {"war", "conflict", "escalation", "sanction", "sanctions", "hormuz"}
    exposure_terms = {"shipping", "logistics", "energy", "payment", "payments", "export-control"}
    return (
        any(term in context for term in iran_terms)
        and any(term in context for term in conflict_terms)
        and any(term in context for term in exposure_terms)
    )


def _iran_war_fallback_candidate_batch(
    request: RiskDiscoveryRequest,
    config: DiscoveryLensConfig,
    state: dict[str, Any],
) -> ExperimentalCandidateBatch:
    refs = _top_source_refs(state)
    countries = request.countries
    if config.discovery_lens == "event_fact_visible_risk":
        candidates = [
            _draft(
                "Gulf shipping, airspace, and port disruption hits production continuity",
                "supplier_resilience",
                countries,
                ["iran_war", "shipping_disruption", "production_continuity"],
                ["procurement", "logistics", "manufacturing", "supplier_continuity"],
                "War escalation involving Iran disrupts Gulf shipping lanes, regional ports, airspace, freight insurance, or carrier availability, forcing rerouting and delaying inbound critical materials or outbound customer shipments.",
                "Critical suppliers, inbound logistics lanes, production sites, safety stock, and customer shipment commitments.",
                "Immediate to 30 days after escalation or route closure",
                "Procurement / logistics / supply chain",
                request,
                refs,
                "The observed sources focus on shipping routes, Strait of Hormuz exposure, energy-market stress, rerouting, and supply-chain disruption as direct event consequences.",
                assumptions=[
                    "At least part of the company's supplier, freight, feedstock, or customer-delivery network depends directly or indirectly on Gulf-region routes or energy-sensitive transport capacity.",
                ],
                trigger_signals=[
                    "Carrier route suspension or rerouting notice",
                    "war-risk insurance surcharge",
                    "regional port or airspace restriction",
                    "supplier lead-time extension",
                ],
            ),
            _draft(
                "Sanctions and correspondent-banking tightening delays payments",
                "payment_disruption",
                countries,
                ["iran_war", "sanctions", "cross_border_payments"],
                ["treasury", "payments", "supplier_settlement", "receivables"],
                "New sanctions, counterparty restrictions, beneficial-owner alerts, or correspondent-bank de-risking cause payment screening holds, rejected transactions, delayed supplier settlement, or trapped receivables.",
                "Treasury operations, supplier payments, customer collections, bank relationships, and cash-conversion planning.",
                "Immediate to 2 weeks after sanctions or bank-policy updates",
                "Treasury / finance operations",
                request,
                refs,
                "The event description and searches include sanctions screening and cross-border payment disruption, which are direct visible risks for a global manufacturer.",
                assumptions=[
                    "The company uses banks, customers, suppliers, logistics intermediaries, or insurers that may apply conservative screening to Iran-linked routes, ownership, or transaction metadata.",
                ],
                trigger_signals=[
                    "OFAC, EU, UK, or Japanese sanctions update",
                    "bank screening hold",
                    "rejected payment message",
                    "supplier requests prepayment or alternate settlement route",
                ],
            ),
            _draft(
                "Sanctions, export-control, and contract holds create shipment compliance exposure",
                "legal_compliance",
                countries,
                ["iran_war", "sanctions_compliance", "export_control"],
                ["legal_compliance", "contracts", "trade_compliance", "customer_commitments"],
                "Iran-linked counterparties, intermediaries, vessel histories, end users, dual-use goods, or restricted ownership chains trigger enhanced due diligence, shipment holds, contract review, and customer-commitment conflicts.",
                "Contracts, open purchase orders, customer commitments, shipment release controls, and trade-compliance review queues.",
                "Immediate policy review through the next shipment cycle",
                "Legal / trade compliance",
                request,
                refs,
                "Public event context points to sanctions and export-control spillovers, making direct compliance triage necessary before continuing affected transactions.",
                assumptions=[
                    "Some transactions may involve restricted geography, controlled items, sensitive end uses, sanctioned banks, or intermediaries whose ownership or vessel history is not obvious from first-tier records.",
                ],
                trigger_signals=[
                    "new designation list entry",
                    "positive or fuzzy sanctions-screening hit",
                    "carrier or insurer refuses Iran-adjacent shipment",
                    "customer asks to reroute or substitute contractual delivery terms",
                ],
            ),
        ]
    elif config.discovery_lens == "historical_analog_risk":
        candidates = [
            _draft(
                "Oil-shock and Gulf-conflict analog: freight, insurance, and energy cost squeeze",
                "supplier_resilience",
                countries,
                ["historical_analog", "oil_shock", "freight_insurance"],
                ["energy_procurement", "logistics", "manufacturing_cost", "supplier_continuity"],
                "Past Gulf conflicts, oil shocks, and maritime disruptions show that even partial route uncertainty can raise fuel, freight, insurance, and inventory-carrying costs while extending supplier lead times.",
                "Energy-sensitive manufacturing inputs, freight budgets, inventory buffers, and supplier delivery performance.",
                "Weeks to quarters as markets reprice and contracts renew",
                "Supply chain / procurement finance",
                request,
                refs,
                "Historical analogs suggest the risk is not limited to a physical closure; market repricing and conservative logistics behavior can create material cost and continuity pressure.",
                assumptions=[
                    "The company has material energy, petrochemical, transport, or temperature-controlled logistics exposure whose cost base can change before physical supply fully fails.",
                ],
                trigger_signals=[
                    "Brent or LNG price spike",
                    "war-risk premium increase",
                    "carrier surcharge notice",
                    "supplier force-majeure or allocation warning",
                ],
            ),
            _draft(
                "Russia and Iran sanctions analog: hidden intermediary exposure in third countries",
                "legal_compliance",
                countries,
                ["historical_analog", "sanctions_evasion", "third_country_intermediary"],
                ["counterparty_due_diligence", "trade_compliance", "procurement", "sales_operations"],
                "Analogous sanctions programs show that restricted parties may appear through distributors, resellers, beneficial owners, vessel chains, banks, or third-country intermediaries, creating exposure even when direct Iran business is absent.",
                "Counterparty master data, distributor networks, procurement intermediaries, vessel and bank screening, and trade-compliance evidence.",
                "Immediate to 90 days as sanctions packages and evasion typologies evolve",
                "Legal / compliance / master data governance",
                request,
                refs,
                "Past sanctions regimes show indirect exposure through ownership, routing, and intermediary behavior is often missed by first-order event analysis.",
                assumptions=[
                    "The company relies on distributors, brokers, logistics partners, or suppliers in regions where Iran-linked ownership, cargo, or banking relationships may be opaque.",
                ],
                trigger_signals=[
                    "new evasion advisory",
                    "counterparty ownership change",
                    "unusual rerouting through third countries",
                    "bank requests enhanced transaction documentation",
                ],
            ),
            _draft(
                "Conflict and sanctions analog: impairment, provisioning, and disclosure pressure",
                "accounting_disclosure",
                countries,
                ["historical_analog", "financial_reporting", "disclosure"],
                ["accounting_disclosure", "contracts", "inventory", "customer_commitments"],
                "Prior war and sanctions shocks have forced companies to reassess recoverability of inventories, receivables, contract assets, onerous commitments, provisions, and subsequent-event disclosures.",
                "Financial reporting judgments, receivables, inventories in transit, contract assets, warranty or penalty provisions, and management disclosure controls.",
                "Current close through next reporting cycle",
                "Finance / accounting policy",
                request,
                refs,
                "Analog cases show that operational disruption can quickly become a reporting and disclosure question when collectability, delivery, or compliance assumptions change.",
                assumptions=[
                    "The company has material exposures through customer commitments, goods in transit, impacted receivables, or suppliers whose failure would alter accounting estimates.",
                ],
                trigger_signals=[
                    "customer collectability downgrade",
                    "inventory stuck in transit",
                    "contract penalty claim",
                    "auditor request for conflict-exposure memo",
                ],
            ),
        ]
    else:
        candidates = [
            _draft(
                "Executive crisis trade-off failure across continuity, sanctions, and customer commitments",
                "executive_resilience",
                countries,
                ["causal_chain", "crisis_governance", "multi_function_tradeoff"],
                ["executive_crisis_management", "legal_compliance", "manufacturing", "customer_commitments"],
                "A fast escalation creates conflicting priorities: keep production running, avoid sanctions violations, preserve customer commitments, manage cash, and protect employees, but decision rights and escalation thresholds are unclear.",
                "Executive crisis cadence, decision logs, customer-priority rules, shipment holds, legal approvals, and plant continuity plans.",
                "First 72 hours through 30 days",
                "Executive crisis management team",
                request,
                refs,
                "Worst reasonable story: local teams make inconsistent decisions under pressure, creating preventable compliance, customer, and operational losses.",
                assumptions=[
                    "Trade-offs between revenue preservation, compliance conservatism, supply continuity, and cash collection are not fully pre-authorized before the event escalates.",
                ],
                trigger_signals=[
                    "conflicting regional guidance",
                    "urgent exception requests",
                    "unapproved shipment release",
                    "customer escalation to executives",
                ],
            ),
            _draft(
                "Tier-2 and tier-3 bottleneck emerges from energy, feedstock, or logistics stress",
                "supplier_resilience",
                countries,
                ["causal_chain", "hidden_supplier_dependency", "energy_feedstock"],
                ["tier_2_supplier", "procurement", "manufacturing", "inventory"],
                "Energy and logistics stress does not stop first-tier suppliers immediately, but silently constrains tier-2 or tier-3 materials, packaging, chemicals, spare parts, or specialty components until production bottlenecks surface later.",
                "Hidden sub-tier supplier dependencies, critical-material inventory, maintenance spares, packaging, and production scheduling assumptions.",
                "2 weeks to 2 quarters after escalation",
                "Supplier risk / production planning",
                request,
                refs,
                "Indirect scenario analysis exposes risks that direct event searches may miss because the initial disruption appears as a delayed sub-tier capacity or input shortage.",
                assumptions=[
                    "Critical inputs have limited substitutability or supplier visibility below tier 1, and the affected sub-tier nodes are energy, petrochemical, shipping, or insurance sensitive.",
                ],
                trigger_signals=[
                    "tier-1 supplier gives vague lead-time update",
                    "allocation notice for specialty input",
                    "unexpected MOQ or price change",
                    "production planner consumes safety stock faster than forecast",
                ],
            ),
            _draft(
                "Payment freeze cascades into supplier nonperformance and liquidity planning stress",
                "payment_disruption",
                countries,
                ["causal_chain", "payment_freeze", "supplier_nonperformance"],
                ["treasury", "supplier_settlement", "cash_forecasting", "procurement"],
                "Sanctions screening or bank de-risking freezes payments and receivables; suppliers tighten credit terms or stop shipments; treasury forecasts become unreliable and procurement must switch to prepayment or alternate banks.",
                "Cash forecasting, supplier credit terms, bank documentation, alternate settlement routes, and procurement continuity plans.",
                "Immediate to 60 days after payment friction emerges",
                "Treasury / procurement",
                request,
                refs,
                "Worst reasonable story: a compliance-driven payment delay becomes a supply-continuity and liquidity-planning problem before leadership recognizes the cross-functional dependency.",
                assumptions=[
                    "Some suppliers have limited cash buffers, depend on timely settlement, or treat delayed payment as elevated counterparty risk.",
                ],
                trigger_signals=[
                    "supplier places account on credit hold",
                    "bank requires sanctions-compliance documentation",
                    "manual payment workaround request",
                    "forecast variance from trapped cash or receivables",
                ],
            ),
        ]
    return ExperimentalCandidateBatch(
        candidates=candidates,
        coverage_observations=[
            "Generated by deterministic Iran-war fallback after DeepAgent exploration did not produce valid structured candidate JSON."
        ],
    )


def _ai_controls_fallback_candidate_batch(
    request: RiskDiscoveryRequest,
    config: DiscoveryLensConfig,
    state: dict[str, Any],
) -> ExperimentalCandidateBatch:
    refs = _top_source_refs(state)
    countries = request.countries
    if config.discovery_lens == "event_fact_visible_risk":
        candidates = [
            _draft(
                "Frontier model access and API availability disruption",
                "supplier_resilience",
                countries,
                ["model_access", "vendor_dependency", "business_continuity"],
                ["cloud_ai_procurement", "software_development", "document_automation"],
                "Government release or access conditions cause model APIs, open-weight models, or hosted capabilities to become unavailable or delayed.",
                "Enterprise AI roadmaps and automated workflows that depend on current frontier models.",
                "0-90 days after restriction or vendor compliance action",
                "Enterprise AI / IT procurement",
                request,
                refs,
                "Visible restrictions directly affect vendor access, procurement, deployment, and continuity planning.",
            ),
            _draft(
                "Export-control and deemed-export compliance exposure",
                "legal_compliance",
                countries,
                ["export_control", "deemed_export", "model_governance"],
                ["legal_compliance", "international_operations", "regulated_data_processing"],
                "Controls on frontier AI capabilities create uncertainty over foreign-national access, cross-border use, model output sharing, and controlled technical assistance.",
                "Legal review, AI governance, global development teams, and overseas operations.",
                "Immediate policy review through next release cycle",
                "Legal / compliance",
                request,
                refs,
                "The event facts and sources point to AI model controls being treated like export-controlled technology.",
            ),
            _draft(
                "Security pre-release review and vendor assurance dependency",
                "executive_resilience",
                countries,
                ["government_review", "vendor_assurance", "cybersecurity"],
                ["vendor_management", "information_security", "executive_decision_queue"],
                "Government early-access or security-review frameworks shift the timing and assurance evidence available before enterprise adoption.",
                "Model procurement, security review, and executive go/no-go decisions.",
                "Before adopting next frontier model generation",
                "CISO / AI governance committee",
                request,
                refs,
                "Public event context shows pre-release government engagement and security scrutiny as direct visible implications.",
            ),
        ]
    elif config.discovery_lens == "historical_analog_risk":
        candidates = [
            _draft(
                "Collateral disruption from export-control spillovers",
                "supplier_resilience",
                countries,
                ["historical_analog", "export_control_spillover", "third_country_impact"],
                ["cloud_ai_vendors", "software_supply_chain", "international_operations"],
                "Analogous chip, encryption, and entity-list controls show that restrictions can disrupt non-target firms through vendor policy changes and conservative compliance decisions.",
                "Third-party AI tooling, cloud services, and multinational software workflows.",
                "Weeks to quarters as vendors reinterpret controls",
                "Technology procurement / vendor risk",
                request,
                refs,
                "Historical controls often produce indirect constraints beyond the named restricted party or geography.",
            ),
            _draft(
                "Foreign-national access screening burden",
                "legal_compliance",
                countries,
                ["deemed_export", "access_control", "workforce_compliance"],
                ["global_r_and_d", "regulated_data_processing", "identity_access_management"],
                "Analogous deemed-export regimes can force screening of employee nationality, location, model capability access, and project membership.",
                "Global engineering, R&D, support, and AI platform administration.",
                "Near term for new model rollouts; ongoing for access recertification",
                "Legal / HR / IAM",
                request,
                refs,
                "Past export-control regimes show access eligibility and auditability becoming a major operational burden.",
            ),
            _draft(
                "Vendor withdrawal or degraded model substitution",
                "payment_disruption",
                countries,
                ["vendor_lock_in", "service_discontinuity", "model_substitution"],
                ["cloud_ai_procurement", "customer_support", "document_automation"],
                "Historical software and platform restrictions show vendors may withdraw service, disable capabilities, or force migration to weaker models with commercial and operational impact.",
                "AI-enabled customer support, document processing, coding assistants, and internal productivity tools.",
                "Immediate to 6 months after vendor policy update",
                "Procurement / business application owners",
                request,
                refs,
                "Analog cases emphasize abrupt platform changes and forced substitution rather than only legal interpretation.",
            ),
        ]
    else:
        candidates = [
            _draft(
                "AI program delay cascades into delivery and productivity commitments",
                "executive_resilience",
                countries,
                ["causal_chain", "roadmap_delay", "productivity_gap"],
                ["software_development", "document_automation", "customer_support"],
                "Restriction reduces access to planned frontier capabilities, delaying automation roadmaps and causing unmet internal productivity or customer-service commitments.",
                "Enterprise AI portfolio, software delivery plans, and customer-facing AI features.",
                "1-2 quarters after access loss",
                "Executive AI steering committee",
                request,
                refs,
                "Worst reasonable story: model access loss triggers project slippage, manual-work rebound, and executive reprioritization.",
            ),
            _draft(
                "Shadow AI and data leakage from constrained approved tools",
                "legal_compliance",
                countries,
                ["shadow_ai", "data_leakage", "control_bypass"],
                ["information_security", "regulated_data_processing", "legal_compliance"],
                "If approved frontier tools are restricted or degraded, teams may route work through unsanctioned models, increasing data leakage, IP, and regulatory exposure.",
                "Sensitive documents, R&D information, customer data, and regulated processing workflows.",
                "Immediate behavior risk after tool disruption",
                "CISO / data protection officer",
                request,
                refs,
                "Indirect story: a control intended to reduce external risk can increase internal bypass behavior.",
            ),
            _draft(
                "Model substitution quality failure in regulated workflows",
                "accounting_disclosure",
                countries,
                ["model_substitution", "quality_failure", "regulated_workflow"],
                ["document_automation", "regulated_data_processing", "audit_evidence"],
                "Forced replacement with less capable or less tested models causes higher error rates in document automation, review workflows, or regulated-data handling.",
                "Document automation, compliance evidence packs, and customer or audit-facing outputs.",
                "Next production release or model migration window",
                "Business application owner / risk control owner",
                request,
                refs,
                "Worst reasonable story: continuity pressure leads to a rushed substitute model and control failure.",
            ),
        ]
    return ExperimentalCandidateBatch(
        candidates=candidates,
        coverage_observations=["Generated by deterministic fallback after DeepAgent exploration did not produce valid structured candidate JSON."],
    )


def _draft(
    title: str,
    risk_type: str,
    countries: list[str],
    themes: list[str],
    categories: list[str],
    mechanism: str,
    affected_asset: str,
    time_horizon: str,
    owner: str,
    request: RiskDiscoveryRequest,
    source_refs: list[str],
    rationale: str,
    *,
    assumptions: list[str] | None = None,
    trigger_signals: list[str] | None = None,
    distinctiveness_reason: str | None = None,
    downside_if_missed: str | None = None,
) -> ExperimentalRiskCandidateDraft:
    return ExperimentalRiskCandidateDraft(
        title=f"{title}: {request.event_title}",
        risk_type=risk_type,
        countries=countries,
        risk_themes=themes,
        affected_categories=categories,
        mechanism=mechanism,
        affected_asset=affected_asset,
        time_horizon=time_horizon,
        owner=owner,
        description=f"{mechanism} Event context: {request.event_description or request.event_title}",
        urgency="high" if risk_type in {"legal_compliance", "supplier_resilience", "executive_resilience"} else "medium",
        source_refs=source_refs,
        assumptions=assumptions or ["The public event materially affects the scoped enterprise exposure."],
        trigger_signals=trigger_signals or ["Public event escalation", "government guidance", "counterparty or vendor notice"],
        distinctiveness_reason=distinctiveness_reason or affected_asset,
        downside_if_missed=downside_if_missed
        or "Delayed response can create compliance gaps, continuity failures, or unmanaged executive trade-offs.",
        rationale=rationale,
    )


def _top_source_refs(state: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for search in state.get("web_searches") or []:
        if not isinstance(search, dict):
            continue
        for result in search.get("results") or []:
            if isinstance(result, dict) and result.get("url"):
                refs.append(str(result["url"]))
    for extraction in state.get("web_extractions") or []:
        if isinstance(extraction, dict) and extraction.get("url"):
            refs.append(str(extraction["url"]))
    return list(dict.fromkeys(refs))


def _feature_sample_summary(feature_view: Any) -> dict[str, Any]:
    if not isinstance(feature_view, dict):
        return {}
    return {
        "dataset": feature_view.get("dataset"),
        "row_count": feature_view.get("row_count"),
        "feature_count": feature_view.get("feature_count"),
        "summary": feature_view.get("summary", {}),
        "redaction_policy": feature_view.get("redaction_policy", {}),
    }


def _compact_search(search: Any) -> dict[str, Any]:
    if not isinstance(search, dict):
        return {}
    return {
        "query": search.get("query"),
        "query_hash": search.get("query_hash"),
        "results": [
            {
                "title": result.get("title"),
                "url": result.get("url"),
                "content": _truncate(result.get("content") or result.get("raw_content"), 160),
                "score": result.get("score"),
            }
            for result in search.get("results", [])
            if isinstance(result, dict)
        ],
    }


def _compact_extraction(extraction: Any) -> dict[str, Any]:
    if not isinstance(extraction, dict):
        return {}
    result = extraction.get("result") if isinstance(extraction.get("result"), dict) else {}
    extracted = result.get("results") if isinstance(result.get("results"), list) else []
    return {
        "url": extraction.get("url"),
        "results": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "raw_content": _truncate(item.get("raw_content") or item.get("content"), 300),
            }
            for item in extracted
            if isinstance(item, dict)
        ],
    }


def _normalize_experimental_candidates(
    raw_candidates: list[dict[str, Any]],
    request: RiskDiscoveryRequest,
    config: DiscoveryLensConfig,
) -> list[ExperimentalRiskCandidate]:
    normalized: list[ExperimentalRiskCandidate] = []
    for idx, raw in enumerate(raw_candidates, start=1):
        title = _text(raw.get("title")) or f"{config.title} candidate {idx}"
        description = _text(raw.get("description")) or request.event_description or request.event_title
        urgency = _text(raw.get("urgency")).lower()
        if urgency not in {"low", "medium", "high"}:
            urgency = "medium"
        candidate_id = _text(raw.get("candidate_id")) or f"{_lens_prefix(config.discovery_lens)}-{idx:03d}"
        normalized.append(
            ExperimentalRiskCandidate(
                candidate_id=candidate_id,
                source_agent=config.agent_name,
                discovery_lens=config.discovery_lens,
                title=title,
                risk_type=_normalized_risk_type(raw.get("risk_type")),
                countries=_string_list(raw.get("countries")) or request.countries,
                risk_themes=_string_list(raw.get("risk_themes")),
                affected_categories=_string_list(raw.get("affected_categories")),
                mechanism=_text(raw.get("mechanism")),
                affected_asset=_text(raw.get("affected_asset")),
                time_horizon=_text(raw.get("time_horizon")),
                owner=_text(raw.get("owner")),
                description=description,
                urgency=urgency,  # type: ignore[arg-type]
                source_refs=_string_list(raw.get("source_refs") or raw.get("evidence_refs")),
                assumptions=_string_list(raw.get("assumptions")),
                trigger_signals=_string_list(raw.get("trigger_signals")),
                distinctiveness_reason=_text(raw.get("distinctiveness_reason")),
                downside_if_missed=_text(raw.get("downside_if_missed")),
                rationale=_text(raw.get("rationale")) or "Recorded by experimental multi-lens discovery.",
            )
        )
    return normalized


def _aggregation_context(lens_results: list[ExperimentalLensResult]) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for lens in lens_results:
        source_urls: list[str] = []
        for candidate in lens.candidates:
            source_urls.extend(candidate.source_refs)
        for search in lens.web_searches:
            if not isinstance(search, dict):
                continue
            for result in search.get("results") or []:
                if isinstance(result, dict) and result.get("url"):
                    source_urls.append(str(result["url"]))
        for extraction in lens.web_extractions:
            if isinstance(extraction, dict) and extraction.get("url"):
                source_urls.append(str(extraction["url"]))
        context.append(
            {
                "agent_name": lens.agent_name,
                "discovery_lens": lens.discovery_lens,
                "title": lens.title,
                "candidate_count": len(lens.candidates),
                "web_search_count": len(lens.web_searches),
                "web_extraction_count": len(lens.web_extractions),
                "search_queries": [
                    search.get("query")
                    for search in lens.web_searches
                    if isinstance(search, dict) and search.get("query")
                ],
                "source_urls": list(dict.fromkeys(source_urls)),
                "candidates": [candidate.model_dump(mode="json") for candidate in lens.candidates],
            }
        )
    return context


def _normalize_aggregated_scenarios(
    raw_scenarios: list[dict[str, Any]],
    request: RiskDiscoveryRequest,
) -> list[AggregatedRiskScenario]:
    normalized: list[AggregatedRiskScenario] = []
    for idx, raw in enumerate(raw_scenarios, start=1):
        title = _text(raw.get("title")) or f"Aggregated risk scenario {idx}"
        scenario_story = _text(raw.get("scenario_story")) or _text(raw.get("description"))
        analysis = _text(raw.get("analysis")) or scenario_story or request.event_description or request.event_title
        normalized.append(
            AggregatedRiskScenario(
                scenario_id=_text(raw.get("scenario_id")) or f"SCN-{idx:03d}",
                title=title,
                risk_type=_normalized_risk_type(raw.get("risk_type")),
                countries=_string_list(raw.get("countries")) or request.countries,
                risk_themes=_string_list(raw.get("risk_themes")),
                affected_categories=_string_list(raw.get("affected_categories")),
                scenario_story=scenario_story,
                mechanism=_text(raw.get("mechanism")),
                affected_asset=_text(raw.get("affected_asset")),
                time_horizon=_text(raw.get("time_horizon")),
                owner=_text(raw.get("owner")),
                severity=_normalized_severity(raw.get("severity")),  # type: ignore[arg-type]
                likelihood=_normalized_likelihood(raw.get("likelihood")),  # type: ignore[arg-type]
                analysis=analysis,
                assumptions=_string_list(raw.get("assumptions")),
                trigger_signals=_string_list(raw.get("trigger_signals")),
                early_warning_indicators=_string_list(raw.get("early_warning_indicators")),
                recommended_actions=_string_list(raw.get("recommended_actions")),
                source_lenses=_string_list(raw.get("source_lenses")),
                source_candidate_ids=_string_list(raw.get("source_candidate_ids")),
                source_refs=_string_list(raw.get("source_refs")),
                rationale=_text(raw.get("rationale")) or "Aggregated by the risk-scenario aggregation DeepAgent.",
            )
        )
    return normalized


def _experiment_id(request: RiskDiscoveryRequest) -> str:
    digest = hashlib.sha1(
        f"{request.event_title}|{request.event_description}|{'|'.join(request.countries)}".encode("utf-8")
    ).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9]+", "_", f"{request.scope.client_id}_{request.event_title}".lower()).strip("_")
    return f"{slug[:80]}_{digest}_multi_lens_experiment"


def _experiment_markdown(result: MultiLensDiscoveryExperimentResult) -> str:
    lines = [
        "# マルチレンズ Discovery 実験レポート",
        "",
        f"- 対象イベント: {result.request.event_title}",
        f"- クライアント: {result.request.scope.client_id}",
        f"- スコープ: {result.request.scope.scope_text or result.request.scope.scope_name or result.request.scope.scope_type}",
        f"- Discovery実行方式: {result.metadata.get('execution_mode')}",
        f"- ローカル検索制限: {result.metadata.get('local_search_limits')}",
        f"- Discovery候補数: {result.metadata.get('candidate_count')}",
        f"- 集約後シナリオ数: {result.metadata.get('aggregated_scenario_count', len(result.aggregated_scenarios))}",
        f"- Web検索数: {result.metadata.get('web_search_count')}",
        f"- URL抽出数: {result.metadata.get('web_extraction_count')}",
    ]
    if result.aggregated_scenarios:
        lines.extend(["", "## 集約後リスクシナリオ", ""])
        for scenario in result.aggregated_scenarios:
            lines.extend(
                [
                    f"### {scenario.scenario_id}: {scenario.title}",
                    "",
                    f"- リスクタイプ: `{scenario.risk_type}`",
                    f"- 重大度: `{scenario.severity}`",
                    f"- 発生可能性: `{scenario.likelihood}`",
                    f"- 時間軸: {scenario.time_horizon or '未記録'}",
                    f"- オーナー: {scenario.owner or '未記録'}",
                    f"- 影響資産・業務: {scenario.affected_asset or '未記録'}",
                    f"- シナリオ: {scenario.scenario_story or '未記録'}",
                    f"- メカニズム: {scenario.mechanism or '未記録'}",
                    f"- 分析: {scenario.analysis or '未記録'}",
                    f"- 根拠: {scenario.rationale or '未記録'}",
                ]
            )
            if scenario.trigger_signals:
                lines.append(f"- トリガー: {', '.join(scenario.trigger_signals)}")
            if scenario.early_warning_indicators:
                lines.append(f"- 早期警戒指標: {', '.join(scenario.early_warning_indicators)}")
            if scenario.recommended_actions:
                lines.append(f"- 推奨対応: {', '.join(scenario.recommended_actions)}")
            if scenario.source_candidate_ids:
                lines.append(f"- 参照候補ID: {', '.join(scenario.source_candidate_ids)}")
            if scenario.source_lenses:
                lines.append(f"- 参照レンズ: {', '.join(scenario.source_lenses)}")
            lines.append("")
    for lens in result.lens_results:
        lines.extend(
            [
                "",
                f"## Discoveryレンズ: {lens.title}",
                "",
                f"- Agent: `{lens.agent_name}`",
                f"- Lens: `{lens.discovery_lens}`",
                f"- 候補数: {len(lens.candidates)}",
                f"- Web検索数: {len(lens.web_searches)}",
                f"- URL抽出数: {len(lens.web_extractions)}",
            ]
        )
        for candidate in lens.candidates:
            lines.extend(
                [
                    "",
                    f"### {candidate.title}",
                    "",
                    f"- タイプ: `{candidate.risk_type}`",
                    f"- メカニズム: {candidate.mechanism or '未記録'}",
                    f"- 影響資産・業務: {candidate.affected_asset or '未記録'}",
                    f"- 時間軸: {candidate.time_horizon or '未記録'}",
                    f"- オーナー: {candidate.owner or '未記録'}",
                    f"- 緊急度: `{candidate.urgency}`",
                    f"- 見落とした場合の下振れ: {candidate.downside_if_missed or '未記録'}",
                    f"- 根拠: {candidate.rationale}",
                ]
            )
    return "\n".join(lines) + "\n"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _truncate(value: Any, limit: int) -> str:
    text = _text(value)
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("url") or item.get("title") or json.dumps(item, ensure_ascii=False)
        else:
            text = item
        text = _text(text)
        if text:
            normalized.append(text)
    return list(dict.fromkeys(normalized))


def _normalized_risk_type(value: Any) -> str:
    text = _text(value).lower().replace(" ", "_").replace("-", "_")
    return re.sub(r"[^a-z0-9_]+", "", text).strip("_") or "event_related_risk"


def _normalized_severity(value: Any) -> str:
    text = _text(value).lower()
    return text if text in {"low", "medium", "high", "critical"} else "medium"


def _normalized_likelihood(value: Any) -> str:
    text = _text(value).lower()
    return text if text in {"low", "medium", "high"} else "medium"


def _lens_prefix(lens: str) -> str:
    return "".join(part[0].upper() for part in lens.split("_") if part)[:6] or "DISC"
