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
        model = (
            os.getenv("DEFAULT_MODEL")
            or os.getenv("REASONING_MODEL")
            or os.getenv("OPENROUTER_MODEL")
            or DEFAULT_OPENROUTER_MODEL
        )
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL),
            model=model,
            temperature=float(os.getenv("OPENROUTER_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("OPENROUTER_MAX_TOKENS", "2048")),
            timeout_seconds=int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("OPENROUTER_MAX_RETRIES", "2")),
            app_url=os.getenv("OPENROUTER_HTTP_REFERER") or os.getenv("OPENROUTER_APP_URL"),
            app_title=os.getenv("OPENROUTER_APP_TITLE") or os.getenv("OPENROUTER_X_TITLE"),
        )


@dataclass(frozen=True)
class StoreSettings:
    qdrant_url: str
    qdrant_api_key: str | None
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    @classmethod
    def from_env(cls) -> "StoreSettings":
        return cls(
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        )


@dataclass(frozen=True)
class LangfuseSettings:
    host: str | None
    public_key: str | None
    secret_key: str | None

    @classmethod
    def from_env(cls) -> "LangfuseSettings":
        return cls(
            host=os.getenv("LANGFUSE_HOST"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
            secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
        )


@dataclass(frozen=True)
class ExternalApiSettings:
    tavily_api_key: str | None

    @classmethod
    def from_env(cls) -> "ExternalApiSettings":
        return cls(tavily_api_key=os.getenv("TAVILY_API_KEY") or None)


def service_urls_from_env() -> dict[str, str]:
    return {
        "orchestrator-agent": os.getenv("ORCHESTRATOR_AGENT_URL", "http://localhost:8100"),
        "source-intelligence-agent": os.getenv("SOURCE_INTELLIGENCE_AGENT_URL", "http://localhost:8101"),
        "client-context-agent": os.getenv("CLIENT_CONTEXT_AGENT_URL", "http://localhost:8102"),
        "treasury-risk-agent": os.getenv("TREASURY_RISK_AGENT_URL", "http://localhost:8103"),
        "legal-risk-agent": os.getenv("LEGAL_RISK_AGENT_URL", "http://localhost:8104"),
        "accounting-risk-agent": os.getenv("ACCOUNTING_RISK_AGENT_URL", "http://localhost:8105"),
        "procurement-risk-agent": os.getenv("PROCUREMENT_RISK_AGENT_URL", "http://localhost:8106"),
        "expert-as-code-agent": os.getenv("EXPERT_AS_CODE_AGENT_URL", "http://localhost:8107"),
        "evidence-redteam-agent": os.getenv("EVIDENCE_REDTEAM_AGENT_URL", "http://localhost:8108"),
        "decision-synthesis-agent": os.getenv("DECISION_SYNTHESIS_AGENT_URL", "http://localhost:8109"),
    }


def mcp_urls_from_env() -> dict[str, str]:
    return {
        "mcp-web-search": os.getenv("MCP_WEB_SEARCH_URL", "http://localhost:8201/mcp"),
        "mcp-document-parser": os.getenv("MCP_DOCUMENT_PARSER_URL", "http://localhost:8202/mcp"),
        "mcp-llm-ocr": os.getenv("MCP_LLM_OCR_URL", "http://localhost:8203/mcp"),
        "mcp-qdrant": os.getenv("MCP_QDRANT_URL", "http://localhost:8204/mcp"),
        "mcp-neo4j": os.getenv("MCP_NEO4J_URL", "http://localhost:8205/mcp"),
        "mcp-filesystem": os.getenv("MCP_FILESYSTEM_URL", "http://localhost:8206/mcp"),
        "mcp-structured-data": os.getenv("MCP_STRUCTURED_DATA_URL", "http://localhost:8207/mcp"),
        "mcp-expert-knowledge": os.getenv("MCP_EXPERT_KNOWLEDGE_URL", "http://localhost:8208/mcp"),
        "mcp-evidence-ledger": os.getenv("MCP_EVIDENCE_LEDGER_URL", "http://localhost:8209/mcp"),
    }


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    openrouter: OpenRouterSettings
    stores: StoreSettings
    external_apis: ExternalApiSettings
    langfuse: LangfuseSettings
    service_urls: dict[str, str]
    mcp_urls: dict[str, str]

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = project_root or Path.cwd()
        load_local_env(root)
        return cls(
            project_root=root,
            data_dir=root / "data",
            openrouter=OpenRouterSettings.from_env(),
            stores=StoreSettings.from_env(),
            external_apis=ExternalApiSettings.from_env(),
            langfuse=LangfuseSettings.from_env(),
            service_urls=service_urls_from_env(),
            mcp_urls=mcp_urls_from_env(),
        )
