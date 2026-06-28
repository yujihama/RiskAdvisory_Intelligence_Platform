from __future__ import annotations

import csv
import base64
import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
import httpx
from fastmcp import FastMCP
from tavily import TavilyClient

from risk_agent_platform.config import Settings
from risk_agent_platform.evidence_repository import EvidenceRepository
from risk_agent_platform.model_profiles import ModelProfileRouter
from risk_agent_platform.query_sanitizer import build_risk_signal_query, sanitize_query
from risk_agent_platform.schemas import EvidenceItem, RiskEvent
from risk_agent_platform.stores.neo4j_store import Neo4jStore
from risk_agent_platform.stores.qdrant_store import QDRANT_COLLECTIONS, QdrantStore


def create_mcp_server(name: str, settings: Settings) -> FastMCP:
    factories = {
        "mcp-web-search": create_web_search_server,
        "mcp-document-parser": create_document_parser_server,
        "mcp-llm-ocr": create_llm_ocr_server,
        "mcp-qdrant": create_qdrant_server,
        "mcp-neo4j": create_neo4j_server,
        "mcp-filesystem": create_filesystem_server,
        "mcp-structured-data": create_structured_data_server,
        "mcp-expert-knowledge": create_expert_knowledge_server,
        "mcp-evidence-ledger": create_evidence_ledger_server,
    }
    try:
        return factories[name](settings)
    except KeyError as exc:
        raise ValueError(f"Unknown MCP server: {name}") from exc


def create_web_search_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-web-search")

    @mcp.tool
    def search_risk_signals(
        risk_event: dict[str, Any],
        max_results: int = 5,
        confidential_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        event = RiskEvent.model_validate(risk_event)
        query = build_risk_signal_query(event, confidential_terms=confidential_terms)
        return _tavily_search(settings, query.sanitized, query.query_hash, max_results=max_results)

    @mcp.tool
    def search_authoritative_sources(
        query: str,
        risk_event: dict[str, Any],
        max_results: int = 5,
        confidential_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        event = RiskEvent.model_validate(risk_event)
        sanitized = sanitize_query(query, event, confidential_terms=confidential_terms)
        return _tavily_search(settings, sanitized.sanitized, sanitized.query_hash, max_results=max_results)

    @mcp.tool
    def extract_url(url: str) -> dict[str, Any]:
        if not settings.external_apis.tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY is required for extract_url")
        client = TavilyClient(api_key=settings.external_apis.tavily_api_key)
        return {"url": url, "result": client.extract(urls=[url])}

    return mcp


def create_qdrant_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-qdrant")

    @mcp.tool
    def ensure_collections() -> dict[str, Any]:
        return {"collections": QdrantStore(settings).ensure_collections()}

    @mcp.tool
    def upsert_document_chunks(collection: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        return QdrantStore(settings).upsert_texts(collection, chunks)

    @mcp.tool
    def search_documents(query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("client_documents", query=query, top_k=top_k, filters=filters)

    @mcp.tool
    def search_evidence(query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("evidence_chunks", query=query, top_k=top_k, filters=filters)

    @mcp.tool
    def search_expert_cases(query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("expert_cases", query=query, top_k=top_k, filters=filters)

    @mcp.tool
    def search_expert_knowledge(query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("expert_knowledge", query=query, top_k=top_k, filters=filters)

    @mcp.tool
    def search_similar_scenarios(query: str, filters: dict[str, Any] | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("scenario_cards", query=query, top_k=top_k, filters=filters)

    @mcp.tool
    def delete_by_client_or_scenario(client_id: str | None = None, scenario_id: str | None = None) -> dict[str, Any]:
        return QdrantStore(settings).delete_by_client_or_scenario(client_id=client_id, scenario_id=scenario_id)

    return mcp


def create_neo4j_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-neo4j")

    @mcp.tool
    def upsert_asset(label: str, asset_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_asset(label, asset_id, properties)
        finally:
            store.close()

    @mcp.tool
    def upsert_relation(source_id: str, target_id: str, relation_type: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_relation(source_id, target_id, relation_type, properties)
        finally:
            store.close()

    @mcp.tool
    def find_related_assets(asset_id: str, depth: int = 2) -> list[dict[str, Any]]:
        store = Neo4jStore(settings)
        try:
            return store.find_related_assets(asset_id, depth=depth)
        finally:
            store.close()

    @mcp.tool
    def find_affected_assets(scenario_id: str) -> list[dict[str, Any]]:
        store = Neo4jStore(settings)
        try:
            return store.find_affected_assets(scenario_id)
        finally:
            store.close()

    @mcp.tool
    def find_risk_paths(scenario_id: str, max_depth: int = 4) -> list[dict[str, Any]]:
        store = Neo4jStore(settings)
        try:
            return store.find_risk_paths(scenario_id, max_depth=max_depth)
        finally:
            store.close()

    @mcp.tool
    def write_hypothesis_edge(source_id: str, target_id: str, relation_type: str, rationale: str) -> dict[str, Any]:
        return upsert_relation(source_id, target_id, relation_type, {"confidence_level": "hypothesis", "rationale": rationale, "requires_validation": True})

    @mcp.tool
    def register_assumption(scenario_id: str, assumption_id: str, description: str) -> dict[str, Any]:
        asset = upsert_asset("Assumption", assumption_id, {"description": description, "confidence_level": "assumption"})
        relation = upsert_relation(scenario_id, assumption_id, "HAS_ASSUMPTION", {"confidence_level": "assumption"})
        return {"asset": asset, "relation": relation}

    @mcp.tool
    def register_unknown(scenario_id: str, unknown_id: str, description: str) -> dict[str, Any]:
        asset = upsert_asset("Unknown", unknown_id, {"description": description, "confidence_level": "unknown", "requires_validation": True})
        relation = upsert_relation(scenario_id, unknown_id, "HAS_UNKNOWN", {"confidence_level": "unknown", "requires_validation": True})
        return {"asset": asset, "relation": relation}

    @mcp.tool
    def attach_evidence_to_scenario(scenario_id: str, evidence_id: str, supports: bool = True) -> dict[str, Any]:
        relation_type = "SUPPORTS" if supports else "CONTRADICTS"
        return upsert_relation(evidence_id, scenario_id, relation_type, {"confidence_level": "source_backed"})

    @mcp.tool
    def attach_decision_to_scenario(scenario_id: str, decision_id: str) -> dict[str, Any]:
        return upsert_relation(decision_id, scenario_id, "MITIGATES", {"confidence_level": "derived"})

    return mcp


def create_structured_data_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-structured-data")

    @mcp.tool
    def list_datasets(client_id: str) -> list[str]:
        root = settings.data_dir / "clients" / client_id / "structured"
        if not root.exists():
            return []
        return sorted(path.stem for path in root.glob("*.csv"))

    @mcp.tool
    def inspect_schema(client_id: str, dataset: str) -> dict[str, Any]:
        rows = _read_rows(settings, client_id, dataset)
        return {"dataset": dataset, "columns": list(rows[0].keys()) if rows else [], "row_count": len(rows)}

    @mcp.tool
    def sample_rows(client_id: str, dataset: str, limit: int = 5) -> list[dict[str, str]]:
        return _read_rows(settings, client_id, dataset)[:limit]

    @mcp.tool
    def profile_dataset(client_id: str, dataset: str) -> dict[str, Any]:
        rows = _read_rows(settings, client_id, dataset)
        return {"dataset": dataset, "row_count": len(rows), "columns": list(rows[0].keys()) if rows else []}

    @mcp.tool
    def query_dataset(client_id: str, dataset: str, filters: dict[str, str] | None = None) -> list[dict[str, str]]:
        rows = _read_rows(settings, client_id, dataset)
        for key, value in (filters or {}).items():
            rows = [row for row in rows if row.get(key) == value]
        return rows

    @mcp.tool
    def summarize_payment_exposure(client_id: str, country: str | None = None) -> dict[str, Any]:
        payments = _read_rows(settings, client_id, "payments")
        if country:
            payments = [row for row in payments if row.get("bank_country", "").lower() == country.lower()]
        total = sum(_to_float(row.get("amount")) for row in payments)
        return {"payment_count": len(payments), "total_amount": total, "items": payments}

    @mcp.tool
    def summarize_supplier_exposure(client_id: str, country: str | None = None) -> dict[str, Any]:
        suppliers = _read_rows(settings, client_id, "suppliers")
        if country:
            suppliers = [row for row in suppliers if row.get("country", "").lower() == country.lower()]
        critical = [row for row in suppliers if row.get("criticality") == "high"]
        return {"supplier_count": len(suppliers), "critical_count": len(critical), "items": suppliers}

    @mcp.tool
    def summarize_invoice_exposure(client_id: str) -> dict[str, Any]:
        invoices = _read_rows(settings, client_id, "invoices")
        total = sum(_to_float(row.get("amount")) for row in invoices)
        return {"invoice_count": len(invoices), "total_amount": total, "items": invoices}

    return mcp


def create_evidence_ledger_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-evidence-ledger")

    @mcp.tool
    def register_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
        item = EvidenceItem.model_validate(evidence)
        return EvidenceRepository(settings).register(item, index_qdrant=True).model_dump(mode="json")

    @mcp.tool
    def search_evidence(query: str, scenario_id: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return EvidenceRepository(settings).search(query, scenario_id=scenario_id, top_k=top_k)

    @mcp.tool
    def get_evidence(evidence_id: str) -> dict[str, Any] | None:
        item = EvidenceRepository(settings).get(evidence_id)
        return item.model_dump(mode="json") if item else None

    @mcp.tool
    def list_evidence_by_scenario(scenario_id: str) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in EvidenceRepository(settings).list_by_scenario(scenario_id)]

    @mcp.tool
    def link_evidence_to_scenario(evidence_id: str, scenario_id: str) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_relation(evidence_id, scenario_id, "SUPPORTS", {"confidence_level": "source_backed"})
        finally:
            store.close()

    @mcp.tool
    def mark_supports(evidence_id: str, scenario_id: str) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_relation(evidence_id, scenario_id, "SUPPORTS", {"confidence_level": "source_backed"})
        finally:
            store.close()

    @mcp.tool
    def mark_contradicts(evidence_id: str, scenario_id: str) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_relation(evidence_id, scenario_id, "CONTRADICTS", {"confidence_level": "source_backed"})
        finally:
            store.close()

    @mcp.tool
    def update_reliability(evidence_id: str, reliability: str) -> dict[str, Any]:
        return {"evidence_id": evidence_id, "reliability": reliability, "status": "queued_for_repository_update"}

    @mcp.tool
    def link_evidence_to_asset(evidence_id: str, asset_id: str) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_relation(evidence_id, asset_id, "SUPPORTS", {"confidence_level": "source_backed"})
        finally:
            store.close()

    @mcp.tool
    def link_evidence_to_decision(evidence_id: str, decision_id: str) -> dict[str, Any]:
        store = Neo4jStore(settings)
        try:
            return store.upsert_relation(evidence_id, decision_id, "SUPPORTS", {"confidence_level": "source_backed"})
        finally:
            store.close()

    return mcp


def create_expert_knowledge_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-expert-knowledge")

    @mcp.tool
    def search_similar_cases(case_description: str, mode: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("expert_cases", query=case_description, top_k=top_k, filters={"mode": mode} if mode else None)

    @mcp.tool
    def search_knowledge_objects(query: str, domain: str | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        return QdrantStore(settings).search("expert_knowledge", query=query, top_k=top_k, filters={"domain": domain} if domain else None)

    @mcp.tool
    def load_knowledge_pack() -> list[dict[str, Any]]:
        path = settings.data_dir / "expert_knowledge" / "rules.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @mcp.tool
    def load_case_bank() -> list[dict[str, Any]]:
        path = settings.data_dir / "expert_knowledge" / "cases.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @mcp.tool
    def load_question_bank() -> list[dict[str, Any]]:
        path = settings.data_dir / "expert_knowledge" / "questions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @mcp.tool
    def load_cta_notes() -> list[dict[str, Any]]:
        path = settings.data_dir / "expert_knowledge" / "cta_notes.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @mcp.tool
    def index_knowledge_pack() -> dict[str, Any]:
        objects = load_knowledge_pack()
        chunks = [
            {
                "text": f"{obj.get('title', '')}\n{obj.get('description', '')}",
                "metadata": {
                    "client_id": None,
                    "scenario_id": None,
                    "source_type": "expert_knowledge",
                    "mode": obj.get("domain"),
                    "asset_id": None,
                    "evidence_id": None,
                    "document_id": obj.get("id"),
                    "confidence": obj.get("expert_confidence"),
                    "tags": obj.get("conditions", []),
                    "domain": obj.get("domain"),
                    "object_type": obj.get("object_type"),
                },
            }
            for obj in objects
        ]
        return QdrantStore(settings).upsert_texts("expert_knowledge", chunks)

    @mcp.tool
    def index_case_bank() -> dict[str, Any]:
        cases = load_case_bank()
        chunks = [
            {
                "text": f"{case.get('title', '')}\n{case.get('scenario_pattern', '')}\n{case.get('outcome', '')}",
                "metadata": {
                    "client_id": None,
                    "scenario_id": None,
                    "source_type": "expert_knowledge",
                    "mode": case.get("domain"),
                    "asset_id": None,
                    "evidence_id": None,
                    "document_id": case.get("case_id"),
                    "confidence": "medium",
                    "tags": case.get("tags", []),
                    "domain": case.get("domain"),
                    "object_type": "expert_case",
                },
            }
            for case in cases
        ]
        return QdrantStore(settings).upsert_texts("expert_cases", chunks)

    return mcp


def create_filesystem_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-filesystem")

    @mcp.tool
    def write_output(scenario_id: str, filename: str, content: str) -> dict[str, Any]:
        path = settings.project_root / "outputs" / scenario_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path)}

    @mcp.tool
    def write_json_output(scenario_id: str, filename: str, data: dict[str, Any] | list[Any]) -> dict[str, Any]:
        path = settings.project_root / "outputs" / scenario_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(path)}

    return mcp


def create_document_parser_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-document-parser")

    @mcp.tool
    def parse_document(path: str) -> dict[str, Any]:
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(path)
        attempts: list[str] = []
        for parser_name, parser in (
            ("docling", _parse_with_docling),
            ("unstructured", _parse_with_unstructured),
            ("pymupdf", _parse_with_pymupdf),
            ("text", _parse_with_text),
        ):
            try:
                pages = parser(source)
            except Exception as exc:
                attempts.append(f"{parser_name}: {exc.__class__.__name__}")
                continue
            if pages:
                return {
                    "document_id": _stable_id(str(source)),
                    "source_path": str(source),
                    "parser": parser_name,
                    "fallback_attempts": attempts,
                    "pages": pages,
                    "parse_confidence": "high" if parser_name == "docling" else "medium",
                }
        raise RuntimeError(f"Unable to parse document. attempts={attempts}")

    return mcp


def create_llm_ocr_server(settings: Settings) -> FastMCP:
    mcp = FastMCP("mcp-llm-ocr")

    @mcp.tool
    def ocr_page(
        document_id: str,
        page_number: int,
        image_path: str | None = None,
        pdf_path: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        if not image_path and not pdf_path:
            raise RuntimeError("mcp-llm-ocr requires image_path or pdf_path; no dummy OCR fallback is used")
        image_bytes, mime_type = _load_ocr_image(image_path=image_path, pdf_path=pdf_path, page_number=page_number)
        result = _openrouter_vision_ocr(settings, image_bytes=image_bytes, mime_type=mime_type, prompt=prompt)
        return {
            "document_id": document_id,
            "page_number": page_number,
            "text": result["text"],
            "tables": result.get("tables", []),
            "detected_entities": result.get("detected_entities", []),
            "confidence": result.get("confidence", "medium"),
            "model_used": result["model_used"],
            "warnings": result.get("warnings", []),
        }

    return mcp


def _tavily_search(settings: Settings, query: str, query_hash: str, max_results: int = 5) -> dict[str, Any]:
    if not settings.external_apis.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is required for web evidence collection; no local fixture fallback is available")
    client = TavilyClient(api_key=settings.external_apis.tavily_api_key)
    result = client.search(query=query, max_results=max_results, include_answer=False, include_raw_content=False)
    return {"query": query, "query_hash": query_hash, "results": result.get("results", [])}


def _read_rows(settings: Settings, client_id: str, dataset: str) -> list[dict[str, str]]:
    path = settings.data_dir / "clients" / client_id / "structured" / f"{dataset}.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _parse_with_docling(source: Path) -> list[dict[str, Any]]:
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(source))
    markdown = result.document.export_to_markdown()
    return [{"page_number": 1, "text": markdown, "tables": [], "parser_metadata": {"source": "docling"}}]


def _parse_with_unstructured(source: Path) -> list[dict[str, Any]]:
    from unstructured.partition.auto import partition

    elements = partition(filename=str(source))
    text = "\n".join(str(element) for element in elements)
    return [{"page_number": 1, "text": text, "tables": [], "parser_metadata": {"source": "unstructured"}}]


def _parse_with_pymupdf(source: Path) -> list[dict[str, Any]]:
    if source.suffix.lower() != ".pdf":
        return []
    with fitz.open(source) as doc:
        return [{"page_number": i + 1, "text": page.get_text(), "tables": []} for i, page in enumerate(doc)]


def _parse_with_text(source: Path) -> list[dict[str, Any]]:
    if source.suffix.lower() not in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".html", ".htm"}:
        return []
    text = source.read_text(encoding="utf-8", errors="replace")
    return [{"page_number": 1, "text": text, "tables": []}]


def _load_ocr_image(*, image_path: str | None, pdf_path: str | None, page_number: int) -> tuple[bytes, str]:
    if image_path:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(image_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        return path.read_bytes(), mime_type
    if not pdf_path:
        raise RuntimeError("pdf_path is required when image_path is not supplied")
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(pdf_path)
    with fitz.open(path) as doc:
        page_index = max(page_number - 1, 0)
        if page_index >= len(doc):
            raise ValueError(f"page_number {page_number} exceeds PDF page count {len(doc)}")
        pixmap = doc[page_index].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png"), "image/png"


def _openrouter_vision_ocr(settings: Settings, *, image_bytes: bytes, mime_type: str, prompt: str | None) -> dict[str, Any]:
    if not settings.openrouter.api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for LLM OCR")
    router = ModelProfileRouter(settings.project_root / "config" / "model_profiles.yaml")
    profile = router.select("vision_ocr")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    endpoint = f"{settings.openrouter.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter.api_key}",
        "Content-Type": "application/json",
        **_openrouter_headers(settings),
    }
    instruction = prompt or (
        "Extract all readable text from this page. Return concise JSON with keys "
        "text, tables, detected_entities, confidence, and warnings. "
        "Do not invent missing text."
    )
    payload = {
        "model": profile.model,
        "temperature": profile.temperature,
        "max_tokens": profile.max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                ],
            }
        ],
    }
    with httpx.Client(timeout=settings.openrouter.timeout_seconds) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    parsed = _parse_ocr_json(content)
    parsed["model_used"] = profile.model
    return parsed


def _parse_ocr_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"text": content, "tables": [], "detected_entities": [], "confidence": "medium", "warnings": ["OCR model returned non-JSON text"]}
    if not isinstance(parsed, dict):
        return {"text": content, "tables": [], "detected_entities": [], "confidence": "low", "warnings": ["OCR model returned non-object JSON"]}
    return {
        "text": str(parsed.get("text") or ""),
        "tables": parsed.get("tables") if isinstance(parsed.get("tables"), list) else [],
        "detected_entities": parsed.get("detected_entities") if isinstance(parsed.get("detected_entities"), list) else [],
        "confidence": parsed.get("confidence") if parsed.get("confidence") in {"low", "medium", "high"} else "medium",
        "warnings": parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else [],
    }


def _openrouter_headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.openrouter.app_url:
        headers["HTTP-Referer"] = settings.openrouter.app_url
    if settings.openrouter.app_title:
        headers["X-Title"] = settings.openrouter.app_title
    return headers
