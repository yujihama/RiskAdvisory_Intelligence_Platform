# Risk Advisory Seed Expert Knowledge Pack

This folder contains an initial Expert-as-Code seed pack for the RiskAdvisory Intelligence Platform.

It is designed to be copied into:

```text
data/expert_knowledge/
```

Expected files:

```text
rules.jsonl
cases.jsonl
questions.jsonl
cta_notes.jsonl
```

Additional optional files:

```text
primitives.jsonl
knowledge_pack_version.json
source_refs.json
source_reliability_seed.yaml
scope_relevance_rules.jsonl
decision_consolidation_rules.jsonl
```

## Scope

This pack is generated from public standards, official guidance, risk-management research, and general risk advisory practice. It is intended as a **bootstrap pack** before client-specific expert interviews and case-answer collection are available.

It should be treated as:

- expert-style seed knowledge
- not final legal, accounting, sanctions, treasury, tax, or audit advice
- not a substitute for expert review
- suitable for Expert-as-Code Agent search, red-flag extraction, rubric selection, and Decision Queue support

## Domain coverage

| Domain | Main coverage |
|---|---|
| cross_functional | evidence standards, Unknown/Assumption handling, red-team review, cascades |
| treasury | cash mobility, trapped cash, supplier payments, liquidity-at-risk |
| legal | sanctions proximity, beneficial ownership, contract notices, force majeure, export-control red flags |
| accounting | IAS 37-style provision triggers, IAS 10 subsequent events, IAS 36 impairment, disclosure pressure |
| procurement | single-source dependency, sub-tier visibility, inventory runway, substitution friction |
| executive | decision urgency, operational resilience, cross-mode conflicts, decision-first output |

## Loading

Current repository code reads:

```text
data/expert_knowledge/rules.jsonl
data/expert_knowledge/cases.jsonl
data/expert_knowledge/questions.jsonl
data/expert_knowledge/cta_notes.jsonl
data/expert_knowledge/primitives.jsonl
data/expert_knowledge/knowledge_pack_version.json
data/expert_knowledge/source_refs.json
data/expert_knowledge/source_reliability_seed.yaml
data/expert_knowledge/scope_relevance_rules.jsonl
data/expert_knowledge/decision_consolidation_rules.jsonl
```

Then call:

```text
mcp-expert-knowledge.index_knowledge_pack
mcp-expert-knowledge.index_case_bank
```

## Counts

- KnowledgeObject rows: 41
- ExpertCase rows: 14
- ExpertQuestion rows: 24
- CTANote rows: 11
- KnowledgePrimitive rows: 20
- ScopeRelevanceRule rows: 10
- DecisionConsolidationRule rows: 4

## Provenance

See `source_refs.json` for source URLs and short notes. The pack draws primarily on:

- ISO 31000 / ISO 31050 / ISO 22301
- NIST CSF 2.0 and NIST SP 800-161
- OFAC sanctions compliance framework and 50 Percent Rule FAQ
- EU and UK sanctions guidance
- BIS export-control red-flag guidance
- IFRS IAS 37, IAS 10, IAS 36, IFRS S1
- BCBS operational resilience principles
- AFP / treasury liquidity references
- CISA / Everstream supply-chain visibility references

## Recommended next step

After expert interviews, do not overwrite this pack blindly. Instead:

1. Add expert responses as new `ExpertResponse` records.
2. Add CTA notes as new `CTANote` records.
3. Promote only validated conclusions into new `KnowledgeObject` versions.
4. Keep `seed-*` IDs as baseline references and create client/industry-specific IDs separately.
