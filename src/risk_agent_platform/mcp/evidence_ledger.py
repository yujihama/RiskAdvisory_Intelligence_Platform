from __future__ import annotations

from pathlib import Path

from risk_agent_platform.mcp.filesystem import FilesystemMCP
from risk_agent_platform.schemas import EvidenceItem


class EvidenceLedgerMCP:
    def __init__(self, filesystem: FilesystemMCP, scenario_dir: Path) -> None:
        self.filesystem = filesystem
        self.scenario_dir = scenario_dir
        self._items: list[EvidenceItem] = []

    @property
    def items(self) -> list[EvidenceItem]:
        return list(self._items)

    def register(self, item: EvidenceItem) -> EvidenceItem:
        self._items.append(item)
        self.filesystem.append_jsonl(self.scenario_dir / "evidence_table.jsonl", [item])
        return item

    def find_contradictory_evidence(self, claim: str) -> list[EvidenceItem]:
        lowered = claim.lower()
        return [
            item
            for item in self._items
            if item.contradicts and any(token in lowered for token in " ".join(item.contradicts).lower().split())
        ]
