# Risk Advisory Intelligence Platform

This repository implements a working slice of the target architecture described in `docs/`. Some target-architecture items are intentionally still partial and are listed under Known Constraints.

The normal execution path is:

```text
CLI / API
  -> optional Risk Discovery DeepAgent for event + scope intake
  -> Orchestrator DeepAgent
  -> A2A SDK-shaped Agent Cards + A2A-compatible HTTP task requests
  -> Domain DeepAgents
  -> Bounded DeepAgent tool-use slots + audited FastMCP tool calls
  -> Tavily / Qdrant / Neo4j / Files / Evidence Ledger / Expert Knowledge
  -> Decision Queue + Executive Brief + Evidence Summary
```

The current execution path is `python -m risk_agent_platform.run_scenario` or `risk-agent-platform run-scenario`.
For event-and-scope intake, use `risk-agent-platform discover-risks`; with `--run-analysis`, all threshold-selected discovered risks are converted to `RiskEvent` items by default and passed into the same scenario analysis path. The CLI also writes a portfolio summary that integrates the per-risk outputs.

## Architecture Diagrams

See [docs/architecture_diagrams.md](docs/architecture_diagrams.md).

## Agents

The following A2A agents are implemented as DeepAgent-backed services:

- `orchestrator-agent`
- `risk-discovery-agent` (front-stage DeepAgent used by the CLI before Orchestrator)
- `source-intelligence-agent`
- `client-context-agent`
- `treasury-risk-agent`
- `legal-risk-agent`
- `accounting-risk-agent`
- `procurement-risk-agent`
- `expert-as-code-agent`
- `evidence-redteam-agent`
- `decision-synthesis-agent`

Each service exposes:

- `/.well-known/agent-card.json`
- `/a2a`
- `/healthz`

`/.well-known/agent-card.json` is emitted through the installed `a2a-sdk` v0.3 `AgentCard` model. The `/a2a` task endpoint remains an A2A-compatible HTTP boundary using the project `AgentTaskRequest` / `AgentTaskResult` schemas, rather than a full SDK server transport.

## MCP Servers

FastMCP servers are implemented for:

- `mcp-web-search`
- `mcp-document-parser`
- `mcp-llm-ocr`
- `mcp-qdrant`
- `mcp-neo4j`
- `mcp-filesystem`
- `mcp-structured-data`
- `mcp-expert-knowledge`
- `mcp-evidence-ledger`

Agents call tools through `MCPGateway`, which uses FastMCP `Client`.

Bounded Autonomy is implemented in the normal path:

- Risk Discovery accepts an external event and scope, samples client structured data through `risk_feature_sample` feature views, loads Expert-as-Code seed knowledge, can use bounded Tavily search/extraction through `mcp-web-search` to record `event_facts`, applies `data/expert_knowledge/scope_relevance_rules.jsonl`, generates `selected_candidates` and `rejected_candidates`, and converts every threshold-selected candidate into `selected_events`. `selected_event` remains the top event for compatibility.
- Orchestrator asks DeepAgent for an `analysis_plan` JSON with `selected_agents`, `skipped_agents`, `recheck_conditions`, and `exploration_questions`; invalid plans fall back to the fixed agent order.
- Source Intelligence uses DeepAgent tool-use for bounded sanitized search and URL extraction, then Python registers selected `EvidenceItem` records through Evidence Ledger.
- Expert-as-Code uses DeepAgent tool-use to explore similar cases, rubrics, red flags, CTA notes, and counterfactuals, then emits a structured `KnowledgeApplicationFinding` inside the A2A finding metadata.
- Evidence / Red Team uses DeepAgent tool-use for evidence search, contradiction search, missing-data detection, and overclaim detection; it does not write the Decision Queue.
- Treasury, Legal, and Accounting keep final scores and review flags in structured Python logic, with a small DeepAgent issue-exploration slot for hypotheses and recheck questions.

## Required Environment Variables

Copy `.env.example` to `.env` and fill in real values.

OpenRouter:

```env
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
DEFAULT_MODEL=qwen/qwen3.6-flash
FAST_MODEL=qwen/qwen3.6-flash
REASONING_MODEL=qwen/qwen3.6-flash
LONG_CONTEXT_MODEL=qwen/qwen3.6-flash
RISK_DISCOVERY_MODEL=qwen/qwen3.7-max
OCR_MODEL=qwen/qwen2.5-vl-72b-instruct
REDTEAM_MODEL=qwen/qwen3.6-flash
EXPERT_SYNTHESIS_MODEL=qwen/qwen3.6-flash
```

Tavily:

```env
TAVILY_API_KEY=
```

Stores:

```env
QDRANT_URL=http://localhost:6333
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

Embeddings:

```env
EMBEDDING_PROVIDER=openrouter
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_FALLBACK_TO_DETERMINISTIC=true
```

Qdrant now uses an `EmbeddingProvider` interface. The default attempts OpenRouter-compatible real embeddings and normalizes vectors to the current 384-dimensional Qdrant collections. Deterministic embeddings remain available for tests and local reproducibility with `EMBEDDING_PROVIDER=deterministic`; if the real embedding endpoint is unavailable and fallback is enabled, deterministic fallback is used.

Langfuse:

```env
LANGFUSE_HOST=http://localhost:3300
LANGFUSE_PUBLIC_KEY=lf_pk_risk_advisory_local
LANGFUSE_SECRET_KEY=lf_sk_risk_advisory_local
```

Docker Compose initializes a local Langfuse org/project with the default local keys above. Change the `LANGFUSE_INIT_*` values before using this outside a local development environment.

## Start Services

For store verification:

```powershell
docker compose up -d qdrant neo4j
```

For the full architecture:

```powershell
docker compose up -d
```

Langfuse self-host services are included in `docker-compose.yml`.
The local UI is exposed at `http://localhost:3300` to avoid collisions with common frontend dev servers on port 3000.

## Platform API

The external REST boundary (roadmap F1) wraps the same discovery/scenario pipelines as the CLI:

```powershell
risk-agent-platform serve-api --host 127.0.0.1 --port 8080
```

Endpoints:

- `POST /v1/discoveries` — submit a discovery job (mirrors `discover-risks` parameters); returns `202` with a `job_id`.
- `POST /v1/scenarios` — submit a scenario job from an inline `RiskEvent` or a path under `data/scenarios/`.
- `GET /v1/jobs/{job_id}` / `GET /v1/jobs?status=` — job status (`submitted -> working -> completed|failed`).
- `GET /v1/scenarios/{scenario_id}/artifacts` and `GET /v1/scenarios/{scenario_id}/artifacts/{name}` — list and fetch output artifacts.
- `GET /healthz` — liveness.

Job state persists in SQLite at `outputs/api_jobs.sqlite3` (override with `PLATFORM_API_JOB_DB`). Jobs left `submitted`/`working` by a previous process are marked `failed` with `orphaned_by_restart` on startup. Each job records a `trace_id` and emits `api_job.*` events through the existing trace recorder. OpenAPI docs are served at `/docs`.

## Run Preflight

```powershell
risk-agent-platform preflight
```

This reports missing keys without printing secret values.

## Run Sample Scenario

Event-and-scope discovery only:

```powershell
risk-agent-platform discover-risks `
  --event-title "Iran war escalation affecting supplier payments" `
  --event-description "Shipping, sanctions screening, and supplier payments may be disrupted." `
  --client-id demo_client `
  --scope-type department `
  --scope-name Treasury `
  --department Treasury `
  --industry manufacturing `
  --country Iran `
  --embedded-services
```

Natural-language scope discovery and end-to-end analysis:

```powershell
risk-agent-platform discover-risks `
  --event-title "Taiwan contingency" `
  --event-description "A Taiwan Strait contingency may disrupt sea and air logistics, export controls, supplier continuity, site operations, customer shipments, and cross-border payments." `
  --client-id fujifilm_dummy `
  --scope-text "富士フイルムの物流。海上輸送、航空輸送、港湾、通関、3PL、重要部材の輸送遅延、代替ルートを含む。" `
  --country Taiwan `
  --run-analysis `
  --embedded-services
```

`--scope-text` is the preferred input for generic business scopes. It does not require `--department` or `--scope-name`; Risk Discovery records a `scope_interpretation` and uses it for candidate generation, relevance scoring, coverage augmentation, and debug output. `--department` and `--scope-name` remain available for backward-compatible structured cases.

During Discovery, the DeepAgent may call `discovery_search_event_context` and `discovery_extract_event_source` through the existing `mcp-web-search` Tavily MCP. These calls are bounded to 3 searches and 3 URL extractions, avoid client-specific query terms, and are summarized into `metadata.event_facts`, `metadata.web_searches`, and `metadata.web_extractions` so candidate recall can use real external event context before downstream evidence collection begins.

Risk Discovery uses the `risk_discovery` model profile, which defaults to `qwen/qwen3.7-max` and can be overridden with `RISK_DISCOVERY_MODEL`.

`--analysis-mode all-selected` is the default and analyzes every selected RiskEvent when `--run-analysis` is used. `--analysis-mode auto` remains available when a caller explicitly wants natural-language `--scope-text` runs narrowed to the interpreted scope-primary risk types.

Discovery followed by scenario analysis for all selected candidates:

```powershell
risk-agent-platform discover-risks `
  --event-title "Iran war escalation affecting supplier payments" `
  --event-description "Shipping, sanctions screening, and supplier payments may be disrupted." `
  --client-id demo_client `
  --scope-type department `
  --scope-name Treasury `
  --department Treasury `
  --industry manufacturing `
  --country Iran `
  --run-analysis `
  --embedded-services
```

`--analysis-mode all-selected` is the default. Use `--analysis-mode top` for the previous one-risk behavior, or `--analysis-mode top-n --top-n 2` to cap the number of selected risks analyzed. `--max-risks` defaults to 5 and is guidance to the DeepAgent for candidate generation, not the final selected count. Final selected candidates are determined by the scope relevance threshold, so more than `--max-risks` can be selected. The number of analyzed risks is controlled by `--analysis-mode` and `--top-n`. Scenario analysis runs selected RiskEvents with `--analysis-concurrency 5` by default; each scenario is analyzed in parallel up to that limit, while each scenario's internal agent delegation still follows the Orchestrator plan order. Same-risk-type scenarios are preserved when their disruption mechanism differs, so logistics, 3PL, customs, critical components, routing, regulatory, or payment pathways can remain separate even if they share a canonical `risk_type`. If Discovery uses template fallback candidates, `--run-analysis` is blocked unless `--allow-fallback-analysis` is explicitly supplied. When multiple risks are analyzed, `outputs/risk_discovery/<top_scenario_id>_portfolio_summary.json` and `.md` integrate the selected/rejected candidates, Discovery metadata, per-scenario status, Decisions, Evidence counts, review-required scenarios, priority Decisions, consolidated similar Decisions, owner/deadline grouping, and potential owner/deadline conflicts.

Discovery quality evaluation:

```powershell
risk-agent-platform evaluate-discovery `
  --cases data\evaluation\risk_discovery_cases.jsonl `
  --embedded-services
```

This runs each evaluation case through Risk Discovery, calculates expected risk-type recall, checks whether `should_not_prioritize` risk types appear in the top results, compares expected questions against Discovery `additional_questions` / `unknowns`, checks missing-data category coverage, scores selected/rejected reason quality, and measures Expert-as-Code rubric coverage.

Local embedded A2A/MCP endpoints:

```powershell
python -m risk_agent_platform.run_scenario --scenario data\scenarios\sample_geopolitical_payment_risk.json --embedded-services
risk-agent-platform run-scenario --scenario data\scenarios\sample_geopolitical_payment_risk.json --embedded-services
```

Docker services:

```powershell
python -m risk_agent_platform.run_scenario --scenario data\scenarios\sample_geopolitical_payment_risk.json
```

Live Tavily/OpenRouter scenario with the included `live_demo_client` fixture:

```powershell
$env:LANGFUSE_HOST='http://localhost:3300'
$env:LANGFUSE_PUBLIC_KEY='lf_pk_risk_advisory_local'
$env:LANGFUSE_SECRET_KEY='lf_sk_risk_advisory_local'
python -m risk_agent_platform.run_scenario --scenario data\scenarios\live_geopolitical_payment_risk.json --embedded-services
```

Expected outputs:

- `outputs/risk_discovery/<scenario_id>.json`
- `outputs/<scenario_id>/final_brief.md`
- `outputs/<scenario_id>/decision_queue.json`
- `outputs/<scenario_id>/evidence_summary.json`
- `outputs/<scenario_id>/red_team_review.md`
- `outputs/<scenario_id>/assumptions_and_unknowns.json`
- `outputs/<scenario_id>/trace_metadata.json`
- `outputs/<scenario_id>/runs/<run_id>.json` (scenario delta ledger snapshot)
- `outputs/<scenario_id>/deltas/<run_id>.json` and `outputs/<scenario_id>/deltas/<run_id>_summary.md` (scenario delta ledger, from the second run onward)
- `outputs/_traces/<trace_id>.jsonl`

## Scenario Delta Ledger

Every completed scenario run (roadmap F2), whether started through `run_scenario.execute_scenario` or the `discover-risks --run-analysis` path, snapshots its comparable state (Evidence IDs with reliability/confidence, per-agent risk scores and review flags, Decisions, assumptions, unknowns, and the `analysis_plan`/per-domain `recheck_conditions`) to `outputs/<scenario_id>/runs/<run_id>.json`. `run_id` is a sortable, unique timestamp-based identifier.

Each run is diffed deterministically (no LLM) against the most recent prior snapshot for the same scenario:

- Evidence is matched by `evidence_id`; new/removed IDs become `evidence_added`/`evidence_removed`.
- Per-agent risk scores are compared by `agent_name` when both runs have a score and it changed.
- Decisions are matched by `decision_id` (falling back to the decision text when `decision_id` is absent); additions, removals, and changes to owner/deadline/priority/review_required/rationale are recorded as `decision_changes`.
- Assumptions with an `expires_at` in the past, or that disappeared from the latest run while still carrying an `expires_at`, are listed in `assumption_expirations`.
- Unknowns present in the previous run but no longer present are listed in `unknown_resolutions`.

The result is written to `outputs/<scenario_id>/deltas/<run_id>.json` (a `ScenarioDelta`) plus a human-readable `outputs/<scenario_id>/deltas/<run_id>_summary.md`; the first run for a scenario is written as `baseline: true` with empty change lists, and a run with no detected changes states so explicitly ("No changes detected since the previous run.") rather than leaving the summary empty.

Each run also consumes the previous run's `recheck_conditions`: they are loaded before the run and passed to the orchestrator as `task.inputs["previous_recheck_conditions"]` so the analysis plan step can see them, then evaluated deterministically against the computed delta (keyword heuristics for evidence/score/decision-shaped conditions; anything else is recorded as `not_evaluable` rather than guessed) and recorded in `recheck_triggers_fired`.

Delta recording is best-effort and never fails scenario analysis: failures are caught, logged, and — where possible — recorded as a `degraded: true` delta with a `degraded_reason` instead of leaving partial output. The delta is also registered as a best-effort `ScenarioDelta` node linked to its scenario in Neo4j; a store failure only logs a warning. Delta artifacts (`deltas/<run_id>.json` and `deltas/<run_id>_summary.md`) are listed and served by the Platform API's `GET /v1/scenarios/{scenario_id}/artifacts` endpoints alongside the other scenario artifacts.

## Evidence Ledger

Source Intelligence plans bounded query themes, runs multiple sanitized Tavily searches, extracts selected URLs, assigns an initial source reliability score, normalizes results into `EvidenceItem`, stores them in JSONL, indexes them into Qdrant, and links them to scenarios/assets/decisions through Neo4j MCP tools.

If `TAVILY_API_KEY` is absent, web evidence collection fails explicitly. There is no local fixture fallback in the normal path.

Initial source reliability scoring is domain-based: government, regulator, international organization, and official disclosure sources are scored `high`; general news or research sources are `medium`; blog-like sources are `low`.

## Expert-as-Code

Expert knowledge is represented as structured Knowledge Objects, Knowledge Primitives, case bank entries, question bank entries, CTA notes, scope relevance rules, decision consolidation rules, source references, source reliability seeds, and pack version metadata. The Expert-as-Code Agent indexes `data/expert_knowledge/rules.jsonl`, `data/expert_knowledge/primitives.jsonl`, `data/expert_knowledge/cases.jsonl`, and decision consolidation rules into Qdrant, explores relevant cases/rubrics/red flags/CTA notes/counterfactuals through DeepAgent tools, and reflects selected IDs in the Decision Queue.

Risk Discovery scope filtering is also Expert-as-Code driven: `data/expert_knowledge/scope_relevance_rules.jsonl` defines what Treasury, Legal, Accounting, Procurement, business units, and industries treat as risk-relevant. Rejected candidates are preserved with a reason and relevance score so specialist reviewers can challenge false negatives.

Portfolio Decision consolidation is Expert-as-Code driven by `data/expert_knowledge/decision_consolidation_rules.jsonl`. Consolidated Decisions retain the matched rule ID, required owners, primary/secondary owners, rationale, and owner gaps for management review.

Risk Discovery evaluation cases live in `data/evaluation/risk_discovery_cases.jsonl`. Each case includes input event/scope, expected selected risk types, risk types that should not be prioritized, expected follow-up questions, expected missing-data categories, and expected Expert-as-Code rubric IDs.

Structured-data MCP tools include LLM-safe summaries: `summarize_payment_exposure_safe`, `summarize_supplier_exposure_safe`, `summarize_invoice_exposure_safe`, and `summarize_contract_exposure_safe`. They return bucketed features and aggregate signals instead of raw rows. DeepAgent tool-use is governed by `src/risk_agent_platform/tool_policy.py`: LLM slots receive safe tools only, while raw rows and raw exposure tools remain available to deterministic Python logic.

## Document Parsing and OCR

`mcp-document-parser` uses a Docling-first parser chain with Unstructured, PyMuPDF, and text fallbacks. `mcp-llm-ocr` invokes the configured OpenRouter `vision_ocr` profile when an image or PDF page is supplied, and fails explicitly if no OCR input is provided.

Docling and Unstructured can be installed for richer parsing with:

```powershell
python -m pip install -e ".[documents]"
```

## Validation

Current checks:

```powershell
python -m compileall src tests
pytest
docker compose config --quiet
docker compose up -d qdrant neo4j langfuse
python -m risk_agent_platform.run_scenario --scenario data\scenarios\sample_geopolitical_payment_risk.json --embedded-services
```

`pytest` includes a dummy-data final architecture E2E with mocked Tavily results, real A2A/FastMCP boundaries, Qdrant, Neo4j, Evidence Ledger, Expert-as-Code, and final output artifact generation.

The live E2E path has also been verified with real Tavily search, OpenRouter DeepAgent calls, Qdrant evidence indexing, Neo4j graph registration/path reads, and Langfuse trace readback. The latest verified live trace is `724f0fa5-8e4c-4db7-a19b-2664bf6e901d`.

Without `TAVILY_API_KEY`, the CLI fails explicitly at Source Intelligence and does not use fixture evidence as a fallback.

See [docs/acceptance_checklist.md](docs/acceptance_checklist.md) for the requirement-by-requirement status.

## Known Constraints

- Live Tavily E2E requires `TAVILY_API_KEY` and the Langfuse environment variables above if Langfuse trace export is required.
- Risk Discovery is event-and-scope intake, not autonomous continuous monitoring; a caller must still provide an event/theme and a client scope.
- DeepAgent tool integration is bounded rather than fully autonomous: exploration and hypothesis generation use tool slots, while registration, scoring, review flags, and Decision Queue writes stay in structured Python logic for auditability.
- A2A is currently an A2A SDK-shaped Agent Card plus A2A-compatible HTTP task boundary; the task transport is not yet a full a2a-sdk server/client implementation.
- Qdrant has an `EmbeddingProvider` abstraction and attempts real OpenRouter-compatible embeddings by default, but deterministic embeddings remain the default fallback and the explicit test mode.
- Source reliability scoring is initial/simple and domain-based; it does not yet perform full source provenance, recency, corroboration, or contradiction analysis.
- Authentication, RBAC, policy engine, ECS deployment, CI/CD, high availability, and real Ariba/SAP API connectivity are intentionally out of scope for this implementation phase.
