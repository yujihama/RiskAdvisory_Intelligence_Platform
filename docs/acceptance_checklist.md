# Final Architecture Acceptance Checklist

This checklist maps the implementation instruction to concrete evidence in the current repository and local verification run.

## DeepAgent

- [x] `deepagents` and `langgraph` are dependencies.
- [x] Orchestrator is backed by `create_deep_agent` through `DeepAgentRunner`.
- [x] Domain Agents are backed by `create_deep_agent` through `DomainDeepAgentService`.
- [x] The codebase uses the A2A-compatible HTTP/client boundary as the runtime agent boundary.
- [x] Orchestrator generates a bounded `analysis_plan` JSON and falls back to fixed agent order if generation or validation fails.
- [x] Risk Discovery DeepAgent converts an event + client scope into scope-relevant selected/rejected candidates and threshold-selected `RiskEvent` items, while preserving the top `selected_event` for compatibility.
- [x] Source Intelligence, Expert-as-Code, and Evidence / Red Team include DeepAgent tool-use slots; Treasury, Legal, and Accounting include bounded issue-exploration slots while final scoring remains structured.

Evidence:

- `src/risk_agent_platform/deepagent_runtime.py`
- `src/risk_agent_platform/final_agents.py`
- `python -m compileall src tests`
- `pytest` -> current suite passes

## A2A

- [x] Each final Agent exposes `/.well-known/agent-card.json`.
- [x] Each final Agent exposes `/a2a`.
- [x] Each final Agent exposes `/healthz`.
- [x] A2A schemas include status, artifacts, errors, `task_id`, `parent_task_id`, and `trace_id`.
- [x] Orchestrator delegates to Domain Agents through `A2AHttpClient`.

Evidence:

- `src/risk_agent_platform/a2a_http.py`
- `src/risk_agent_platform/agent_server.py`
- `tests/test_final_embedded_e2e.py`

## MCP

- [x] FastMCP servers exist for all required MCP server names.
- [x] Agents call external capabilities through `MCPGateway` and FastMCP `Client`.
- [x] Docker HTTP MCP tools were verified for Qdrant, Neo4j, structured data, document parser, expert knowledge, and OCR error handling.
- [x] Normal execution uses FastMCP servers through `MCPGateway`.

Verified command summary:

- `docker compose up -d --build mcp-web-search mcp-document-parser mcp-llm-ocr mcp-qdrant mcp-neo4j mcp-filesystem mcp-structured-data mcp-expert-knowledge mcp-evidence-ledger`
- FastMCP HTTP smoke returned Qdrant collections, Neo4j `RiskScenario`, client datasets, expert cases, document parser result, and expected OCR missing-input error.

## Tavily

- [x] `mcp-web-search` wraps Tavily.
- [x] Query Sanitizer redacts IDs, amounts, client/scenario IDs, and domain-specific confidential terms.
- [x] Source Intelligence performs bounded query planning, multiple sanitized searches, selected URL extraction, and Evidence Ledger registration.
- [x] Tavily results are normalized to `EvidenceItem`.
- [x] Evidence registration writes JSONL, indexes Qdrant, and registers Evidence/Scenario relations in Neo4j.
- [x] Web evidence collection uses Tavily through `mcp-web-search`; there is no local fixture fallback in the runtime path.
- [x] Missing `TAVILY_API_KEY` fails explicitly without silent fallback.
- [x] Live Tavily E2E verified with a real `TAVILY_API_KEY`.

Verified live run:

- `python -m risk_agent_platform.run_scenario --scenario data\scenarios\live_geopolitical_payment_risk.json --embedded-services`
- Final status: `completed`
- Final trace id: `724f0fa5-8e4c-4db7-a19b-2664bf6e901d`
- Evidence domains: `skilldynamics.com`, `www.cmtradelaw.com`, `www.consilium.europa.eu`, `www.steptoe.com`, `home.treasury.gov`

## OpenRouter

- [x] DeepAgent execution uses OpenRouter through `ChatOpenAI`.
- [x] Qwen defaults are configured in `config/model_profiles.yaml`.
- [x] Agent-specific model profile routing exists.
- [x] LLM OCR uses the `vision_ocr` model profile through OpenRouter when an image or PDF page is supplied.

Evidence:

- `src/risk_agent_platform/model_profiles.py`
- `src/risk_agent_platform/deepagent_runtime.py`
- `src/risk_agent_platform/mcp_servers/factory.py`

## Qdrant

- [x] Qdrant collections are created through `mcp-qdrant`.
- [x] Evidence and Expert Knowledge are indexed into Qdrant.
- [x] Agents use Qdrant through MCP tools.

Verified collections:

- `client_documents`
- `external_sources`
- `evidence_chunks`
- `expert_cases`
- `expert_knowledge`
- `scenario_cards`

Live scenario verification:

- Qdrant `evidence_chunks` search with `scenario_id=scenario_live_2026_001` returned 5 evidence points.
- Evidence payloads retain `source_domain`, `source_url`, `source_title`, and stable `evidence_id` metadata.
- Evidence point IDs are stable by `evidence_id`, so rerunning the same scenario does not multiply duplicate evidence search hits.

## Neo4j

- [x] Neo4j is called through `mcp-neo4j`.
- [x] Client, RiskScenario, Supplier, Evidence, Decision, Assumption, and Unknown node labels are supported.
- [x] RiskScenario, Evidence, Asset, and Decision relations are registered through MCP/Evidence Ledger flows.
- [x] `source_backed`, `derived`, `hypothesis`, `assumption`, and `unknown` confidence layers are represented in node/relation properties.

Evidence:

- HTTP MCP smoke inserted `RiskScenario` node `http_mcp_check`.
- Mocked-Tavily final E2E queried affected assets from Neo4j.
- Live final E2E registered `scenario_live_2026_001`, linked 3 affected suppliers, and returned 3 risk paths.
- Neo4j variable-depth graph reads were verified through `find_affected_assets`, `find_related_assets`, and `find_risk_paths`.

## Langfuse

- [x] Self-hosted Langfuse stack is included in Docker Compose.
- [x] Langfuse web and worker containers start successfully.
- [x] Langfuse UI responds at `http://localhost:3300`.
- [x] Local headless project/API key initialization is configured for Docker Compose.
- [x] SDK `auth_check()` returned `True` with the local initialized keys.
- [x] `TraceRecorder` sends A2A/MCP/LLM events to Langfuse using a Langfuse-compatible trace id.
- [x] Local JSONL trace is written under `outputs/_traces`.
- [x] Live final E2E trace was read back through the Langfuse public API.

Verified commands:

- `docker compose up -d langfuse`
- `curl.exe -I --max-time 20 http://localhost:3300` -> `HTTP/1.1 200 OK`
- `Langfuse(...).auth_check()` -> `True`
- Langfuse-enabled final E2E test passed.
- Live trace API readback: `trace_id=724f0fa58e4c4db7a19b2664bf6e901d`, `project_id=risk-advisory-local-project`, `observation_count=144`.
- Local trace `outputs/_traces/724f0fa5-8e4c-4db7-a19b-2664bf6e901d.jsonl` includes A2A, MCP, and OpenRouter events with `langfuse_enabled=true` and no `langfuse_event_error`.

## Expert-as-Code

- [x] Knowledge Object and Knowledge Primitive schemas are defined.
- [x] Expert case, question, response, CTA note, and Knowledge Pack version schemas are defined.
- [x] Sample Knowledge Pack files exist under `data/expert_knowledge/`.
- [x] Expert Knowledge MCP loaders read rules, primitives, scope relevance rules, cases, questions, CTA notes, source refs, source reliability seed, and pack version metadata.
- [x] Expert-as-Code Agent indexes knowledge objects and case bank into Qdrant.
- [x] Expert-as-Code Agent uses bounded DeepAgent tools for similar cases, rubrics, red flags, CTA notes, and counterfactuals.
- [x] Expert-as-Code emits a structured `KnowledgeApplicationFinding` inside the AgentFinding metadata.
- [x] Expert-as-Code output is reflected in `DecisionItem.expert_knowledge_ids`.

Evidence:

- `data/expert_knowledge/rules.jsonl`
- `data/expert_knowledge/cases.jsonl`
- `data/expert_knowledge/questions.jsonl`
- `data/expert_knowledge/cta_notes.jsonl`
- `data/expert_knowledge/primitives.jsonl`
- `data/expert_knowledge/scope_relevance_rules.jsonl`
- `data/expert_knowledge/knowledge_pack_version.json`
- `data/expert_knowledge/source_refs.json`
- `data/expert_knowledge/source_reliability_seed.yaml`
- `tests/test_final_embedded_e2e.py`

## Document Parsing / OCR

- [x] `mcp-document-parser` implements a Docling-first fallback chain: Docling, Unstructured, PyMuPDF, text.
- [x] `mcp-llm-ocr` invokes OpenRouter vision OCR when `image_path` or `pdf_path` is supplied.
- [x] OCR no-input mode fails explicitly instead of returning placeholder OCR text.

Evidence:

- `tests/test_final_architecture_boundaries.py`
- HTTP MCP smoke confirmed expected OCR missing-input error.

## E2E

- [x] `pytest` includes a final architecture embedded E2E using dummy client data, mocked Tavily results, real A2A/FastMCP boundaries, Qdrant, Neo4j, Evidence Ledger, Expert-as-Code, and output artifact generation.
- [x] `pytest` includes Risk Discovery fallback coverage for event + department scope intake, selected `RiskEvent` generation, all-selected/top/top-n analysis mode selection, rejected candidate reasons, and portfolio summary integration.
- [x] Langfuse-enabled final E2E passed.
- [x] Final CLI fails explicitly when Tavily is missing.
- [x] Full live E2E with real Tavily search, Qdrant, Neo4j, Langfuse, OpenRouter, and output artifacts is verified.

Final live E2E evidence:

- Command: `python -m risk_agent_platform.run_scenario --scenario data\scenarios\live_geopolitical_payment_risk.json --embedded-services`
- Required outputs written under `outputs/scenario_live_2026_001/`: `final_brief.md`, `decision_queue.json`, `evidence_summary.json`, `red_team_review.md`, `assumptions_and_unknowns.json`, `trace_metadata.json`.
- `evidence_summary.json` contains 5 Tavily-backed evidence records.
- `decision_queue.json` contains `scenario_live_2026_001_decision_001` linked to all 5 evidence IDs.
- Qdrant returned 5 live evidence hits after scenario-scoped cleanup and stable evidence upsert.
- Neo4j returned affected suppliers `SUP-LIVE-001`, `SUP-LIVE-002`, and `SUP-LIVE-003`.
