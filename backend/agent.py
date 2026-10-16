
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_tools import execute_tool


def run_agent(request: str) -> dict[str, Any]:
    """Run a deterministic security-investigation workflow."""

    request = request.strip()
    if not request:
        raise ValueError("Request cannot be empty")

    normalized = request.lower()
    run_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # These are the demo graph's default endpoints.
    # Explicit IDs can be supplied as source=... target=...
    source = "external-bot"
    target = "prod-secrets"

    for token in request.split():
        if token.startswith("source="):
            source = token[len("source="):].strip()
        elif token.startswith("target="):
            target = token[len("target="):].strip()

    if not source or not target:
        raise ValueError("Source and target must be non-empty")

    if "verify" in normalized or "simulate fix" in normalized:
        cut_edge_id = None

        for token in request.split():
            if token.startswith("edge="):
                cut_edge_id = token[len("edge="):].strip()

        if not cut_edge_id:
            return {
                "run_id": run_id,
                "timestamp": timestamp,
                "status": "needs_input",
                "message": (
                    "Provide an edge ID, for example "
                    "edge=edge-deploy-secrets."
                ),
                "available_tools": ["verify_simulated_cut"],
            }

        tool_name = "verify_simulated_cut"
        arguments = {
            "source": source,
            "target": target,
            "cut_edge_id": cut_edge_id,
        }

    elif "path" in normalized or "investigate" in normalized or "risk" in normalized:
        tool_name = "analyze_path"
        arguments = {"source": source, "target": target}

    else:
        return {
            "run_id": run_id,
            "timestamp": timestamp,
            "status": "needs_clarification",
            "message": (
                "Ask me to investigate a path or simulate a fix. "
                "Example: investigate source=external-bot "
                "target=prod-secrets"
            ),
        }

    result = execute_tool(tool_name, arguments)

    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "status": "completed",
        "request": request,
        "decision": {
            "selected_tool": tool_name,
            "arguments": arguments,
            "reason": (
                "The request asks for graph path analysis."
                if tool_name == "analyze_path"
                else "The request asks to verify a simulated edge exclusion."
            ),
        },
        "result": result,
        "safety": {
            "approval_required_before_real_changes": True,
            "real_changes_performed": False,
            "simulation_only": True,
        },
    }
