from __future__ import annotations

import json
from pathlib import Path

from risk_agent_platform.schemas import KnowledgeObject


class ExpertKnowledgeMCP:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._objects = self._load_objects(data_dir / "expert_knowledge" / "rules.jsonl")

    @staticmethod
    def _load_objects(path: Path) -> list[KnowledgeObject]:
        if not path.exists():
            return []
        objects: list[KnowledgeObject] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                objects.append(KnowledgeObject.model_validate(json.loads(line)))
        return objects

    def search(self, *, domains: set[str] | None = None, object_types: set[str] | None = None) -> list[KnowledgeObject]:
        results = self._objects
        if domains:
            results = [item for item in results if item.domain in domains]
        if object_types:
            results = [item for item in results if item.object_type in object_types]
        return results

    def get_language_guardrails(self) -> list[KnowledgeObject]:
        return self.search(object_types={"language_guardrail"})

    def get_review_triggers(self) -> list[KnowledgeObject]:
        return self.search(object_types={"review_trigger"})
