# Risk Discovery Portfolio Summary: 台湾有事

- Client: `fujifilm_dummy`
- Scope: `company` `富士フイルムの物流。海上輸送、航空輸送、港湾、通関、3PL、重要部材の輸送遅延、代替ルートを含む。`
- Discovery confidence: `agent_recorded_candidates`
- Fallback used: `False`
- Selected candidates: 1
- Rejected candidates: 4
- Analyses executed: 1

## Portfolio Overview
- Completed analyses: 1 / 1
- Failed analyses: 0
- Total decisions: 1
- Total evidence records: 5
- Risk types: supplier_resilience
- Evidence domains: financialprofessionals.org, henryjacksonsociety.org, ibuyxs.com, interos.ai, wild-tech.com
- Review-required scenarios: 1

## Priority Decisions
- `scenario_discovered_fujifilm_dummy_070419c9_disc_001` Decide whether to activate logistics continuity actions for critical materials and customer shipments. (owner=Procurement / Operations / Logistics, priority=1, review_required=True)

## Consolidated Decisions
- `supplier_continuity` Decide whether to activate logistics continuity actions for critical materials and customer shipments. (owners=Logistics, Operations, Procurement, required=Procurement, Operations, owner_gap=None, deadlines=24 hours, sources=1)

## Decision Conflicts
- None

## Selected Candidates
- `DISC-001` 台湾有事による海上・航空輸送ルートの分断と物流遅延 (score=100, type=supplier_resilience)

## Rejected Candidates
- `DISC-003` 3PLプロバイダーの機能停止による物流代行サービスの中断 (score=100): Moved below threshold by scope diversity pass: duplicate selected risk_type `supplier_resilience` was demoted so scope-primary coverage can remain visible. Original relevance score was 100; selection threshold was 40.
- `DISC-005` 代替ルートへの転換遅延による物流ボトルネック (score=100): Moved below threshold by scope diversity pass: duplicate selected risk_type `supplier_resilience` was demoted so scope-primary coverage can remain visible. Original relevance score was 100; selection threshold was 40.
- `DISC-002` 港湾機能停止および通関手続きの遅延 (score=90): Moved below threshold by scope diversity pass: duplicate selected risk_type `supplier_resilience` was demoted so scope-primary coverage can remain visible. Original relevance score was 90; selection threshold was 40.
- `DISC-004` 重要部材の輸送遅延による生産停止リスク (score=90): Moved below threshold by scope diversity pass: duplicate selected risk_type `supplier_resilience` was demoted so scope-primary coverage can remain visible. Original relevance score was 90; selection threshold was 40.

## Scenario Analyses
### 台湾有事による海上・航空輸送ルートの分断と物流遅延
- Scenario ID: `scenario_discovered_fujifilm_dummy_070419c9_disc_001`
- Status: `completed`
- Trace ID: `342cf3e8-c790-484f-a502-daf8578821ce`
- Output: `C:\Users\nyham\work\risk_analysis_platform\outputs\scenario_discovered_fujifilm_dummy_070419c9_disc_001`
- Decisions: 1
- Evidence: 5
- Decision: Decide whether to activate logistics continuity actions for critical materials and customer shipments.
