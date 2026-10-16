from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from typing import Any

import fflake_graph.engine as engine


def _path_row(edge_ids: list[str], risks: list[int] | None = None) -> list[Any]:
    risks = risks or [1] * len(edge_ids)
    nodes = [
        {"id": f"node-{i}", "name": f"Node {i}", "kind": "asset", "risk": 1}
        for i in range(len(edge_ids) + 1)
    ]
    edges = [
        {
            "id": edge_id,
            "kind": "CAN_REACH",
            "name": f"edge {edge_id}",
            "risk": risk,
            "reason": "test evidence",
        }
        for edge_id, risk in zip(edge_ids, risks)
    ]
    return [nodes, edges]


def test_find_paths_scores_risk_and_assigns_critical_band(monkeypatch):
    monkeypatch.setattr(
        engine,
        "run_query",
        lambda query, params: [_path_row(
            ["edge-a", "edge-b", "edge-c"], [5, 9, 10]
        )],
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
    assert "does not prove" in result["claim_boundary"]


def test_simulated_cut_is_verified_only_when_all_paths_are_blocked(monkeypatch):
    baseline = [_path_row(["edge-a", "edge-b"], [4, 8])]

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


def test_simulated_cut_does_not_claim_success_if_alternative_path_remains(monkeypatch):
    path_one = _path_row(["edge-a", "edge-b"], [4, 8])
    path_two = _path_row(["edge-a", "edge-c"], [4, 7])

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

