from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from langchain_core.tools import tool

from risk_agent_platform.config import Settings
from risk_agent_platform.deepagent_runtime import DeepAgentRunner
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.schemas import (
    DiscoveredRisk,
    RejectedRiskCandidate,
    RiskDiscoveryCandidateDraft,
    RiskDiscoveryCandidatesToolInput,
    RiskDiscoveryEventFacts,
    RiskDiscoveryEventFactsToolInput,
    RiskDiscoveryRequest,
    RiskDiscoveryResult,
    RiskEvent,
)
from risk_agent_platform.tool_policy import ensure_llm_tool_allowed


DISCOVERY_AGENT_NAME = "risk-discovery-agent"
DISCOVERY_DATASET_LIMIT = 25
DISCOVERY_WEB_MAX_QUERIES = 3
DISCOVERY_WEB_MAX_EXTRACT_URLS = 3
DISCOVERY_WEB_MAX_RESULTS = 5
DISCOVERY_EVENT_FACT_KEYS = [
    "affected_geographies",
    "affected_industries",
    "infrastructure_chokepoints",
    "critical_goods_or_services",
    "regulatory_or_sanctions_signals",
    "financial_or_payment_signals",
    "supply_chain_tier_risks",
    "time_horizons",
    "source_refs",
    "uncertainties",
]
CANONICAL_RISK_TYPES = {
    "payment_disruption",
    "supplier_resilience",
    "legal_compliance",
    "accounting_disclosure",
    "executive_resilience",
}
LEGAL_SIGNAL_TERMS = [
    "compliance",
    "sanction",
    "sanctions",
    "export",
    "contract",
    "contractual",
    "regulatory",
    "legal",
    "counterparty",
    "beneficial ownership",
    "restricted party",
    "force majeure",
    "termination",
    "notice",
]
PAYMENT_SIGNAL_TERMS = [
    "payment",
    "payments",
    "cash",
    "liquidity",
    "bank",
    "banking",
    "settlement",
    "treasury",
    "correspondent",
    "funding",
    "currency",
]
ACCOUNTING_SIGNAL_TERMS = [
    "accounting",
    "impairment",
    "provision",
    "disclosure",
    "auditor",
    "recoverability",
    "materiality",
    "subsequent event",
    "contingent liability",
]
SUPPLIER_SIGNAL_TERMS = [
    "supplier",
    "supply chain",
    "inventory",
    "logistics",
    "shipment",
    "shipping",
    "sourcing",
    "alternative source",
    "procurement",
    "lead time",
]
SCOPE_DOMAIN_KEYWORDS: dict[str, dict[str, Any]] = {
    "logistics": {
        "primary_risk_types": ["supplier_resilience"],
        "terms": [
            "logistics",
            "logistic",
            "transport",
            "transportation",
            "shipping",
            "shipment",
            "sea freight",
            "air freight",
            "air cargo",
            "freight",
            "port",
            "ports",
            "customs",
            "warehouse",
            "warehousing",
            "3pl",
            "carrier",
            "forwarder",
            "route",
            "routes",
            "lead time",
            "delivery",
            "物流",
            "輸送",
            "海上輸送",
            "航空輸送",
            "空輸",
            "港湾",
            "通関",
            "倉庫",
            "フォワーダー",
            "配送",
            "代替ルート",
            "リードタイム",
        ],
    },
    "procurement": {
        "primary_risk_types": ["supplier_resilience"],
        "terms": [
            "procurement",
            "sourcing",
            "supplier",
            "suppliers",
            "alternative supplier",
            "sub-tier",
            "parts",
            "materials",
            "購買",
            "調達",
            "仕入",
            "サプライヤー",
            "部材",
            "代替調達",
        ],
    },
    "treasury": {
        "primary_risk_types": ["payment_disruption"],
        "terms": [*PAYMENT_SIGNAL_TERMS, "支払", "支払い", "資金", "銀行", "送金", "決済", "流動性"],
    },
    "legal": {
        "primary_risk_types": ["legal_compliance"],
        "terms": [*LEGAL_SIGNAL_TERMS, "法務", "契約", "制裁", "輸出規制", "通告", "解除", "規制", "コンプライアンス"],
    },
    "accounting": {
        "primary_risk_types": ["accounting_disclosure"],
        "terms": [*ACCOUNTING_SIGNAL_TERMS, "会計", "開示", "減損", "引当", "重要性", "監査"],
    },
    "executive": {
        "primary_risk_types": ["executive_resilience"],
        "terms": [
            "executive",
            "management",
            "board",
            "crisis committee",
            "decision",
            "owner",
            "経営",
            "役員",
            "取締役",
            "危機対策",
            "意思決定",
        ],
    },
}


class RiskDiscoveryDeepAgent:
    """Front-stage DeepAgent that turns an event + scope into analyzable RiskEvents."""

    def __init__(self, settings: Settings, *, embedded_mcp: bool = False) -> None:
        self.settings = settings
        self.mcp = MCPGateway(settings, embedded=embedded_mcp)
        self._state: dict[str, Any] = {}
        self.runner = DeepAgentRunner(settings, DISCOVERY_AGENT_NAME, self.system_prompt(), tools=self.deepagent_tools())

    def system_prompt(self) -> str:
        return (
            "You are the Risk Discovery DeepAgent. Given an external event and a client scope, "
            "identify related risks, filter them to the scope, and record bounded candidate risks. "
            "Use bounded web search/extraction through discovery tools to build event_facts when event-specific "
            "facts are needed for realistic scenario discovery. Use at most 3 searches and 3 URL extractions. "
            "Avoid client-specific names in web queries; search by event, geography, industry, infrastructure, "
            "product category, regulation, or payment mechanism instead. "
            "Record event_facts before candidates when web tools are used, and use those facts to expand "
            "second-order supply, logistics, regulatory, and payment scenarios. "
            "Generate distinct scenario mechanisms even when they share the same risk_type; do not merge logistics, "
            "3PL, customs, critical components, supplier tiers, routing, regulatory, or payment pathways into one item. "
            "If scope_text is provided, treat that free-form natural-language scope as the primary scope signal; "
            "do not require department or scope_name to classify the scope. "
            "Cover the scope-primary risk types implied by the Expert-as-Code scope relevance rules. "
            "Do not collapse legal or payment risks into supplier_resilience merely because a supplier is involved. "
            "Do not collapse legal_compliance into accounting_disclosure merely because disclosure may later be required. "
            "Do not perform final scoring or write the Decision Queue."
        )

    def deepagent_tools(self) -> list[Any]:
        @tool("discovery_list_datasets")
        def discovery_list_datasets(client_id: str) -> str:
            """List available structured client datasets for scope filtering."""
            ensure_llm_tool_allowed(DISCOVERY_AGENT_NAME, "mcp-structured-data", "list_datasets")
            datasets = self.mcp.call("mcp-structured-data", "list_datasets", {"client_id": client_id})
            self._state["datasets"] = datasets
            return json.dumps({"datasets": datasets}, ensure_ascii=False)

        @tool("discovery_sample_dataset")
        def discovery_sample_dataset(client_id: str, dataset: str, limit: int = 10) -> str:
            """Sample abstracted risk features without exposing raw client rows."""
            ensure_llm_tool_allowed(DISCOVERY_AGENT_NAME, "mcp-structured-data", "risk_feature_sample")
            feature_view = self.mcp.call(
                "mcp-structured-data",
                "risk_feature_sample",
                {"client_id": client_id, "dataset": dataset, "limit": min(limit, DISCOVERY_DATASET_LIMIT)},
            )
            features = feature_view.get("features", []) if isinstance(feature_view, dict) else []
            self._state.setdefault("samples", {})[dataset] = features
            self._state.setdefault("feature_summaries", {})[dataset] = (
                feature_view.get("summary", {}) if isinstance(feature_view, dict) else {}
            )
            return json.dumps(
                {
                    "dataset": dataset,
                    "row_count": feature_view.get("row_count", 0) if isinstance(feature_view, dict) else 0,
                    "features": features[:5],
                    "summary": feature_view.get("summary", {}) if isinstance(feature_view, dict) else {},
                },
                ensure_ascii=False,
            )

        @tool("discovery_load_expert_pack")
        def discovery_load_expert_pack() -> str:
            """Load seed Expert-as-Code objects, primitives, cases, questions, and CTA notes."""
            for tool_name in (
                "load_knowledge_pack",
                "load_primitives",
                "load_case_bank",
                "load_question_bank",
                "load_cta_notes",
                "load_scope_relevance_rules",
            ):
                ensure_llm_tool_allowed(DISCOVERY_AGENT_NAME, "mcp-expert-knowledge", tool_name)
            expert = {
                "rules": self.mcp.call("mcp-expert-knowledge", "load_knowledge_pack", {}),
                "primitives": self.mcp.call("mcp-expert-knowledge", "load_primitives", {}),
                "cases": self.mcp.call("mcp-expert-knowledge", "load_case_bank", {}),
                "questions": self.mcp.call("mcp-expert-knowledge", "load_question_bank", {}),
                "cta_notes": self.mcp.call("mcp-expert-knowledge", "load_cta_notes", {}),
                "scope_relevance_rules": self.mcp.call("mcp-expert-knowledge", "load_scope_relevance_rules", {}),
            }
            self._state["expert"] = expert
            return json.dumps({key: len(value) for key, value in expert.items()}, ensure_ascii=False)

        @tool("discovery_search_event_context")
        def discovery_search_event_context(query: str, max_results: int = 3) -> str:
            """Run one sanitized Tavily search through MCP for Discovery event context."""
            ensure_llm_tool_allowed(DISCOVERY_AGENT_NAME, "mcp-web-search", "search_authoritative_sources")
            searches = self._state.setdefault("web_searches", [])
            if len(searches) >= DISCOVERY_WEB_MAX_QUERIES:
                return json.dumps(
                    {
                        "status": "skipped",
                        "reason": f"Discovery web search budget exhausted at {DISCOVERY_WEB_MAX_QUERIES} queries.",
                    },
                    ensure_ascii=False,
                )
            request = RiskDiscoveryRequest.model_validate(self._state["request"])
            bounded_results = max(1, min(_to_int(max_results, default=3), DISCOVERY_WEB_MAX_RESULTS))
            try:
                result = self.mcp.call(
                    "mcp-web-search",
                    "search_authoritative_sources",
                    {
                        "query": query,
                        "risk_event": _discovery_context_event(request, self._state),
                        "max_results": bounded_results,
                        "confidential_terms": _discovery_confidential_terms(request),
                    },
                )
                summary = _web_search_summary(query, result)
                summary["status"] = "ok"
            except RuntimeError as exc:
                summary = {
                    "status": "unavailable",
                    "query": "",
                    "query_hash": "",
                    "result_count": 0,
                    "results": [],
                    "error": _truncate_text(str(exc), 300),
                }
            searches.append(summary)
            return json.dumps(summary, ensure_ascii=False)

        @tool("discovery_extract_event_source")
        def discovery_extract_event_source(url: str) -> str:
            """Extract one selected source URL through Tavily for Discovery event facts."""
            ensure_llm_tool_allowed(DISCOVERY_AGENT_NAME, "mcp-web-search", "extract_url")
            extractions = self._state.setdefault("web_extractions", [])
            if len(extractions) >= DISCOVERY_WEB_MAX_EXTRACT_URLS:
                return json.dumps(
                    {
                        "status": "skipped",
                        "reason": f"Discovery URL extraction budget exhausted at {DISCOVERY_WEB_MAX_EXTRACT_URLS} URLs.",
                    },
                    ensure_ascii=False,
                )
            try:
                result = self.mcp.call("mcp-web-search", "extract_url", {"url": url})
                summary = _web_extraction_summary(url, result)
                summary["status"] = "ok"
            except RuntimeError as exc:
                summary = {
                    "status": "unavailable",
                    "url": url,
                    "error": _truncate_text(str(exc), 300),
                }
            extractions.append(summary)
            return json.dumps(summary, ensure_ascii=False)

        @tool("discovery_record_event_facts", args_schema=RiskDiscoveryEventFactsToolInput)
        def discovery_record_event_facts(
            event_facts: dict[str, Any] | None = None,
            event_facts_json: str | None = None,
        ) -> str:
            """Record external event facts used to broaden Discovery candidates."""
            facts_model = _event_facts_from_tool_input(event_facts=event_facts, event_facts_json=event_facts_json)
            facts = _normalize_event_facts(facts_model.model_dump(mode="json"))
            self._state["event_facts"] = facts
            self._state["event_facts_source"] = "agent_recorded"
            return json.dumps(
                {
                    "status": "recorded",
                    "fact_counts": {key: len(value) for key, value in facts.items()},
                },
                ensure_ascii=False,
            )

        @tool("discovery_record_candidates", args_schema=RiskDiscoveryCandidatesToolInput)
        def discovery_record_candidates(
            candidates: list[dict[str, Any]] | None = None,
            candidates_json: str | None = None,
        ) -> str:
            """Record bounded risk candidates as JSON for structured filtering."""
            draft_candidates = _candidate_drafts_from_tool_input(candidates=candidates, candidates_json=candidates_json)
            self._state["raw_candidates"] = [
                candidate.model_dump(mode="json", exclude_none=True) for candidate in draft_candidates
            ]
            return json.dumps({"candidate_count": len(self._state["raw_candidates"])}, ensure_ascii=False)

        return [
            discovery_list_datasets,
            discovery_sample_dataset,
            discovery_load_expert_pack,
            discovery_search_event_context,
            discovery_extract_event_source,
            discovery_record_event_facts,
            discovery_record_candidates,
        ]

    def discover(self, request: RiskDiscoveryRequest) -> RiskDiscoveryResult:
        scope_interpretation = _interpret_scope(request)
        self._state = {
            "request": request.model_dump(mode="json"),
            "scope_interpretation": scope_interpretation,
            "datasets": [],
            "samples": {},
            "feature_summaries": {},
            "expert": {},
            "web_searches": [],
            "web_extractions": [],
            "event_facts": {},
            "raw_candidates": [],
        }
        self.runner.synthesize(
            "Use discovery tools to inspect client scope, expert knowledge, and bounded external event context, "
            "then record risk candidates. Use discovery_search_event_context when event-specific facts could affect "
            "industries, infrastructure, logistics lanes, supplier tiers, regulation, sanctions, banking, or payments. "
            "Use discovery_extract_event_source only for the most useful URLs. Record event_facts with keys "
            f"{DISCOVERY_EVENT_FACT_KEYS} before candidates when web tools are used. "
            "Avoid client-specific names in web queries; search by event, geography, industry, infrastructure, "
            "product category, regulation, or payment mechanism. "
            "Generate about request.max_risks distinct risk scenarios. Multiple candidates may share the same "
            "risk_type if their disruption mechanism, affected asset, time horizon, or decision owner differs. "
            "If request.scope.scope_text is present, interpret that free-form natural-language scope directly; "
            "do not require department or scope_name values to infer relevant business concerns. "
            "Cover the scope-primary risk types from applicable scope relevance rules. "
            "Do not collapse legal or payment risks into supplier_resilience merely because a supplier is involved. "
            "Do not collapse legal_compliance into accounting_disclosure merely because disclosure may later be required. "
            "Return no prose after recording. Call discovery_record_event_facts with the structured event_facts "
            "argument. Call discovery_record_candidates with the structured candidates list argument, not a JSON string. "
            "Candidate fields: title, risk_type, risk_themes, affected_categories, description, urgency, "
            "scope_matches, rationale.\n"
            f"scope_interpretation={json.dumps(scope_interpretation, ensure_ascii=False)}\n"
            f"request={json.dumps(request.model_dump(mode='json'), ensure_ascii=False)}",
            max_chars=3000,
        )
        self._ensure_context(request)
        if not _has_event_facts(self._state.get("event_facts")) and (
            self._state.get("web_searches") or self._state.get("web_extractions")
        ):
            derived_facts = _derive_event_facts_from_web(request, self._state)
            if _has_event_facts(derived_facts):
                self._state["event_facts"] = derived_facts
                self._state["event_facts_source"] = "derived_from_web_summaries"
        raw_candidates = self._state.get("raw_candidates") or []
        candidates = _normalize_candidates(raw_candidates, request) if raw_candidates else self._fallback_candidates(request)
        candidates, coverage_augmented_count = _augment_scope_coverage(candidates, request, self._state)
        selected_candidates, rejected_candidates = self._filter_to_scope(candidates, request)
        selected_candidates = [
            candidate.model_copy(update={"selected_for_analysis": True})
            for candidate in selected_candidates
        ]
        selected_events = [_candidate_to_event(candidate, request) for candidate in selected_candidates]
        selected_event = selected_events[0] if selected_events else None
        fallback_used = not bool(raw_candidates)
        additional_questions = _discovery_questions(selected_candidates, request)
        unknowns = _discovery_unknowns(selected_candidates, request)
        return RiskDiscoveryResult(
            request=request,
            selected_candidates=selected_candidates,
            rejected_candidates=rejected_candidates,
            selected_event=selected_event,
            selected_events=selected_events,
            metadata={
                "agent_name": DISCOVERY_AGENT_NAME,
                "datasets": self._state.get("datasets", []),
                "sampled_datasets": sorted((self._state.get("samples") or {}).keys()),
                "structured_sample_view": "risk_feature_sample",
                "feature_summaries": self._state.get("feature_summaries", {}),
                "scope_interpretation": scope_interpretation,
                "expert_counts": {key: len(value) for key, value in (self._state.get("expert") or {}).items()},
                "raw_candidate_count": len(raw_candidates),
                "coverage_augmented_candidate_count": coverage_augmented_count,
                "web_search_count": len(self._state.get("web_searches") or []),
                "web_extraction_count": len(self._state.get("web_extractions") or []),
                "web_searches": self._state.get("web_searches", []),
                "web_extractions": self._state.get("web_extractions", []),
                "event_facts": self._state.get("event_facts", {}),
                "event_facts_source": self._state.get("event_facts_source", ""),
                "fallback_used": fallback_used,
                "discovery_confidence": "template_fallback" if fallback_used else "agent_recorded_candidates",
                "additional_questions": additional_questions,
                "unknowns": unknowns,
                "scope_relevance_rule_count": len(_scope_relevance_rules(self._state)),
            },
        )

    def _ensure_context(self, request: RiskDiscoveryRequest) -> None:
        if not self._state.get("datasets"):
            self._state["datasets"] = self.mcp.call("mcp-structured-data", "list_datasets", {"client_id": request.scope.client_id})
        samples = self._state.setdefault("samples", {})
        for dataset in _datasets_for_scope(self._state.get("datasets", [])):
            if dataset not in samples:
                feature_view = self.mcp.call(
                    "mcp-structured-data",
                    "risk_feature_sample",
                    {"client_id": request.scope.client_id, "dataset": dataset, "limit": DISCOVERY_DATASET_LIMIT},
                )
                samples[dataset] = feature_view.get("features", []) if isinstance(feature_view, dict) else []
                self._state.setdefault("feature_summaries", {})[dataset] = (
                    feature_view.get("summary", {}) if isinstance(feature_view, dict) else {}
                )
        if not self._state.get("expert"):
            self._state["expert"] = {
                "rules": self.mcp.call("mcp-expert-knowledge", "load_knowledge_pack", {}),
                "primitives": self.mcp.call("mcp-expert-knowledge", "load_primitives", {}),
                "cases": self.mcp.call("mcp-expert-knowledge", "load_case_bank", {}),
                "questions": self.mcp.call("mcp-expert-knowledge", "load_question_bank", {}),
                "cta_notes": self.mcp.call("mcp-expert-knowledge", "load_cta_notes", {}),
                "scope_relevance_rules": self.mcp.call("mcp-expert-knowledge", "load_scope_relevance_rules", {}),
            }

    def _fallback_candidates(self, request: RiskDiscoveryRequest) -> list[DiscoveredRisk]:
        event_text = f"{request.event_title} {request.event_description}".lower()
        countries = request.countries or _country_hints(request.event_title, request.event_description)
        templates = [
            (
                "payment_disruption",
                "Treasury payment disruption and cash mobility risk",
                ["payment_disruption", "cash_mobility", "liquidity_at_risk"],
                ["cross_border_payments", "bank_routes", "near_term_supplier_payments"],
                "The event may disrupt bank routes, sanctions screening, liquidity availability, or urgent supplier payments.",
                "high" if _contains_any(event_text, ["war", "sanction", "capital control", "bank"]) else "medium",
            ),
            (
                "supplier_resilience",
                "Supplier continuity and logistics disruption risk",
                ["supplier_resilience", "logistics", "alternative_sourcing"],
                ["critical_suppliers", "inventory_runway", "inbound_logistics"],
                "The event may affect critical suppliers, sub-tier dependencies, ports, freight routes, or inventory runway.",
                "high" if _contains_any(event_text, ["war", "port", "supply", "export", "shipping"]) else "medium",
            ),
            (
                "legal_compliance",
                "Sanctions, export-control, and contract obligation risk",
                ["sanctions", "export_control", "contract_obligation"],
                ["contracts", "counterparties", "payment_or_shipment_controls"],
                "The event may trigger sanctions proximity, beneficial ownership review, contract notice, or force majeure questions.",
                "high" if _contains_any(event_text, ["sanction", "war", "export", "iran", "russia"]) else "medium",
            ),
            (
                "accounting_disclosure",
                "Accounting provision, impairment, and disclosure pressure",
                ["provision_trigger", "impairment_trigger", "disclosure_pressure"],
                ["material_exposures", "financial_reporting", "auditor_evidence_pack"],
                "The event may affect recoverability, provisions, subsequent-event analysis, or disclosure if impact becomes material.",
                "medium",
            ),
            (
                "executive_resilience",
                "Cross-functional executive decision urgency",
                ["decision_urgency", "operational_resilience", "cross_mode_conflict"],
                ["critical_services", "decision_queue", "specialist_review"],
                "The event may require an executive trade-off across treasury, legal, accounting, procurement, and operations.",
                "high" if request.scope.scope_type == "company" else "medium",
            ),
        ]
        candidates = [
            _build_candidate(idx, template, request, countries)
            for idx, template in enumerate(templates, start=1)
        ]
        return candidates

    def _filter_to_scope(
        self,
        candidates: list[DiscoveredRisk],
        request: RiskDiscoveryRequest,
    ) -> tuple[list[DiscoveredRisk], list[RejectedRiskCandidate]]:
        rules = _scope_relevance_rules(self._state)
        enriched = [_score_scope_relevance(candidate, request, self._state.get("samples") or {}, rules) for candidate in candidates]
        threshold = 40 if request.scope.scope_type == "company" else 50
        sorted_candidates = sorted(enriched, key=lambda item: item.relevance_score, reverse=True)
        selected = [candidate for candidate in sorted_candidates if candidate.relevance_score >= threshold]
        if not selected and sorted_candidates:
            selected = sorted_candidates[:1]
        selected = selected[: request.max_risks]
        selected_ids = {candidate.candidate_id for candidate in selected}
        rejected = [
            _rejection_for_candidate(candidate, request, threshold)
            for candidate in sorted_candidates
            if candidate.candidate_id not in selected_ids
        ]
        return selected, rejected


def _datasets_for_scope(datasets: list[str]) -> list[str]:
    preferred = ["segments", "regions", "sites", "suppliers", "payments", "contracts", "customers"]
    return [dataset for dataset in preferred if dataset in datasets][:6]


def _event_facts_from_tool_input(
    *,
    event_facts: Any = None,
    event_facts_json: str | None = None,
) -> RiskDiscoveryEventFacts:
    if event_facts_json:
        data = _json_object_from_text(event_facts_json) or {}
        payload = data.get("event_facts") if isinstance(data.get("event_facts"), dict) else data
        return RiskDiscoveryEventFacts.model_validate(payload)
    if isinstance(event_facts, RiskDiscoveryEventFacts):
        return event_facts
    return RiskDiscoveryEventFacts.model_validate(event_facts or {})


def _candidate_drafts_from_tool_input(
    *,
    candidates: Any = None,
    candidates_json: str | None = None,
) -> list[RiskDiscoveryCandidateDraft]:
    if candidates_json:
        data = _json_object_from_text(candidates_json) or {}
        raw_candidates = data.get("candidates") or []
    else:
        raw_candidates = candidates or []
    if not isinstance(raw_candidates, list):
        raise ValueError("candidates must be a list")
    return [
        item if isinstance(item, RiskDiscoveryCandidateDraft) else RiskDiscoveryCandidateDraft.model_validate(item)
        for item in raw_candidates
    ]


def _normalize_candidates(raw_candidates: list[Any], request: RiskDiscoveryRequest) -> list[DiscoveredRisk]:
    candidates: list[DiscoveredRisk] = []
    countries = request.countries or _country_hints(request.event_title, request.event_description)
    for idx, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or f"Discovered risk {idx}")
        risk_themes = [str(item) for item in raw.get("risk_themes") or []]
        affected_categories = [str(item) for item in raw.get("affected_categories") or []]
        description = str(raw.get("description") or request.event_description or request.event_title)
        risk_type = _canonical_risk_type(
            str(raw.get("risk_type") or "event_related_risk"),
            title=title,
            risk_themes=risk_themes,
            affected_categories=affected_categories,
            description=description,
            request=request,
        )
        candidate = DiscoveredRisk(
            candidate_id=str(raw.get("candidate_id") or f"DISC-{idx:03d}"),
            title=title,
            risk_type=risk_type,
            countries=[str(item) for item in raw.get("countries") or countries],
            risk_themes=risk_themes,
            affected_categories=affected_categories,
            description=description,
            urgency=str(raw.get("urgency") or "medium").lower() if str(raw.get("urgency") or "").lower() in {"low", "medium", "high"} else "medium",
            scope_matches=[str(item) for item in raw.get("scope_matches") or []],
            rationale=str(raw.get("rationale") or "Generated by Risk Discovery DeepAgent."),
        )
        candidates.append(candidate)
    return candidates


def _augment_scope_coverage(
    candidates: list[DiscoveredRisk],
    request: RiskDiscoveryRequest,
    state: dict[str, Any],
) -> tuple[list[DiscoveredRisk], int]:
    augmented = list(candidates)
    added = 0
    coverage_specs = _coverage_candidate_specs(augmented, request, state)
    for spec in coverage_specs:
        augmented.append(
            DiscoveredRisk(
                candidate_id=spec["candidate_id"],
                title=spec["title"],
                risk_type=spec["risk_type"],
                countries=request.countries or _country_hints(request.event_title, request.event_description),
                risk_themes=spec["risk_themes"],
                affected_categories=spec["affected_categories"],
                description=spec["description"],
                urgency=spec["urgency"],
                scope_matches=spec["scope_matches"],
                rationale=spec["rationale"],
            )
        )
        added += 1
    scope_is_executive = _is_broad_executive_scope(request) or str(request.scope.department or "").lower() == "executive"
    if scope_is_executive and not any(candidate.risk_type == "executive_resilience" for candidate in augmented):
        augmented.append(
            DiscoveredRisk(
                candidate_id="DISC-AUG-EXEC",
                title=f"Cross-functional executive decision urgency: {request.event_title}",
                risk_type="executive_resilience",
                countries=request.countries or _country_hints(request.event_title, request.event_description),
                risk_themes=["decision_urgency", "operational_resilience", "cross_mode_conflict"],
                affected_categories=["critical_services", "decision_queue", "specialist_review"],
                description=(
                    "The event may require an executive trade-off across treasury, legal, accounting, "
                    "procurement, and operations. Event: "
                    f"{request.event_description or request.event_title}"
                ),
                urgency="high",
                scope_matches=["coverage_augmentation:executive_scope"],
                rationale="Added by deterministic coverage augmentation for company or executive scope.",
            )
        )
        added += 1
    return augmented, added


def _interpret_scope(request: RiskDiscoveryRequest) -> dict[str, Any]:
    raw_parts = [
        request.scope.scope_text or "",
        request.scope.scope_name or "",
        request.scope.department or "",
        request.scope.region or "",
        request.scope.site_id or "",
        json.dumps(request.scope.metadata, ensure_ascii=False),
    ]
    text = " ".join(raw_parts).replace("_", " ").lower()
    matched_domains: list[str] = []
    matched_terms: list[str] = []
    primary_risk_types: list[str] = []
    for domain, config in SCOPE_DOMAIN_KEYWORDS.items():
        terms = [str(term).lower() for term in config.get("terms", [])]
        hits = [term for term in terms if term and term in text]
        if not hits:
            continue
        matched_domains.append(domain)
        matched_terms.extend(hits)
        for risk_type in config.get("primary_risk_types", []):
            if risk_type not in primary_risk_types:
                primary_risk_types.append(str(risk_type))
    if request.scope.scope_type == "company" and not primary_risk_types and request.scope.scope_text:
        primary_risk_types.append("executive_resilience")
    return {
        "scope_text": request.scope.scope_text,
        "matched_domains": matched_domains,
        "matched_terms": list(dict.fromkeys(matched_terms)),
        "primary_risk_types": primary_risk_types,
        "source": "scope_text" if request.scope.scope_text else "structured_scope",
    }


def _coverage_candidate_specs(
    candidates: list[DiscoveredRisk],
    request: RiskDiscoveryRequest,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_types = {candidate.risk_type for candidate in candidates}
    context = _coverage_context_text(candidates, request, state)
    specs: list[dict[str, Any]] = []
    planned_types: set[str] = set()
    scope_interpretation = state.get("scope_interpretation") if isinstance(state.get("scope_interpretation"), dict) else {}
    scope_primary_types = [str(item) for item in scope_interpretation.get("primary_risk_types") or []]
    scope_terms = [str(item) for item in scope_interpretation.get("matched_terms") or []]
    if scope_interpretation.get("source") == "scope_text" and scope_terms:
        for risk_type in scope_primary_types:
            if risk_type in existing_types or risk_type in planned_types:
                continue
            specs.append(
                _coverage_candidate_spec(
                    {"rule_id": "SCOPE-TEXT-PRIMARY", "match_terms": scope_terms},
                    risk_type,
                    scope_terms,
                    request,
                )
            )
            planned_types.add(risk_type)
    if _is_broad_executive_scope(request):
        broad_terms = ["executive", "portfolio", "cross-functional", request.event_title, request.event_description]
        for risk_type in ["supplier_resilience", "payment_disruption", "legal_compliance", "executive_resilience"]:
            if risk_type in existing_types or risk_type in planned_types:
                continue
            specs.append(
                _coverage_candidate_spec(
                    {"rule_id": "SCOPE-BROAD-EXECUTIVE", "match_terms": broad_terms},
                    risk_type,
                    broad_terms,
                    request,
                )
            )
            planned_types.add(risk_type)
    for rule in _coverage_scope_rules(state, request):
        matched_terms = _matched_rule_terms(rule, context)
        if not matched_terms:
            continue
        for risk_type in _canonical_primary_risk_types(rule):
            if risk_type in existing_types or risk_type in planned_types:
                continue
            specs.append(_coverage_candidate_spec(rule, risk_type, matched_terms, request))
            planned_types.add(risk_type)
    return specs


def _coverage_scope_rules(state: dict[str, Any], request: RiskDiscoveryRequest) -> list[dict[str, Any]]:
    applicable = [rule for rule in _scope_relevance_rules(state) if _rule_applies_to_scope(rule, request)]
    department_rules = [rule for rule in applicable if str(rule.get("scope_kind") or "").lower() == "department"]
    if request.scope.scope_type == "department" and department_rules:
        return department_rules
    return applicable


def _is_broad_executive_scope(request: RiskDiscoveryRequest) -> bool:
    if request.scope.scope_text:
        return False
    scope_text = " ".join(
        [
            request.scope.scope_type,
            request.scope.scope_name or "",
            request.scope.department or "",
        ]
    ).lower()
    return request.scope.scope_type == "company" or "executive" in scope_text or "management" in scope_text


def _canonical_primary_risk_types(rule: dict[str, Any]) -> list[str]:
    risk_types: list[str] = []
    for raw_risk_type in rule.get("primary_risk_types") or []:
        canonical = _canonical_primary_risk_type(str(raw_risk_type))
        if canonical and canonical not in risk_types:
            risk_types.append(canonical)
    return risk_types


def _canonical_primary_risk_type(risk_type: str) -> str | None:
    normalized = risk_type.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in CANONICAL_RISK_TYPES:
        return normalized
    text = normalized.replace("_", " ")
    if _contains_any(text, LEGAL_SIGNAL_TERMS):
        return "legal_compliance"
    if _contains_any(text, PAYMENT_SIGNAL_TERMS):
        return "payment_disruption"
    if _contains_any(text, ACCOUNTING_SIGNAL_TERMS):
        return "accounting_disclosure"
    if _contains_any(text, SUPPLIER_SIGNAL_TERMS):
        return "supplier_resilience"
    if _contains_any(text, ["decision urgency", "operational resilience", "executive"]):
        return "executive_resilience"
    return None


def _coverage_context_text(
    candidates: list[DiscoveredRisk],
    request: RiskDiscoveryRequest,
    state: dict[str, Any],
) -> str:
    parts: list[str] = [
        request.event_title,
        request.event_description,
        " ".join(request.countries),
        request.scope.scope_text or "",
        request.scope.scope_type,
        request.scope.scope_name or "",
        request.scope.department or "",
        request.scope.region or "",
        request.scope.site_id or "",
        json.dumps(request.scope.metadata, ensure_ascii=False),
        json.dumps(state.get("feature_summaries") or {}, ensure_ascii=False),
        json.dumps(state.get("samples") or {}, ensure_ascii=False),
        json.dumps(state.get("event_facts") or {}, ensure_ascii=False),
        json.dumps(state.get("web_searches") or [], ensure_ascii=False),
        json.dumps(state.get("web_extractions") or [], ensure_ascii=False),
    ]
    for candidate in candidates:
        parts.extend(
            [
                candidate.title,
                candidate.risk_type,
                " ".join(candidate.risk_themes),
                " ".join(candidate.affected_categories),
                candidate.description,
                candidate.rationale,
            ]
        )
    return " ".join(parts).replace("_", " ").lower()


def _matched_rule_terms(rule: dict[str, Any], context: str) -> list[str]:
    matches = []
    for term in [str(item).lower() for item in rule.get("match_terms") or []]:
        if term and term in context:
            matches.append(term)
    return list(dict.fromkeys(matches))


def _coverage_candidate_spec(
    rule: dict[str, Any],
    risk_type: str,
    matched_terms: list[str],
    request: RiskDiscoveryRequest,
) -> dict[str, Any]:
    rule_id = str(rule.get("rule_id") or rule.get("scope_key") or "scope_rule")
    title_prefix = {
        "payment_disruption": "Treasury payment disruption coverage",
        "legal_compliance": "Legal compliance and sanctions coverage",
        "accounting_disclosure": "Accounting disclosure and reporting coverage",
        "supplier_resilience": "Supplier continuity coverage",
        "executive_resilience": "Executive resilience coverage",
    }.get(risk_type, "Scope-primary risk coverage")
    themes = {
        "payment_disruption": ["payment_disruption", "cash_mobility", "bank_route_validation"],
        "legal_compliance": ["sanctions", "export_control", "contract_obligation"],
        "accounting_disclosure": ["provision_trigger", "impairment_trigger", "disclosure_pressure"],
        "supplier_resilience": ["supplier_resilience", "logistics", "alternative_sourcing"],
        "executive_resilience": ["decision_urgency", "operational_resilience", "cross_mode_conflict"],
    }.get(risk_type, [risk_type])
    categories = {
        "payment_disruption": ["cross_border_payments", "bank_routes", "liquidity"],
        "legal_compliance": ["contracts", "counterparties", "regulatory_controls"],
        "accounting_disclosure": ["financial_reporting", "materiality", "auditor_evidence_pack"],
        "supplier_resilience": ["critical_suppliers", "inventory_runway", "inbound_logistics"],
        "executive_resilience": ["critical_services", "decision_queue", "specialist_review"],
    }.get(risk_type, ["scope_primary_risk"])
    matched = ", ".join(matched_terms[:8])
    return {
        "candidate_id": f"DISC-AUG-{_slug(rule_id)}-{_slug(risk_type)}"[:80],
        "title": f"{title_prefix}: {request.event_title}",
        "risk_type": risk_type,
        "risk_themes": themes,
        "affected_categories": categories,
        "description": (
            f"Added to cover scope-primary risk type `{risk_type}` under Expert-as-Code rule {rule_id}. "
            f"Matched event, feature, or candidate signals: {matched}. Event: "
            f"{request.event_description or request.event_title}"
        ),
        "urgency": "high" if risk_type in {"payment_disruption", "legal_compliance", "supplier_resilience"} else "medium",
        "scope_matches": [f"{rule_id}:coverage_primary", *[f"coverage_term:{term}" for term in matched_terms[:5]]],
        "rationale": (
            f"Deterministic coverage augmentation added this candidate because applicable scope rule {rule_id} "
            f"lists `{risk_type}` or its aliases as primary, matched terms were present, and no candidate of this "
            "risk type was recorded by the LLM."
        ),
    }


def _discovery_context_event(request: RiskDiscoveryRequest, state: dict[str, Any]) -> dict[str, Any]:
    scope_interpretation = state.get("scope_interpretation") if isinstance(state.get("scope_interpretation"), dict) else {}
    matched_domains = [str(item) for item in scope_interpretation.get("matched_domains") or []]
    primary_types = [str(item) for item in scope_interpretation.get("primary_risk_types") or []]
    themes = list(dict.fromkeys(["event_context", *primary_types, *matched_domains]))
    categories = matched_domains or primary_types or ["event_context"]
    return RiskEvent(
        scenario_id="discovery_event_context",
        client_id=request.scope.client_id,
        title="External event context",
        risk_type="event_context",
        countries=request.countries or _country_hints(request.event_title, request.event_description),
        risk_themes=themes,
        affected_categories=categories,
        description="Public event context search for risk scenario discovery.",
        event_date=request.event_date or date.today(),
        urgency="medium",
    ).model_dump(mode="json")


def _discovery_confidential_terms(request: RiskDiscoveryRequest) -> list[str]:
    terms: list[str] = [
        request.scope.client_id,
        request.scope.site_id or "",
    ]
    explicit_terms = request.scope.metadata.get("confidential_terms")
    if isinstance(explicit_terms, list):
        terms.extend(str(item) for item in explicit_terms)
    elif isinstance(explicit_terms, str):
        terms.append(explicit_terms)
    if request.scope.scope_text:
        terms.extend(_capitalized_phrases(request.scope.scope_text))
    return [
        term
        for term in dict.fromkeys(term.strip() for term in terms if isinstance(term, str))
        if len(term) >= 4 and not _is_generic_scope_term(term)
    ]


def _web_search_summary(query: str, result: Any) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    return {
        "query": str(payload.get("query") or query),
        "query_hash": str(payload.get("query_hash") or ""),
        "result_count": len(results),
        "results": [_web_result_item(item) for item in results[:DISCOVERY_WEB_MAX_RESULTS] if isinstance(item, dict)],
    }


def _web_result_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _truncate_text(str(item.get("title") or ""), 160),
        "url": _truncate_text(str(item.get("url") or ""), 240),
        "content": _truncate_text(str(item.get("content") or item.get("raw_content") or ""), 320),
    }


def _web_extraction_summary(url: str, result: Any) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    extraction_result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    extracted = extraction_result.get("results") if isinstance(extraction_result.get("results"), list) else []
    return {
        "url": url,
        "result_count": len(extracted),
        "results": [_web_result_item(item) for item in extracted[:2] if isinstance(item, dict)],
    }


def _normalize_event_facts(data: Any) -> dict[str, list[Any]]:
    source = data if isinstance(data, dict) else {}
    return {key: _normalize_fact_list(source.get(key)) for key in DISCOVERY_EVENT_FACT_KEYS}


def _has_event_facts(facts: Any) -> bool:
    return isinstance(facts, dict) and any(facts.get(key) for key in DISCOVERY_EVENT_FACT_KEYS)


def _derive_event_facts_from_web(request: RiskDiscoveryRequest, state: dict[str, Any]) -> dict[str, list[Any]]:
    text = " ".join(
        [
            request.event_title,
            request.event_description,
            json.dumps(state.get("web_searches") or [], ensure_ascii=False),
            json.dumps(state.get("web_extractions") or [], ensure_ascii=False),
        ]
    )
    lowered = text.lower()
    source_refs = _source_refs_from_web_state(state)
    if not source_refs and not lowered.strip():
        return _normalize_event_facts({})
    facts = {
        "affected_geographies": list(
            dict.fromkeys([*request.countries, *_label_matches(lowered, {"Taiwan Strait": ["taiwan strait"]})])
        ),
        "affected_industries": _label_matches(
            lowered,
            {
                "semiconductors": ["semiconductor", "chip", "foundry", "tsmc"],
                "electronics": ["electronics", "electronic component", "electronic assemblies"],
                "logistics": ["logistics", "3pl", "shipping", "air cargo", "sea freight"],
                "pharmaceuticals": ["pharmaceutical", "medical device"],
                "imaging materials": ["imaging materials", "photomask", "specialty film"],
            },
        ),
        "infrastructure_chokepoints": _label_matches(
            lowered,
            {
                "Taiwan Strait": ["taiwan strait"],
                "ports": ["port", "harbor", "container terminal"],
                "air cargo routes": ["air cargo", "airport", "taoyuan"],
                "sea freight lanes": ["sea freight", "shipping lane", "ocean freight"],
                "customs clearance": ["customs", "clearance"],
                "3PL hubs": ["3pl", "third-party logistics", "warehouse"],
            },
        ),
        "critical_goods_or_services": _label_matches(
            lowered,
            {
                "semiconductor components": ["semiconductor", "chip", "foundry"],
                "electronic assemblies": ["electronic assemblies", "electronics"],
                "photomasks": ["photomask"],
                "specialty imaging materials": ["specialty imaging", "imaging materials", "specialty film"],
                "air freight capacity": ["air freight", "air cargo"],
                "sea freight capacity": ["sea freight", "ocean freight", "container"],
            },
        ),
        "regulatory_or_sanctions_signals": _label_matches(
            lowered,
            {
                "export controls": ["export control", "export restriction", "dual-use"],
                "sanctions screening": ["sanction", "restricted party"],
                "customs restrictions": ["customs restriction", "customs clearance"],
            },
        ),
        "financial_or_payment_signals": _label_matches(
            lowered,
            {
                "cross-border payments": ["cross-border payment", "international payment"],
                "bank routing": ["bank routing", "correspondent bank", "settlement"],
                "liquidity planning": ["liquidity", "cash"],
            },
        ),
        "supply_chain_tier_risks": _label_matches(
            lowered,
            {
                "sub-tier semiconductor dependency": ["semiconductor", "chip", "foundry", "sub-tier"],
                "3PL service dependency": ["3pl", "third-party logistics"],
                "alternate route capacity dependency": ["alternate route", "rerouting", "diversion"],
            },
        ),
        "time_horizons": _label_matches(
            lowered,
            {
                "near-term disruption": ["near-term", "immediate", "0-2 weeks", "suspension", "delay"],
                "medium-term rerouting": ["rerouting", "alternate route", "capacity"],
            },
        ),
        "source_refs": source_refs,
        "uncertainties": ["Client-specific dependency depth and exposure amounts still require validation."],
    }
    return _normalize_event_facts(facts)


def _source_refs_from_web_state(state: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for bucket in ("web_searches", "web_extractions"):
        for item in state.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            for result in item.get("results") or []:
                if not isinstance(result, dict):
                    continue
                url = str(result.get("url") or "").strip()
                if not url:
                    continue
                refs.append(
                    {
                        "title": _truncate_text(str(result.get("title") or url), 160),
                        "url": _truncate_text(url, 240),
                    }
                )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in refs:
        if ref["url"] in seen:
            continue
        seen.add(ref["url"])
        deduped.append(ref)
    return deduped[:5]


def _label_matches(text: str, label_aliases: dict[str, list[str]]) -> list[str]:
    return [label for label, aliases in label_aliases.items() if any(alias in text for alias in aliases)]


def _normalize_fact_list(value: Any) -> list[Any]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    normalized: list[Any] = []
    for item in items[:10]:
        if isinstance(item, dict):
            compact = {
                str(key): _truncate_text(str(val), 240)
                for key, val in item.items()
                if val is not None and str(val).strip()
            }
            if compact:
                normalized.append(compact)
        else:
            text = _truncate_text(str(item).strip(), 240)
            if text:
                normalized.append(text)
    return normalized


def _capitalized_phrases(text: str) -> list[str]:
    return re.findall(r"\b[A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+){0,4}\b", text)


def _is_generic_scope_term(term: str) -> bool:
    generic = {
        "logistics",
        "supply",
        "procurement",
        "treasury",
        "finance",
        "legal",
        "accounting",
        "manufacturing",
        "operations",
        "payment",
        "payments",
        "supplier",
        "suppliers",
        "shipping",
        "transport",
        "transportation",
        "customs",
        "warehouse",
    }
    return term.strip().lower() in generic


def _truncate_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."


def _canonical_risk_type(
    risk_type: str,
    *,
    title: str,
    risk_themes: list[str],
    affected_categories: list[str],
    description: str,
    request: RiskDiscoveryRequest | None = None,
) -> str:
    normalized = risk_type.strip().lower().replace(" ", "_").replace("-", "_")
    raw = risk_type.lower()
    text = " ".join([raw, title, " ".join(risk_themes), " ".join(affected_categories), description]).lower()
    scope_hint = " ".join(
        [
            str((request.scope.department if request else "") or ""),
            str((request.scope.scope_name if request else "") or ""),
            str((request.scope.scope_text if request else "") or ""),
        ]
    ).lower()
    if _contains_any(scope_hint, ["legal", "法務"]) and _contains_any(text, LEGAL_SIGNAL_TERMS):
        return "legal_compliance"
    if _contains_any(scope_hint, ["treasury", "finance", "財務", "資金"]) and _contains_any(text, PAYMENT_SIGNAL_TERMS):
        return "payment_disruption"
    if _contains_any(raw, LEGAL_SIGNAL_TERMS):
        return "legal_compliance"
    if _contains_any(raw, PAYMENT_SIGNAL_TERMS):
        return "payment_disruption"
    if normalized in CANONICAL_RISK_TYPES:
        return normalized
    if _contains_any(text, LEGAL_SIGNAL_TERMS):
        return "legal_compliance"
    if _contains_any(text, PAYMENT_SIGNAL_TERMS):
        return "payment_disruption"
    if "financial reporting" in raw or _contains_any(text, ["accounting", "impairment", "provision", "disclosure", "auditor", "recoverability"]):
        return "accounting_disclosure"
    if "supply chain" in raw or _contains_any(text, ["supplier", "inventory", "logistics", "shipment", "sourcing", "alternative source"]):
        return "supplier_resilience"
    if _contains_any(text, ["executive", "cross-functional", "decision ownership", "board", "crisis committee"]):
        return "executive_resilience"
    return normalized or "event_related_risk"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _build_candidate(
    idx: int,
    template: tuple[str, str, list[str], list[str], str, str],
    request: RiskDiscoveryRequest,
    countries: list[str],
) -> DiscoveredRisk:
    risk_type, title, themes, categories, description, urgency = template
    return DiscoveredRisk(
        candidate_id=f"DISC-{idx:03d}",
        title=f"{title}: {request.event_title}",
        risk_type=risk_type,
        countries=countries,
        risk_themes=themes,
        affected_categories=categories,
        description=f"{description} Event: {request.event_description or request.event_title}",
        urgency=urgency,
        scope_matches=[],
        rationale="Fallback candidate generated from event terms, scope, and seed Expert-as-Code domains.",
    )


def _score_scope_relevance(
    candidate: DiscoveredRisk,
    request: RiskDiscoveryRequest,
    samples: dict[str, list[dict[str, str]]],
    rules: list[dict[str, Any]],
) -> DiscoveredRisk:
    score = 35 if request.scope.scope_text else (65 if request.scope.scope_type == "company" else 35)
    matches: list[str] = []
    candidate_text = " ".join(
        [
            candidate.title,
            candidate.risk_type,
            " ".join(candidate.risk_themes),
            " ".join(candidate.affected_categories),
            candidate.description,
        ]
    ).lower()
    scope_interpretation = _interpret_scope(request)
    scope_primary_types = {str(item) for item in scope_interpretation.get("primary_risk_types") or []}
    scope_matched_terms = [str(item) for item in scope_interpretation.get("matched_terms") or []]
    if candidate.risk_type in scope_primary_types:
        score += 35
        matches.append("scope_text:primary")
    scope_term_hits = [term for term in scope_matched_terms if term and term.lower() in candidate_text]
    if scope_term_hits:
        score += min(30, 10 * len(scope_term_hits))
        matches.extend(f"scope_text:{term}" for term in scope_term_hits[:5])
    scope_terms = _scope_terms(request, samples)
    for term in scope_terms:
        if term and term.lower() in candidate_text:
            score += 12
            matches.append(term)
    for rule in rules:
        if not _rule_applies_to_scope(rule, request):
            continue
        rule_id = str(rule.get("rule_id") or rule.get("scope_key") or "scope_rule")
        primary_risk_types = {str(item).lower() for item in rule.get("primary_risk_types") or []}
        if candidate.risk_type.lower() in primary_risk_types:
            score += _to_int(rule.get("score_if_primary"), default=0)
            matches.append(f"{rule_id}:primary")
        match_terms = [str(item).lower() for item in rule.get("match_terms") or []]
        if match_terms and any(term in candidate_text for term in match_terms):
            score += _to_int(rule.get("score_if_term_match"), default=0)
            matches.append(f"{rule_id}:term")
        elif match_terms:
            score += _to_int(rule.get("score_if_no_term_match"), default=0)
    for dataset, rows in samples.items():
        for row in rows:
            row_text = " ".join(str(value) for value in row.values()).lower()
            if request.scope.scope_name and request.scope.scope_name.lower() in row_text:
                score += 10
                matches.append(f"{dataset}:{request.scope.scope_name}")
                break
            if any(marker in row_text for marker in candidate.risk_themes):
                score += 5
                matches.append(f"{dataset}:theme_match")
                break
    score = max(0, min(100, score))
    merged_matches = list(dict.fromkeys([*candidate.scope_matches, *matches]))
    return candidate.model_copy(update={"relevance_score": score, "scope_matches": merged_matches})


def _scope_relevance_rules(state: dict[str, Any]) -> list[dict[str, Any]]:
    expert = state.get("expert") if isinstance(state.get("expert"), dict) else {}
    rules = expert.get("scope_relevance_rules") or []
    return [rule for rule in rules if isinstance(rule, dict)]


def _rule_applies_to_scope(rule: dict[str, Any], request: RiskDiscoveryRequest) -> bool:
    scope_kind = str(rule.get("scope_kind") or "").lower()
    scope_key = str(rule.get("scope_key") or "").lower()
    if not scope_key:
        return False
    haystacks: list[str] = []
    if scope_kind == "department":
        haystacks = [request.scope.department or "", request.scope.scope_name or "", request.scope.scope_text or ""]
    elif scope_kind in {"business_unit", "segment", "scope_name"}:
        haystacks = [request.scope.scope_name or "", request.scope.department or "", request.scope.scope_text or ""]
    elif scope_kind == "industry":
        haystacks = [
            str(request.scope.metadata.get("industry") or ""),
            request.scope.scope_name or "",
            request.scope.department or "",
            request.scope.scope_text or "",
        ]
    elif scope_kind in {"scope_type", "company"}:
        haystacks = [request.scope.scope_type, request.scope.scope_name or "", request.scope.scope_text or ""]
    else:
        haystacks = [
            request.scope.scope_type,
            request.scope.scope_text or "",
            request.scope.scope_name or "",
            request.scope.department or "",
            request.scope.region or "",
            str(request.scope.metadata),
        ]
    return any(scope_key in text.lower() for text in haystacks if text)


def _rejection_for_candidate(
    candidate: DiscoveredRisk,
    request: RiskDiscoveryRequest,
    threshold: int,
) -> RejectedRiskCandidate:
    scope_label = request.scope.scope_name or request.scope.scope_text or request.scope.scope_type
    reason = (
        f"Low relevance to {scope_label} scope: "
        f"score {candidate.relevance_score} below threshold {threshold}."
    )
    if candidate.scope_matches:
        reason += f" Matched signals: {', '.join(candidate.scope_matches[:5])}."
    else:
        reason += " No strong scope-specific signals were found."
    return RejectedRiskCandidate(
        candidate_id=candidate.candidate_id,
        title=candidate.title,
        risk_type=candidate.risk_type,
        relevance_score=candidate.relevance_score,
        reason=reason,
        scope_matches=candidate.scope_matches,
    )


def _to_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_to_event(candidate: DiscoveredRisk, request: RiskDiscoveryRequest) -> RiskEvent:
    scenario_id = _scenario_id(request, candidate)
    return RiskEvent(
        scenario_id=scenario_id,
        client_id=request.scope.client_id,
        title=candidate.title,
        risk_type=candidate.risk_type,
        countries=candidate.countries,
        risk_themes=candidate.risk_themes,
        affected_categories=candidate.affected_categories,
        description=candidate.description,
        event_date=request.event_date or date.today(),
        urgency=candidate.urgency,
    )


def _discovery_questions(candidates: list[DiscoveredRisk], request: RiskDiscoveryRequest) -> list[str]:
    risk_types = {candidate.risk_type for candidate in candidates}
    questions: list[str] = []
    if "payment_disruption" in risk_types:
        questions.extend(
            [
                "Which pending payments are near term and routed through affected bank countries?",
                "Which alternate payment routes are available without increasing sanctions risk?",
            ]
        )
    if "supplier_resilience" in risk_types:
        questions.extend(
            [
                "Which critical suppliers have low inventory runway or no qualified alternative source?",
                "Which logistics lanes or sites need immediate continuity validation?",
            ]
        )
    if "legal_compliance" in risk_types:
        questions.extend(
            [
                "Which contracts include sanctions, force majeure, notice, or termination clauses?",
                "Which counterparties require beneficial ownership or restricted party review?",
            ]
        )
    if "accounting_disclosure" in risk_types:
        questions.extend(
            [
                "Which exposures could become material for impairment, provision, or disclosure?",
                "What evidence package is required for auditor review?",
            ]
        )
    if request.scope.scope_type == "company" or request.scope.department == "Executive" or "executive_resilience" in risk_types:
        questions.extend(
            [
                "Which selected risks require executive cross-functional decision ownership?",
                "Which evidence gaps block immediate mitigation decisions?",
            ]
        )
    return list(dict.fromkeys(questions))


def _discovery_unknowns(candidates: list[DiscoveredRisk], request: RiskDiscoveryRequest) -> list[str]:
    unknowns = ["Validated external evidence is still required before final risk scoring."]
    if any(candidate.risk_type == "payment_disruption" for candidate in candidates):
        unknowns.append("Near-term payment route availability and sanctions-screening ownership are not yet validated.")
    if any(candidate.risk_type == "legal_compliance" for candidate in candidates):
        unknowns.append("Counterparty restricted-party status and contract notice obligations require legal validation.")
    if any(candidate.risk_type == "accounting_disclosure" for candidate in candidates):
        unknowns.append("Materiality and auditor evidence sufficiency require accounting validation.")
    return unknowns


def _scenario_id(request: RiskDiscoveryRequest, candidate: DiscoveredRisk) -> str:
    event_fingerprint = hashlib.sha1(
        f"{request.event_title}|{request.event_description}|{'|'.join(request.countries)}".encode("utf-8")
    ).hexdigest()[:8]
    event_slug = _slug(f"{request.scope.client_id}_{request.event_title}")[:55].strip("_")
    event_slug = f"{event_slug}_{event_fingerprint}" if event_slug else event_fingerprint
    candidate_slug = _slug(candidate.candidate_id or candidate.risk_type)[:24].strip("_")
    return f"scenario_discovered_{event_slug}_{candidate_slug}".strip("_")


def _scope_terms(request: RiskDiscoveryRequest, samples: dict[str, list[dict[str, str]]]) -> list[str]:
    terms = [
        request.scope.client_id,
        request.scope.scope_text or "",
        request.scope.scope_type,
        request.scope.scope_name or "",
        request.scope.department or "",
        request.scope.region or "",
        request.scope.site_id or "",
    ]
    terms.extend(_interpret_scope(request).get("matched_terms") or [])
    if request.scope.scope_name:
        needle = request.scope.scope_name.lower()
        for rows in samples.values():
            for row in rows:
                if needle in " ".join(str(value).lower() for value in row.values()):
                    terms.extend(str(value) for value in row.values() if value)
    return [term for term in dict.fromkeys(str(term).strip() for term in terms) if len(term) >= 3]


def _country_hints(title: str, description: str) -> list[str]:
    text = f"{title} {description}"
    known = ["Iran", "Russia", "China", "Ukraine", "Israel", "Taiwan", "Noveria"]
    return [country for country in known if country.lower() in text.lower()]


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
