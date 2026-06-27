from __future__ import annotations

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.agents.base import BaseAgent
from risk_agent_platform.schemas import AgentFinding, AgentTask, ExpertAssessment


class ExpertEvidenceAgent(BaseAgent):
    name = "expert-evidence-agent"
    description = "Applies Expert-as-Code and evidence/red-team checks."
    skills = ["expert_as_code", "review_trigger", "language_guardrail", "red_team"]
    modes = ["expert", "evidence_red_team"]

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        findings = [item for item in context.state.get("findings", []) if isinstance(item, AgentFinding)]
        triggers = context.expert_knowledge.get_review_triggers()
        guardrails = context.expert_knowledge.get_language_guardrails()
        evidence_items = context.evidence_ledger.items
        external_evidence = [item for item in evidence_items if item.source_type == "external_source"]

        score_adjustments: dict[str, int] = {}
        review_required = any(finding.review_required for finding in findings)
        observations: list[str] = []
        questions: list[str] = []

        treasury = next((finding for finding in findings if finding.mode == "treasury"), None)
        if treasury and treasury.risk_score and treasury.risk_score >= 60:
            score_adjustments["decision_urgency"] = 10
            review_required = True
            questions.append("Can the bank country, correspondent bank, and beneficiary screening status be confirmed today?")

        client_context = context.state.get("client_context")
        unknowns = getattr(client_context, "unknowns", []) if client_context else []
        if unknowns:
            observations.append("Unknown register is non-empty; do not treat inferred dependencies as confirmed facts.")
            questions.extend(str(item) for item in unknowns[:3])

        if not external_evidence:
            observations.append("No independent external evidence is attached; confidence should remain low or medium.")

        assessment = ExpertAssessment(
            knowledge_object_ids=[item.id for item in [*triggers, *guardrails]],
            review_required=review_required,
            recommended_guardrails=[item.description for item in guardrails],
            additional_questions=questions,
            score_adjustments=score_adjustments,
            red_team_observations=observations,
        )
        context.state["expert_assessment"] = assessment
        confidence = "medium" if external_evidence else "low"
        return AgentFinding(
            agent_name=self.name,
            mode="expert_evidence",
            summary=f"Applied {len(triggers)} review triggers and {len(guardrails)} language guardrails.",
            risk_score=None,
            confidence=confidence,
            evidence_ids=[item.evidence_id for item in evidence_items],
            assumptions=[],
            unknowns=questions,
            recommended_actions=[
                "Keep payment actions framed as controlled options requiring client approval.",
                "Resolve high-impact unknowns before final high-confidence recommendations.",
            ],
            review_required=review_required,
            rationale="Expert-as-Code is used to trigger review, cap confidence, and guard final wording.",
            metadata=assessment.model_dump(mode="json"),
        )
