
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import fflake_graph.engine as engine


def _path_row(
    edge_ids: list[str],
    risks: list[int] | None = None,
    costs: list[int | None] | None = None,
) -> list[Any]:
    risks = risks if risks is not None else [1] * len(edge_ids)
    costs = costs if costs is not None else [None] * len(edge_ids)

    nodes = [
        {
            "id": f"node-{i}",
            "name": f"Node {i}",
            "kind": "asset",
            "risk": 1,
        }
        for i in range(len(edge_ids) + 1)
    ]

    edges = [
        {
            "id": edge_id,
            "kind": "CAN_REACH",
            "name": f"edge {edge_id}",
            "risk": risk,
            "remediation_cost": cost,
            "reason": "test evidence",
        }
        for edge_id, risk, cost in zip(edge_ids, risks, costs)
    ]

    return [nodes, edges]


def test_find_paths_scores_risk_and_assigns_critical_band(monkeypatch):
    monkeypatch.setattr(
        engine,
        "run_query",
        lambda query, params: [
            _path_row(
                ["edge-a", "edge-b", "edge-c"],
                [5, 9, 10],
                [3, 2, 8],
            )
        ],
    )

    paths = engine.find_paths("source", "target")

    assert len(paths) == 1
    assert paths[0]["hops"] == 3
    assert paths[0]["risk_score"] == 24
    assert paths[0]["risk_band"] == "critical"


def test_find_paths_returns_empty_when_no_route_exists(monkeypatch):
    monkeypatch.setattr(engine, "run_query", lambda query, params: [])
    assert engine.find_paths("source", "unreachable-target") == []


def test_analyze_explains_when_no_path_is_found(monkeypatch):
    monkeypatch.setattr(engine, "run_query", lambda query, params: [])

    result = engine.analyze("source", "target")

    assert result["finding"] == "no_path_found"
    assert result["baseline_path_count"] == 0
    assert result["paths"] == []
    assert result["candidate_fixes"] == []
    assert result["minimum_cost_cut"] is None
    assert "does not prove" in result["claim_boundary"]


def test_simulated_cut_is_verified_only_when_all_paths_are_blocked(
    monkeypatch,
):
    baseline = [_path_row(["edge-a", "edge-b"], [4, 8], [3, 2])]

    def fake_query(query: str, params: dict[str, Any]):
        if params.get("excluded_edge_id") == "edge-b":
            return []
        return baseline

    monkeypatch.setattr(engine, "run_query", fake_query)

    result = engine.verify_simulated_cut("source", "target", "edge-b")

    assert result["baseline_path_count"] == 1
    assert result["remaining_path_count"] == 0
    assert result["verified_in_simulation"] is True
    assert result["simulation_only"] is True
    assert "does not delete or change" in result["important"]


def test_simulated_cut_does_not_claim_success_if_alternative_path_remains(
    monkeypatch,
):
    path_one = _path_row(["edge-a", "edge-b"], [4, 8], [3, 2])
    path_two = _path_row(["edge-a", "edge-c"], [4, 7], [3, 8])

    def fake_query(query: str, params: dict[str, Any]):
        if params.get("excluded_edge_id") == "edge-b":
            return [path_two]
        return [path_one, path_two]

    monkeypatch.setattr(engine, "run_query", fake_query)

    result = engine.verify_simulated_cut("source", "target", "edge-b")

    assert result["baseline_path_count"] == 2
    assert result["remaining_path_count"] == 1
    assert result["verified_in_simulation"] is False
    assert result["simulation_only"] is True


def test_minimum_cost_cut_chooses_cheapest_edge_in_single_chain(
    monkeypatch,
):
    baseline = [
        _path_row(
            ["edge-a", "edge-b", "edge-c"],
            [5, 9, 10],
            [3, 2, 8],
        )
    ]

    def fake_query(query: str, params: dict[str, Any]):
        excluded = params.get("excluded_edge_id")
        if excluded in {"edge-a", "edge-b", "edge-c"}:
            return []
        return baseline

    monkeypatch.setattr(engine, "run_query", fake_query)

    result = engine.analyze("source", "target")
    cut = result["minimum_cost_cut"]

    assert cut is not None
    assert [edge["edge_id"] for edge in cut["edges"]] == ["edge-b"]
    assert cut["total_remediation_cost"] == 2
    assert cut["simulation_only"] is True


def test_minimum_cost_cut_blocks_all_alternative_paths(monkeypatch):
    # Both paths share edge-a, which costs 4.
    # Cutting edge-b and edge-c costs 2 + 3 = 5.
    path_one = _path_row(["edge-a", "edge-b"], costs=[4, 2])
    path_two = _path_row(["edge-a", "edge-c"], costs=[4, 3])

    result = engine._minimum_cost_cut([
        {"edges": path_one[1]},
        {"edges": path_two[1]},
    ])

    assert result is not None
    assert [edge["edge_id"] for edge in result["edges"]] == ["edge-a"]
    assert result["total_remediation_cost"] == 4


def test_minimum_cost_cut_can_choose_multiple_edges():
    path_one = _path_row(["edge-a", "edge-b"], costs=[5, 2])
    path_two = _path_row(["edge-a", "edge-c"], costs=[5, 3])

    result = engine._minimum_cost_cut([
        {"edges": path_one[1]},
        {"edges": path_two[1]},
    ])

    assert result is not None
    assert {edge["edge_id"] for edge in result["edges"]} == {
        "edge-b",
        "edge-c",
    }
    assert result["total_remediation_cost"] == 5


def test_minimum_cost_cut_flags_assumed_legacy_cost():
    path = _path_row(["edge-a"])

    result = engine._minimum_cost_cut([{"edges": path[1]}])

    assert result is not None
    assert result["total_remediation_cost"] == 1
    assert result["cost_assumption_used"] is True
    assert result["edges"][0]["cost_was_assumed"] is True


def test_minimum_cost_cut_rejects_negative_cost():
    path = _path_row(["edge-a"], costs=[-1])

    try:
        engine._minimum_cost_cut([{"edges": path[1]}])
    except ValueError as exc:
        assert "Negative remediation cost" in str(exc)
    else:
        raise AssertionError("Expected negative remediation cost to fail")
