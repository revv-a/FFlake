
from __future__ import annotations

from .db import run_query

# Fictional example:
# external bot -> webhook runner -> deploy identity -> secrets vault.
#
# This demonstrates graph reachability, not a claim about a real environment.
# remediation_cost values are illustrative units, not real financial costs.

NODES = [
    {
        "id": "external-bot",
        "name": "External Automation Bot",
        "kind": "principal",
        "risk": 4,
        "description": "External automation identity with access to a webhook.",
    },
    {
        "id": "webhook-runner",
        "name": "Webhook Runner",
        "kind": "service",
        "risk": 5,
        "description": "Service that runs automation jobs.",
    },
    {
        "id": "deploy-identity",
        "name": "Deployment Identity",
        "kind": "principal",
        "risk": 8,
        "description": "Identity permitted to assume deployment privileges.",
    },
    {
        "id": "prod-secrets",
        "name": "Production Secrets Vault",
        "kind": "resource",
        "risk": 10,
        "description": "Sensitive production secret store.",
    },
]

EDGES = [
    {
        "id": "edge-bot-webhook",
        "from": "external-bot",
        "to": "webhook-runner",
        "kind": "CAN_TRIGGER",
        "risk": 5,
        "remediation_cost": 3,
        "name": "can trigger webhook jobs",
        "reason": "The external bot can invoke the webhook runner.",
    },
    {
        "id": "edge-webhook-deploy",
        "from": "webhook-runner",
        "to": "deploy-identity",
        "kind": "CAN_ASSUME",
        "risk": 9,
        "remediation_cost": 2,
        "name": "can assume deployment identity",
        "reason": "The runner can assume the deployment identity.",
    },
    {
        "id": "edge-deploy-secrets",
        "from": "deploy-identity",
        "to": "prod-secrets",
        "kind": "CAN_ACCESS",
        "risk": 10,
        "remediation_cost": 8,
        "name": "can access production secrets",
        "reason": "The deployment identity can access the vault.",
    },
]

ALLOWED_EDGE_KINDS = [
    "CAN_TRIGGER",
    "CAN_ASSUME",
    "CAN_ACCESS",
    "TRUSTS",
    "EXPOSES",
    "CAN_REACH",
]


def seed_demo_graph() -> dict:
    """Upsert demo data without clearing existing graph data."""

    for node in NODES:
        run_query(
            """
            MERGE (n:FFAsset {id: $id})
            SET n.name = $name,
                n.kind = $kind,
                n.risk = $risk,
                n.description = $description,
                n.demo = true
            """,
            node,
        )

    for edge in EDGES:
        run_query(
            """
            MATCH (a:FFAsset {id: $from_id}),
                  (b:FFAsset {id: $to_id})
            MERGE (a)-[r:FF_REL {id: $id}]->(b)
            SET r.kind = $kind,
                r.risk = $risk,
                r.remediation_cost = $remediation_cost,
                r.name = $name,
                r.reason = $reason,
                r.demo = true
            """,
            {
                "id": edge["id"],
                "from_id": edge["from"],
                "to_id": edge["to"],
                "kind": edge["kind"],
                "risk": edge["risk"],
                "remediation_cost": edge["remediation_cost"],
                "name": edge["name"],
                "reason": edge["reason"],
            },
        )

    return {
        "seeded": True,
        "nodes": len(NODES),
        "relationships": len(EDGES),
        "source": "external-bot",
        "target": "prod-secrets",
        "note": (
            "Fictional demo data upserted; existing graph data "
            "was not cleared."
        ),
    }
