from __future__ import annotations


RAW_STRUCTURED_DATA_TOOLS = frozenset(
    {
        "sample_rows",
        "query_dataset",
        "summarize_payment_exposure",
        "summarize_supplier_exposure",
        "summarize_invoice_exposure",
    }
)

LLM_SAFE_STRUCTURED_DATA_TOOLS = frozenset(
    {
        "list_datasets",
        "inspect_schema",
        "profile_dataset",
        "risk_feature_sample",
        "summarize_payment_exposure_safe",
        "summarize_supplier_exposure_safe",
        "summarize_invoice_exposure_safe",
        "summarize_contract_exposure_safe",
    }
)

AGENT_LLM_TOOL_ALLOWLIST: dict[str, dict[str, frozenset[str]]] = {
    "risk-discovery-agent": {
        "mcp-structured-data": frozenset({"list_datasets", "risk_feature_sample"}),
        "mcp-expert-knowledge": frozenset(
            {
                "load_knowledge_pack",
                "load_primitives",
                "load_case_bank",
                "load_question_bank",
                "load_cta_notes",
                "load_scope_relevance_rules",
            }
        ),
    },
    "source-intelligence-agent": {
        "mcp-web-search": frozenset({"search_authoritative_sources", "extract_url"}),
    },
    "expert-as-code-agent": {
        "mcp-expert-knowledge": frozenset(
            {
                "search_similar_cases",
                "search_knowledge_objects",
                "load_knowledge_pack",
                "load_cta_notes",
            }
        ),
    },
    "evidence-red-team-agent": {
        "mcp-evidence-ledger": frozenset({"list_evidence_by_scenario", "search_evidence"}),
        "mcp-qdrant": frozenset({"search_evidence"}),
        "mcp-neo4j": frozenset({"find_risk_paths"}),
        "mcp-structured-data": frozenset(
            {
                "risk_feature_sample",
                "summarize_payment_exposure_safe",
                "summarize_supplier_exposure_safe",
                "summarize_invoice_exposure_safe",
                "summarize_contract_exposure_safe",
            }
        ),
    },
    "treasury-risk-agent": {
        "mcp-structured-data": frozenset({"summarize_payment_exposure_safe"}),
    },
    "legal-risk-agent": {
        "mcp-structured-data": frozenset({"summarize_contract_exposure_safe"}),
    },
    "accounting-risk-agent": {
        "mcp-structured-data": frozenset({"summarize_payment_exposure_safe", "summarize_invoice_exposure_safe"}),
    },
}


def ensure_llm_tool_allowed(agent_name: str, server_name: str, tool_name: str) -> None:
    allowed = AGENT_LLM_TOOL_ALLOWLIST.get(agent_name, {}).get(server_name, frozenset())
    if tool_name not in allowed:
        raise ValueError(f"{agent_name} may not expose {server_name}.{tool_name} to DeepAgent tool-use")


def agent_llm_tools(agent_name: str, server_name: str) -> frozenset[str]:
    return AGENT_LLM_TOOL_ALLOWLIST.get(agent_name, {}).get(server_name, frozenset())
