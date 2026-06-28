# Risk Discovery Evaluation

- Passed: `True`
- Cases: 4
- Average recall: 0.938
- Forbidden top violations: 0
- Average question match: 1.000
- Average question semantic match: 1.000
- Average missing-data category match: 1.000
- Average selected/rejected reason quality: 1.000
- Average expert rubric coverage: 1.000

## Cases
### rdc_treasury_iran_payment_001
- Passed: `True`
- Recall: 1.000
- Question match: 1.000
- Question semantic match: 1.000
- Missing-data category match: 1.000
- Reason quality: 1.000
- Expert rubric coverage: 1.000
- Selected risk types: payment_disruption, supplier_resilience, payment_disruption
- Forbidden in top: None
- Missing-data category hits: payment_route, sanctions_screening
- Rubric hits: SCOPE-DEPT-TREASURY-001
- Discovery confidence: `agent_recorded_candidates`
### rdc_legal_sanctions_contract_001
- Passed: `True`
- Recall: 1.000
- Question match: 1.000
- Question semantic match: 1.000
- Missing-data category match: 1.000
- Reason quality: 1.000
- Expert rubric coverage: 1.000
- Selected risk types: legal_compliance, supplier_resilience, accounting_disclosure
- Forbidden in top: None
- Missing-data category hits: contract_terms, sanctions_screening
- Rubric hits: SCOPE-DEPT-LEGAL-001
- Discovery confidence: `agent_recorded_candidates`
### rdc_accounting_disclosure_001
- Passed: `True`
- Recall: 1.000
- Question match: 1.000
- Question semantic match: 1.000
- Missing-data category match: 1.000
- Reason quality: 1.000
- Expert rubric coverage: 1.000
- Selected risk types: accounting_disclosure, accounting_disclosure, accounting_disclosure
- Forbidden in top: None
- Missing-data category hits: evidence_gap, materiality_reporting
- Rubric hits: SCOPE-DEPT-ACCOUNTING-001
- Discovery confidence: `agent_recorded_candidates`
### rdc_executive_manufacturing_portfolio_001
- Passed: `True`
- Recall: 0.750
- Question match: 1.000
- Question semantic match: 1.000
- Missing-data category match: 1.000
- Reason quality: 1.000
- Expert rubric coverage: 1.000
- Selected risk types: supplier_resilience, executive_resilience, payment_disruption, accounting_disclosure
- Forbidden in top: None
- Missing-data category hits: evidence_gap, executive_ownership, payment_route, supplier_continuity
- Rubric hits: SCOPE-IND-MANUFACTURING-001
- Discovery confidence: `agent_recorded_candidates`
