
from __future__ import annotations

from collections import Counter
from typing import Any

from .db import run_query
from .demo import ALLOWED_EDGE_KINDS
from .errors import EntityNotFoundError

# Path discovery limits. These bound the search so results stay fast and
# reviewable; they are reported in API responses via `path_limits`.
MAX_HOPS = 6
MAX_PATHS = 50

RISK_BANDS = {
    "critical": 20,
    "high": 12,
    "moderate": 6,
}


def risk_band(risk: int) -> str:
    """Map a summed path risk score to a severity band.

    Bands are additive: a longer path of medium-risk edges can reach a higher
    band than a single high-risk edge. See README "Scoring semantics".
    """
    if risk >= RISK_BANDS["critical"]:
        return "critical"
    if risk >= RISK_BANDS["high"]:
        return "high"
    if risk >= RISK_BANDS["moderate"]:
        return "moderate"
    return "low"


def require_entities(*entity_ids: str) -> None:
    """Raise EntityNotFoundError when any requested node is absent from the graph."""
    ids = [entity_id.strip() for entity_id in entity_ids if entity_id and entity_id.strip()]
    if not ids:
        raise ValueError("At least one entity id is required")

    rows = run_query(
        "MATCH (n:FFAsset) WHERE n.id IN $ids RETURN n.id",
        {"ids": ids},
    )
    found = {str(row[0]) for row in rows if row and row[0] is not None}
    missing = [entity_id for entity_id in ids if entity_id not in found]

    if missing:
        raise EntityNotFoundError(missing)


def list_entities() -> list[dict[str, Any]]:
    """List every node in the graph so clients can offer real entity pickers."""
    rows = run_query(
        """
        MATCH (n:FFAsset)
        RETURN n.id, n.name, n.kind, n.risk
        ORDER BY n.kind, n.name
        LIMIT 500
        """
    )
    entities = []
    for row in rows:
        if not row or row[0] is None:
            continue
        entities.append({
            "id": str(row[0]),
            "name": row[1] if len(row) > 1 else None,
            "kind": row[2] if len(row) > 2 else None,
            "risk": int(row[3]) if len(row) > 3 and row[3] is not None else None,
        })
    return entities


def _path_query(
    excluded_edge_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    exclusion = ""
    params: dict[str, Any] = {"allowed_kinds": ALLOWED_EDGE_KINDS}

    if excluded_edge_id:
        exclusion = (
            "AND all(r IN relationships(p) "
            "WHERE r.id <> $excluded_edge_id)"
        )
        params["excluded_edge_id"] = excluded_edge_id

    # One extra row is fetched so callers can detect truncation.
    query = f"""
    MATCH p=(s:FFAsset {{id: $source}})-[:FF_REL*1..{MAX_HOPS}]->(t:FFAsset {{id: $target}})
    WHERE all(r IN relationships(p) WHERE r.kind IN $allowed_kinds)
    {exclusion}
    RETURN
      [n IN nodes(p) | {{id:n.id, name:n.name, kind:n.kind, risk:n.risk}}] AS nodes,
      [r IN relationships(p) | {{
          id:r.id,
          kind:r.kind,
          name:r.name,
          risk:r.risk,
          remediation_cost:r.remediation_cost,
          reason:r.reason
      }}] AS edges
    LIMIT {MAX_PATHS + 1}
    """
    return query, params


def find_paths(
    source: str,
    target: str,
    excluded_edge_id: str | None = None,
) -> list[dict[str, Any]]:
    """Enumerate directed capability paths between two entities.

    Bounded by MAX_HOPS hops and MAX_PATHS results, restricted to
    ALLOWED_EDGE_KINDS. Results are deterministic: highest summed edge risk
    first, then fewest hops.
    """
    query, params = _path_query(excluded_edge_id)
    params.update({"source": source, "target": target})
    rows = run_query(query, params)

    paths = []
    for row in rows:
        nodes, edges = row[0] or [], row[1] or []

        # FalkorDB paths may revisit nodes; only simple paths are reported.
        node_ids = [str(node.get("id")) for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            continue

        risk = sum(int(edge.get("risk") or 0) for edge in edges)

        paths.append({
            "nodes": nodes,
            "edges": edges,
            "hops": len(edges),
            "risk_score": risk,
            "risk_band": risk_band(risk),
        })

    paths = paths[:MAX_PATHS]
    paths.sort(
        key=lambda item: (
            -item["risk_score"],
            item["hops"],
            [str(edge.get("id")) for edge in item["edges"]],
        ),
    )
    return paths


def _minimum_cost_cut(
    paths: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Find an exact minimum-cost hitting set for the supplied path set.

    Every path must contain at least one selected edge.
    This is exact for the supplied paths, not necessarily the entire graph.
    """

    if not paths:
        return {
            "edges": [],
            "total_remediation_cost": 0,
            "cost_assumption_used": False,
        }

    path_edge_sets: list[frozenset[str]] = []
    edge_meta: dict[str, dict[str, Any]] = {}
    assumed_cost_used = False

    for path in paths:
        ids: set[str] = set()

        for edge in path["edges"]:
            edge_id = edge.get("id")
            if not edge_id:
                continue

            ids.add(str(edge_id))

            if edge_id not in edge_meta:
                raw_cost = edge.get("remediation_cost")
                if raw_cost is None:
                    cost = 1
                    assumed_cost_used = True
                else:
                    cost = int(raw_cost)

                if cost < 0:
                    raise ValueError(
                        f"Negative remediation cost for edge {edge_id!r}"
                    )

                edge_meta[edge_id] = {
                    "edge_id": str(edge_id),
                    "relationship": edge.get("name") or edge.get("kind"),
                    "relationship_kind": edge.get("kind"),
                    "risk": int(edge.get("risk") or 0),
                    "remediation_cost": cost,
                    "cost_was_assumed": raw_cost is None,
                }

        # A path without any identifiable edge cannot be cut safely
        # by this edge-ID-based algorithm.
        if not ids:
            return None

        path_edge_sets.append(frozenset(ids))

    best_cost: int | None = None
    best_cut: frozenset[str] | None = None

    def search(
        selected: frozenset[str],
        current_cost: int,
    ) -> None:
        nonlocal best_cost, best_cut

        if best_cost is not None and current_cost >= best_cost:
            return

        uncovered = [
            path_edges
            for path_edges in path_edge_sets
            if selected.isdisjoint(path_edges)
        ]

        if not uncovered:
            best_cost = current_cost
            best_cut = selected
            return

        # Branch on the smallest uncovered path first.
        next_path = min(
            uncovered,
            key=lambda path_edges: (
                len(path_edges),
                tuple(sorted(path_edges)),
            ),
        )

        for edge_id in sorted(
            next_path,
            key=lambda item: (
                edge_meta[item]["remediation_cost"],
                item,
            ),
        ):
            if edge_id in selected:
                continue

            edge_cost = edge_meta[edge_id]["remediation_cost"]
            search(selected | {edge_id}, current_cost + edge_cost)

    search(frozenset(), 0)

    if best_cut is None or best_cost is None:
        return None

    chosen_edges = [
        {**edge_meta[edge_id]}
        for edge_id in sorted(best_cut)
    ]

    return {
        "edges": chosen_edges,
        "total_remediation_cost": best_cost,
        "cost_assumption_used": assumed_cost_used,
    }


def analyze(source: str, target: str) -> dict[str, Any]:
    paths = find_paths(source, target)

    if not paths:
        return {
            "source": source,
            "target": target,
            "finding": "no_path_found",
            "baseline_path_count": 0,
            "paths": [],
            "candidate_fixes": [],
            "minimum_cost_cut": None,
            "claim_boundary": (
                "No matching path was found within six hops and the "
                "configured relationship types. This does not prove "
                "no other route exists."
            ),
        }

    edge_frequency: Counter[str] = Counter()
    edge_meta: dict[str, dict[str, Any]] = {}
    edge_paths: dict[str, list[int]] = {}

    for path_index, path in enumerate(paths):
        for edge in path["edges"]:
            edge_id = edge.get("id")
            if edge_id:
                edge_id = str(edge_id)
                edge_frequency[edge_id] += 1
                edge_meta[edge_id] = edge
                edge_paths.setdefault(edge_id, []).append(path_index)

    candidates = []

    for edge_id, count in edge_frequency.most_common():
        remaining = find_paths(
            source,
            target,
            excluded_edge_id=edge_id,
        )
        edge = edge_meta[edge_id]
        raw_cost = edge.get("remediation_cost")
        affected_indexes = edge_paths.get(edge_id, [])

        candidates.append({
            "edge_id": edge_id,
            "relationship": edge.get("name") or edge.get("kind"),
            "relationship_kind": edge.get("kind"),
            "risk": int(edge.get("risk") or 0),
            "remediation_cost": (
                int(raw_cost) if raw_cost is not None else 1
            ),
            "cost_was_assumed": raw_cost is None,
            "baseline_paths_containing_edge": count,
            "affected_path_indexes": affected_indexes,
            "remaining_path_count_after_simulated_cut": len(remaining),
            "paths_blocked": max(0, len(paths) - len(remaining)),
            "why_recommended": (
                f"Observed on {count} of {len(paths)} enumerated path(s); "
                f"excluding it during search leaves {len(remaining)} path(s)."
            ),
            "limitations": (
                "Simulation only: excluding an edge during path search does "
                "not modify the graph or any real permission. Remediation "
                "cost is modeled metadata, not an executed change."
            ),
            "simulation_only": True,
        })

    candidates.sort(
        key=lambda item: (
            item["remaining_path_count_after_simulated_cut"] == 0,
            item["paths_blocked"],
            -item["remediation_cost"],
            -item["risk"],
        ),
        reverse=True,
    )

    minimum_cut = _minimum_cost_cut(paths)

    return {
        "source": source,
        "target": target,
        "finding": "capability_path_found",
        "baseline_path_count": len(paths),
        "paths": paths,
        "candidate_fixes": candidates,
        "minimum_cost_cut": (
            {
                **minimum_cut,
                "simulation_only": True,
                "claim_boundary": (
                    "Minimum-cost cut for the enumerated path set only. "
                    "Path discovery is limited to six hops and 50 results; "
                    "this is not a global optimality guarantee for the "
                    "entire graph."
                ),
            }
            if minimum_cut is not None else None
        ),
        "claim_boundary": (
            "Graph-reachable capability paths for investigation, not "
            "proof of exploitability or a confirmed vulnerability."
        ),
        "path_limits": {
            "max_hops": MAX_HOPS,
            "max_paths": MAX_PATHS,
            "possibly_truncated": len(paths) >= MAX_PATHS,
        },
        "scoring": {
            "method": "path_risk_score = sum of enumerated edge risk values",
            "risk_bands": RISK_BANDS,
            "ordering": "highest risk_score first, then fewest hops",
        },
    }


def rank_chokepoints(
    source: str,
    target: str,
    excluded_edge_id: str | None = None,
) -> dict[str, Any]:
    """Rank intermediate nodes by how often they appear on enumerated paths."""
    paths = find_paths(source, target, excluded_edge_id=excluded_edge_id)
    counts: Counter[str] = Counter()
    details: dict[str, dict[str, Any]] = {}

    for item in paths:
        for node in item.get("nodes", [])[1:-1]:
            node_id = node.get("id")
            if not node_id:
                continue
            counts[str(node_id)] += 1
            details[str(node_id)] = node

    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0]),
    )

    chokepoints = []
    for node_id, count in ranked:
        node = details[node_id]
        chokepoints.append({
            "rank": len(chokepoints) + 1,
            "node_id": node_id,
            "name": node.get("name", node_id),
            "kind": node.get("kind"),
            "paths_containing_node": count,
            "total_paths": len(paths),
            "path_participation_percent": (
                round(100 * count / len(paths), 2) if paths else 0
            ),
            "interpretation": (
                "Candidate chokepoint observed on enumerated paths; "
                "evaluate the impact of restricting this component."
            ),
        })

    return {
        "source": source,
        "target": target,
        "graph": "fflake",
        "paths_analyzed": len(paths),
        "ranking_method": "dangerous_path_participation",
        "chokepoints": chokepoints,
        "limitations": (
            "Ranks intermediate nodes on the enumerated paths only. "
            "Path discovery is bounded, so this is not a minimum-cut "
            "result or proof that removing a node is safe."
        ),
    }


def verify_simulated_cut(
    source: str,
    target: str,
    cut_edge_id: str,
) -> dict[str, Any]:
    baseline = find_paths(source, target)
    remaining = find_paths(
        source,
        target,
        excluded_edge_id=cut_edge_id,
    )
    blocked = max(0, len(baseline) - len(remaining))

    return {
        "source": source,
        "target": target,
        "cut_edge_id": cut_edge_id,
        "baseline_path_count": len(baseline),
        "remaining_path_count": len(remaining),
        "paths_blocked_by_cut": blocked,
        "verified_in_simulation": bool(baseline) and not remaining,
        "simulation_only": True,
        "important": (
            "This excludes the edge during path search; it does not delete "
            "or change the relationship in FalkorDB. Apply an approved "
            "change and rerun verification against the updated graph "
            "before claiming remediation."
        ),
        "remaining_paths": remaining,
    }
