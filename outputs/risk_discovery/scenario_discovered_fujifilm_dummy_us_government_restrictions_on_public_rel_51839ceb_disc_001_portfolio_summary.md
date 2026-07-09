# Risk Discovery Portfolio Summary: US government restrictions on public release of frontier LLM models

- Client: `fujifilm_dummy`
- Scope: `company` `Fujifilm enterprise AI and LLM use across software development, document automation, customer support, R&D, regulated data processing, cloud AI procurement, legal compliance, information security, business continuity, and international operations.`
- Discovery confidence: `agent_recorded_candidates`
- Fallback used: `False`
- Selected candidates: 6
- Rejected candidates: 0
- Analyses executed: 4

## Portfolio Overview
- Completed analyses: 0 / 4
- Failed analyses: 4
- Total decisions: 4
- Total evidence records: 20
- Risk types: legal_compliance
- Evidence domains: alston.com, contractken.com, csis.org, datamatters.sidley.com, en.wikipedia.org, fdassociates.net, federalregister.gov, freshfields.com, inboundlogistics.com, jdsupra.com, justice.gov, kslaw.com, lexisnexis.com, mofo.com, research.columbia.edu, scoperecruiting.com, wsgr.com
- Review-required scenarios: 4

## Priority Decisions
- `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_001` Decide whether to freeze new frontier-model API deployments, notify affected product owners, and activate approved fallback model or provider paths. (owner=AI Platform / Legal / Procurement, priority=1, review_required=True)
- `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_004` Decide whether each country, user group, and model-access path is permitted under current AI export-control obligations before continued use. (owner=Legal / Compliance / AI Governance, priority=1, review_required=True)
- `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_002` Decide whether each country, user group, and model-access path is permitted under current AI export-control obligations before continued use. (owner=Legal / Compliance / AI Governance, priority=2, review_required=True)
- `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_003` Decide whether the AI continuity plan still has an approved fallback model source if open-weight distribution is restricted. (owner=AI Platform / Procurement / Information Security, priority=4, review_required=True)

## Consolidated Decisions
- `sanctions_review` Decide whether the AI continuity plan still has an approved fallback model source if open-weight distribution is restricted. (owners=AI Governance, AI Platform, Compliance, Information Security, Legal, Procurement, required=Legal, owner_gap=None, deadlines=24 hours, 48 hours, 5 business days, sources=3)
- `decide_whether_freeze_frontier_model` Decide whether to freeze new frontier-model API deployments, notify affected product owners, and activate approved fallback model or provider paths. (owners=AI Platform, Legal, Procurement, required=None, owner_gap=None, deadlines=24 hours, sources=1)

## Decision Conflicts
- `sanctions_review` Potential duplicate decision with different owner or deadline. (owners=AI Governance, AI Platform, Compliance, Information Security, Legal, Procurement, missing=None, deadlines=24 hours, 48 hours, 5 business days)

## Selected Candidates
- `DISC-001` Cloud AI Platform Frontier Model API Withdrawal (score=100, type=legal_compliance)
- `DISC-002` Export Control Violation from International AI Deployments (score=100, type=legal_compliance)
- `DISC-003` Open-Weight Frontier Model Supply Disruption for On-Premise AI (score=100, type=legal_compliance)
- `DISC-004` VEU Certification Compliance Program Burden (score=100, type=legal_compliance)
- `DISC-005` Cloud AI Vendor Consolidation and Procurement Cost Escalation (score=100, type=legal_compliance)
- `DISC-AUG-scope_text_primary-supplier_resilience` Supplier continuity coverage: US government restrictions on public release of frontier LLM models (score=100, type=supplier_resilience)

## Rejected Candidates
- None

## Scenario Analyses
### Cloud AI Platform Frontier Model API Withdrawal
- Scenario ID: `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_001`
- Status: `failed`
- Trace ID: `f6e80710-e73e-4395-8c35-78f9fddab6f6`
- Output: `C:\Users\nyham\work\risk_analysis_platform\outputs\scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_001`
- Decisions: 1
- Evidence: 5
- Decision: Decide whether to freeze new frontier-model API deployments, notify affected product owners, and activate approved fallback model or provider paths.
### Export Control Violation from International AI Deployments
- Scenario ID: `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_002`
- Status: `failed`
- Trace ID: `c2f60ce6-0e37-4b10-8b77-b8e12c2291d6`
- Output: `C:\Users\nyham\work\risk_analysis_platform\outputs\scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_002`
- Decisions: 1
- Evidence: 5
- Decision: Decide whether each country, user group, and model-access path is permitted under current AI export-control obligations before continued use.
### Open-Weight Frontier Model Supply Disruption for On-Premise AI
- Scenario ID: `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_003`
- Status: `failed`
- Trace ID: `3a828921-f9f1-4af4-b238-2fdf4c1043c0`
- Output: `C:\Users\nyham\work\risk_analysis_platform\outputs\scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_003`
- Decisions: 1
- Evidence: 5
- Decision: Decide whether the AI continuity plan still has an approved fallback model source if open-weight distribution is restricted.
### VEU Certification Compliance Program Burden
- Scenario ID: `scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_004`
- Status: `failed`
- Trace ID: `614ca003-24e1-42db-8b0b-005c9daf4386`
- Output: `C:\Users\nyham\work\risk_analysis_platform\outputs\scenario_discovered_fujifilm_dummy_us_government_restrictions_on_public_rel_51839ceb_disc_004`
- Decisions: 1
- Evidence: 5
- Decision: Decide whether each country, user group, and model-access path is permitted under current AI export-control obligations before continued use.
