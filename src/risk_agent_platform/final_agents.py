from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from risk_agent_platform.a2a_http import A2AHttpClient, A2AService, create_a2a_app
from risk_agent_platform.config import Settings
from risk_agent_platform.deepagent_runtime import DeepAgentRunner
from risk_agent_platform.mcp_gateway import MCPGateway
from risk_agent_platform.schemas import (
    AgentCard,
    AgentError,
    AgentFinding,
    AgentTask,
    AgentTaskRequest,
    AgentTaskResult,
    DecisionItem,
    RiskEvent,
)
from risk_agent_platform.tracing import TraceRecorder


class DomainDeepAgentService(A2AService):
    name = "domain-agent"
    description = "Domain DeepAgent"
    skills: list[str] = []
    modes: list[str] = []

    def __init__(self, settings: Settings, *, embedded_mcp: bool = False) -> None:
        self.settings = settings
        self.mcp = MCPGateway(settings, embedded=embedded_mcp)
        self.runner = DeepAgentRunner(settings, self.name, self.system_prompt())

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


class SourceIntelligenceDeepAgent(DomainDeepAgentService):
    name = "source-intelligence-agent"
    description = "Uses Tavily via MCP to collect external risk evidence."
    skills = ["tavily_search", "evidence_registration", "source_quality"]
    modes = ["source_intelligence"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        result = self.mcp.call("mcp-web-search", "search_and_register_evidence", {"risk_event": event.model_dump(mode="json"), "max_results": 5})
        evidence = result.get("evidence", [])
        synthesis = self.synthesize(f"Summarize source intelligence for this risk event in one sentence: {event.title}")
        return AgentFinding(
            agent_name=self.name,
            mode="source_intelligence",
            summary=f"{synthesis} Registered {len(evidence)} Tavily evidence items.",
            confidence="medium",
            evidence_ids=[item["evidence_id"] for item in evidence],
            recommended_actions=["Review authoritative sources and retain query hash for audit."],
            review_required=False,
            rationale="Tavily results are sanitized, normalized to EvidenceItem, stored in Evidence Ledger, and indexed in Qdrant.",
            metadata={"query": result.get("query"), "query_hash": result.get("query_hash")},
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
            metadata={"datasets": datasets, "affected_supplier_ids": affected},
        )


class TreasuryRiskDeepAgent(DomainDeepAgentService):
    name = "treasury-risk-agent"
    description = "Analyzes payment disruption, cash mobility, and liquidity-at-risk."
    skills = ["payment_exposure", "cash_mobility", "liquidity_at_risk"]
    modes = ["treasury"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        exposure = self.mcp.call("mcp-structured-data", "summarize_payment_exposure", {"client_id": event.client_id, "country": event.countries[0] if event.countries else None})
        evidence = self.mcp.call("mcp-qdrant", "search_evidence", {"query": event.title, "filters": {"scenario_id": event.scenario_id}, "top_k": 5})
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
            metadata={"payment_exposure": exposure, "qdrant_hits": evidence},
        )


class LegalRiskDeepAgent(DomainDeepAgentService):
    name = "legal-risk-agent"
    description = "Analyzes sanctions, contract obligations, notices, and legal guardrails."
    skills = ["sanctions_proximity", "contract_obligation", "regulatory_trigger"]
    modes = ["legal"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        contracts = self.mcp.call("mcp-structured-data", "sample_rows", {"client_id": event.client_id, "dataset": "contracts", "limit": 100})
        issues = [row["contract_id"] for row in contracts if row.get("sanctions_clause") == "true" or row.get("force_majeure_clause") == "true"]
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
            metadata={"contract_issue_ids": issues},
        )


class AccountingRiskDeepAgent(DomainDeepAgentService):
    name = "accounting-risk-agent"
    description = "Analyzes provision, impairment, subsequent event, and disclosure pressure."
    skills = ["provision_trigger", "impairment_trigger", "disclosure_pressure"]
    modes = ["accounting"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        exposure = self.mcp.call("mcp-structured-data", "summarize_payment_exposure", {"client_id": event.client_id})
        amount = float(exposure.get("total_amount", 0))
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
            metadata={"payment_exposure": exposure},
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

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        indexed = self.mcp.call("mcp-expert-knowledge", "index_knowledge_pack", {})
        indexed_cases = self.mcp.call("mcp-expert-knowledge", "index_case_bank", {})
        questions = self.mcp.call("mcp-expert-knowledge", "load_question_bank", {})
        cta_notes = self.mcp.call("mcp-expert-knowledge", "load_cta_notes", {})
        hits = self.mcp.call("mcp-expert-knowledge", "search_knowledge_objects", {"query": event.title, "top_k": 10})
        case_hits = self.mcp.call("mcp-expert-knowledge", "search_similar_cases", {"case_description": event.description, "top_k": 5})
        object_ids = [hit.get("payload", {}).get("document_id") for hit in hits if hit.get("payload", {}).get("document_id")]
        case_ids = [hit.get("payload", {}).get("document_id") for hit in case_hits if hit.get("payload", {}).get("document_id")]
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
            },
        )


class EvidenceRedTeamDeepAgent(DomainDeepAgentService):
    name = "evidence-redteam-agent"
    description = "Challenges evidence quality, overclaiming, and missing data."
    skills = ["red_team", "counter_evidence", "evidence_quality"]
    modes = ["evidence_red_team"]

    def analyze(self, task: AgentTask) -> AgentFinding:
        event = self.event(task)
        evidence = self.mcp.call("mcp-evidence-ledger", "list_evidence_by_scenario", {"scenario_id": event.scenario_id})
        unknowns = []
        if len(evidence) < 2:
            unknowns.append("External evidence base is thin; avoid high confidence.")
        return AgentFinding(
            agent_name=self.name,
            mode="evidence_red_team",
            summary=f"Red team reviewed {len(evidence)} evidence items.",
            confidence="medium" if evidence else "low",
            unknowns=unknowns,
            recommended_actions=["Separate facts, assumptions, and inferred risk paths in the final output."],
            review_required=bool(unknowns),
            rationale="Evidence / Red Team Agent reads Evidence Ledger through MCP and challenges confidence.",
            metadata={"evidence_count": len(evidence)},
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
        decision_id = f"{event.scenario_id}_decision_001"
        decision = DecisionItem(
            decision_id=decision_id,
            priority=1,
            decision="Decide whether to continue, hold, or reroute high-risk supplier payments under controlled approval.",
            owner="CFO / Legal / Procurement",
            deadline="24 hours",
            rationale="Treasury, legal, accounting, and procurement findings converge on payment and supplier continuity risk.",
            options=["Proceed after screening", "Hold pending legal review", "Prepare approved alternative route"],
            evidence_ids=[item["evidence_id"] for item in evidence],
            expert_knowledge_ids=knowledge_ids,
            risk_if_delayed="Uncontrolled payment or delayed supplier action can worsen sanctions, liquidity, and supply risk.",
            review_required=True,
        )
        self.mcp.call(
            "mcp-neo4j",
            "upsert_asset",
            {
                "label": "Decision",
                "asset_id": decision_id,
                "properties": decision.model_dump(mode="json") | {"confidence_level": "derived", "source_type": "derived"},
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
        self.runner.synthesize(f"Plan stages for scenario {event.title}. Return one sentence.")
        agent_order = [
            "client-context-agent",
            "source-intelligence-agent",
            "treasury-risk-agent",
            "legal-risk-agent",
            "accounting-risk-agent",
            "procurement-risk-agent",
            "expert-as-code-agent",
            "evidence-redteam-agent",
        ]
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
                inputs={"risk_event": event.model_dump(mode="json"), "findings": findings},
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
            inputs={"risk_event": event.model_dump(mode="json"), "findings": findings},
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
            metadata={"findings": findings},
        )


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
            f"   - Review required: {decision.review_required}",
            "",
            "## Evidence Summary",
        ]
    )
    for item in evidence:
        lines.append(f"- `{item.get('evidence_id')}` {item.get('source_title') or item.get('summary', '')[:120]}")
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
