# Final Architecture Acceptance Checklist

This checklist maps the implementation instruction to concrete evidence in the current repository and local verification run.

## DeepAgent

- [x] `deepagents` and `langgraph` are dependencies.
- [x] Orchestrator is backed by `create_deep_agent` through `DeepAgentRunner`.
- [x] Domain Agents are backed by `create_deep_agent` through `DomainDeepAgentService`.
- [x] Legacy `LocalA2ARegistry` remains only in the previous PoC path; final path uses A2A HTTP/client boundaries.

Evidence:

- `src/risk_agent_platform/deepagent_runtime.py`
- `src/risk_agent_platform/final_agents.py`
- `python -m compileall src tests`
- `pytest` -> `9 passed`

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
- [x] Legacy MCP-style classes are not used by `run-final-scenario` / `run_scenario`.

Verified command summary:

- `docker compose up -d --build mcp-web-search mcp-document-parser mcp-llm-ocr mcp-qdrant mcp-neo4j mcp-filesystem mcp-structured-data mcp-expert-knowledge mcp-evidence-ledger`
- FastMCP HTTP smoke returned Qdrant collections, Neo4j `RiskScenario`, client datasets, expert cases, document parser result, and expected OCR missing-input error.

## Tavily

- [x] `mcp-web-search` wraps Tavily.
- [x] Query Sanitizer redacts IDs, amounts, client/scenario IDs, and domain-specific confidential terms.
- [x] Tavily results are normalized to `EvidenceItem`.
- [x] Evidence registration writes JSONL, indexes Qdrant, and registers Evidence/Scenario relations in Neo4j.
- [x] `dummy_sources.json` is fixture-only and is not used by the final path.
- [x] Missing `TAVILY_API_KEY` fails explicitly without silent dummy fallback.
- [ ] Live Tavily E2E verified with a real `TAVILY_API_KEY`.

Current blocker:

- `TAVILY_API_KEY` is not configured locally.
- Verified failure mode: `python -m risk_agent_platform.run_scenario --scenario data\scenarios\sample_geopolitical_payment_risk.json --embedded-services` fails at Source Intelligence with `TAVILY_API_KEY is required; dummy_sources.json is fixture-only and is not used in the normal path`.

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

## Neo4j

- [x] Neo4j is called through `mcp-neo4j`.
- [x] Client, RiskScenario, Supplier, Evidence, Decision, Assumption, and Unknown node labels are supported.
- [x] RiskScenario, Evidence, Asset, and Decision relations are registered through MCP/Evidence Ledger flows.
- [x] `source_backed`, `derived`, `hypothesis`, `assumption`, and `unknown` confidence layers are represented in node/relation properties.

Evidence:

- HTTP MCP smoke inserted `RiskScenario` node `http_mcp_check`.
- Dummy final E2E queried affected assets from Neo4j.

## Langfuse

- [x] Self-hosted Langfuse stack is included in Docker Compose.
- [x] Langfuse web and worker containers start successfully.
- [x] Langfuse UI responds at `http://localhost:3300`.
- [x] Local headless project/API key initialization is configured for Docker Compose.
- [x] SDK `auth_check()` returned `True` with the local initialized keys.
- [x] `TraceRecorder` sends A2A/MCP/LLM events to Langfuse using a Langfuse-compatible trace id.
- [x] Local JSONL trace is written under `outputs/_traces`.

Verified commands:

- `docker compose up -d langfuse`
- `curl.exe -I --max-time 20 http://localhost:3300` -> `HTTP/1.1 200 OK`
- `Langfuse(...).auth_check()` -> `True`
- Langfuse-enabled dummy final E2E test passed.

## Expert-as-Code

- [x] Knowledge Object and Knowledge Primitive schemas are defined.
- [x] Expert case, question, response, CTA note, and Knowledge Pack version schemas are defined.
- [x] Sample Knowledge Pack files exist under `data/expert_knowledge/`.
- [x] Expert-as-Code Agent indexes knowledge objects and case bank into Qdrant.
- [x] Expert-as-Code output is reflected in `DecisionItem.expert_knowledge_ids`.

Evidence:

- `data/expert_knowledge/rules.jsonl`
- `data/expert_knowledge/cases.jsonl`
- `data/expert_knowledge/questions.jsonl`
- `data/expert_knowledge/cta_notes.jsonl`
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
- [x] Langfuse-enabled dummy final E2E passed.
- [x] Final CLI fails explicitly when Tavily is missing.
- [ ] Full live E2E with real Tavily search is not yet verified because `TAVILY_API_KEY` is not configured.
