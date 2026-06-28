from __future__ import annotations

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
    RiskDiscoveryRequest,
    RiskDiscoveryResult,
    RiskEvent,
)


DISCOVERY_AGENT_NAME = "risk-discovery-agent"
DISCOVERY_DATASET_LIMIT = 25


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
            "Do not perform final scoring or write the Decision Queue."
        )

    def deepagent_tools(self) -> list[Any]:
        @tool("discovery_list_datasets")
        def discovery_list_datasets(client_id: str) -> str:
            """List available structured client datasets for scope filtering."""
            datasets = self.mcp.call("mcp-structured-data", "list_datasets", {"client_id": client_id})
            self._state["datasets"] = datasets
            return json.dumps({"datasets": datasets}, ensure_ascii=False)

        @tool("discovery_sample_dataset")
        def discovery_sample_dataset(client_id: str, dataset: str, limit: int = 10) -> str:
            """Sample a structured client dataset for scope relevance signals."""
            rows = self.mcp.call(
                "mcp-structured-data",
                "sample_rows",
                {"client_id": client_id, "dataset": dataset, "limit": min(limit, DISCOVERY_DATASET_LIMIT)},
            )
            self._state.setdefault("samples", {})[dataset] = rows
            return json.dumps({"dataset": dataset, "row_count": len(rows), "rows": rows[:5]}, ensure_ascii=False)

        @tool("discovery_load_expert_pack")
        def discovery_load_expert_pack() -> str:
            """Load seed Expert-as-Code objects, primitives, cases, questions, and CTA notes."""
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

        @tool("discovery_record_candidates")
        def discovery_record_candidates(candidates_json: str) -> str:
            """Record bounded risk candidates as JSON for structured filtering."""
            data = _json_object_from_text(candidates_json) or {}
            candidates = data.get("candidates") or []
            self._state["raw_candidates"] = candidates if isinstance(candidates, list) else []
            return json.dumps({"candidate_count": len(self._state["raw_candidates"])}, ensure_ascii=False)

        return [
            discovery_list_datasets,
            discovery_sample_dataset,
            discovery_load_expert_pack,
            discovery_record_candidates,
        ]

    def discover(self, request: RiskDiscoveryRequest) -> RiskDiscoveryResult:
        self._state = {
            "request": request.model_dump(mode="json"),
            "datasets": [],
            "samples": {},
            "expert": {},
            "raw_candidates": [],
        }
        self.runner.synthesize(
            "Use discovery tools to inspect client scope and expert knowledge, then record risk candidates. "
            "Return no prose after recording. Candidate schema: "
            "{\"candidates\": [{\"title\": \"...\", \"risk_type\": \"...\", \"risk_themes\": [], "
            "\"affected_categories\": [], \"description\": \"...\", \"urgency\": \"medium\", "
            "\"scope_matches\": [], \"rationale\": \"...\"}]}.\n"
            f"request={json.dumps(request.model_dump(mode='json'), ensure_ascii=False)}",
            max_chars=1200,
        )
        self._ensure_context(request)
        raw_candidates = self._state.get("raw_candidates") or []
        candidates = _normalize_candidates(raw_candidates, request) if raw_candidates else self._fallback_candidates(request)
        selected_candidates, rejected_candidates = self._filter_to_scope(candidates, request)
        selected_candidates = [
            candidate.model_copy(update={"selected_for_analysis": True})
            for candidate in selected_candidates
        ]
        selected_events = [_candidate_to_event(candidate, request) for candidate in selected_candidates]
        selected_event = selected_events[0] if selected_events else None
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
                "expert_counts": {key: len(value) for key, value in (self._state.get("expert") or {}).items()},
                "raw_candidate_count": len(raw_candidates),
                "fallback_used": not bool(raw_candidates),
                "scope_relevance_rule_count": len(_scope_relevance_rules(self._state)),
            },
        )

    def _ensure_context(self, request: RiskDiscoveryRequest) -> None:
        if not self._state.get("datasets"):
            self._state["datasets"] = self.mcp.call("mcp-structured-data", "list_datasets", {"client_id": request.scope.client_id})
        samples = self._state.setdefault("samples", {})
        for dataset in _datasets_for_scope(self._state.get("datasets", [])):
            if dataset not in samples:
                samples[dataset] = self.mcp.call(
                    "mcp-structured-data",
                    "sample_rows",
                    {"client_id": request.scope.client_id, "dataset": dataset, "limit": DISCOVERY_DATASET_LIMIT},
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


def _normalize_candidates(raw_candidates: list[Any], request: RiskDiscoveryRequest) -> list[DiscoveredRisk]:
    candidates: list[DiscoveredRisk] = []
    countries = request.countries or _country_hints(request.event_title, request.event_description)
    for idx, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            continue
        candidate = DiscoveredRisk(
            candidate_id=str(raw.get("candidate_id") or f"DISC-{idx:03d}"),
            title=str(raw.get("title") or f"Discovered risk {idx}"),
            risk_type=str(raw.get("risk_type") or "event_related_risk"),
            countries=[str(item) for item in raw.get("countries") or countries],
            risk_themes=[str(item) for item in raw.get("risk_themes") or []],
            affected_categories=[str(item) for item in raw.get("affected_categories") or []],
            description=str(raw.get("description") or request.event_description or request.event_title),
            urgency=str(raw.get("urgency") or "medium").lower() if str(raw.get("urgency") or "").lower() in {"low", "medium", "high"} else "medium",
            scope_matches=[str(item) for item in raw.get("scope_matches") or []],
            rationale=str(raw.get("rationale") or "Generated by Risk Discovery DeepAgent."),
        )
        candidates.append(candidate)
    return candidates


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
    score = 65 if request.scope.scope_type == "company" else 35
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
        haystacks = [request.scope.department or "", request.scope.scope_name or ""]
    elif scope_kind in {"business_unit", "segment", "scope_name"}:
        haystacks = [request.scope.scope_name or "", request.scope.department or ""]
    elif scope_kind == "industry":
        haystacks = [str(request.scope.metadata.get("industry") or ""), request.scope.scope_name or "", request.scope.department or ""]
    elif scope_kind in {"scope_type", "company"}:
        haystacks = [request.scope.scope_type, request.scope.scope_name or ""]
    else:
        haystacks = [
            request.scope.scope_type,
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
    reason = (
        f"Low relevance to {request.scope.scope_name or request.scope.scope_type} scope: "
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


def _scenario_id(request: RiskDiscoveryRequest, candidate: DiscoveredRisk) -> str:
    base = f"{request.scope.client_id}_{request.event_title}_{candidate.candidate_id}"
    slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return f"scenario_discovered_{slug[:80]}"


def _scope_terms(request: RiskDiscoveryRequest, samples: dict[str, list[dict[str, str]]]) -> list[str]:
    terms = [
        request.scope.client_id,
        request.scope.scope_type,
        request.scope.scope_name or "",
        request.scope.department or "",
        request.scope.region or "",
        request.scope.site_id or "",
    ]
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
