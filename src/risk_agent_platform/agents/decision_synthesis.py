from __future__ import annotations

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.agents.base import BaseAgent
from risk_agent_platform.schemas import AgentFinding, AgentTask, DecisionItem


class DecisionSynthesisAgent(BaseAgent):
    name = "decision-synthesis-agent"
    description = "Builds Decision Queue and final executive brief."
    skills = ["decision_queue", "executive_brief", "raci_tasks"]
    modes = ["decision_synthesis", "executive"]

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        findings = [item for item in context.state.get("findings", []) if isinstance(item, AgentFinding)]
        evidence_ids = [item.evidence_id for item in context.evidence_ledger.items]
        expert_assessment = context.state.get("expert_assessment")
        knowledge_ids = list(getattr(expert_assessment, "knowledge_object_ids", []))
        review_required = any(finding.review_required for finding in findings) or bool(getattr(expert_assessment, "review_required", False))

        decisions = [
            DecisionItem(
                priority=1,
                decision="Continue, hold, or reroute near-term payment to the high-risk supplier under controlled approval.",
                owner="CFO / Legal / Procurement",
                deadline="24 hours",
                rationale="Treasury exposure and sanctions-clause implications converge on the same supplier and payment window.",
                options=[
                    "Proceed after sanctions and bank screening confirmation",
                    "Temporarily hold payment pending Legal review",
                    "Prepare an approved alternative route without executing automatically",
                ],
                evidence_ids=evidence_ids,
                expert_knowledge_ids=knowledge_ids,
                risk_if_delayed="Payment disruption or unmanaged sanctions exposure may affect supply continuity and control evidence.",
                review_required=True,
            ),
            DecisionItem(
                priority=2,
                decision="Start alternative sourcing readiness check for the critical component.",
                owner="CPO / Operations",
                deadline="72 hours",
                rationale="Client context shows critical supplier dependency and short inventory runway.",
                options=[
                    "Expedite alternative supplier qualification",
                    "Increase safety stock where feasible",
                    "Confirm realistic lead time and price impact",
                ],
                evidence_ids=evidence_ids,
                expert_knowledge_ids=knowledge_ids,
                risk_if_delayed="Inventory runway may narrow before a qualified alternative is ready.",
                review_required=review_required,
            ),
            DecisionItem(
                priority=3,
                decision="Prepare legal/accounting triage memo for notice, force majeure, and disclosure implications.",
                owner="Legal / Accounting",
                deadline="7 days",
                rationale="Contract clauses and materiality-sensitive pending payments require a traceable review package.",
                options=[
                    "Prepare notice analysis",
                    "Document accounting/disclosure assessment",
                    "Open auditor-ready evidence folder",
                ],
                evidence_ids=evidence_ids,
                expert_knowledge_ids=knowledge_ids,
                risk_if_delayed="Late legal or accounting review can weaken audit trail and stakeholder messaging.",
                review_required=review_required,
            ),
        ]
        decisions.sort(key=lambda item: item.priority)
        context.state["decisions"] = decisions
        context.filesystem.write_json(context.scenario_dir / "decision_queue.json", decisions)
        brief = _render_brief(context, findings, decisions)
        brief_path = context.filesystem.write_text(context.scenario_dir / "final_brief.md", brief)
        context.state["final_brief_path"] = str(brief_path)
        return AgentFinding(
            agent_name=self.name,
            mode="decision_synthesis",
            summary=f"Generated Decision Queue with {len(decisions)} decision items.",
            risk_score=max((finding.risk_score or 0 for finding in findings), default=0),
            confidence="medium",
            evidence_ids=evidence_ids,
            recommended_actions=[decision.decision for decision in decisions],
            review_required=review_required,
            rationale="Decision-first output converts cross-mode risk findings into owners, deadlines, options, and evidence.",
            metadata={"decision_count": len(decisions), "final_brief_path": str(brief_path)},
        )


def _render_brief(context: AgentRunContext, findings: list[AgentFinding], decisions: list[DecisionItem]) -> str:
    event = context.risk_event
    lines = [
        f"# Executive Brief: {event.title}",
        "",
        f"- Scenario ID: `{event.scenario_id}`",
        f"- Client ID: `{event.client_id}`",
        f"- Risk type: `{event.risk_type}`",
        f"- Countries: {', '.join(event.countries) or 'n/a'}",
        "",
        "## Key Findings",
    ]
    for finding in findings:
        score = f" score={finding.risk_score}" if finding.risk_score is not None else ""
        lines.append(f"- **{finding.mode}** ({finding.confidence}{score}): {finding.summary}")
    lines.extend(["", "## Decision Queue"])
    for decision in decisions:
        lines.extend(
            [
                f"### {decision.priority}. {decision.decision}",
                f"- Owner: {decision.owner}",
                f"- Deadline: {decision.deadline}",
                f"- Rationale: {decision.rationale}",
                f"- Risk if delayed: {decision.risk_if_delayed}",
                f"- Review required: {decision.review_required}",
                "- Options:",
            ]
        )
        for option in decision.options:
            lines.append(f"  - {option}")
    guardrails = getattr(context.state.get("expert_assessment"), "recommended_guardrails", [])
    if guardrails:
        lines.extend(["", "## Guardrails"])
        for guardrail in guardrails:
            lines.append(f"- {guardrail}")
    lines.extend(["", "## Evidence IDs", ", ".join(item.evidence_id for item in context.evidence_ledger.items) or "n/a", ""])
    return "\n".join(lines)
