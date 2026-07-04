from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

from risk_agent_platform.config import Settings


ALLOWED_NODE_LABELS = {
    "Client",
    "LegalEntity",
    "BusinessUnit",
    "Site",
    "Supplier",
    "Customer",
    "Product",
    "Contract",
    "PurchaseOrder",
    "Invoice",
    "BankAccount",
    "Document",
    "RiskScenario",
    "Evidence",
    "Decision",
    "Assumption",
    "Unknown",
    "ScenarioDelta",
}

ALLOWED_RELATIONSHIPS = {
    "OWNS",
    "OPERATES",
    "SUPPLIES",
    "BUYS_FROM",
    "SELLS_TO",
    "GOVERNED_BY",
    "BILLED_BY",
    "PLACED_TO",
    "HOLDS",
    "AFFECTS",
    "SUPPORTS",
    "CONTRADICTS",
    "MITIGATES",
    "DEPENDS_ON",
    "HAS_ASSUMPTION",
    "HAS_UNKNOWN",
    "HAS_DELTA",
}


class Neo4jStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver = GraphDatabase.driver(
            settings.stores.neo4j_uri,
            auth=(settings.stores.neo4j_user, settings.stores.neo4j_password),
        )

    def close(self) -> None:
        self.driver.close()

    def ping(self) -> bool:
        self.driver.verify_connectivity()
        return True

    def upsert_asset(self, label: str, asset_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        label = _validate_label(label)
        props = _with_confidence_defaults(properties)
        query = f"MERGE (n:{label} {{id: $id}}) SET n += $props RETURN n.id AS id"
        with self.driver.session() as session:
            record = session.run(query, id=asset_id, props=props).single()
        return {"id": record["id"] if record else asset_id, "label": label}

    def upsert_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        relation_type = _validate_relationship(relation_type)
        props = _with_confidence_defaults(properties or {})
        query = (
            "MATCH (a {id: $source_id}) "
            "MATCH (b {id: $target_id}) "
            f"MERGE (a)-[r:{relation_type}]->(b) "
            "SET r += $props "
            "RETURN type(r) AS type"
        )
        with self.driver.session() as session:
            record = session.run(query, source_id=source_id, target_id=target_id, props=props).single()
        return {"source_id": source_id, "target_id": target_id, "relation_type": record["type"] if record else relation_type}

    def find_related_assets(self, asset_id: str, depth: int = 2) -> list[dict[str, Any]]:
        depth = _safe_relationship_depth(depth, maximum=5)
        query = (
            f"MATCH p=(n {{id: $asset_id}})-[*1..{depth}]-(m) "
            "RETURN m.id AS id, labels(m) AS labels, properties(m) AS properties LIMIT 50"
        )
        with self.driver.session() as session:
            return [dict(record) for record in session.run(query, asset_id=asset_id)]

    def find_affected_assets(self, scenario_id: str) -> list[dict[str, Any]]:
        query = (
            "MATCH (:RiskScenario {id: $scenario_id})-[:AFFECTS]->(m) "
            "RETURN m.id AS id, labels(m) AS labels, properties(m) AS properties LIMIT 100"
        )
        with self.driver.session() as session:
            return [dict(record) for record in session.run(query, scenario_id=scenario_id)]

    def find_risk_paths(self, scenario_id: str, max_depth: int = 4) -> list[dict[str, Any]]:
        max_depth = _safe_relationship_depth(max_depth, maximum=6)
        query = (
            f"MATCH p=(:RiskScenario {{id: $scenario_id}})-[*1..{max_depth}]->(m) "
            "RETURN [node IN nodes(p) | node.id] AS node_ids, [rel IN relationships(p) | type(rel)] AS rels LIMIT 50"
        )
        with self.driver.session() as session:
            return [dict(record) for record in session.run(query, scenario_id=scenario_id)]


def _validate_label(label: str) -> str:
    if label not in ALLOWED_NODE_LABELS:
        raise ValueError(f"Unsupported node label: {label}")
    return label


def _validate_relationship(relation_type: str) -> str:
    if relation_type not in ALLOWED_RELATIONSHIPS:
        raise ValueError(f"Unsupported relation type: {relation_type}")
    return relation_type


def _with_confidence_defaults(properties: dict[str, Any]) -> dict[str, Any]:
    props = dict(properties)
    props.setdefault("confidence_level", "source_backed")
    props.setdefault("source_type", "client_data")
    props.setdefault("requires_validation", False)
    return props


def _safe_relationship_depth(value: int, *, maximum: int) -> int:
    try:
        depth = int(value)
    except (TypeError, ValueError):
        depth = 1
    return max(1, min(depth, maximum))
