
from typing import Any

from fflake_graph.engine import (
    analyze,
    find_paths,
    verify_simulated_cut,
)


def analyze_path(source: str, target: str) -> dict[str, Any]:
    """Analyze modeled capability paths between two graph assets."""
    return analyze(source, target)


def get_paths(source: str, target: str) -> dict[str, Any]:
    """Retrieve modeled reachability paths between two graph assets."""
    paths = find_paths(source, target)

    return {
        "source": source,
        "target": target,
        "path_count": len(paths),
        "paths": paths,
        "simulation_only": True,
        "claim_boundary": (
            "Graph reachability is investigation evidence, "
            "not proof of exploitability."
        ),
    }


def verify_cut(
    source: str,
    target: str,
    cut_edge_id: str,
) -> dict[str, Any]:
    """Verify a proposed edge exclusion without modifying the graph."""
    return verify_simulated_cut(source, target, cut_edge_id)


TOOL_REGISTRY = {
    "analyze_path": analyze_path,
    "find_paths": get_paths,
    "verify_simulated_cut": verify_cut,
}


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Execute a registered investigation tool with basic input validation."""
    tool = TOOL_REGISTRY.get(tool_name)

    if tool is None:
        raise ValueError(f"Unknown agent tool: {tool_name}")

    required_arguments = {
        "analyze_path": {"source", "target"},
        "find_paths": {"source", "target"},
        "verify_simulated_cut": {
            "source",
            "target",
            "cut_edge_id",
        },
    }[tool_name]

    if set(arguments) != required_arguments:
        raise ValueError(
            f"{tool_name} requires exactly these arguments: "
            f"{sorted(required_arguments)}"
        )

    for name, value in arguments.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")

    return tool(**arguments)
