from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "qwen/qwen3.6-flash"


def load_dotenv(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if override or key not in os.environ:
            os.environ[key] = value


def load_local_env(root: Path | None = None) -> None:
    base = root or Path.cwd()
    load_dotenv(base / ".env.local")
    load_dotenv(base / ".env")


@dataclass(frozen=True)
class OpenRouterSettings:
    api_key: str | None
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    max_retries: int
    app_url: str | None
    app_title: str | None

    @classmethod
    def from_env(cls) -> "OpenRouterSettings":
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL),
            model=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            temperature=float(os.getenv("OPENROUTER_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("OPENROUTER_MAX_TOKENS", "2048")),
            timeout_seconds=int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("OPENROUTER_MAX_RETRIES", "2")),
            app_url=os.getenv("OPENROUTER_HTTP_REFERER") or os.getenv("OPENROUTER_APP_URL"),
            app_title=os.getenv("OPENROUTER_APP_TITLE") or os.getenv("OPENROUTER_X_TITLE"),
        )


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    openrouter: OpenRouterSettings

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = project_root or Path.cwd()
        load_local_env(root)
        return cls(
            project_root=root,
            data_dir=root / "data",
            openrouter=OpenRouterSettings.from_env(),
        )
