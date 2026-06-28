# Risk Discovery Portfolio Summary: Iran war escalation affecting supplier payments

- Client: `demo_client`
- Scope: `department` `Treasury`
- Discovery confidence: `agent_recorded_candidates`
- Fallback used: `False`
- Selected candidates: 1
- Rejected candidates: 0
- Analyses executed: 1

## Portfolio Overview
- Completed analyses: 1 / 1
- Failed analyses: 0
- Total decisions: 1
- Total evidence records: 5
- Risk types: supplier_resilience
- Evidence domains: govinfo.gov, home.treasury.gov, ismworld.org, ofac.treasury.gov, oxfordcollegeofprocurementandsupply.com
- Review-required scenarios: 1

## Priority Decisions
- `scenario_discovered_demo_client_iran_war_escalation_affecting_supplier_payments_disc_001` Decide whether to continue, hold, or reroute high-risk supplier payments under controlled approval. (owner=CFO / Legal / Procurement, priority=1, review_required=True)

## Consolidated Decisions
- `payment_execution` Decide whether to continue, hold, or reroute high-risk supplier payments under controlled approval. (owners=CFO / Legal / Procurement, required=Treasury, Legal, owner_gap=Treasury, Legal, deadlines=24 hours, sources=1)

## Decision Conflicts
- `payment_execution` Required owner is missing from consolidated decision. (owners=CFO / Legal / Procurement, missing=Treasury, Legal, deadlines=24 hours)

## Selected Candidates
- `DISC-001` Iran sanctions escalation disrupts supplier payments and triggers compliance exposure (score=100, type=supplier_resilience)

## Rejected Candidates
- None

## Scenario Analyses
### Iran sanctions escalation disrupts supplier payments and triggers compliance exposure
- Scenario ID: `scenario_discovered_demo_client_iran_war_escalation_affecting_supplier_payments_disc_001`
- Status: `completed`
- Trace ID: `1c885781-4307-44e7-a590-cb0a1e309395`
- Output: `C:\Users\nyham\work\risk_analysis_platform\outputs\scenario_discovered_demo_client_iran_war_escalation_affecting_supplier_payments_disc_001`
- Decisions: 1
- Evidence: 5
- Decision: Decide whether to continue, hold, or reroute high-risk supplier payments under controlled approval.
