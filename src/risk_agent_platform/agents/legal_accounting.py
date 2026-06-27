from __future__ import annotations

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.agents.base import BaseAgent
from risk_agent_platform.schemas import AgentFinding, AgentTask


class LegalAccountingAgent(BaseAgent):
    name = "legal-accounting-agent"
    description = "Analyzes legal, regulatory, accounting, and disclosure implications."
    skills = ["contract_risk", "sanctions_clause", "accounting_disclosure"]
    modes = ["legal", "accounting"]

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        event = context.risk_event
        dataset = context.state.get("client_dataset") or context.structured_data.load_client_dataset(event.client_id)
        assert isinstance(dataset, dict)
        suppliers = {row["supplier_id"]: row for row in dataset.get("suppliers", [])}
        risk_countries = {country.lower() for country in event.countries}
        at_risk_supplier_ids = {
            supplier_id
            for supplier_id, supplier in suppliers.items()
            if supplier.get("country", "").lower() in risk_countries or supplier.get("criticality", "").lower() == "high"
        }

        contracts = [row for row in dataset.get("contracts", []) if row.get("supplier_id") in at_risk_supplier_ids]
        issues: list[str] = []
        unknowns: list[str] = []
        for contract in contracts:
            if contract.get("sanctions_clause", "").lower() == "true":
                issues.append(f"{contract['contract_id']} has sanctions clause implications.")
            if contract.get("notice_days"):
                issues.append(f"{contract['contract_id']} has notice period of {contract['notice_days']} days.")
            if contract.get("force_majeure_clause", "").lower() == "true":
                issues.append(f"{contract['contract_id']} has force majeure language to review.")
        missing_contracts = at_risk_supplier_ids - {row.get("supplier_id") for row in contracts}
        for supplier_id in sorted(missing_contracts):
            unknowns.append(f"No contract record found for affected supplier {supplier_id}.")

        treasury_payments = context.state.get("treasury_at_risk_payments", [])
        material_amount = sum(float(row.get("amount", 0) or 0) for row in treasury_payments if isinstance(row, dict))
        if material_amount >= 1_000_000:
            issues.append("At-risk pending payments exceed the demo materiality threshold for disclosure triage.")

        score = min(100, 25 + len(issues) * 12 + len(unknowns) * 8)
        context.state["legal_accounting_issues"] = issues
        return AgentFinding(
            agent_name=self.name,
            mode="legal_accounting",
            summary=f"Found {len(issues)} legal/accounting issues and {len(unknowns)} unresolved data gaps.",
            risk_score=score,
            confidence="medium" if contracts else "low",
            evidence_ids=[item.evidence_id for item in context.evidence_ledger.items],
            assumptions=["Demo materiality threshold is 1,000,000 in payment currency units."],
            unknowns=unknowns,
            recommended_actions=[
                "Review sanctions, notice, termination, and force majeure clauses with Legal.",
                "Prepare accounting/disclosure triage if payment or supply disruption becomes probable.",
            ],
            review_required=score >= 50 or bool(unknowns),
            rationale="Legal-accounting bridge flags clauses and materiality-sensitive exposure for joint review.",
            metadata={"issues": issues, "material_amount": material_amount},
        )
