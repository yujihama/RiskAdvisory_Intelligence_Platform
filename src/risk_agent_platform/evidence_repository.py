from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from risk_agent_platform.config import Settings
from risk_agent_platform.schemas import EvidenceItem
from risk_agent_platform.stores.neo4j_store import Neo4jStore
from risk_agent_platform.stores.qdrant_store import QdrantStore


class EvidenceRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.data_dir / "evidence" / "evidence.jsonl"

    def register(self, evidence: EvidenceItem, *, index_qdrant: bool = True, index_neo4j: bool = True) -> EvidenceItem:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = [item for item in self._read_all() if item.evidence_id != evidence.evidence_id]
        self._write_all([*existing, evidence])
        if index_qdrant:
            QdrantStore(self.settings).upsert_texts(
                "evidence_chunks",
                [
                    {
                        "text": evidence.summary,
                        "metadata": {
                            "client_id": evidence.client_id,
                            "scenario_id": evidence.scenario_id,
                            "source_type": evidence.source_type,
                            "mode": "evidence",
                            "asset_id": None,
                            "evidence_id": evidence.evidence_id,
                            "document_id": None,
                            "source_url": evidence.source_url,
                            "source_title": evidence.source_title,
                            "source_domain": evidence.source_domain,
                            "reliability": evidence.reliability,
                            "confidence": evidence.confidence,
                            "tags": evidence.supports,
                        },
                    }
                ],
            )
        if index_neo4j:
            store = Neo4jStore(self.settings)
            try:
                store.upsert_asset(
                    "RiskScenario",
                    evidence.scenario_id,
                    {
                        "scenario_id": evidence.scenario_id,
                        "client_id": evidence.client_id,
                        "source_type": "derived",
                        "confidence_level": "derived",
                    },
                )
                store.upsert_asset(
                    "Evidence",
                    evidence.evidence_id,
                    {
                        "scenario_id": evidence.scenario_id,
                        "client_id": evidence.client_id,
                        "source_type": evidence.source_type,
                        "source_url": evidence.source_url,
                        "source_title": evidence.source_title,
                        "source_domain": evidence.source_domain,
                        "summary": evidence.summary[:1000],
                        "reliability": evidence.reliability,
                        "confidence_level": "source_backed",
                        "requires_validation": False,
                    },
                )
                store.upsert_relation(evidence.evidence_id, evidence.scenario_id, "SUPPORTS", {"confidence_level": "source_backed"})
            finally:
                store.close()
        return evidence

    def list_by_scenario(self, scenario_id: str) -> list[EvidenceItem]:
        return [item for item in self._read_latest_by_id() if item.scenario_id == scenario_id]

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return next((item for item in self._read_latest_by_id() if item.evidence_id == evidence_id), None)

    def search(self, query: str, scenario_id: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
        filters = {"scenario_id": scenario_id} if scenario_id else {}
        return QdrantStore(self.settings).search("evidence_chunks", query=query, top_k=top_k, filters=filters)

    def _read_all(self) -> list[EvidenceItem]:
        if not self.path.exists():
            return []
        items: list[EvidenceItem] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(EvidenceItem.model_validate_json(line))
        return items

    def _read_latest_by_id(self) -> list[EvidenceItem]:
        by_id: dict[str, EvidenceItem] = {}
        for item in self._read_all():
            by_id[item.evidence_id] = item
        return list(by_id.values())

    def _write_all(self, items: list[EvidenceItem]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
