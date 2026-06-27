from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class FilesystemMCP:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def scenario_dir(self, scenario_id: str) -> Path:
        path = self.data_dir / "scenarios" / scenario_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def reset_scenario_dir(self, scenario_id: str) -> Path:
        path = self.data_dir / "scenarios" / scenario_id
        expected_parent = (self.data_dir / "scenarios").resolve()
        resolved = path.resolve()
        if expected_parent not in resolved.parents:
            raise ValueError(f"Refusing to reset path outside scenario root: {resolved}")
        if path.exists():
            for child in path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, path: Path, data: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def append_jsonl(self, path: Path, records: list[Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(_jsonable(record), ensure_ascii=False) + "\n")
        return path


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
