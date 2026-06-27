from __future__ import annotations

from risk_agent_platform.a2a import AgentRunContext
from risk_agent_platform.agents.base import BaseAgent
from risk_agent_platform.schemas import AgentFinding, AgentTask, AssetRelation, ClientAsset, ClientContext


class ClientContextAgent(BaseAgent):
    name = "client-context-agent"
    description = "Builds source-backed client context and a sparse Client Asset Graph."
    skills = ["client_asset_graph", "unknown_register", "safe_contextualization"]
    modes = ["client_context"]

    def handle(self, task: AgentTask, context: AgentRunContext) -> AgentFinding:
        event = context.risk_event
        dataset = context.structured_data.load_client_dataset(event.client_id)
        context.state["client_dataset"] = dataset

        countries = {country.lower() for country in event.countries}
        affected_supplier_ids = {
            row["supplier_id"]
            for row in dataset["suppliers"]
            if row.get("country", "").lower() in countries or row.get("criticality", "").lower() == "high"
        }

        assets: list[ClientAsset] = []
        relations: list[AssetRelation] = []
        unknowns: list[str] = []
        assumptions: list[str] = []

        for supplier in dataset["suppliers"]:
            if supplier["supplier_id"] in affected_supplier_ids:
                assets.append(
                    ClientAsset(
                        asset_id=supplier["supplier_id"],
                        asset_type="Supplier",
                        name=supplier["name"],
                        country=supplier.get("country") or None,
                        attributes=supplier,
                        source_ref="suppliers.csv",
                    )
                )
                product_id = supplier.get("product_id")
                site_id = supplier.get("site_id")
                if product_id:
                    assets.append(
                        ClientAsset(
                            asset_id=product_id,
                            asset_type="Product",
                            name=supplier.get("product_name") or product_id,
                            attributes={"product_id": product_id},
                            source_ref="suppliers.csv",
                        )
                    )
                    relations.append(
                        AssetRelation(
                            source_asset_id=supplier["supplier_id"],
                            target_asset_id=product_id,
                            relation_type="SUPPLIES",
                            rationale="Supplier master maps supplier to critical product.",
                            source_ref="suppliers.csv",
                        )
                    )
                if site_id:
                    relations.append(
                        AssetRelation(
                            source_asset_id=site_id,
                            target_asset_id=supplier["supplier_id"],
                            relation_type="DEPENDS_ON",
                            rationale="Site depends on supplier for product supply.",
                            source_ref="suppliers.csv",
                        )
                    )
                if supplier.get("alternative_available", "").lower() == "false":
                    unknowns.append(f"Alternative sourcing readiness for {supplier['supplier_id']} needs validation.")

        for site in dataset["sites"]:
            if any(rel.source_asset_id == site["site_id"] for rel in relations):
                assets.append(
                    ClientAsset(
                        asset_id=site["site_id"],
                        asset_type="Site",
                        name=site["name"],
                        country=site.get("country") or None,
                        attributes=site,
                        source_ref="sites.csv",
                    )
                )

        for payment in dataset["payments"]:
            if payment["supplier_id"] in affected_supplier_ids:
                assets.append(
                    ClientAsset(
                        asset_id=payment["payment_id"],
                        asset_type="Payment",
                        name=payment["payment_id"],
                        country=payment.get("bank_country") or None,
                        attributes=payment,
                        source_ref="payments.csv",
                    )
                )
                relations.append(
                    AssetRelation(
                        source_asset_id=payment["payment_id"],
                        target_asset_id=payment["supplier_id"],
                        relation_type="PAYS_TO",
                        rationale="Payment schedule links pending payment to supplier.",
                        source_ref="payments.csv",
                    )
                )
                if not payment.get("bank_country"):
                    unknowns.append(f"Bank country is missing for payment {payment['payment_id']}.")

        contract_supplier_ids = {row.get("supplier_id") for row in dataset["contracts"]}
        for supplier_id in affected_supplier_ids - contract_supplier_ids:
            unknowns.append(f"Contract record is missing for affected supplier {supplier_id}.")

        if affected_supplier_ids:
            assumptions.append("Affected suppliers include direct country matches and high-criticality suppliers.")

        sufficiency = "medium" if dataset["suppliers"] and dataset["payments"] and dataset["contracts"] else "low"
        client_context = ClientContext(
            scenario_id=event.scenario_id,
            client_id=event.client_id,
            assets=assets,
            relations=relations,
            assumptions=assumptions,
            unknowns=unknowns,
            context_sufficiency=sufficiency,
        )
        context.state["client_context"] = client_context
        context.filesystem.write_json(context.scenario_dir / "graph_imports" / "client_asset_graph.json", client_context)
        return AgentFinding(
            agent_name=self.name,
            mode="client_context",
            summary=f"Built sparse Client Asset Graph with {len(assets)} assets and {len(relations)} relations.",
            risk_score=None,
            confidence=sufficiency,
            evidence_ids=[],
            assumptions=assumptions,
            unknowns=unknowns,
            recommended_actions=["Validate unknowns before using inferred dependencies for final decisions."],
            review_required=bool(unknowns),
            rationale="The graph separates source-backed records from unknowns and assumptions.",
            metadata={"asset_count": len(assets), "relation_count": len(relations), "affected_supplier_ids": sorted(affected_supplier_ids)},
        )
