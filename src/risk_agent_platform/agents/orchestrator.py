from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from risk_agent_platform.a2a import AgentRunContext, LocalA2ARegistry
from risk_agent_platform.agents.client_context import ClientContextAgent
from risk_agent_platform.agents.decision_synthesis import DecisionSynthesisAgent
from risk_agent_platform.agents.expert_evidence import ExpertEvidenceAgent
from risk_agent_platform.agents.legal_accounting import LegalAccountingAgent
from risk_agent_platform.agents.source_intelligence import SourceIntelligenceAgent
from risk_agent_platform.agents.treasury_risk import TreasuryRiskAgent
from risk_agent_platform.config import Settings
from risk_agent_platform.mcp.evidence_ledger import EvidenceLedgerMCP
from risk_agent_platform.mcp.expert_knowledge import ExpertKnowledgeMCP
from risk_agent_platform.mcp.filesystem import FilesystemMCP
from risk_agent_platform.mcp.source_catalog import SourceCatalogMCP
from risk_agent_platform.mcp.structured_data import StructuredDataMCP
from risk_agent_platform.schemas import AgentFinding, AgentTask, RiskEvent, ScenarioResult


STAGES = [
    ("stage_1_context", "client-context-agent", "Build source-backed client context and Unknown Register.", "ClientContext"),
    ("stage_2_evidence", "source-intelligence-agent", "Collect controlled external evidence candidates.", "AgentFinding"),
    ("stage_3_treasury", "treasury-risk-agent", "Analyze cash mobility and payment disruption.", "AgentFinding"),
    ("stage_3_legal_accounting", "legal-accounting-agent", "Analyze legal, regulatory, accounting, and disclosure implications.", "AgentFinding"),
    ("stage_4_5_expert_evidence", "expert-evidence-agent", "Apply Expert-as-Code, review triggers, and red-team checks.", "ExpertAssessment"),
    ("stage_6_decision", "decision-synthesis-agent", "Create Decision Queue and final executive brief.", "DecisionItem"),
]


class OrchestratorDeepAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = LocalA2ARegistry()
        for agent in [
            ClientContextAgent(),
            SourceIntelligenceAgent(),
            TreasuryRiskAgent(),
            LegalAccountingAgent(),
            ExpertEvidenceAgent(),
            DecisionSynthesisAgent(),
        ]:
            self.registry.register(agent)

    def run_from_file(self, input_path: Path) -> ScenarioResult:
        event = RiskEvent.model_validate(json.loads(input_path.read_text(encoding="utf-8")))
        return self.run(event)

    def run(self, event: RiskEvent) -> ScenarioResult:
        filesystem = FilesystemMCP(self.settings.data_dir)
        scenario_dir = filesystem.reset_scenario_dir(event.scenario_id)
        evidence_ledger = EvidenceLedgerMCP(filesystem, scenario_dir)
        context = AgentRunContext(
            settings=self.settings,
            risk_event=event,
            scenario_dir=scenario_dir,
            filesystem=filesystem,
            structured_data=StructuredDataMCP(self.settings.data_dir),
            evidence_ledger=evidence_ledger,
            expert_knowledge=ExpertKnowledgeMCP(self.settings.data_dir),
            source_catalog=SourceCatalogMCP(self.settings.data_dir),
        )
        self._write_plan(context)
        findings: list[AgentFinding] = []
        context.state["findings"] = findings
        for stage_id, agent_name, objective, expected_schema in STAGES:
            task = AgentTask(
                task_id=f"{event.scenario_id}_{stage_id}",
                scenario_id=event.scenario_id,
                client_id=event.client_id,
                requested_by="orchestrator-agent",
                objective=objective,
                inputs={"risk_event": event.model_dump(mode="json")},
                expected_output_schema=expected_schema,
                trace_id=context.trace_id,
            )
            finding = self.registry.invoke(agent_name, task, context)
            findings.append(finding)
            context.filesystem.append_jsonl(context.scenario_dir / "trace.jsonl", [{"stage": stage_id, "agent": agent_name, "finding": finding}])
            self._write_stage_markdown(context, stage_id, finding)

        decisions = list(context.state.get("decisions", []))
        final_brief_path = str(context.state.get("final_brief_path", scenario_dir / "final_brief.md"))
        result = ScenarioResult(
            scenario_id=event.scenario_id,
            client_id=event.client_id,
            artifact_dir=str(scenario_dir),
            findings=findings,
            decisions=decisions,
            evidence=context.evidence_ledger.items,
            final_brief_path=final_brief_path,
        )
        filesystem.write_json(scenario_dir / "scenario_result.json", result)
        return result

    def _write_plan(self, context: AgentRunContext) -> None:
        lines = [
            f"# Analysis Plan: {context.risk_event.title}",
            "",
            f"- Trace ID: `{context.trace_id}`",
            f"- Scenario ID: `{context.risk_event.scenario_id}`",
            "",
            "## Stages",
        ]
        for stage_id, agent_name, objective, _schema in STAGES:
            lines.append(f"- `{stage_id}` -> `{agent_name}`: {objective}")
        context.filesystem.write_text(context.scenario_dir / "plan.md", "\n".join(lines) + "\n")
        context.filesystem.write_json(context.scenario_dir / "agent_cards.json", self.registry.agent_cards())

    def _write_stage_markdown(self, context: AgentRunContext, stage_id: str, finding: AgentFinding) -> None:
        path_by_stage = {
            "stage_1_context": "context_summary.md",
            "stage_2_evidence": "source_intelligence.md",
            "stage_3_treasury": "treasury_analysis.md",
            "stage_3_legal_accounting": "legal_accounting_analysis.md",
            "stage_4_5_expert_evidence": "expert_review.md",
            "stage_6_decision": "decision_synthesis.md",
        }
        path = context.scenario_dir / path_by_stage.get(stage_id, f"{stage_id}.md")
        lines = [
            f"# {stage_id}",
            "",
            f"- Agent: `{finding.agent_name}`",
            f"- Mode: `{finding.mode}`",
            f"- Confidence: `{finding.confidence}`",
            f"- Risk score: `{finding.risk_score}`",
            f"- Review required: `{finding.review_required}`",
            "",
            "## Summary",
            finding.summary,
            "",
            "## Rationale",
            finding.rationale,
            "",
            "## Recommended Actions",
        ]
        lines.extend(f"- {item}" for item in finding.recommended_actions)
        if finding.unknowns:
            lines.extend(["", "## Unknowns"])
            lines.extend(f"- {item}" for item in finding.unknowns)
        context.filesystem.write_text(path, "\n".join(lines) + "\n")


def create_run_id() -> str:
    return str(uuid4())
