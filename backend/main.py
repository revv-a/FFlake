import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Ensure backend modules (agent, agent_tools, workflow_store) import
# correctly regardless of the working directory uvicorn was started from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from fflake_graph.db import run_query
from fflake_graph.engine import analyze, find_paths, rank_chokepoints, require_entities
from fflake_graph.errors import (
    EntityNotFoundError,
    GraphQueryError,
    GraphUnavailableError,
)
from fflake_graph.router import router as graph_hacks_router
from workflow_store import (
    ConflictError,
    NotFoundError,
    create_proposal,
    get_proposal,
    list_investigations,
    list_proposals,
    record_simulation,
    set_proposal_status,
)

app = FastAPI(
    title="FFlake API",
    description="Capability-path security investigation engine",
    version="0.4.0",
)

app_version = "0.4.0"

# Entity, edge, and proposal ids are short slugs such as "external-bot".
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"


def _allowed_origins() -> list[str]:
    """Dev origins plus any extra origins from FFLAKE_CORS_ORIGINS."""
    origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    extra = os.getenv("FFLAKE_CORS_ORIGINS", "")
    for origin in extra.split(","):
        origin = origin.strip()
        if origin:
            origins.add(origin)
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph_hacks_router, prefix="/api")


@app.exception_handler(GraphUnavailableError)
async def graph_unavailable_handler(
    request: Request,
    exc: GraphUnavailableError,
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "The graph database is not reachable. Start the FalkorDB "
                "container and check FALKORDB_HOST/FALKORDB_PORT. "
                f"Technical detail: {exc}"
            )
        },
    )


@app.exception_handler(GraphQueryError)
async def graph_query_handler(
    request: Request,
    exc: GraphQueryError,
) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "detail": (
                "The graph database rejected the query. Check the server "
                "logs for details."
            )
        },
    )


@app.exception_handler(EntityNotFoundError)
async def entity_not_found_handler(
    request: Request,
    exc: EntityNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": str(exc),
            "missing": list(exc.missing),
        },
    )


class AgentRunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)


class InvestigateRequest(BaseModel):
    source: str | None = Field(
        default=None, min_length=1, max_length=160, pattern=ID_PATTERN
    )
    target: str | None = Field(
        default=None, min_length=1, max_length=160, pattern=ID_PATTERN
    )


class ProposalCreateRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=200, pattern=ID_PATTERN)
    target: str = Field(min_length=1, max_length=200, pattern=ID_PATTERN)
    edge_id: str = Field(min_length=1, max_length=200, pattern=ID_PATTERN)
    description: str = Field(min_length=1, max_length=1000)


class ProposalDecisionRequest(BaseModel):
    decision: str = Field(min_length=1, max_length=20)


def _validate_proposal_id(proposal_id: str) -> None:
    if not re.match(ID_PATTERN, proposal_id):
        raise HTTPException(
            status_code=422,
            detail="Invalid proposal id format",
        )


@app.get("/")
def root():
    return {
        "message": "FFlake API is running",
        "version": app_version,
    }


@app.get("/health")
def health():
    rows = run_query("RETURN 1")
    return {
        "status": "healthy",
        "database": "connected" if rows else "empty",
        "graph": "fflake",
    }


@app.post("/investigate")
def investigate(payload: InvestigateRequest | None = None):
    """Backward-compatible investigate endpoint.

    Accepts an optional JSON body with source/target. With no body it keeps
    the original external-bot -> prod-secrets demo scenario.
    """
    source = (payload.source if payload else None) or "external-bot"
    target = (payload.target if payload else None) or "prod-secrets"

    require_entities(source, target)
    result = analyze(source, target)
    findings = []

    for index, item in enumerate(result.get("paths", []), start=1):
        edge_risk_total = sum(
            int(edge.get("risk") or 0) for edge in item.get("edges", [])
        )
        findings.append({
            "finding_id": f"FF-{index:03d}",
            "title": "Untrusted source can reach sensitive data",
            "risk_score": item.get("risk_score", 0),
            "severity": item.get("risk_band", "unknown"),
            "path": item,
            "scoring": {
                "edge_risk_total": edge_risk_total,
                "hop_count": item.get("hops", 0),
                "scoring_method": "sum of edge risk values",
            },
            "interpretation": (
                "A modeled capability path was found. "
                "This does not prove exploitability."
            ),
        })

    return {
        "investigation_id": (
            f"INV-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-"
            f"{uuid4().hex[:8]}"
        ),
        "graph": "fflake",
        "source": source,
        "target": target,
        "paths_found": len(findings),
        "findings": findings,
        "claim_boundary": result.get("claim_boundary"),
    }


@app.get("/rank-chokepoints")
def rank_chokepoints_endpoint(
    source: str = "external-bot",
    target: str = "prod-secrets",
):
    """Backward-compatible chokepoint ranking, now parameterized."""
    require_entities(source, target)
    return rank_chokepoints(source, target)



@app.post("/api/agent/run")
def run_agent_endpoint(payload: AgentRunRequest):
    from agent import run_agent

    try:
        return run_agent(payload.request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GraphUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Agent execution failed. Check the server logs.",
        ) from exc


@app.get("/api/workflows/investigations")
def get_investigations(limit: int = 50):
    return {"investigations": list_investigations(limit)}


def validate_proposal_edge(source: str, target: str, edge_id: str) -> None:
    """Require the proposed edge to exist on an enumerated source-target path.

    Uses the same bounded path discovery as analysis and verification so the
    validation matches what a simulation would actually consider.
    """
    require_entities(source, target)
    paths = find_paths(source, target)

    matching = any(
        edge.get("id") == edge_id
        for path in paths
        for edge in path.get("edges", [])
    )

    if not matching:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Edge '{edge_id}' is not on any enumerated path from "
                f"'{source}' to '{target}'. Check the edge id or run the "
                "analysis first."
            ),
        )


@app.get("/api/workflows/proposals")
def get_proposals():
    return {"proposals": list_proposals()}


@app.post("/api/workflows/proposals")
def propose_fix(payload: ProposalCreateRequest):
    try:
        validate_proposal_edge(
            source=payload.source,
            target=payload.target,
            edge_id=payload.edge_id,
        )

        proposal_id = str(uuid4())
        return create_proposal(
            proposal_id=proposal_id,
            run_id=payload.run_id,
            source=payload.source,
            target=payload.target,
            edge_id=payload.edge_id,
            description=payload.description,
        )
    except (ConflictError, NotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/workflows/proposals/{proposal_id}")
def get_proposal_endpoint(proposal_id: str):
    _validate_proposal_id(proposal_id)
    try:
        return get_proposal(proposal_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/workflows/proposals/{proposal_id}/decision")
def decide_proposal(
    proposal_id: str,
    payload: ProposalDecisionRequest,
):
    _validate_proposal_id(proposal_id)
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
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Could not record decision. Check the server logs.",
        ) from exc


# Workflow: simulation-only verification of an approved proposal

@app.post("/api/workflows/proposals/{proposal_id}/verify")
def verify_proposal(proposal_id: str):
    _validate_proposal_id(proposal_id)

    try:
        proposal = get_proposal(proposal_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    saved = record_simulation(proposal_id, verification)

    if verification.get("verified_in_simulation"):
        message = (
            "Simulation verification completed: no enumerated path "
            "remains after excluding the edge. No infrastructure was "
            "modified."
        )
    else:
        message = (
            "Simulation completed but the fix was not verified: "
            "enumerated paths remain after excluding the edge. The "
            "proposal stays approved. No infrastructure was modified."
        )

    return {
        "proposal": saved,
        "verification": verification,
        "real_changes_performed": False,
        "message": message,
    }


