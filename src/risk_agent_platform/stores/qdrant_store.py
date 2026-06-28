from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from risk_agent_platform.config import Settings
from risk_agent_platform.embeddings import create_embedding_provider
from risk_agent_platform.vector import VECTOR_SIZE


QDRANT_COLLECTIONS = [
    "client_documents",
    "external_sources",
    "evidence_chunks",
    "expert_cases",
    "expert_knowledge",
    "scenario_cards",
]


class QdrantStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = QdrantClient(
            url=settings.stores.qdrant_url,
            api_key=settings.stores.qdrant_api_key,
            timeout=10,
        )
        self.embedding_provider = create_embedding_provider(settings)

    def ensure_collections(self) -> list[str]:
        existing = {collection.name for collection in self.client.get_collections().collections}
        for name in QDRANT_COLLECTIONS:
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
        return QDRANT_COLLECTIONS

    def upsert_texts(self, collection: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        self.ensure_collections()
        points: list[PointStruct] = []
        for chunk in chunks:
            text = str(chunk.get("text") or chunk.get("summary") or "")
            payload = dict(chunk.get("metadata") or {})
            payload.update(
                {
                    "text": text,
                    "created_at": payload.get("created_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
            point_id = _point_id(collection, payload, text)
            vector = self.embedding_provider.embed(text)
            payload["embedding_provider"] = payload.get("embedding_provider") or getattr(
                self.embedding_provider,
                "last_provider_name",
                self.embedding_provider.name,
            )
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
        if points:
            self.client.upsert(collection_name=collection, points=points)
        return {"collection": collection, "upserted": len(points)}

    def search(self, collection: str, query: str, top_k: int = 5, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.ensure_collections()
        q_filter = _build_filter(filters or {})
        try:
            result = self.client.query_points(
                collection_name=collection,
                query=self.embedding_provider.embed(query),
                query_filter=q_filter,
                limit=top_k,
                with_payload=True,
            )
        except UnexpectedResponse:
            return []
        return [
            {
                "id": str(point.id),
                "score": point.score,
                "payload": point.payload or {},
            }
            for point in result.points
        ]

    def delete_by_client_or_scenario(self, client_id: str | None = None, scenario_id: str | None = None) -> dict[str, Any]:
        self.ensure_collections()
        filters = {}
        if client_id:
            filters["client_id"] = client_id
        if scenario_id:
            filters["scenario_id"] = scenario_id
        q_filter = _build_filter(filters)
        deleted = 0
        for collection in QDRANT_COLLECTIONS:
            self.client.delete(collection_name=collection, points_selector=q_filter)
            deleted += 1
        return {"collections_touched": deleted, "filters": filters}


def _build_filter(filters: dict[str, Any]) -> Filter | None:
    conditions = [
        FieldCondition(key=key, match=MatchValue(value=value))
        for key, value in filters.items()
        if value not in (None, "")
    ]
    if not conditions:
        return None
    return Filter(must=conditions)


def _point_id(collection: str, payload: dict[str, Any], text: str) -> str:
    for key in ("evidence_id", "knowledge_id", "case_id", "document_id", "asset_id"):
        value = payload.get(key)
        if value:
            chunk = payload.get("chunk_id") or payload.get("page_number") or ""
            return str(uuid5(NAMESPACE_URL, f"{collection}:{key}:{value}:{chunk}"))
    return str(uuid5(NAMESPACE_URL, f"{collection}:{payload}:{text[:200]}"))
