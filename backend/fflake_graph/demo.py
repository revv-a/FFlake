from __future__ import annotations

from .db import run_query

# Fictional security graph for the FFlake demo.
# Demonstrates graph reachability, not a real environment.

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
        "id": "ci-runner",
        "name": "CI Runner",
        "kind": "service",
        "risk": 6,
        "description": "Continuous integration runner with deployment access.",
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
        "id": "edge-bot-ci",
        "from": "external-bot",
        "to": "ci-runner",
        "kind": "CAN_TRIGGER",
        "risk": 4,
        "remediation_cost": 1,
        "name": "can trigger CI workflows",
        "reason": "The external bot can trigger CI workflows.",
    },
    {
        "id": "edge-ci-deploy",
        "from": "ci-runner",
        "to": "deploy-identity",
        "kind": "CAN_ASSUME",
        "risk": 8,
        "remediation_cost": 3,
        "name": "can assume deployment identity through CI",
        "reason": "The CI runner can assume the deployment identity.",
    },
    {
        "id": "edge-deploy-secrets",
        "from": "deploy-identity",
        "to": "prod-secrets",
        "kind": "CAN_ACCESS",
        "risk": 10,
        "remediation_cost": 4,
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


def _demo_pair(source: str, target: str, description: str) -> dict:
    try:
        path_count = len(find_paths(source, target))
    except Exception:  # pragma: no cover - presets must never break seeding
        path_count = None

    return {
        "source": source,
        "target": target,
        "description": description,
        "current_path_count": path_count,
    }


def demo_presets() -> list[dict]:
    """Label convenient demo entity pairs computed against the live graph.

    These are selectable examples only. Every investigation runs against the
    entities the user actually chooses.
    """
    return [
        _demo_pair(
            "external-bot",
            "prod-secrets",
            "Default scenario: external automation identity to the "
            "production secrets vault.",
        ),
        _demo_pair(
            "webhook-runner",
            "prod-secrets",
            "Alternative path: the webhook runner to the vault.",
        ),
        _demo_pair(
            "webhook-runner",
            "ci-runner",
            "Unreachable pair: exists in the graph but has no path, "
            "to demonstrate the empty state.",
        ),
    ]


DEMO_PRESETS = demo_presets()


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

    from .engine import find_paths

    default_paths = find_paths("external-bot", "prod-secrets")

    return {
        "seeded": True,
        "nodes": len(NODES),
        "relationships": len(EDGES),
        "source": "external-bot",
        "target": "prod-secrets",
        "default_path_count": len(default_paths),
        "note": (
            "Fictional demo data upserted with MERGE; existing graph data "
            "was not cleared."
        ),
        "presets": demo_presets(),
    }
