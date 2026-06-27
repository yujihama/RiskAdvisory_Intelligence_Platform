from __future__ import annotations

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.agents.base import BaseAgent
from risk_agent_platform.schemas import AgentFinding, AgentTask, EvidenceItem


class SourceIntelligenceAgent(BaseAgent):
    name = "source-intelligence-agent"
    description = "Collects controlled external risk evidence and weak signals."
    skills = ["evidence_collection", "weak_signal_extraction", "source_quality"]
    modes = ["source_intelligence"]

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        event = context.risk_event
        evidence: list[EvidenceItem] = [
            EvidenceItem(
                evidence_id=f"{event.scenario_id}_ev_user_001",
                scenario_id=event.scenario_id,
                source_type="user_input",
                source_ref="scenario_input",
                summary=event.description,
                supports=[event.risk_type],
                reliability="medium",
                client_relevance="high",
                used_by_agents=[self.name],
            )
        ]
        for idx, source in enumerate(
            context.source_catalog.matching_dummy_sources(countries=event.countries, risk_themes=event.risk_themes),
            start=1,
        ):
            evidence.append(
                EvidenceItem(
                    evidence_id=f"{event.scenario_id}_ev_ext_{idx:03d}",
                    scenario_id=event.scenario_id,
                    source_type="external_source",
                    source_ref=str(source.get("source_ref", "dummy://unknown")),
                    summary=str(source.get("summary", "")),
                    supports=[event.risk_type, *event.risk_themes],
                    reliability=str(source.get("reliability", "medium")),  # type: ignore[arg-type]
                    client_relevance="medium",
                    used_by_agents=[self.name],
                )
            )
        for item in evidence:
            context.evidence_ledger.register(item)
        context.state["source_evidence"] = evidence
        return AgentFinding(
            agent_name=self.name,
            mode="source_intelligence",
            summary=f"Collected {len(evidence)} controlled evidence items for {event.title}.",
            risk_score=None,
            confidence="medium",
            evidence_ids=[item.evidence_id for item in evidence],
            recommended_actions=["Use these items as evidence candidates; do not treat dummy sources as live intelligence."],
            review_required=False,
            rationale="The initial implementation uses a controlled source catalog to avoid leaking client identifiers to web search.",
        )
