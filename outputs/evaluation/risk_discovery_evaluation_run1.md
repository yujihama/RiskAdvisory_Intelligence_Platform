# Risk Discovery Evaluation

- Passed: `False`
- Cases: 4
- Average recall: 0.438
- Forbidden top violations: 0
- Average question match: 0.519
- Average question semantic match: 0.519
- Average missing-data category match: 0.500
- Average selected/rejected reason quality: 1.000
- Average expert rubric coverage: 1.000

## Cases
### rdc_treasury_iran_payment_001
- Passed: `False`
- Recall: 0.000
- Question match: 0.031
- Question semantic match: 0.031
- Missing-data category match: 0.000
- Reason quality: 1.000
- Expert rubric coverage: 1.000
- Selected risk types: supplier_resilience, supplier_resilience, supplier_resilience
- Forbidden in top: None
- Missing-data category hits: None
- Rubric hits: SCOPE-DEPT-TREASURY-001
- Discovery confidence: `agent_recorded_candidates`
### rdc_legal_sanctions_contract_001
- Passed: `False`
- Recall: 0.000
- Question match: 0.045
- Question semantic match: 0.045
- Missing-data category match: 0.000
- Reason quality: 1.000
- Expert rubric coverage: 1.000
- Selected risk types: supplier_resilience, supplier_resilience, accounting_disclosure
- Forbidden in top: None
- Missing-data category hits: None
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
- Selected risk types: supplier_resilience, supplier_resilience, executive_resilience, payment_disruption
- Forbidden in top: None
- Missing-data category hits: evidence_gap, executive_ownership, payment_route, supplier_continuity
- Rubric hits: SCOPE-IND-MANUFACTURING-001
- Discovery confidence: `agent_recorded_candidates`
