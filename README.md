# Risk Advisory Intelligence Platform

This repository implements a working slice of the target architecture described in `docs/`, beyond the earlier local PoC skeleton. Some target-architecture items are intentionally still partial and are listed under Known Constraints.

The normal execution path is:

```text
CLI / API
  -> Orchestrator DeepAgent
  -> A2A SDK-shaped Agent Cards + A2A-compatible HTTP task requests
  -> Domain DeepAgents
  -> FastMCP tool calls, including a partial DeepAgent tool-integration path
  -> Tavily / Qdrant / Neo4j / Files / Evidence Ledger / Expert Knowledge
  -> Decision Queue + Executive Brief + Evidence Summary
```

The earlier local PoC classes remain for compatibility tests, but the current target path is `python -m risk_agent_platform.run_scenario` or `risk-agent-platform run-final-scenario`.

## Architecture Diagrams

See [docs/architecture_diagrams.md](docs/architecture_diagrams.md).

## Agents

The following A2A agents are implemented as DeepAgent-backed services:

- `orchestrator-agent`
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
- `/.well-known/agent-card.internal.json`
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

The Source Intelligence Agent also demonstrates partial DeepAgent tool integration: its Tavily evidence registration MCP call is wrapped as a DeepAgent tool named `register_external_risk_evidence`. The remaining agents still keep MCP orchestration in Python `analyze()` methods for auditability and deterministic control.

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

## Run Preflight

```powershell
risk-agent-platform preflight
```

This reports missing keys without printing secret values.

## Run Sample Scenario

Local embedded A2A/MCP endpoints:

```powershell
python -m risk_agent_platform.run_scenario --scenario data\scenarios\sample_geopolitical_payment_risk.json --embedded-services
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

- `outputs/<scenario_id>/final_brief.md`
- `outputs/<scenario_id>/decision_queue.json`
- `outputs/<scenario_id>/evidence_summary.json`
- `outputs/<scenario_id>/red_team_review.md`
- `outputs/<scenario_id>/assumptions_and_unknowns.json`
- `outputs/<scenario_id>/trace_metadata.json`
- `outputs/_traces/<trace_id>.jsonl`

## Evidence Ledger

Tavily results are sanitized, assigned an initial source reliability score, normalized into `EvidenceItem`, stored in JSONL, indexed into Qdrant, and linked to scenarios/assets/decisions through Neo4j MCP tools.

`dummy_sources.json` is fixture-only. The final path does not silently fall back to dummy sources. If `TAVILY_API_KEY` is absent, the final path fails explicitly.

Initial source reliability scoring is domain-based: government, regulator, international organization, and official disclosure sources are scored `high`; general news or research sources are `medium`; blog-like sources are `low`.

## Expert-as-Code

Expert knowledge is represented as structured Knowledge Objects, Knowledge Primitives, case bank entries, question bank entries, and CTA notes. The Expert-as-Code Agent indexes `data/expert_knowledge/rules.jsonl` and `data/expert_knowledge/cases.jsonl` into Qdrant and reflects retrieved IDs in the Decision Queue.

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

Without `TAVILY_API_KEY`, the final CLI fails explicitly at Source Intelligence and does not use `dummy_sources.json` as a fallback.

See [docs/acceptance_checklist.md](docs/acceptance_checklist.md) for the requirement-by-requirement status.

## Known Constraints

- Live Tavily E2E requires `TAVILY_API_KEY` and the Langfuse environment variables above if Langfuse trace export is required.
- DeepAgent tool integration is partial: Source Intelligence has a DeepAgent-wrapped MCP tool example, while most domain agents still orchestrate MCP calls in Python for stability and auditability.
- A2A is currently an A2A SDK-shaped Agent Card plus A2A-compatible HTTP task boundary; the task transport is not yet a full a2a-sdk server/client implementation.
- Qdrant has an `EmbeddingProvider` abstraction and attempts real OpenRouter-compatible embeddings by default, but deterministic embeddings remain the default fallback and the explicit test mode.
- Source reliability scoring is initial/simple and domain-based; it does not yet perform full source provenance, recency, corroboration, or contradiction analysis.
- Authentication, RBAC, policy engine, ECS deployment, CI/CD, high availability, and real Ariba/SAP API connectivity are intentionally out of scope for this implementation phase.
