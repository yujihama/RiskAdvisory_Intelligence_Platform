from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from langchain_core.tools import tool

from risk_agent_platform.a2a_http import A2AHttpClient, A2AService, create_a2a_app
from risk_agent_platform.config import Settings
from risk_agent_platform.deepagent_runtime import DeepAgentRunner
from risk_agent_platform.evidence_repository import EvidenceRepository
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.schemas import (
    AgentCard,
    AgentError,
    AgentFinding,
    AgentTask,
    AgentTaskRequest,
    AgentTaskResult,
    AnalysisPlan,
    CounterfactualRecordInput,
    DecisionItem,
    DecisionSynthesisOutput,
    EvidenceItem,
    IssueExplorationRecordInput,
    KnowledgeApplicationFinding,
    PriorityEvidenceItem,
    RedTeamMissingDataInput,
    RedTeamOverclaimsInput,
    RiskEvent,
    SourceQueryPlan,
)
from risk_agent_platform.source_reliability import score_source
from risk_agent_platform.tool_policy import ensure_llm_tool_allowed
from risk_agent_platform.tracing import TraceRecorder


FIXED_AGENT_ORDER = [
    "client-context-agent",
    "source-intelligence-agent",
    "treasury-risk-agent",
    "legal-risk-agent",
    "accounting-risk-agent",
    "procurement-risk-agent",
    "expert-as-code-agent",
    "evidence-redteam-agent",
]
CANONICAL_RISK_AGENT_PLAN = {
    "payment_disruption": {
        "client-context-agent",
        "source-intelligence-agent",
        "treasury-risk-agent",
        "expert-as-code-agent",
        "evidence-redteam-agent",
    },
    "supplier_resilience": {
        "client-context-agent",
        "source-intelligence-agent",
        "procurement-risk-agent",
        "expert-as-code-agent",
        "evidence-redteam-agent",
    },
    "legal_compliance": {
        "client-context-agent",
        "source-intelligence-agent",
        "legal-risk-agent",
        "expert-as-code-agent",
        "evidence-redteam-agent",
    },
    "accounting_disclosure": {
        "client-context-agent",
        "source-intelligence-agent",
        "accounting-risk-agent",
        "expert-as-code-agent",
        "evidence-redteam-agent",
    },
    "executive_resilience": set(FIXED_AGENT_ORDER),
}

SOURCE_MAX_QUERIES = 3
SOURCE_MAX_EXTRACT_URLS = 3
SOURCE_MAX_EVIDENCE = 5


class DomainDeepAgentService(A2AService):
    name = "domain-agent"
    description = "Domain DeepAgent"
    skills: list[str] = []
    modes: list[str] = []

    def __init__(self, settings: Settings, *, embedded_mcp: bool = False) -> None:
        self.settings = settings
        self.mcp = MCPGateway(settings, embedded=embedded_mcp)
        self._deepagent_tool_state: dict[str, Any] = {}
        self.runner = DeepAgentRunner(settings, self.name, self.system_prompt(), tools=self.deepagent_tools())

    def deepagent_tools(self) -> list[Any]:
        return []

    def card(self) -> AgentCard:
        return AgentCard(
            name=self.name,
            description=self.description,
            skills=self.skills,
            modes=self.modes,
        )

    def run_task(self, request: AgentTaskRequest) -> AgentTaskResult:
        started = datetime.now(timezone.utc)
        self.mcp.tracer = TraceRecorder(self.settings, request.task.trace_id)
        self.runner.tracer = TraceRecorder(self.settings, request.task.trace_id)
        try:
            finding = self.analyze(request.task)
            return AgentTaskResult(
                task_id=request.task.task_id,
                parent_task_id=request.task.parent_task_id,
                trace_id=request.task.trace_id,
                agent_name=self.name,
                status="completed",
                finding=finding,
                completed_at=datetime.now(timezone.utc),
                started_at=started,
            )
        except Exception as exc:
            return AgentTaskResult(
                task_id=request.task.task_id,
                parent_task_id=request.task.parent_task_id,
                trace_id=request.task.trace_id,
                agent_name=self.name,
                status="failed",
                error=AgentError(code=exc.__class__.__name__, message=str(exc)),
                completed_at=datetime.now(timezone.utc),
                started_at=started,
            )

    def system_prompt(self) -> str:
        return f"You are {self.name}. Use structured, concise risk analysis."

    def analyze(self, task: AgentTask) -> AgentFinding:
        raise NotImplementedError

    def event(self, task: AgentTask) -> RiskEvent:
        return RiskEvent.model_validate(task.inputs["risk_event"])

    def synthesize(self, prompt: str) -> str:
        return self.runner.synthesize(prompt)

    def explore_issues(self, task: AgentTask, domain: str, context: dict[str, Any]) -> dict[str, Any]:
        event = self.event(task)
        self._deepagent_tool_state["issue_exploration"] = None
        self._deepagent_tool_state["safe_tool_results"] = []
        prompt = (
            "Use the provided issue exploration tool once to record bounded hypotheses. "
            "If you need client structured data, use only the safe summary tools exposed to you; "
            "do not request raw rows, raw identifiers, raw amounts, or raw account data. "
            "Do not make final scores or decisions. Use structured tool arguments with fields: "
            "issues, missing_data, recheck_conditions, exploration_questions.\n"
            f"domain={domain}\n"
            f"risk_event={json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"context={json.dumps(context, ensure_ascii=False, default=str)}"
        )
        synthesis = self.synthesize(prompt)
        recorded = self._deepagent_tool_state.get("issue_exploration")
        if isinstance(recorded, dict):
            recorded["deepagent_tool_invoked"] = True
            recorded["synthesis"] = synthesis
            recorded["safe_tool_results"] = self._deepagent_tool_state.get("safe_tool_results", [])
            return recorded
        return {
            "issues": _default_domain_issues(domain, event),
            "missing_data": [],
            "recheck_conditions": [],
            "exploration_questions": [],
            "deepagent_tool_invoked": False,
            "safe_tool_results": self._deepagent_tool_state.get("safe_tool_results", []),
            "synthesis": synthesis,
        }

    def _call_llm_safe_structured_tool(self, tool_name: str, payload: dict[str, Any]) -> str:
        ensure_llm_tool_allowed(self.name, "mcp-structured-data", tool_name)
        result = self.mcp.call("mcp-structured-data", tool_name, payload)
        self._deepagent_tool_state.setdefault("safe_tool_results", []).append(
            {
                "server": "mcp-structured-data",
                "tool": tool_name,
                "result": result,
            }
        )
        return json.dumps({"tool": tool_name, "result": result}, ensure_ascii=False)

    def _record_issue_exploration(
        self,
        *,
        issues: list[str] | None = None,
        missing_data: list[str] | None = None,
        recheck_conditions: list[str] | None = None,
        exploration_questions: list[str] | None = None,
        issues_json: str | None = None,
    ) -> str:
        record = _issue_exploration_from_tool_input(
            issues=issues,
            missing_data=missing_data,
            recheck_conditions=recheck_conditions,
            exploration_questions=exploration_questions,
            issues_json=issues_json,
        )
        result = {
            "issues": _string_list(record.issues),
            "missing_data": _string_list(record.missing_data),
            "recheck_conditions": _string_list(record.recheck_conditions),
            "exploration_questions": _string_list(record.exploration_questions),
        }
        self._deepagent_tool_state["issue_exploration"] = result
        return json.dumps(result, ensure_ascii=False)


class SourceIntelligenceDeepAgent(DomainDeepAgentService):
    name = "source-intelligence-agent"
    description = "Uses Tavily via MCP to collect external risk evidence."
    skills = ["tavily_search", "evidence_registration", "source_quality"]
    modes = ["source_intelligence"]

    def deepagent_tools(self) -> list[Any]:
        @tool("source_search_authoritative_sources")
        def source_search_authoritative_sources(query: str, max_results: int = 3) -> str:
            """Run one sanitized Tavily search through MCP within the Source Agent query budget."""
            ensure_llm_tool_allowed(self.name, "mcp-web-search", "search_authoritative_sources")
            self._deepagent_tool_state.setdefault("source", {})["deepagent_tool_invoked"] = True
            return json.dumps(self._source_search(query, max_results=max_results), ensure_ascii=False)

        @tool("source_extract_url")
        def source_extract_url(url: str) -> str:
            """Extract one selected URL through Tavily within the Source Agent extraction budget."""
            ensure_llm_tool_allowed(self.name, "mcp-web-search", "extract_url")
            self._deepagent_tool_state.setdefault("source", {})["deepagent_tool_invoked"] = True
            return json.dumps(self._source_extract(url), ensure_ascii=False)

        return [source_search_authoritative_sources, source_extract_url]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        confidential_terms = _confidential_terms_from_findings(task.inputs.get("findings", []))
        self._deepagent_tool_state["source"] = {
            "event": event,
            "confidential_terms": confidential_terms,
            "searches": [],
            "extractions": [],
            "max_queries": SOURCE_MAX_QUERIES,
            "max_extract_urls": SOURCE_MAX_EXTRACT_URLS,
            "max_evidence": SOURCE_MAX_EVIDENCE,
            "deepagent_tool_invoked": False,
        }
        planned_queries = self._plan_queries(event, confidential_terms)
        synthesis = self.synthesize(
            "Use bounded source tools to explore external evidence. "
            f"Run at most {SOURCE_MAX_QUERIES} searches and extract at most {SOURCE_MAX_EXTRACT_URLS} URLs. "
            "Do not register evidence yourself; registration is handled after selection. "
            "Use these planned query themes first, but refine if needed.\n"
            f"planned_queries={json.dumps(planned_queries, ensure_ascii=False)}\n"
            f"risk_event={json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"confidential_terms_count={len(confidential_terms)}"
        )
        state = self._deepagent_tool_state["source"]
        if not state["searches"]:
            for query in planned_queries[:SOURCE_MAX_QUERIES]:
                self._source_search(query, max_results=SOURCE_MAX_EVIDENCE)
        selected_urls = _select_urls_for_extraction(state["searches"], SOURCE_MAX_EXTRACT_URLS)
        if not state["extractions"]:
            for url in selected_urls:
                self._source_extract(url)
        evidence = self._register_selected_evidence(event)
        return AgentFinding(
            agent_name=self.name,
            mode="source_intelligence",
            summary=f"{synthesis} Registered {len(evidence)} bounded Tavily evidence items.",
            confidence="medium",
            evidence_ids=[item["evidence_id"] for item in evidence],
            recommended_actions=["Review authoritative sources and retain query hash for audit."],
            review_required=False,
            rationale="Source Intelligence planned bounded queries, ran sanitized Tavily searches through MCP, extracted selected URLs, and registered EvidenceItems through Evidence Ledger.",
            metadata={
                "queries": [{"query": item.get("query"), "query_hash": item.get("query_hash")} for item in state["searches"]],
                "extracted_urls": [item.get("url") for item in state["extractions"]],
                "deepagent_tool_invoked": bool(state.get("deepagent_tool_invoked")),
                "confidential_terms_count": len(confidential_terms),
                "limits": {
                    "max_queries": SOURCE_MAX_QUERIES,
                    "max_extract_urls": SOURCE_MAX_EXTRACT_URLS,
                    "max_evidence": SOURCE_MAX_EVIDENCE,
                },
            },
        )

    def _plan_queries(self, event: RiskEvent, confidential_terms: list[str]) -> list[str]:
        prompt = (
            "Return bounded external source query planning. "
            f"Use at most {SOURCE_MAX_QUERIES} query strings. Avoid client-specific names. "
            f"risk_event={json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"confidential_terms_count={len(confidential_terms)}"
        )
        try:
            plan = self.runner.synthesize_structured(prompt, SourceQueryPlan, max_chars=2000)
            queries = _string_list(plan.queries, limit=SOURCE_MAX_QUERIES)
            if queries:
                return queries
        except Exception:
            pass
        country = " ".join(event.countries) if event.countries else "affected country"
        themes = " ".join(event.risk_themes or [event.risk_type])
        return [
            f"{country} {themes} official regulatory update",
            f"{country} payment disruption sanctions banking official source",
            f"{country} supplier continuity logistics disruption authoritative source",
        ][:SOURCE_MAX_QUERIES]

    def _source_search(self, query: str, *, max_results: int = 3) -> dict[str, Any]:
        state = self._deepagent_tool_state.get("source") or {}
        searches = state.setdefault("searches", [])
        if len(searches) >= SOURCE_MAX_QUERIES:
            return {"status": "skipped", "reason": "max_queries_reached"}
        event = state.get("event")
        if not isinstance(event, RiskEvent):
            return {"status": "skipped", "reason": "source_state_not_initialized"}
        result = self.mcp.call(
            "mcp-web-search",
            "search_authoritative_sources",
            {
                "query": query,
                "risk_event": event.model_dump(mode="json"),
                "max_results": min(max_results, SOURCE_MAX_EVIDENCE),
                "confidential_terms": state.get("confidential_terms") or [],
            },
        )
        searches.append(result)
        return {
            "status": "searched",
            "query": result.get("query"),
            "query_hash": result.get("query_hash"),
            "result_count": len(result.get("results", [])),
        }

    def _source_extract(self, url: str) -> dict[str, Any]:
        state = self._deepagent_tool_state.get("source") or {}
        extractions = state.setdefault("extractions", [])
        if len(extractions) >= SOURCE_MAX_EXTRACT_URLS:
            return {"status": "skipped", "reason": "max_extract_urls_reached", "url": url}
        try:
            result = self.mcp.call("mcp-web-search", "extract_url", {"url": url})
            item = {"status": "extracted", "url": url, "result": result}
        except Exception as exc:
            item = {"status": "extract_failed", "url": url, "error": str(exc)}
        extractions.append(item)
        return {"status": item["status"], "url": url}

    def _register_selected_evidence(self, event: RiskEvent) -> list[dict[str, Any]]:
        state = self._deepagent_tool_state["source"]
        candidates = _rank_source_candidates(state["searches"], event)
        extracted_text_by_url = _extracted_text_by_url(state["extractions"])
        registered: list[dict[str, Any]] = []
        for idx, candidate in enumerate(candidates[:SOURCE_MAX_EVIDENCE], start=1):
            result = candidate["result"]
            url = str(result.get("url") or "")
            domain = urlparse(url).netloc
            source_score = score_source(result, event)
            extracted_text = extracted_text_by_url.get(url)
            summary = _clean_evidence_text(extracted_text or result.get("content") or result.get("raw_content") or "")
            evidence = EvidenceItem(
                evidence_id=f"{event.scenario_id}_tavily_{idx:03d}",
                scenario_id=event.scenario_id,
                client_id=event.client_id,
                source_type="web",
                source_ref=url or f"tavily:{idx}",
                source_url=url or None,
                source_title=_clean_evidence_text(result.get("title") or ""),
                source_domain=str(source_score.get("source_domain") or domain or "") or None,
                search_query_hash=str(candidate.get("query_hash") or ""),
                summary=summary,
                raw_snippet=_clean_evidence_text(result.get("content") or ""),
                supports=[event.risk_type, *event.risk_themes],
                reliability=source_score["reliability"],
                client_relevance=source_score["client_relevance"],
                used_by_agents=[self.name],
                confidence=source_score["confidence"],
                extraction_method="tavily_extract" if extracted_text else "tavily_search",
            )
            registered_item = self._register_evidence(evidence)
            registered.append(registered_item)
        return registered

    def _register_evidence(self, evidence: EvidenceItem) -> dict[str, Any]:
        try:
            return EvidenceRepository(self.settings).register(
                evidence,
                index_qdrant=False,
                index_neo4j=False,
            ).model_dump(mode="json")
        except Exception:
            pass
        try:
            return self.mcp.call(
                "mcp-evidence-ledger",
                "register_evidence_json",
                {"evidence_json": evidence.model_dump_json()},
            )
        except Exception:
            sanitized = evidence.model_copy(
                update={
                    "source_title": _clean_evidence_text(evidence.source_title or ""),
                    "summary": _clean_evidence_text(evidence.summary),
                    "raw_snippet": _clean_evidence_text(evidence.raw_snippet),
                }
            )
            return self.mcp.call(
                "mcp-evidence-ledger",
                "register_evidence_json",
                {"evidence_json": sanitized.model_dump_json()},
            )


class ClientContextDeepAgent(DomainDeepAgentService):
    name = "client-context-agent"
    description = "Builds Client Asset Graph through structured-data and Neo4j MCP tools."
    skills = ["client_asset_graph", "source_backed_context", "unknown_register"]
    modes = ["client_context"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        datasets = self.mcp.call("mcp-structured-data", "list_datasets", {"client_id": event.client_id})
        suppliers = self.mcp.call("mcp-structured-data", "sample_rows", {"client_id": event.client_id, "dataset": "suppliers", "limit": 100})
        sites = self.mcp.call("mcp-structured-data", "sample_rows", {"client_id": event.client_id, "dataset": "sites", "limit": 100}) if "sites" in datasets else []
        contracts = self.mcp.call("mcp-structured-data", "sample_rows", {"client_id": event.client_id, "dataset": "contracts", "limit": 100}) if "contracts" in datasets else []
        customers = self.mcp.call("mcp-structured-data", "sample_rows", {"client_id": event.client_id, "dataset": "customers", "limit": 100}) if "customers" in datasets else []
        confidential_terms = _confidential_terms_from_rows([*suppliers, *sites, *contracts, *customers])
        self.mcp.call("mcp-neo4j", "upsert_asset", {"label": "Client", "asset_id": event.client_id, "properties": {"name": event.client_id}})
        self.mcp.call("mcp-neo4j", "upsert_asset", {"label": "RiskScenario", "asset_id": event.scenario_id, "properties": event.model_dump(mode="json")})
        affected = []
        for row in suppliers:
            supplier_id = row["supplier_id"]
            self.mcp.call("mcp-neo4j", "upsert_asset", {"label": "Supplier", "asset_id": supplier_id, "properties": row | {"confidence_level": "source_backed"}})
            self.mcp.call("mcp-neo4j", "upsert_relation", {"source_id": event.scenario_id, "target_id": supplier_id, "relation_type": "AFFECTS", "properties": {"confidence_level": "derived"}})
            if row.get("country") in event.countries or row.get("criticality") == "high":
                affected.append(supplier_id)
        return AgentFinding(
            agent_name=self.name,
            mode="client_context",
            summary=f"Registered RiskScenario and {len(suppliers)} suppliers in Neo4j; affected candidates: {len(affected)}.",
            confidence="medium",
            unknowns=["Sub-tier suppliers remain unknown until additional data is supplied."],
            recommended_actions=["Validate supplier criticality and sub-tier dependencies."],
            review_required=True,
            rationale="Client context is source-backed from structured data and relationship-backed in Neo4j.",
            metadata={
                "datasets": datasets,
                "affected_supplier_ids": affected,
                "confidential_terms": confidential_terms,
            },
        )


class TreasuryRiskDeepAgent(DomainDeepAgentService):
    name = "treasury-risk-agent"
    description = "Analyzes payment disruption, cash mobility, and liquidity-at-risk."
    skills = ["payment_exposure", "cash_mobility", "liquidity_at_risk"]
    modes = ["treasury"]

    def deepagent_tools(self) -> list[Any]:
        @tool("treasury_summarize_payment_exposure_safe")
        def treasury_summarize_payment_exposure_safe(client_id: str, country: str = "") -> str:
            """Summarize payment exposure for Treasury issue exploration without raw rows or raw amounts."""
            payload: dict[str, Any] = {"client_id": client_id}
            if country:
                payload["country"] = country
            return self._call_llm_safe_structured_tool("summarize_payment_exposure_safe", payload)

        @tool("record_treasury_issue_exploration", args_schema=IssueExplorationRecordInput)
        def record_treasury_issue_exploration(
            issues: list[str] | None = None,
            missing_data: list[str] | None = None,
            recheck_conditions: list[str] | None = None,
            exploration_questions: list[str] | None = None,
            issues_json: str | None = None,
        ) -> str:
            """Record bounded Treasury hypotheses and missing data; do not score or decide."""
            return self._record_issue_exploration(
                issues=issues,
                missing_data=missing_data,
                recheck_conditions=recheck_conditions,
                exploration_questions=exploration_questions,
                issues_json=issues_json,
            )

        return [treasury_summarize_payment_exposure_safe, record_treasury_issue_exploration]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        exposure = self.mcp.call("mcp-structured-data", "summarize_payment_exposure", {"client_id": event.client_id, "country": event.countries[0] if event.countries else None})
        safe_exposure = self.mcp.call("mcp-structured-data", "summarize_payment_exposure_safe", {"client_id": event.client_id, "country": event.countries[0] if event.countries else None})
        evidence = self.mcp.call("mcp-qdrant", "search_evidence", {"query": event.title, "filters": {"scenario_id": event.scenario_id}, "top_k": 5})
        issue_exploration = self.explore_issues(task, "treasury", {"payment_exposure_safe": safe_exposure, "evidence_hit_count": len(evidence)})
        score = min(100, 40 + int(float(exposure.get("total_amount", 0)) / 100000))
        return AgentFinding(
            agent_name=self.name,
            mode="treasury",
            summary=f"Payment exposure count={exposure.get('payment_count')} amount={exposure.get('total_amount')}.",
            risk_score=score,
            confidence="medium",
            evidence_ids=[item.get("payload", {}).get("evidence_id") for item in evidence if item.get("payload", {}).get("evidence_id")],
            assumptions=["Pending payments are used as near-term liquidity exposure until bank confirmations arrive."],
            unknowns=["Correspondent bank status and sanctions screening result must be confirmed."],
            recommended_actions=["Prepare controlled CFO/Legal/Procurement decision on payment continuation or hold."],
            review_required=True,
            rationale="Treasury analysis uses structured payment exposure and Qdrant evidence search through MCP.",
            metadata={"payment_exposure": exposure, "payment_exposure_safe": safe_exposure, "qdrant_hits": evidence, "issue_exploration": issue_exploration},
        )


class LegalRiskDeepAgent(DomainDeepAgentService):
    name = "legal-risk-agent"
    description = "Analyzes sanctions, contract obligations, notices, and legal guardrails."
    skills = ["sanctions_proximity", "contract_obligation", "regulatory_trigger"]
    modes = ["legal"]

    def deepagent_tools(self) -> list[Any]:
        @tool("legal_summarize_contract_exposure_safe")
        def legal_summarize_contract_exposure_safe(client_id: str) -> str:
            """Summarize contract exposure for Legal issue exploration without raw contract rows."""
            return self._call_llm_safe_structured_tool("summarize_contract_exposure_safe", {"client_id": client_id})

        @tool("record_legal_issue_exploration", args_schema=IssueExplorationRecordInput)
        def record_legal_issue_exploration(
            issues: list[str] | None = None,
            missing_data: list[str] | None = None,
            recheck_conditions: list[str] | None = None,
            exploration_questions: list[str] | None = None,
            issues_json: str | None = None,
        ) -> str:
            """Record bounded Legal hypotheses and missing data; do not score or decide."""
            return self._record_issue_exploration(
                issues=issues,
                missing_data=missing_data,
                recheck_conditions=recheck_conditions,
                exploration_questions=exploration_questions,
                issues_json=issues_json,
            )

        return [legal_summarize_contract_exposure_safe, record_legal_issue_exploration]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        contracts = self.mcp.call("mcp-structured-data", "sample_rows", {"client_id": event.client_id, "dataset": "contracts", "limit": 100})
        issues = [row["contract_id"] for row in contracts if row.get("sanctions_clause") == "true" or row.get("force_majeure_clause") == "true"]
        safe_contracts = self.mcp.call("mcp-structured-data", "summarize_contract_exposure_safe", {"client_id": event.client_id})
        issue_exploration = self.explore_issues(task, "legal", {"contract_exposure_safe": safe_contracts, "contract_issue_count": len(issues)})
        return AgentFinding(
            agent_name=self.name,
            mode="legal",
            summary=f"Legal review found {len(issues)} contracts with sanctions or force majeure clauses.",
            risk_score=min(100, 35 + len(issues) * 20),
            confidence="medium" if contracts else "low",
            unknowns=["Beneficial ownership and current sanctions list match require confirmation."],
            recommended_actions=["Review notice, termination, sanctions, and force majeure clauses before payment decision."],
            review_required=bool(issues),
            rationale="Legal Agent is separated from Accounting and uses structured contract data via MCP.",
            metadata={"contract_issue_ids": issues, "contract_exposure_safe": safe_contracts, "issue_exploration": issue_exploration},
        )


class AccountingRiskDeepAgent(DomainDeepAgentService):
    name = "accounting-risk-agent"
    description = "Analyzes provision, impairment, subsequent event, and disclosure pressure."
    skills = ["provision_trigger", "impairment_trigger", "disclosure_pressure"]
    modes = ["accounting"]

    def deepagent_tools(self) -> list[Any]:
        @tool("accounting_summarize_payment_exposure_safe")
        def accounting_summarize_payment_exposure_safe(client_id: str) -> str:
            """Summarize payment exposure for Accounting issue exploration without raw rows or raw amounts."""
            return self._call_llm_safe_structured_tool("summarize_payment_exposure_safe", {"client_id": client_id})

        @tool("accounting_summarize_invoice_exposure_safe")
        def accounting_summarize_invoice_exposure_safe(client_id: str) -> str:
            """Summarize invoice exposure for Accounting issue exploration without raw rows or raw amounts."""
            return self._call_llm_safe_structured_tool("summarize_invoice_exposure_safe", {"client_id": client_id})

        @tool("record_accounting_issue_exploration", args_schema=IssueExplorationRecordInput)
        def record_accounting_issue_exploration(
            issues: list[str] | None = None,
            missing_data: list[str] | None = None,
            recheck_conditions: list[str] | None = None,
            exploration_questions: list[str] | None = None,
            issues_json: str | None = None,
        ) -> str:
            """Record bounded Accounting hypotheses and missing data; do not score or decide."""
            return self._record_issue_exploration(
                issues=issues,
                missing_data=missing_data,
                recheck_conditions=recheck_conditions,
                exploration_questions=exploration_questions,
                issues_json=issues_json,
            )

        return [
            accounting_summarize_payment_exposure_safe,
            accounting_summarize_invoice_exposure_safe,
            record_accounting_issue_exploration,
        ]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        exposure = self.mcp.call("mcp-structured-data", "summarize_payment_exposure", {"client_id": event.client_id})
        safe_exposure = self.mcp.call("mcp-structured-data", "summarize_payment_exposure_safe", {"client_id": event.client_id})
        amount = float(exposure.get("total_amount", 0))
        issue_exploration = self.explore_issues(task, "accounting", {"payment_exposure_safe": safe_exposure})
        score = min(100, 25 + int(amount / 100000))
        return AgentFinding(
            agent_name=self.name,
            mode="accounting",
            summary=f"Accounting triage found payment exposure of {amount:,.0f} for provision/disclosure review.",
            risk_score=score,
            confidence="medium",
            unknowns=["Materiality threshold and auditor view are not yet confirmed."],
            recommended_actions=["Prepare auditor evidence pack if disruption becomes probable."],
            review_required=score >= 50,
            rationale="Accounting Agent is separate and maps operational/payment disruption to reporting pressure.",
            metadata={"payment_exposure": exposure, "payment_exposure_safe": safe_exposure, "issue_exploration": issue_exploration},
        )


class ProcurementRiskDeepAgent(DomainDeepAgentService):
    name = "procurement-risk-agent"
    description = "Analyzes supplier resilience, inventory runway, and alternative sourcing."
    skills = ["supplier_resilience", "inventory_runway", "alternative_sourcing"]
    modes = ["procurement"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        suppliers = self.mcp.call("mcp-structured-data", "summarize_supplier_exposure", {"client_id": event.client_id, "country": event.countries[0] if event.countries else None})
        critical = suppliers.get("critical_count", 0)
        return AgentFinding(
            agent_name=self.name,
            mode="procurement",
            summary=f"Procurement exposure includes {critical} critical suppliers in the target country filter.",
            risk_score=min(100, 30 + int(critical) * 25),
            confidence="medium",
            unknowns=["Alternative qualification status must be validated with procurement owner."],
            recommended_actions=["Start alternative sourcing and inventory runway validation."],
            review_required=critical > 0,
            rationale="Procurement Agent uses supplier exposure MCP tools and remains separate from Treasury.",
            metadata={"supplier_exposure": suppliers},
        )


class ExpertAsCodeDeepAgent(DomainDeepAgentService):
    name = "expert-as-code-agent"
    description = "Applies structured expert knowledge objects, red flags, rubrics, and guardrails."
    skills = ["expert_knowledge", "red_flag", "rubric", "language_guardrail"]
    modes = ["expert_as_code"]

    def deepagent_tools(self) -> list[Any]:
        @tool("expert_search_similar_cases")
        def expert_search_similar_cases(case_description: str, mode: str = "", top_k: int = 5) -> str:
            """Search similar Expert-as-Code cases through MCP."""
            ensure_llm_tool_allowed(self.name, "mcp-expert-knowledge", "search_similar_cases")
            self._deepagent_tool_state.setdefault("expert", {})["deepagent_tool_invoked"] = True
            result = self.mcp.call(
                "mcp-expert-knowledge",
                "search_similar_cases",
                {"case_description": case_description, "mode": mode or None, "top_k": min(top_k, 5)},
            )
            self._deepagent_tool_state.setdefault("expert", {}).setdefault("similar_cases", []).extend(result)
            return json.dumps({"case_count": len(result), "case_ids": _document_ids(result)}, ensure_ascii=False)

        @tool("expert_search_rubrics")
        def expert_search_rubrics(query: str, domain: str = "", top_k: int = 10) -> str:
            """Search rubrics, guardrails, review triggers, and evidence standards through MCP."""
            ensure_llm_tool_allowed(self.name, "mcp-expert-knowledge", "search_knowledge_objects")
            self._deepagent_tool_state.setdefault("expert", {})["deepagent_tool_invoked"] = True
            result = self.mcp.call(
                "mcp-expert-knowledge",
                "search_knowledge_objects",
                {"query": query, "domain": domain or None, "top_k": min(top_k, 10)},
            )
            self._deepagent_tool_state.setdefault("expert", {}).setdefault("rubrics", []).extend(result)
            return json.dumps({"object_count": len(result), "object_ids": _document_ids(result)}, ensure_ascii=False)

        @tool("expert_load_red_flags")
        def expert_load_red_flags(domain: str = "") -> str:
            """Load red-flag-like expert knowledge objects through MCP."""
            ensure_llm_tool_allowed(self.name, "mcp-expert-knowledge", "load_knowledge_pack")
            self._deepagent_tool_state.setdefault("expert", {})["deepagent_tool_invoked"] = True
            objects = self.mcp.call("mcp-expert-knowledge", "load_knowledge_pack", {})
            selected = [
                item
                for item in objects
                if (not domain or item.get("domain") in {domain, "cross_functional"})
                and item.get("object_type") in {"red_flag", "review_trigger", "evidence_standard"}
            ]
            self._deepagent_tool_state.setdefault("expert", {}).setdefault("red_flags", []).extend(selected)
            return json.dumps({"red_flag_count": len(selected), "red_flags": [item.get("title") for item in selected]}, ensure_ascii=False)

        @tool("expert_load_cta_notes")
        def expert_load_cta_notes(case_id: str = "") -> str:
            """Load CTA notes and optionally filter by case id."""
            ensure_llm_tool_allowed(self.name, "mcp-expert-knowledge", "load_cta_notes")
            self._deepagent_tool_state.setdefault("expert", {})["deepagent_tool_invoked"] = True
            notes = self.mcp.call("mcp-expert-knowledge", "load_cta_notes", {})
            selected = [item for item in notes if not case_id or item.get("case_id") == case_id]
            self._deepagent_tool_state.setdefault("expert", {}).setdefault("cta_notes", []).extend(selected)
            return json.dumps({"cta_note_count": len(selected), "note_ids": [item.get("note_id") for item in selected]}, ensure_ascii=False)

        @tool("expert_record_counterfactuals", args_schema=CounterfactualRecordInput)
        def expert_record_counterfactuals(
            counterfactuals: list[str] | None = None,
            counterfactuals_json: str | None = None,
        ) -> str:
            """Record bounded counterfactuals selected by the Expert-as-Code Agent."""
            self._deepagent_tool_state.setdefault("expert", {})["deepagent_tool_invoked"] = True
            record = _counterfactuals_from_tool_input(
                counterfactuals=counterfactuals,
                counterfactuals_json=counterfactuals_json,
            )
            recorded = _string_list(record.counterfactuals)
            self._deepagent_tool_state.setdefault("expert", {})["counterfactuals"] = recorded
            return json.dumps({"counterfactual_count": len(recorded)}, ensure_ascii=False)

        return [
            expert_search_similar_cases,
            expert_search_rubrics,
            expert_load_red_flags,
            expert_load_cta_notes,
            expert_record_counterfactuals,
        ]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        self._deepagent_tool_state["expert"] = {}
        indexed = self.mcp.call("mcp-expert-knowledge", "index_knowledge_pack", {})
        indexed_cases = self.mcp.call("mcp-expert-knowledge", "index_case_bank", {})
        questions = self.mcp.call("mcp-expert-knowledge", "load_question_bank", {})
        state = self._deepagent_tool_state["expert"]
        state["similar_cases"] = self.mcp.call(
            "mcp-expert-knowledge",
            "search_similar_cases",
            {"case_description": f"{event.title}\n{event.description}", "top_k": 5},
        )
        state["rubrics"] = self.mcp.call(
            "mcp-expert-knowledge",
            "search_knowledge_objects",
            {"query": " ".join([event.title, event.risk_type, *event.risk_themes]), "top_k": 10},
        )
        objects = self.mcp.call("mcp-expert-knowledge", "load_knowledge_pack", {})
        event_text = " ".join([event.title, event.risk_type, *event.risk_themes, *event.affected_categories]).lower()
        state["red_flags"] = [
            item
            for item in objects
            if item.get("object_type") in {"red_flag", "review_trigger", "evidence_standard"}
            and _knowledge_object_relevant(item, event_text)
        ]
        if not state["red_flags"]:
            state["red_flags"] = [
                item
                for item in objects
                if item.get("object_type") in {"red_flag", "review_trigger", "evidence_standard"}
            ]
        state["cta_notes"] = self.mcp.call("mcp-expert-knowledge", "load_cta_notes", {})
        state["counterfactuals"] = _default_counterfactuals(event)
        hits = state["rubrics"]
        case_hits = state["similar_cases"]
        cta_notes = state["cta_notes"]
        object_ids = _document_ids(hits)
        case_ids = _document_ids(case_hits)
        cta_note_ids = [str(item.get("note_id")) for item in cta_notes if item.get("note_id")]
        knowledge_application = KnowledgeApplicationFinding(
            similar_case_ids=case_ids,
            rubric_ids=object_ids,
            red_flags=[str(item.get("title") or item.get("description") or item) for item in state["red_flags"]],
            cta_note_ids=cta_note_ids,
            cta_notes=[str(item.get("interpretation") or item.get("cue") or item) for item in cta_notes],
            counterfactuals=_string_list(state.get("counterfactuals")),
            recommended_guardrails=_recommended_guardrails_from_knowledge(hits),
            additional_questions=[item.get("question") for item in questions if item.get("question")],
            review_required=True,
            rationale="Expert-as-Code selected bounded comparable cases, rubrics, red flags, CTA notes, and counterfactual checks.",
        )
        return AgentFinding(
            agent_name=self.name,
            mode="expert_as_code",
            summary=f"Indexed expert knowledge and case bank; retrieved {len(hits)} objects and {len(case_hits)} similar cases.",
            confidence="medium",
            recommended_actions=["Apply payment action language guardrails and joint review triggers."],
            review_required=True,
            rationale="Expert-as-Code uses structured Knowledge Objects and case bank entries indexed into Qdrant via MCP.",
            metadata={
                "indexed": indexed,
                "indexed_cases": indexed_cases,
                "knowledge_object_ids": object_ids,
                "case_ids": case_ids,
                "question_count": len(questions),
                "cta_note_count": len(cta_notes),
                "hits": hits,
                "case_hits": case_hits,
                "deepagent_tool_invoked": bool(state.get("deepagent_tool_invoked")),
                "knowledge_application_finding": knowledge_application.model_dump(mode="json"),
            },
        )


class EvidenceRedTeamDeepAgent(DomainDeepAgentService):
    name = "evidence-redteam-agent"
    description = "Challenges evidence quality, overclaiming, and missing data."
    skills = ["red_team", "counter_evidence", "evidence_quality"]
    modes = ["evidence_red_team"]

    def deepagent_tools(self) -> list[Any]:
        @tool("redteam_list_scenario_evidence")
        def redteam_list_scenario_evidence(scenario_id: str) -> str:
            """List scenario evidence from Evidence Ledger for challenge review."""
            ensure_llm_tool_allowed(self.name, "mcp-evidence-ledger", "list_evidence_by_scenario")
            self._deepagent_tool_state.setdefault("redteam", {})["deepagent_tool_invoked"] = True
            result = self.mcp.call("mcp-evidence-ledger", "list_evidence_by_scenario", {"scenario_id": scenario_id})
            self._deepagent_tool_state.setdefault("redteam", {})["evidence"] = result
            return json.dumps({"evidence_count": len(result), "evidence_ids": [item.get("evidence_id") for item in result]}, ensure_ascii=False)

        @tool("redteam_search_evidence")
        def redteam_search_evidence(query: str, scenario_id: str, top_k: int = 5) -> str:
            """Search scenario evidence for support strength."""
            ensure_llm_tool_allowed(self.name, "mcp-evidence-ledger", "search_evidence")
            self._deepagent_tool_state.setdefault("redteam", {})["deepagent_tool_invoked"] = True
            result = self.mcp.call("mcp-evidence-ledger", "search_evidence", {"query": query, "scenario_id": scenario_id, "top_k": min(top_k, 5)})
            self._deepagent_tool_state.setdefault("redteam", {}).setdefault("evidence_searches", []).append({"query": query, "results": result})
            return json.dumps({"result_count": len(result)}, ensure_ascii=False)

        @tool("redteam_search_contradictions")
        def redteam_search_contradictions(query: str, scenario_id: str, top_k: int = 5) -> str:
            """Search for contradiction candidates in the scenario evidence index."""
            ensure_llm_tool_allowed(self.name, "mcp-evidence-ledger", "search_evidence")
            self._deepagent_tool_state.setdefault("redteam", {})["deepagent_tool_invoked"] = True
            result = self.mcp.call(
                "mcp-evidence-ledger",
                "search_evidence",
                {"query": f"contradiction alternative view {query}", "scenario_id": scenario_id, "top_k": min(top_k, 5)},
            )
            self._deepagent_tool_state.setdefault("redteam", {}).setdefault("contradiction_searches", []).append({"query": query, "results": result})
            return json.dumps({"candidate_count": len(result)}, ensure_ascii=False)

        @tool("redteam_find_risk_paths")
        def redteam_find_risk_paths(scenario_id: str, max_depth: int = 4) -> str:
            """Read bounded graph risk paths for challenge review without mutating the graph."""
            ensure_llm_tool_allowed(self.name, "mcp-neo4j", "find_risk_paths")
            self._deepagent_tool_state.setdefault("redteam", {})["deepagent_tool_invoked"] = True
            result = self.mcp.call("mcp-neo4j", "find_risk_paths", {"scenario_id": scenario_id, "max_depth": min(max_depth, 4)})
            self._deepagent_tool_state.setdefault("redteam", {})["risk_paths"] = result
            return json.dumps({"path_count": len(result)}, ensure_ascii=False)

        @tool("redteam_summarize_payment_exposure_safe")
        def redteam_summarize_payment_exposure_safe(client_id: str, country: str = "") -> str:
            """Read LLM-safe payment exposure for missing-data and overclaim checks."""
            payload: dict[str, Any] = {"client_id": client_id}
            if country:
                payload["country"] = country
            return self._call_llm_safe_structured_tool("summarize_payment_exposure_safe", payload)

        @tool("redteam_summarize_supplier_exposure_safe")
        def redteam_summarize_supplier_exposure_safe(client_id: str, country: str = "") -> str:
            """Read LLM-safe supplier exposure for missing-data and overclaim checks."""
            payload: dict[str, Any] = {"client_id": client_id}
            if country:
                payload["country"] = country
            return self._call_llm_safe_structured_tool("summarize_supplier_exposure_safe", payload)

        @tool("redteam_summarize_contract_exposure_safe")
        def redteam_summarize_contract_exposure_safe(client_id: str) -> str:
            """Read LLM-safe contract exposure for missing-data and overclaim checks."""
            return self._call_llm_safe_structured_tool("summarize_contract_exposure_safe", {"client_id": client_id})

        @tool("redteam_record_missing_data", args_schema=RedTeamMissingDataInput)
        def redteam_record_missing_data(
            missing_data: list[str] | None = None,
            missing_data_json: str | None = None,
        ) -> str:
            """Record missing data detected by Red Team without writing decisions."""
            self._deepagent_tool_state.setdefault("redteam", {})["deepagent_tool_invoked"] = True
            record = _redteam_missing_data_from_tool_input(
                missing_data=missing_data,
                missing_data_json=missing_data_json,
            )
            recorded = _string_list(record.missing_data)
            self._deepagent_tool_state.setdefault("redteam", {})["missing_data"] = recorded
            return json.dumps({"missing_data_count": len(recorded)}, ensure_ascii=False)

        @tool("redteam_record_overclaims", args_schema=RedTeamOverclaimsInput)
        def redteam_record_overclaims(
            overclaims: list[str] | None = None,
            overclaims_json: str | None = None,
        ) -> str:
            """Record overclaim warnings detected by Red Team without writing decisions."""
            self._deepagent_tool_state.setdefault("redteam", {})["deepagent_tool_invoked"] = True
            record = _redteam_overclaims_from_tool_input(
                overclaims=overclaims,
                overclaims_json=overclaims_json,
            )
            recorded = _string_list(record.overclaims)
            self._deepagent_tool_state.setdefault("redteam", {})["overclaims"] = recorded
            return json.dumps({"overclaim_count": len(recorded)}, ensure_ascii=False)

        return [
            redteam_list_scenario_evidence,
            redteam_search_evidence,
            redteam_search_contradictions,
            redteam_find_risk_paths,
            redteam_summarize_payment_exposure_safe,
            redteam_summarize_supplier_exposure_safe,
            redteam_summarize_contract_exposure_safe,
            redteam_record_missing_data,
            redteam_record_overclaims,
        ]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        self._deepagent_tool_state["redteam"] = {}
        prior = task.inputs.get("findings", [])
        self.synthesize(
            "Use Red Team tools to search evidence, search contradiction candidates, record missing data, "
            "and record overclaim warnings. Do not write or modify the Decision Queue.\n"
            f"scenario_id={event.scenario_id}\n"
            f"risk_event={json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"prior_findings={json.dumps(prior, ensure_ascii=False, default=str)}"
        )
        state = self._deepagent_tool_state["redteam"]
        evidence = state.get("evidence")
        if evidence is None:
            evidence = self.mcp.call("mcp-evidence-ledger", "list_evidence_by_scenario", {"scenario_id": event.scenario_id})
        if not state.get("contradiction_searches"):
            state["contradiction_searches"] = [
                {
                    "query": event.title,
                    "results": self.mcp.call(
                        "mcp-evidence-ledger",
                        "search_evidence",
                        {"query": f"contradiction alternative view {event.title}", "scenario_id": event.scenario_id, "top_k": 5},
                    ),
                }
            ]
        missing_data = state.get("missing_data") or _redteam_missing_data(event, evidence)
        overclaims = state.get("overclaims") or _redteam_overclaims(prior, evidence)
        unknowns = list(missing_data)
        if len(evidence) < 2:
            unknowns.append("External evidence base is thin; avoid high confidence.")
        return AgentFinding(
            agent_name=self.name,
            mode="evidence_red_team",
            summary=f"Red team reviewed {len(evidence)} evidence items.",
            confidence="medium" if evidence else "low",
            unknowns=unknowns,
            recommended_actions=["Separate facts, assumptions, and inferred risk paths in the final output."],
            review_required=bool(unknowns or overclaims),
            rationale="Evidence / Red Team Agent reads Evidence Ledger through MCP and challenges confidence.",
            metadata={
                "evidence_count": len(evidence),
                "contradiction_searches": state.get("contradiction_searches", []),
                "missing_data": missing_data,
                "overclaims": overclaims,
                "deepagent_tool_invoked": bool(state.get("deepagent_tool_invoked")),
                "decision_queue_written": False,
            },
        )


class DecisionSynthesisDeepAgent(DomainDeepAgentService):
    name = "decision-synthesis-agent"
    description = "Generates Decision Queue, Executive Brief, Evidence Summary, and review requests."
    skills = ["decision_queue", "executive_brief", "evidence_summary"]
    modes = ["decision_synthesis"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        prior = task.inputs.get("findings", [])
        evidence = self.mcp.call("mcp-evidence-ledger", "list_evidence_by_scenario", {"scenario_id": event.scenario_id})
        knowledge_ids = _knowledge_ids_from_findings(prior)
        draft_decision_id = f"{event.scenario_id}_decision_001"
        decision = _decision_for_event(event, draft_decision_id, evidence, knowledge_ids, self.runner, prior)
        decision_id = _decision_id_for_content(event, decision)
        decision = decision.model_copy(update={"decision_id": decision_id})
        self.mcp.call(
            "mcp-neo4j",
            "upsert_asset",
            {
                "label": "Decision",
                "asset_id": decision_id,
                "properties": _neo4j_decision_properties(decision) | {"confidence_level": "derived", "source_type": "derived"},
            },
        )
        self.mcp.call("mcp-neo4j", "attach_decision_to_scenario", {"scenario_id": event.scenario_id, "decision_id": decision_id})
        for item in evidence:
            self.mcp.call("mcp-evidence-ledger", "link_evidence_to_decision", {"evidence_id": item["evidence_id"], "decision_id": decision_id})
        self.mcp.call("mcp-filesystem", "write_json_output", {"scenario_id": event.scenario_id, "filename": "decision_queue.json", "data": {"decisions": [decision.model_dump(mode="json")]}})
        self.mcp.call("mcp-filesystem", "write_json_output", {"scenario_id": event.scenario_id, "filename": "evidence_summary.json", "data": {"evidence": evidence}})
        self.mcp.call("mcp-filesystem", "write_output", {"scenario_id": event.scenario_id, "filename": "final_brief.md", "content": _brief_markdown(event, prior, decision, evidence)})
        self.mcp.call("mcp-filesystem", "write_output", {"scenario_id": event.scenario_id, "filename": "red_team_review.md", "content": "# Red Team Review\n\nSee evidence-redteam-agent finding.\n"})
        self.mcp.call("mcp-filesystem", "write_json_output", {"scenario_id": event.scenario_id, "filename": "assumptions_and_unknowns.json", "data": {"findings": prior}})
        self.mcp.call("mcp-filesystem", "write_json_output", {"scenario_id": event.scenario_id, "filename": "trace_metadata.json", "data": {"trace_id": task.trace_id, "scenario_id": event.scenario_id}})
        return AgentFinding(
            agent_name=self.name,
            mode="decision_synthesis",
            summary="Generated Decision Queue, Executive Brief, Evidence Summary, Red Team Review, Unknowns, and Trace Metadata.",
            risk_score=max([finding.get("risk_score") or 0 for finding in prior] or [0]),
            confidence="medium",
            evidence_ids=[item["evidence_id"] for item in evidence],
            recommended_actions=[decision.decision],
            review_required=True,
            rationale="Decision Synthesis Agent writes final artifacts via MCP filesystem and uses Evidence Ledger through MCP.",
            metadata={"decision": decision.model_dump(mode="json"), "output_dir": str(self.settings.project_root / "outputs" / event.scenario_id)},
        )


def _neo4j_decision_properties(decision: DecisionItem) -> dict[str, Any]:
    properties = decision.model_dump(mode="json")
    priority_evidence = properties.pop("priority_evidence", [])
    if priority_evidence:
        properties["priority_evidence_json"] = json.dumps(priority_evidence, ensure_ascii=False)
        properties["priority_evidence_summaries"] = [
            str(item.get("evidence_text") or "")
            for item in priority_evidence
            if isinstance(item, dict) and item.get("evidence_text")
        ]
    return properties


class OrchestratorDeepAgentService(A2AService):
    name = "orchestrator-agent"

    def __init__(self, settings: Settings, a2a_client: A2AHttpClient) -> None:
        self.settings = settings
        self.a2a_client = a2a_client
        self.runner = DeepAgentRunner(settings, self.name, "You are the Orchestrator DeepAgent. Plan, delegate, and synthesize; do not call external stores directly.")

    def card(self) -> AgentCard:
        return AgentCard(
            name=self.name,
            description="Plans and delegates risk analysis to Domain Agents through A2A.",
            skills=["intake", "planning", "a2a_delegation", "decision_integration"],
            modes=["orchestrator"],
        )

    def run_task(self, request: AgentTaskRequest) -> AgentTaskResult:
        started = datetime.now(timezone.utc)
        self.runner.tracer = TraceRecorder(self.settings, request.task.trace_id)
        try:
            finding = self.run_orchestration(request.task)
            return AgentTaskResult(
                task_id=request.task.task_id,
                parent_task_id=request.task.parent_task_id,
                trace_id=request.task.trace_id,
                agent_name=self.name,
                status="completed",
                finding=finding,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return AgentTaskResult(
                task_id=request.task.task_id,
                parent_task_id=request.task.parent_task_id,
                trace_id=request.task.trace_id,
                agent_name=self.name,
                status="failed",
                error=AgentError(code=exc.__class__.__name__, message=str(exc)),
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )

    def run_orchestration(self, task: AgentTask) -> AgentFinding:
        event = RiskEvent.model_validate(task.inputs["risk_event"])
        analysis_plan = self._create_analysis_plan(task, event)
        agent_order = [agent_name for agent_name in FIXED_AGENT_ORDER if agent_name in analysis_plan.selected_agents]
        if not agent_order:
            analysis_plan = _fallback_analysis_plan()
            agent_order = list(FIXED_AGENT_ORDER)
        findings: list[dict[str, Any]] = []
        for agent_name in agent_order:
            child_task = AgentTask(
                task_id=f"{task.task_id}:{agent_name}",
                parent_task_id=task.task_id,
                scenario_id=event.scenario_id,
                client_id=event.client_id,
                requested_by=self.name,
                objective=f"Run {agent_name} analysis",
                mode=agent_name.replace("-agent", ""),
                inputs={
                    "risk_event": event.model_dump(mode="json"),
                    "findings": findings,
                    "analysis_plan": analysis_plan.model_dump(mode="json"),
                },
                expected_output_schema="AgentFinding",
                trace_id=task.trace_id,
            )
            result = self.a2a_client.send_task(agent_name, AgentTaskRequest(task=child_task))
            if result.status != "completed" or not result.finding:
                raise RuntimeError(f"{agent_name} failed: {result.error.message if result.error else result.status}")
            findings.append(result.finding.model_dump(mode="json"))

        decision_task = AgentTask(
            task_id=f"{task.task_id}:decision-synthesis-agent",
            parent_task_id=task.task_id,
            scenario_id=event.scenario_id,
            client_id=event.client_id,
            requested_by=self.name,
            objective="Generate final Decision-first outputs",
            mode="decision_synthesis",
            inputs={"risk_event": event.model_dump(mode="json"), "findings": findings, "analysis_plan": analysis_plan.model_dump(mode="json")},
            expected_output_schema="AgentFinding",
            trace_id=task.trace_id,
        )
        decision_result = self.a2a_client.send_task("decision-synthesis-agent", AgentTaskRequest(task=decision_task))
        if decision_result.status != "completed" or not decision_result.finding:
            raise RuntimeError(f"decision-synthesis-agent failed: {decision_result.error.message if decision_result.error else decision_result.status}")
        findings.append(decision_result.finding.model_dump(mode="json"))
        return AgentFinding(
            agent_name=self.name,
            mode="orchestrator",
            summary=f"Delegated scenario to {len(findings)} Domain Agent findings through A2A.",
            confidence="medium",
            recommended_actions=decision_result.finding.recommended_actions,
            review_required=True,
            rationale="Orchestrator used A2A task requests and did not directly call Tavily, Qdrant, Neo4j, or filesystem.",
            metadata={"analysis_plan": analysis_plan.model_dump(mode="json"), "findings": findings},
        )

    def _create_analysis_plan(self, task: AgentTask, event: RiskEvent) -> AnalysisPlan:
        previous_recheck_conditions = _string_list(task.inputs.get("previous_recheck_conditions"), limit=12)
        deterministic_plan = _deterministic_analysis_plan(event)
        if deterministic_plan:
            return _with_previous_recheck_conditions(deterministic_plan, previous_recheck_conditions)
        prompt = (
            "Return a bounded risk-analysis plan. Preserve the fixed agent order by selecting names "
            "from fixed_agent_order; do not invent agent names. If previous_recheck_conditions is non-empty, "
            "consider whether they should still apply and may be reflected in recheck_conditions.\n"
            f"fixed_agent_order={json.dumps(FIXED_AGENT_ORDER)}\n"
            f"previous_recheck_conditions={json.dumps(previous_recheck_conditions, ensure_ascii=False)}\n"
            f"risk_event={json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}"
        )
        try:
            plan = self.runner.synthesize_structured(prompt, AnalysisPlan, max_chars=4000)
            normalized = _normalize_analysis_plan(plan)
            if normalized:
                return _with_previous_recheck_conditions(normalized, previous_recheck_conditions)
        except Exception:
            pass
        return _with_previous_recheck_conditions(_fallback_analysis_plan(), previous_recheck_conditions)


def create_domain_services(settings: Settings, *, embedded_mcp: bool = False) -> dict[str, A2AService]:
    services: list[A2AService] = [
        SourceIntelligenceDeepAgent(settings, embedded_mcp=embedded_mcp),
        ClientContextDeepAgent(settings, embedded_mcp=embedded_mcp),
        TreasuryRiskDeepAgent(settings, embedded_mcp=embedded_mcp),
        LegalRiskDeepAgent(settings, embedded_mcp=embedded_mcp),
        AccountingRiskDeepAgent(settings, embedded_mcp=embedded_mcp),
        ProcurementRiskDeepAgent(settings, embedded_mcp=embedded_mcp),
        ExpertAsCodeDeepAgent(settings, embedded_mcp=embedded_mcp),
        EvidenceRedTeamDeepAgent(settings, embedded_mcp=embedded_mcp),
        DecisionSynthesisDeepAgent(settings, embedded_mcp=embedded_mcp),
    ]
    return {service.name: service for service in services}


def create_embedded_a2a_apps(settings: Settings, *, embedded_mcp: bool = True) -> dict[str, Any]:
    services = create_domain_services(settings, embedded_mcp=embedded_mcp)
    return {name: create_a2a_app(service) for name, service in services.items()}


def create_orchestrator_service(settings: Settings, embedded_apps: dict[str, Any] | None = None) -> OrchestratorDeepAgentService:
    client = A2AHttpClient(settings.service_urls, embedded_apps=embedded_apps, settings=settings)
    return OrchestratorDeepAgentService(settings, client)


def _deterministic_analysis_plan(event: RiskEvent) -> AnalysisPlan | None:
    planned_agents = CANONICAL_RISK_AGENT_PLAN.get(event.risk_type)
    if not planned_agents:
        return None
    selected = [agent for agent in FIXED_AGENT_ORDER if agent in planned_agents]
    skipped = [agent for agent in FIXED_AGENT_ORDER if agent not in selected]
    return AnalysisPlan(
        selected_agents=selected,
        skipped_agents=skipped,
        recheck_conditions=[
            f"Escalate to skipped specialist agents if evidence contradicts `{event.risk_type}` scope or reveals material cross-domain exposure."
        ],
        exploration_questions=[
            f"Which evidence gaps would change the `{event.risk_type}` conclusion or require cross-functional escalation?"
        ],
        rationale=f"Deterministic canonical-risk plan for `{event.risk_type}` preserves fixed agent order without mid-run selection.",
        fallback_used=False,
    )

def _analysis_plan_from_text(text: str) -> AnalysisPlan | None:
    data = _json_object_from_text(text)
    if not data:
        return None
    try:
        return _normalize_analysis_plan(AnalysisPlan.model_validate(data))
    except ValueError:
        return None


def _normalize_analysis_plan(plan: AnalysisPlan) -> AnalysisPlan | None:
    requested = set(_string_list(plan.selected_agents, limit=len(FIXED_AGENT_ORDER)))
    selected = [agent for agent in FIXED_AGENT_ORDER if agent in requested]
    if not selected:
        return None
    skipped = [agent for agent in FIXED_AGENT_ORDER if agent not in selected]
    return AnalysisPlan(
        selected_agents=selected,
        skipped_agents=skipped,
        recheck_conditions=_string_list(plan.recheck_conditions, limit=12),
        exploration_questions=_string_list(plan.exploration_questions, limit=12),
        rationale=plan.rationale,
        fallback_used=plan.fallback_used,
    )


def _with_previous_recheck_conditions(plan: AnalysisPlan, previous_recheck_conditions: list[str]) -> AnalysisPlan:
    if not previous_recheck_conditions:
        return plan
    merged = list(plan.recheck_conditions)
    for condition in previous_recheck_conditions:
        if condition not in merged:
            merged.append(condition)
    return plan.model_copy(update={"recheck_conditions": merged})


def _fallback_analysis_plan() -> AnalysisPlan:
    return AnalysisPlan(
        selected_agents=list(FIXED_AGENT_ORDER),
        skipped_agents=[],
        recheck_conditions=["Re-run all fixed-order agents when bounded plan generation fails."],
        exploration_questions=[],
        rationale="DeepAgent analysis_plan generation failed or returned no valid selected agents; fixed order was used.",
        fallback_used=True,
    )


def _issue_exploration_from_tool_input(
    *,
    issues: list[str] | None = None,
    missing_data: list[str] | None = None,
    recheck_conditions: list[str] | None = None,
    exploration_questions: list[str] | None = None,
    issues_json: str | None = None,
) -> IssueExplorationRecordInput:
    if issues_json:
        data = _json_object_from_text(issues_json) or {}
        return IssueExplorationRecordInput.model_validate(data)
    return IssueExplorationRecordInput(
        issues=issues or [],
        missing_data=missing_data or [],
        recheck_conditions=recheck_conditions or [],
        exploration_questions=exploration_questions or [],
    )


def _counterfactuals_from_tool_input(
    *,
    counterfactuals: list[str] | None = None,
    counterfactuals_json: str | None = None,
) -> CounterfactualRecordInput:
    if counterfactuals_json:
        data = _json_object_from_text(counterfactuals_json) or {}
        return CounterfactualRecordInput.model_validate(data)
    return CounterfactualRecordInput(counterfactuals=counterfactuals or [])


def _redteam_missing_data_from_tool_input(
    *,
    missing_data: list[str] | None = None,
    missing_data_json: str | None = None,
) -> RedTeamMissingDataInput:
    if missing_data_json:
        data = _json_object_from_text(missing_data_json) or {}
        return RedTeamMissingDataInput.model_validate(data)
    return RedTeamMissingDataInput(missing_data=missing_data or [])


def _redteam_overclaims_from_tool_input(
    *,
    overclaims: list[str] | None = None,
    overclaims_json: str | None = None,
) -> RedTeamOverclaimsInput:
    if overclaims_json:
        data = _json_object_from_text(overclaims_json) or {}
        return RedTeamOverclaimsInput.model_validate(data)
    return RedTeamOverclaimsInput(overclaims=overclaims or [])


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


def _string_list(value: Any, *, limit: int | None = None) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
        if limit is not None and len(items) >= limit:
            break
    return items


def _select_urls_for_extraction(searches: list[dict[str, Any]], limit: int) -> list[str]:
    urls: list[str] = []
    for candidate in _rank_source_candidates(searches, None):
        url = str(candidate["result"].get("url") or "")
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _rank_source_candidates(searches: list[dict[str, Any]], event: RiskEvent | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for search_index, search in enumerate(searches):
        for result_index, result in enumerate(search.get("results") or []):
            key = str(result.get("url") or result.get("title") or result.get("content") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            if event:
                source_score = score_source(result, event)
                reliability = _confidence_rank(source_score["reliability"])
                relevance = _confidence_rank(source_score["client_relevance"])
                confidence = _confidence_rank(source_score["confidence"])
            else:
                reliability = relevance = confidence = 1
            candidates.append(
                {
                    "result": result,
                    "query_hash": search.get("query_hash"),
                    "sort_key": (-reliability, -relevance, -confidence, search_index, result_index),
                }
            )
    candidates.sort(key=lambda item: item["sort_key"])
    return candidates


def _confidence_rank(value: Any) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(value), 0)


def _extracted_text_by_url(extractions: list[dict[str, Any]]) -> dict[str, str]:
    by_url: dict[str, str] = {}
    for item in extractions:
        url = str(item.get("url") or "")
        if not url or item.get("status") != "extracted":
            continue
        text = _extract_text_from_tavily_payload(item.get("result"))
        if text:
            by_url[url] = text
    return by_url


def _extract_text_from_tavily_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("result", payload)
    if isinstance(data, dict):
        results = data.get("results") or data.get("response") or []
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict):
                    text = str(result.get("raw_content") or result.get("content") or "")
                    if text:
                        return text
        text = str(data.get("raw_content") or data.get("content") or "")
        return text or None
    return None


def _clean_evidence_text(value: Any, limit: int | None = None) -> str:
    text = str(value or "")
    cleaned = "".join(char if char in "\n\t" or ord(char) >= 32 else " " for char in text)
    normalized = re.sub(r"\s+", " ", cleaned).strip()
    return normalized if limit is None else normalized[:limit]


def _document_ids(items: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in items:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        for key in ("document_id", "id", "case_id", "note_id"):
            value = payload.get(key) or item.get(key)
            if value and str(value) not in ids:
                ids.append(str(value))
                break
    return ids


def _knowledge_object_relevant(item: dict[str, Any], event_text: str) -> bool:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
    searchable = " ".join(
        [
            str(payload.get("domain") or ""),
            str(payload.get("object_type") or ""),
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            str(payload.get("text") or ""),
            " ".join(str(tag) for tag in payload.get("tags") or []),
        ]
    ).lower()
    tokens = [token for token in re.split(r"[^a-z0-9_]+", event_text.lower()) if len(token) >= 4]
    return any(token in searchable for token in tokens)


def _recommended_guardrails_from_knowledge(items: list[dict[str, Any]]) -> list[str]:
    guardrails: list[str] = []
    for item in items:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        object_type = str(payload.get("object_type") or "")
        if object_type in {"language_guardrail", "evidence_standard", "review_trigger"}:
            title = str(payload.get("title") or payload.get("document_id") or "")
            if title:
                guardrails.append(title)
        for effect in payload.get("output_effects") or []:
            if str(effect) not in guardrails:
                guardrails.append(str(effect))
    return guardrails


def _default_counterfactuals(event: RiskEvent) -> list[str]:
    country = ", ".join(event.countries) if event.countries else "the affected country"
    return [
        f"What if the supplier is outside {country} but its bank route is exposed?",
        "What if public evidence describes sector risk but not this client's product category?",
        "What if contract continuity risk is lower because alternate supply is already qualified?",
    ]


def _decision_id_for_content(event: RiskEvent, decision: DecisionItem, *, slot: int = 1) -> str:
    payload = decision.model_dump(mode="json")
    payload.pop("decision_id", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"{event.scenario_id}_decision_{slot:03d}_{digest}"


def _decision_for_event(
    event: RiskEvent,
    decision_id: str,
    evidence: list[dict[str, Any]],
    knowledge_ids: list[str],
    runner: DeepAgentRunner,
    prior_findings: list[dict[str, Any]] | None = None,
) -> DecisionItem:
    prompt = _decision_synthesis_prompt(event, evidence, knowledge_ids, prior_findings or [])
    structured = runner.synthesize_structured(
        prompt,
        DecisionSynthesisOutput,
        max_chars=6000,
        provider_first=True,
        allow_text_fallback=False,
    )
    evidence_ids = _validated_decision_ids(
        structured.cited_evidence_ids,
        [str(item["evidence_id"]) for item in evidence if item.get("evidence_id")],
        "evidence_id",
    )
    if evidence and not evidence_ids:
        raise ValueError("Decision synthesis must cite at least one available evidence_id.")
    expert_ids = _validated_decision_ids(
        structured.cited_expert_knowledge_ids,
        knowledge_ids,
        "expert_knowledge_id",
    )
    priority_evidence = _priority_evidence_from_findings(prior_findings or [])
    return DecisionItem(
        decision_id=decision_id,
        priority=structured.priority,
        decision=structured.decision,
        owner=structured.owner,
        deadline=structured.deadline,
        deadline_rationale=structured.deadline_rationale,
        deadline_signals=structured.deadline_signals,
        rationale=structured.rationale,
        options=structured.options,
        evidence_ids=evidence_ids,
        expert_knowledge_ids=expert_ids,
        priority_evidence=priority_evidence,
        risk_if_delayed=structured.risk_if_delayed,
        review_required=structured.review_required,
    )


def _decision_synthesis_prompt(
    event: RiskEvent,
    evidence: list[dict[str, Any]],
    knowledge_ids: list[str],
    prior_findings: list[dict[str, Any]],
) -> str:
    evidence_digest = [
        {
            "evidence_id": item.get("evidence_id"),
            "source_title": _clean_evidence_text(item.get("source_title") or ""),
            "source_domain": item.get("source_domain"),
            "summary": _clean_evidence_text(item.get("summary") or item.get("raw_snippet") or ""),
            "supports": item.get("supports") or [],
            "reliability": item.get("reliability"),
            "confidence": item.get("confidence"),
        }
        for item in evidence
    ]
    findings_digest = [
        {
            "agent_name": finding.get("agent_name"),
            "mode": finding.get("mode"),
            "summary": _clean_evidence_text(finding.get("summary") or ""),
            "risk_score": finding.get("risk_score"),
            "confidence": finding.get("confidence"),
            "unknowns": _string_list(finding.get("unknowns")),
            "recommended_actions": _string_list(finding.get("recommended_actions")),
            "review_required": finding.get("review_required"),
            "rationale": _clean_evidence_text(finding.get("rationale") or ""),
        }
        for finding in prior_findings
        if isinstance(finding, dict)
    ]
    priority_evidence_digest = [
        item.model_dump(mode="json")
        for item in _priority_evidence_from_findings(prior_findings)
    ]
    return (
        "Generate exactly one decision-synthesis output for the risk scenario. Return JSON for the provided structured output schema. "
        "Infer the decision, owner, deadline, options, and review requirement from the event, prior agent findings, "
        "expert knowledge IDs, and evidence. Do not use hard-coded keyword taxonomy, static risk_type templates, "
        "or fallback/default decision text. If the evidence does not justify urgency, choose a non-immediate deadline "
        "and explain why in deadline_rationale. Do not collapse legal, payment, supplier, accounting, data-validation, "
        "technology-access, or operational-continuity issues into another domain merely because they co-occur. "
        "Use priority_evidence_digest as natural-language, source-backed context from prior agents when deciding priority, rationale, deadline, and review requirement. "
        "Use cited_evidence_ids only from available_evidence_ids and cited_expert_knowledge_ids only from available_expert_knowledge_ids. "
        "priority must be an integer where 1 is most urgent and 5 is least urgent.\n"
        f"risk_event={json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n"
        f"available_evidence_ids={json.dumps([item.get('evidence_id') for item in evidence if item.get('evidence_id')], ensure_ascii=False)}\n"
        f"evidence_digest={json.dumps(evidence_digest, ensure_ascii=False)}\n"
        f"available_expert_knowledge_ids={json.dumps(knowledge_ids, ensure_ascii=False)}\n"
        f"prior_agent_findings={json.dumps(findings_digest, ensure_ascii=False)}\n"
        f"priority_evidence_digest={json.dumps(priority_evidence_digest, ensure_ascii=False)}"
    )


def _priority_evidence_from_findings(findings: list[dict[str, Any]]) -> list[PriorityEvidenceItem]:
    items: list[PriorityEvidenceItem] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        source_agent = str(finding.get("agent_name") or finding.get("mode") or "unknown-agent")
        evidence_text = _natural_priority_evidence_text(finding)
        if not evidence_text:
            continue
        key = (source_agent, evidence_text[:240])
        if key in seen:
            continue
        items.append(
            PriorityEvidenceItem(
                source_agent=source_agent,
                evidence_text=evidence_text,
                source_refs=_priority_source_refs(finding),
                limitations=_priority_limitations(finding),
            )
        )
        seen.add(key)
    return items


def _natural_priority_evidence_text(finding: dict[str, Any]) -> str:
    source_agent = str(finding.get("agent_name") or finding.get("mode") or "unknown-agent")
    summary = _clean_evidence_text(finding.get("summary") or "")
    rationale = _clean_evidence_text(finding.get("rationale") or "")
    metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
    metadata_digest = _priority_metadata_digest(metadata)
    actions = _string_list(finding.get("recommended_actions"))
    risk_score = finding.get("risk_score")
    confidence = finding.get("confidence")
    review_required = finding.get("review_required")
    context_parts: list[str] = []
    if summary:
        context_parts.append(f"{source_agent} reported: {summary}")
    if metadata_digest:
        context_parts.append(f"Priority-relevant data it used includes {metadata_digest}.")
    if rationale:
        context_parts.append(f"Rationale: {rationale}")
    if actions:
        context_parts.append(f"Recommended actions include {', '.join(actions)}.")
    signal_parts: list[str] = []
    if risk_score is not None:
        signal_parts.append(f"risk_score={risk_score}")
    if confidence:
        signal_parts.append(f"confidence={confidence}")
    if review_required is not None:
        signal_parts.append(f"review_required={review_required}")
    if signal_parts:
        context_parts.append(f"Agent-level priority signals: {', '.join(signal_parts)}.")
    return _clean_evidence_text(" ".join(context_parts))


def _priority_source_refs(finding: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    source_agent = str(finding.get("agent_name") or finding.get("mode") or "unknown-agent")
    for evidence_id in _string_list(finding.get("evidence_ids")):
        refs.append(f"evidence_id:{evidence_id}")
    metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
    for key, value in metadata.items():
        if _metadata_key_is_priority_relevant(key, value):
            refs.append(f"{source_agent}.metadata.{key}")
    return refs


def _priority_limitations(finding: dict[str, Any]) -> str:
    limitations: list[str] = []
    limitations.extend(_string_list(finding.get("unknowns")))
    metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
    issue_exploration = metadata.get("issue_exploration")
    if isinstance(issue_exploration, dict):
        limitations.extend(_string_list(issue_exploration.get("missing_data")))
    limitations.extend(_string_list(metadata.get("missing_data")))
    limitations.extend(_string_list(metadata.get("overclaims")))
    if _has_redaction_policy(metadata):
        limitations.append("Raw identifiers, names, account data, or row-level sensitive fields may be omitted or bucketed by redaction policy.")
    return _clean_evidence_text("; ".join(_unique_strings(limitations)))


def _priority_metadata_digest(metadata: dict[str, Any]) -> str:
    compact = _compact_priority_metadata(metadata)
    if not compact:
        return ""
    return _clean_evidence_text(_render_priority_value(compact))


def _compact_priority_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in metadata.items():
        if not _metadata_key_is_priority_relevant(key, value):
            continue
        if key in {"qdrant_hits", "hits", "case_hits"} and isinstance(value, list):
            compact[f"{key}_count"] = len(value)
            continue
        if key.endswith("_ids") and isinstance(value, list):
            compact[f"{key}_count"] = len(value)
            continue
        sanitized = _sanitize_priority_value(value, depth=0)
        if sanitized not in (None, "", [], {}):
            compact[key] = sanitized
    return compact


def _metadata_key_is_priority_relevant(key: str, value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    lowered = key.lower()
    if lowered in {"confidential_terms"}:
        return False
    if lowered.startswith("_"):
        return False
    return True


def _sanitize_priority_value(value: Any, *, depth: int) -> Any:
    if depth >= 4:
        if isinstance(value, list):
            return f"{len(value)} items"
        if isinstance(value, dict):
            return f"{len(value)} fields"
        return _clean_evidence_text(str(value))
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_priority_key(key):
                continue
            rendered = _sanitize_priority_value(item, depth=depth + 1)
            if rendered not in (None, "", [], {}):
                sanitized[key] = rendered
        return sanitized
    if isinstance(value, list):
        if not value:
            return []
        sanitized_list: list[Any] = []
        for item in value:
            rendered = _sanitize_priority_value(item, depth=depth + 1)
            if rendered not in (None, "", [], {}):
                sanitized_list.append(rendered)
        return sanitized_list
    if isinstance(value, bool | int | float):
        return value
    return _clean_evidence_text(str(value))


def _is_sensitive_priority_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in {"amount", "due_date", "raw_snippet", "text"}:
        return True
    sensitive_parts = ("id", "name", "account", "email", "phone", "address", "confidential")
    if any(part in lowered for part in sensitive_parts):
        return True
    return False


def _render_priority_value(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{key}={_render_priority_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        rendered_items = [_render_priority_value(item) for item in value]
        return "[" + ", ".join(item for item in rendered_items if item) + "]"
    return str(value)


def _has_redaction_policy(value: Any) -> bool:
    if isinstance(value, dict):
        if "redaction_policy" in value:
            return True
        return any(_has_redaction_policy(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_redaction_policy(item) for item in value)
    return False


def _unique_strings(values: list[Any], *, limit: int | None = None) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)
        if limit is not None and len(items) >= limit:
            break
    return items


def _validated_decision_ids(requested: list[str], allowed: list[str], field_name: str) -> list[str]:
    allowed_set = set(allowed)
    unknown = [item for item in requested if item not in allowed_set]
    if unknown:
        raise ValueError(f"Decision synthesis returned unknown {field_name}: {unknown}")
    return requested


def _default_domain_issues(domain: str, event: RiskEvent) -> list[str]:
    defaults = {
        "treasury": [
            "Payment route, correspondent bank, and currency controls may change the cash mobility conclusion.",
            "Near-term invoice timing may require CFO approval before any hold or reroute option.",
        ],
        "legal": [
            "Sanctions proximity, beneficial ownership, and force majeure clauses must be checked before action language is finalized.",
            "Notice and termination obligations may differ by contract even when the event country is the same.",
        ],
        "accounting": [
            "Provision, impairment, subsequent-event, and disclosure treatment depend on materiality and probability.",
            "Auditor evidence pack may be needed if supplier continuity or payment recoverability becomes uncertain.",
        ],
    }
    return defaults.get(domain, [f"Explore {domain} implications for {event.risk_type}."])


def _redteam_missing_data(event: RiskEvent, evidence: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    if not evidence:
        missing.append("No external evidence is registered for this scenario.")
    if not any(item.get("reliability") == "high" for item in evidence):
        missing.append("No high-reliability government, regulator, international organization, or official disclosure source is present.")
    if event.countries and not any(any(country.lower() in str(item).lower() for country in event.countries) for item in evidence):
        missing.append("Registered evidence does not clearly mention the affected country.")
    return missing


def _redteam_overclaims(findings: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[str]:
    evidence_ids = {item.get("evidence_id") for item in evidence}
    warnings: list[str] = []
    for finding in findings:
        if finding.get("confidence") == "high" and not set(finding.get("evidence_ids") or []).intersection(evidence_ids):
            warnings.append(f"{finding.get('agent_name') or finding.get('mode')} uses high confidence without registered supporting evidence.")
        if (finding.get("risk_score") or 0) >= 80 and not finding.get("review_required"):
            warnings.append(f"{finding.get('agent_name') or finding.get('mode')} has a high score without review_required=true.")
    return warnings


def _brief_markdown(event: RiskEvent, findings: list[dict[str, Any]], decision: DecisionItem, evidence: list[dict[str, Any]]) -> str:
    lines = [
        f"# Executive Brief: {event.title}",
        "",
        f"- Scenario ID: `{event.scenario_id}`",
        f"- Client ID: `{event.client_id}`",
        "",
        "## Findings",
    ]
    for finding in findings:
        lines.append(f"- **{finding.get('mode')}**: {finding.get('summary')}")
    lines.extend(
        [
            "",
            "## Decision Queue",
            f"1. {decision.decision}",
            f"   - Owner: {decision.owner}",
            f"   - Deadline: {decision.deadline}",
            f"   - Priority: {decision.priority}",
            f"   - Review required: {decision.review_required}",
            "",
            "## Priority Evidence",
        ]
    )
    if decision.priority_evidence:
        for item in decision.priority_evidence:
            lines.append(f"- **{item.source_agent}**: {item.evidence_text}")
            if item.source_refs:
                lines.append(f"  - Source refs: {', '.join(item.source_refs)}")
            if item.limitations:
                lines.append(f"  - Limitations: {item.limitations}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Evidence Summary",
        ]
    )
    for item in evidence:
        lines.append(f"- `{item.get('evidence_id')}` {item.get('source_title') or item.get('summary', '')}")
    return "\n".join(lines) + "\n"


def _knowledge_ids_from_findings(findings: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for finding in findings:
        metadata = finding.get("metadata") or {}
        for key in ("knowledge_object_ids", "case_ids"):
            for value in metadata.get(key) or []:
                if value and value not in ids:
                    ids.append(str(value))
    return ids


def _confidential_terms_from_findings(findings: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for finding in findings:
        metadata = finding.get("metadata") or {}
        for term in metadata.get("confidential_terms") or []:
            _append_unique_term(terms, term)
    return terms


def _confidential_terms_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    sensitive_keys = {
        "name",
        "supplier_name",
        "customer_name",
        "site_name",
        "contract_name",
        "contract_id",
        "supplier_id",
        "customer_id",
        "site_id",
        "payment_id",
        "bank_name",
        "product_name",
    }
    for row in rows:
        for key, value in row.items():
            if key in sensitive_keys or key.endswith("_id") or key.endswith("_name"):
                _append_unique_term(terms, value)
    return terms


def _append_unique_term(terms: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if len(text) < 3:
        return
    if text.lower() in {item.lower() for item in terms}:
        return
    terms.append(text)


def new_root_task(event: RiskEvent) -> AgentTask:
    return AgentTask(
        task_id=f"{event.scenario_id}:{uuid4()}",
        scenario_id=event.scenario_id,
        client_id=event.client_id,
        requested_by="cli",
        objective="Run final architecture risk analysis",
        mode="orchestrator",
        inputs={"risk_event": event.model_dump(mode="json")},
        expected_output_schema="AgentFinding",
        trace_id=str(uuid4()),
    )
