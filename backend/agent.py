
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_tools import execute_tool
from fflake_graph.engine import MAX_HOPS, MAX_PATHS, require_entities
from fflake_graph.errors import EntityNotFoundError
from workflow_store import save_investigation

# Tool timeout (seconds). Keeps a slow graph query from hanging the request.
TOOL_TIMEOUT_SECONDS = 30

MUTATION_REQUEST_PATTERN = re.compile(
    r"\b(apply|execute|delete|remove|revoke|drop|grant|rotate|update|"
    r"modify|mutate|change)\b",
    re.IGNORECASE,
)
SIMULATION_INTENT_PATTERN = re.compile(
    r"\b(simulate|simulation|verify|verified|hypothetical|dry[- ]?run|"
    r"model|project|preview|would|impact)\b",
    re.IGNORECASE,
)
SOURCE_PATTERN = re.compile(r"source=([A-Za-z0-9][A-Za-z0-9_.:-]*)")
TARGET_PATTERN = re.compile(r"target=([A-Za-z0-9][A-Za-z0-9_.:-]*)")
EDGE_PATTERN = re.compile(r"edge=([A-Za-z0-9][A-Za-z0-9_.:-]*)")

RISK_BAND_THRESHOLDS = {
    "critical": 20,
    "high": 12,
    "moderate": 6,
    "low": 0,
}

TOOL_DESCRIPTIONS = {
    "analyze_path": (
        "Enumerate capability paths between two entities, score them, "
        "and rank candidate intervention edges."
    ),
    "find_paths": (
        "List the modeled reachability paths between two entities "
        "without remediation ranking."
    ),
    "rank_chokepoints": (
        "Rank intermediate nodes by how often they appear on "
        "source-to-target paths."
    ),
    "verify_simulated_cut": (
        "Exclude an edge during path search and compare the before and "
        "after path counts. Does not modify the graph."
    ),
}


def _run_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool on a worker thread so a hung query can time out."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute_tool, tool_name, arguments)
        return future.result(timeout=TOOL_TIMEOUT_SECONDS)


def _evidence_from_result(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Extract reviewable, tool-derived facts for the response."""
    evidence: dict[str, Any] = {
        "tool_name": tool_name,
        "arguments": arguments,
        "claim_boundary": result.get("claim_boundary"),
        "simulation_only": bool(result.get("simulation_only")),
        "paths": [],
    }

    for path in result.get("paths") or []:
        evidence["paths"].append({
            "hops": path.get("hops"),
            "risk_score": path.get("risk_score"),
            "risk_band": path.get("risk_band"),
            "edge_ids": [edge.get("id") for edge in path.get("edges", [])],
        })

    if tool_name == "rank_chokepoints":
        evidence["chokepoints"] = result.get("chokepoints", [])

    if tool_name == "verify_simulated_cut":
        evidence["baseline_path_count"] = result.get("baseline_path_count")
        evidence["remaining_path_count"] = result.get("remaining_path_count")
        evidence["paths_blocked_by_cut"] = result.get("paths_blocked_by_cut")
        evidence["verified_in_simulation"] = result.get(
            "verified_in_simulation"
        )

    if tool_name == "analyze_path":
        evidence["baseline_path_count"] = result.get("baseline_path_count")
        evidence["candidate_fixes"] = [
            {
                "edge_id": fix.get("edge_id"),
                "relationship": fix.get("relationship"),
                "relationship_kind": fix.get("relationship_kind"),
                "risk": fix.get("risk"),
                "remediation_cost": fix.get("remediation_cost"),
                "cost_was_assumed": fix.get("cost_was_assumed"),
                "paths_blocked": fix.get("paths_blocked"),
                "affected_path_indexes": fix.get("affected_path_indexes"),
                "why_recommended": fix.get("why_recommended"),
                "limitations": fix.get("limitations"),
                "simulation_only": True,
            }
            for fix in result.get("candidate_fixes", [])
        ]

    return evidence


def _select_tool(normalized: str) -> str | None:
    """Map the request text to the single most appropriate read-only tool."""
    if "chokepoint" in normalized:
        return "rank_chokepoints"

    if "verify" in normalized or "simulate fix" in normalized:
        return "verify_simulated_cut"

    if (
        "list path" in normalized
        or "show path" in normalized
        or "reachability" in normalized
    ):
        return "find_paths"

    if any(
        word in normalized
        for word in (
            "investigate", "analyze", "analyse", "risk", "path",
            "recommend", "fix", "proposal",
        )
    ):
        return "analyze_path"

    return None


def _failed_run(
    run_id: str,
    timestamp: str,
    request: str,
    tool_name: str | None,
    arguments: dict[str, Any],
    message: str,
    reason: str,
    status: str = "failed",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and persist an honest failed/refused run record."""
    response: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp,
        "request": request,
        "status": status,
        "message": message,
        "safety": {
            "real_changes_performed": False,
            "simulation_only": True,
            "mutation_possible": False,
        },
    }

    if tool_name:
        response["decision"] = {
            "selected_tool": tool_name,
            "arguments": arguments,
            "reason": reason,
        }

    if extra:
        response.update(extra)

    save_investigation(response)
    return response


def run_agent(request: str) -> dict[str, Any]:
    """Run a deterministic, simulation-only security investigation.

    This agent is rule-based: it selects tools from explicit keywords in
    the request. It does not call an LLM, and it has no tools that can
    mutate the graph or any external system. Every recommendation it
    produces is derived from live graph queries and is labeled accordingly.
    """

    request = request.strip()

    if not request:
        raise ValueError("Request cannot be empty")

    normalized = request.lower()
    run_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    source_match = SOURCE_PATTERN.search(request)
    target_match = TARGET_PATTERN.search(request)
    edge_match = EDGE_PATTERN.search(request)

    source = source_match.group(1) if source_match else "external-bot"
    target = target_match.group(1) if target_match else "prod-secrets"
    source_default = source_match is None
    target_default = target_match is None

    tool_name = _select_tool(normalized)

    # Safety boundary: FFlake has no tools that mutate the graph. A request
    # that asks for real changes is never silently simulated as if the
    # change had happened.
    mutation_requested = bool(MUTATION_REQUEST_PATTERN.search(request))
    simulation_intent = bool(SIMULATION_INTENT_PATTERN.search(request))

    if mutation_requested and not simulation_intent:
        response = {
            "run_id": run_id,
            "timestamp": timestamp,
            "request": request,
            "status": "refused",
            "message": (
                "This request asks to apply a real change. FFlake cannot "
                "modify FalkorDB, permissions, or any external system. It "
                "only reads the graph and simulates the effect of an "
                "approved edge exclusion. Rephrase with 'simulate' or "
                "'verify' to run the read-only analysis."
            ),
            "available_tools": sorted(TOOL_DESCRIPTIONS),
            "safety": {
                "mutation_requested": True,
                "mutation_possible": False,
                "real_changes_performed": False,
                "simulation_only": True,
            },
        }
        save_investigation(response)
        return response

    if tool_name is None:
        response = {
            "run_id": run_id,
            "timestamp": timestamp,
            "status": "needs_clarification",
            "request": request,
            "message": (
                "Ask me to investigate a path, rank chokepoints, or "
                "simulate a fix. Example: investigate source=external-bot "
                "target=prod-secrets"
            ),
            "available_tools": sorted(TOOL_DESCRIPTIONS),
        }
        save_investigation(response)
        return response

    arguments: dict[str, Any] = {
        "source": source,
        "target": target,
    }

    if tool_name == "verify_simulated_cut":
        if not edge_match:
            response = {
                "run_id": run_id,
                "timestamp": timestamp,
                "request": request,
                "status": "needs_input",
                "message": (
                    "Provide an edge ID, for example "
                    "edge=edge-deploy-secrets."
                ),
                "available_tools": ["verify_simulated_cut"],
            }
            save_investigation(response)
            return response

        arguments["cut_edge_id"] = edge_match.group(1)

    # Entity checks run against the live graph. Missing entities produce an
    # honest not_found status, never a fabricated result.
    try:
        require_entities(source, target)
        result = _run_tool(tool_name, arguments)

    except EntityNotFoundError as exc:
        response = _failed_run(
            run_id,
            timestamp,
            request,
            tool_name,
            arguments,
            message=(
                "The requested entity was not found in the graph. "
                f"Check the id or seed the demo data. Details: {exc}"
            ),
            reason=(
                "The planner mapped the request to a graph tool, but "
                "entity validation failed before execution."
            ),
            status="not_found",
            extra={"evidence": {"missing": list(exc.missing)}},
        )
        return response

    except FutureTimeout:
        return _failed_run(
            run_id,
            timestamp,
            request,
            tool_name,
            arguments,
            message=(
                f"Tool '{tool_name}' timed out after "
                f"{TOOL_TIMEOUT_SECONDS}s. No result was produced."
            ),
            reason="The tool exceeded its execution budget.",
        )

    except ValueError as exc:
        return _failed_run(
            run_id,
            timestamp,
            request,
            tool_name,
            arguments,
            message=f"Tool execution was rejected: {exc}",
            reason="Input validation failed inside the tool.",
        )

    except Exception as exc:  # noqa: BLE001 - report, never fabricate success
        return _failed_run(
            run_id,
            timestamp,
            request,
            tool_name,
            arguments,
            message=(
                f"Tool '{tool_name}' failed: {type(exc).__name__}: {exc}"
            ),
            reason="The tool raised an unexpected error.",
        )

    # Heuristic recommendations stay separate from graph-derived facts.
    recommendation = None
    if tool_name == "analyze_path":
        candidates = result.get("candidate_fixes") or []
        if candidates:
            best = candidates[0]
            recommendation = {
                "source": "heuristic_planner",
                "text": (
                    f"Simulate excluding edge '{best.get('edge_id')}' "
                    f"({best.get('relationship')})."
                ),
                "basis": best.get("why_recommended"),
                "limitations": best.get("limitations"),
            }
        elif result.get("finding") == "no_path_found":
            recommendation = {
                "source": "heuristic_planner",
                "text": (
                    "No path was found within the search bounds; no "
                    "intervention is proposed."
                ),
                "basis": "no enumerated path between the selected entities",
                "limitations": (
                    "Bounded search; other routes beyond the hop or "
                    "result limits may exist."
                ),
            }

    explanation = (
        f"The planner selected '{tool_name}' based on the request text, "
        f"and the tool read the live FalkorDB graph for {source} -> {target}."
    )
    if source_default or target_default:
        explanation += (
            " No explicit source=/target= arguments were provided, so the "
            "demo defaults were used; re-run with source=<id> target=<id> "
            "to analyze different entities."
        )

    reason_by_tool = {
        "analyze_path": "The request asks for graph path analysis.",
        "find_paths": "The request asks to list reachability paths.",
        "rank_chokepoints": "The request asks for chokepoint ranking.",
        "verify_simulated_cut": (
            "The request asks to verify a simulated edge exclusion."
        ),
    }

    evidence = _evidence_from_result(tool_name, arguments, result)
    evidence["risk_band_thresholds"] = RISK_BAND_THRESHOLDS
    evidence["path_limits"] = {"max_hops": MAX_HOPS, "max_paths": MAX_PATHS}

    response = {
        "run_id": run_id,
        "timestamp": timestamp,
        "status": "completed",
        "request": request,
        "decision": {
            "selected_tool": tool_name,
            "arguments": arguments,
            "reason": reason_by_tool[tool_name],
            "defaults_applied": {
                "source": source_default,
                "target": target_default,
            },
            "tool_descriptions": TOOL_DESCRIPTIONS,
        },
        "explanation": explanation,
        "result": result,
        "evidence": evidence,
        "recommendation": recommendation,
        "safety": {
            "approval_required_before_real_changes": True,
            "real_changes_performed": False,
            "simulation_only": True,
            "mutation_possible": False,
            "risk_band_thresholds": RISK_BAND_THRESHOLDS,
        },
    }

    # Save every completed investigation to the local workflow store.
    save_investigation(response)

    return response

