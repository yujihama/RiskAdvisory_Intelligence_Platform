from __future__ import annotations

import json
from pathlib import Path


class SourceCatalogMCP:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def matching_dummy_sources(self, *, countries: list[str], risk_themes: list[str]) -> list[dict[str, object]]:
        path = self.data_dir / "external_sources" / "dummy_sources.json"
        if not path.exists():
            return []
        records = json.loads(path.read_text(encoding="utf-8"))
        country_set = {country.lower() for country in countries}
        theme_set = {theme.lower() for theme in risk_themes}
        matches: list[dict[str, object]] = []
        for record in records:
            record_countries = {str(country).lower() for country in record.get("countries", [])}
            record_themes = {str(theme).lower() for theme in record.get("risk_themes", [])}
            if country_set & record_countries or theme_set & record_themes:
                matches.append(record)
        return matches
