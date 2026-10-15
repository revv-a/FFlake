from __future__ import annotations
from collections import Counter
from typing import Any
from .db import run_query
from .demo import ALLOWED_EDGE_KINDS

def _path_query(excluded_edge_id: str | None = None) -> tuple[str, dict[str, Any]]:
    exclusion = ""
    params: dict[str, Any] = {"allowed_kinds": ALLOWED_EDGE_KINDS}
    if excluded_edge_id:
        exclusion = "AND all(r IN relationships(p) WHERE r.id <> $excluded_edge_id)"
        params["excluded_edge_id"] = excluded_edge_id
    query = f"""
    MATCH p=(s:FFAsset {{id: $source}})-[:FF_REL*1..6]->(t:FFAsset {{id: $target}})
    WHERE all(r IN relationships(p) WHERE r.kind IN $allowed_kinds)
    {exclusion}
    RETURN
      [n IN nodes(p) | {{id:n.id, name:n.name, kind:n.kind, risk:n.risk}}] AS nodes,
      [r IN relationships(p) | {{id:r.id, kind:r.kind, name:r.name, risk:r.risk, reason:r.reason}}] AS edges
    LIMIT 50
    """
    return query, params

def find_paths(source: str, target: str, excluded_edge_id: str | None = None) -> list[dict[str, Any]]:
    query, params = _path_query(excluded_edge_id)
    params.update({"source": source, "target": target})
    rows = run_query(query, params)
    paths = []
    for row in rows:
        nodes, edges = row[0] or [], row[1] or []
        risk = sum(int(edge.get("risk") or 0) for edge in edges)
        paths.append({
            "nodes": nodes, "edges": edges, "hops": len(edges),
            "risk_score": risk,
            "risk_band": "critical" if risk >= 20 else "high" if risk >= 12 else "moderate" if risk >= 6 else "low",
        })
    paths.sort(key=lambda item: (item["risk_score"], -item["hops"]), reverse=True)
    return paths

def analyze(source: str, target: str) -> dict[str, Any]:
    paths = find_paths(source, target)
    if not paths:
        return {
            "source": source, "target": target, "finding": "no_path_found",
            "baseline_path_count": 0, "paths": [], "candidate_fixes": [],
            "claim_boundary": "No matching path was found within six hops and the configured relationship types. This does not prove no other route exists."
        }
    edge_frequency: Counter[str] = Counter()
    edge_meta: dict[str, dict[str, Any]] = {}
    for path in paths:
        for edge in path["edges"]:
            edge_id = edge.get("id")
            if edge_id:
                edge_frequency[edge_id] += 1
                edge_meta[edge_id] = edge
    candidates = []
    for edge_id, count in edge_frequency.most_common():
        remaining = find_paths(source, target, excluded_edge_id=edge_id)
        edge = edge_meta[edge_id]
        candidates.append({
            "edge_id": edge_id, "relationship": edge.get("name") or edge.get("kind"),
            "relationship_kind": edge.get("kind"), "risk": int(edge.get("risk") or 0),
            "baseline_paths_containing_edge": count,
            "remaining_path_count_after_simulated_cut": len(remaining),
            "paths_blocked": max(0, len(paths) - len(remaining)),
            "simulation_only": True,
        })
    candidates.sort(key=lambda item: (
        item["remaining_path_count_after_simulated_cut"] == 0,
        item["paths_blocked"], -item["risk"]
    ), reverse=True)
    return {
        "source": source, "target": target, "finding": "capability_path_found",
        "baseline_path_count": len(paths), "paths": paths, "candidate_fixes": candidates,
        "claim_boundary": "Graph-reachable capability paths for investigation, not proof of exploitability or a confirmed vulnerability."
    }

def verify_simulated_cut(source: str, target: str, cut_edge_id: str) -> dict[str, Any]:
    baseline = find_paths(source, target)
    remaining = find_paths(source, target, excluded_edge_id=cut_edge_id)
    return {
        "source": source, "target": target, "cut_edge_id": cut_edge_id,
        "baseline_path_count": len(baseline), "remaining_path_count": len(remaining),
        "verified_in_simulation": bool(baseline) and not remaining,
        "simulation_only": True,
        "important": "This excludes the edge during path search; it does not delete or change the relationship in FalkorDB. Apply an approved change and rerun verification against the updated graph before claiming remediation.",
        "remaining_paths": remaining,
    }
