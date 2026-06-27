from __future__ import annotations

import csv
from pathlib import Path


class StructuredDataMCP:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def client_structured_dir(self, client_id: str) -> Path:
        return self.data_dir / "clients" / client_id / "structured"

    def read_client_table(self, client_id: str, table_name: str) -> list[dict[str, str]]:
        path = self.client_structured_dir(client_id) / f"{table_name}.csv"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def load_client_dataset(self, client_id: str) -> dict[str, list[dict[str, str]]]:
        return {
            "suppliers": self.read_client_table(client_id, "suppliers"),
            "payments": self.read_client_table(client_id, "payments"),
            "contracts": self.read_client_table(client_id, "contracts"),
            "sites": self.read_client_table(client_id, "sites"),
        }
