from __future__ import annotations

from datetime import date

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.agents.base import BaseAgent
from risk_agent_platform.schemas import AgentFinding, AgentTask


class TreasuryRiskAgent(BaseAgent):
    name = "treasury-risk-agent"
    description = "Analyzes cash mobility, payment disruption, and liquidity-at-risk."
    skills = ["liquidity_at_risk", "payment_disruption", "cash_mobility"]
    modes = ["treasury"]

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        event = context.risk_event
        dataset = context.state.get("client_dataset") or context.structured_data.load_client_dataset(event.client_id)
        assert isinstance(dataset, dict)
        suppliers = {row["supplier_id"]: row for row in dataset.get("suppliers", [])}
        risk_countries = {country.lower() for country in event.countries}

        at_risk_payments: list[dict[str, object]] = []
        total_amount = 0.0
        unknowns: list[str] = []
        for payment in dataset.get("payments", []):
            supplier = suppliers.get(payment.get("supplier_id", ""), {})
            due_days = _days_between(event.event_date, payment.get("due_date", ""))
            supplier_in_country = supplier.get("country", "").lower() in risk_countries
            bank_in_country = payment.get("bank_country", "").lower() in risk_countries
            critical = supplier.get("criticality", "").lower() == "high"
            due_soon = due_days is not None and due_days <= 14
            if supplier_in_country or bank_in_country or (critical and due_soon):
                amount = _float(payment.get("amount", "0"))
                total_amount += amount
                item = dict(payment)
                item.update({"due_days": due_days, "supplier_country": supplier.get("country"), "supplier_criticality": supplier.get("criticality")})
                at_risk_payments.append(item)
                if not payment.get("bank_country"):
                    unknowns.append(f"Payment {payment['payment_id']} lacks bank country, limiting cash mobility confidence.")

        score = min(100, 20 + len(at_risk_payments) * 15 + int(total_amount / 100000) + len(unknowns) * 5)
        confidence = "medium" if at_risk_payments else "low"
        review_required = score >= 60 or bool(unknowns)
        context.state["treasury_at_risk_payments"] = at_risk_payments
        return AgentFinding(
            agent_name=self.name,
            mode="treasury",
            summary=f"Identified {len(at_risk_payments)} payment items with potential disruption exposure.",
            risk_score=score,
            confidence=confidence,
            evidence_ids=[item.evidence_id for item in context.evidence_ledger.items],
            assumptions=["Pending payments are used as a proxy for near-term cash mobility exposure."],
            unknowns=unknowns,
            recommended_actions=[
                "Prepare CFO / Legal / Procurement joint review for payment continuation, hold, or controlled reroute options.",
                "Confirm correspondent bank and beneficiary screening status before any payment action.",
            ],
            review_required=review_required,
            rationale=f"Liquidity-at-risk proxy amount is {total_amount:,.0f} across at-risk pending payments.",
            metadata={"at_risk_payments": at_risk_payments, "liquidity_at_risk_amount": total_amount},
        )


def _days_between(base: date, value: str) -> int | None:
    try:
        return (date.fromisoformat(value) - base).days
    except ValueError:
        return None


def _float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0
