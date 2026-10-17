
from datetime import datetime, timezone
from uuid import uuid4
from fflake_graph.db import run_query
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from falkordb import FalkorDB
from pydantic import BaseModel, Field

from fflake_graph.router import router as graph_hacks_router
from workflow_store import (
    create_proposal,
    list_investigations,
    list_proposals,
    save_verification,
    set_proposal_status,
)

app = FastAPI(
    title="FFlake API",
    description="Capability-path security investigation engine",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph_hacks_router, prefix="/api")

db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("fflake")


class AgentRunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)


class ProposalCreateRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    edge_id: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)


class ProposalDecisionRequest(BaseModel):
    decision: str


app_version = "0.3.0"


@app.get("/")
def root():
    return {
        "message": "FFlake API is running",
        "version": app_version,
    }


@app.get("/health")
def health():
    try:
        graph.query("RETURN 1")
        return {
            "status": "healthy",
            "database": "connected",
            "graph": "fflake",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Graph database unavailable: {exc}",
        ) from exc


@app.post("/investigate")
def investigate():
    try:
        from fflake_graph.engine import analyze

        result = analyze("external-bot", "prod-secrets")
        findings = []

        for index, item in enumerate(result.get("paths", []), start=1):
            findings.append({
                "finding_id": f"FF-{index:03d}",
                "title": "Untrusted source can reach sensitive data",
                "risk_score": item.get("risk_score", 0),
                "severity": item.get("risk_band", "unknown"),
                "path": item,
                "score_breakdown": {
                    "edge_risk_total": item.get("risk_score", 0),
                    "hop_count": item.get("hops", 0),
                    "scoring_method": "sum of edge risk values",
                },
                "interpretation": (
                    "A modeled capability path was found. "
                    "This does not prove exploitability."
                ),
            })

        return {
            "investigation_id": datetime.now(timezone.utc).strftime(
                "INV-%Y%m%dT%H%M%SZ"
            ),
            "graph": "fflake",
            "paths_found": len(findings),
            "findings": findings,
            "claim_boundary": result.get("claim_boundary"),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Investigation failed: {exc}",
        ) from exc



@app.get("/rank-chokepoints")
def rank_chokepoints():
    try:
        from fflake_graph.engine import analyze

        result = analyze("external-bot", "prod-secrets")
        paths = result.get("paths", [])
        counts = {}
        details = {}

        for item in paths:
            for node in item.get("nodes", [])[1:-1]:
                node_id = node.get("id")
                if not node_id:
                    continue
                counts[node_id] = counts.get(node_id, 0) + 1
                details[node_id] = node

        ranked = sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
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
                    "Candidate chokepoint; evaluate the impact "
                    "of restricting this component."
                ),
            })

        return {
            "graph": "fflake",
            "paths_analyzed": len(paths),
            "ranking_method": "dangerous_path_participation",
            "chokepoints": chokepoints,
            "limitations": (
                "Ranks nodes on enumerated paths only. This is not "
                "a minimum-cut result or proof that removing a node is safe."
            ),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Chokepoint ranking failed: {exc}",
        ) from exc



@app.post("/api/agent/run")
def run_agent_endpoint(payload: AgentRunRequest):
    from agent import run_agent

    try:
        return run_agent(payload.request)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Agent execution failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc


# Workflow: persistent investigation history

@app.get("/api/workflows/investigations")
def get_investigations(limit: int = 50):
    try:
        return {
            "investigations": list_investigations(limit),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load investigations: {exc}",
        ) from exc


# Workflow: proposed fixes

def validate_proposal_edge(source: str, target: str, edge_id: str) -> None:
    """Require the proposed edge to exist on a path from source to target."""
    try:
        rows = run_query(
            """
            MATCH (s:FFAsset)-[r:FF_REL]->(t:FFAsset)
            RETURN s.id, r.id, t.id
            """
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not validate the proposed edge against the graph",
        ) from exc

    edges = [
        (str(row[0]), str(row[1]), str(row[2]))
        for row in rows
    ]

    matching_edges = [
        (start, end)
        for start, edge, end in edges
        if edge == edge_id
    ]

    if not matching_edges:
        raise HTTPException(
            status_code=400,
            detail=f"Edge '{edge_id}' was not found in the graph",
        )

    adjacency: dict[str, set[str]] = {}
    for start, _, end in edges:
        adjacency.setdefault(start, set()).add(end)

    def reachable(start: str, goal: str) -> bool:
        pending = [start]
        visited: set[str] = set()

        while pending:
            current = pending.pop()

            if current == goal:
                return True

            if current in visited:
                continue

            visited.add(current)
            pending.extend(adjacency.get(current, set()) - visited)

        return False

    # The proposed edge can be an intermediate edge on the path.
    # It does not have to connect the source directly to the target.
    if not any(
        reachable(source, edge_start)
        and reachable(edge_end, target)
        for edge_start, edge_end in matching_edges
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Edge '{edge_id}' is not on a directed path "
                f"from '{source}' to '{target}'"
            ),
        )


@app.get("/api/workflows/proposals")
def get_proposals():
    try:
        return {
            "proposals": list_proposals(),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load proposals: {exc}",
        ) from exc


@app.post("/api/workflows/proposals")
def propose_fix(payload: ProposalCreateRequest):
    try:
        validate_proposal_edge(
            source=payload.source,
            target=payload.target,
            edge_id=payload.edge_id,
        )

        proposal_id = str(uuid4())
        proposal = create_proposal(
            proposal_id=proposal_id,
            run_id=payload.run_id,
            source=payload.source,
            target=payload.target,
            edge_id=payload.edge_id,
            description=payload.description,
        )
        return proposal

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not create proposal: {exc}",
        ) from exc


# Workflow: explicit human decision

@app.post("/api/workflows/proposals/{proposal_id}/decision")
def decide_proposal(
    proposal_id: str,
    payload: ProposalDecisionRequest,
):
    decision = payload.decision.strip().lower()

    if decision not in {"approved", "rejected"}:
        raise HTTPException(
            status_code=400,
            detail="Decision must be 'approved' or 'rejected'",
        )

    try:
        proposal = set_proposal_status(proposal_id, decision)
        return {
            "proposal": proposal,
            "real_changes_performed": False,
            "message": (
                "Proposal decision recorded. No infrastructure "
                "was modified."
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not record decision: {exc}",
        ) from exc


# Workflow: simulation-only verification of an approved proposal

@app.post("/api/workflows/proposals/{proposal_id}/verify")
def verify_proposal(proposal_id: str):
    try:
        proposals = list_proposals()
        proposal = next(
            (
                item for item in proposals
                if item["proposal_id"] == proposal_id
            ),
            None,
        )

        if proposal is None:
            raise HTTPException(
                status_code=404,
                detail="Proposal was not found",
            )

        if proposal["status"] != "approved":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only approved proposals can be verified. "
                    "Approve the proposal first."
                ),
            )

        from fflake_graph.engine import verify_simulated_cut

        verification = verify_simulated_cut(
            source=proposal["source"],
            target=proposal["target"],
            cut_edge_id=proposal["edge_id"],
        )

        # Only persist a successful simulation verification.
        saved = save_verification(
            proposal_id,
            verification,
        )

        return {
            "proposal": saved,
            "verification": verification,
            "real_changes_performed": False,
            "message": (
                "Simulation verification completed. "
                "No infrastructure was modified."
            ),
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Simulation verification failed: {exc}",
        ) from exc
