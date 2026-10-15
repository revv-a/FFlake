from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from .db import run_query
from .demo import seed_demo_graph
from .engine import analyze, find_paths, verify_simulated_cut

router = APIRouter(prefix="/graph-hacks", tags=["FFlake GraphHacks"])

class AnalyzeRequest(BaseModel):
    source: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=160)

class VerifyRequest(AnalyzeRequest):
    cut_edge_id: str = Field(min_length=1, max_length=200)

def _db_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=("FFlake could not query FalkorDB. Check the running container, connection settings, "
                "and installed falkordb package. "
                f"Technical detail: {type(exc).__name__}: {exc}")
    )

@router.get("/health")
def graph_health():
    try:
        rows = run_query("RETURN 1 AS ok")
        return {"ok": bool(rows), "database": "FalkorDB", "graph": "configured"}
    except Exception as exc:
        raise _db_error(exc) from exc

@router.post("/demo/seed")
def seed_demo():
    try:
        return seed_demo_graph()
    except Exception as exc:
        raise _db_error(exc) from exc

@router.get("/paths")
def paths(
    source: str = Query(min_length=1, max_length=160),
    target: str = Query(min_length=1, max_length=160),
):
    try:
        found = find_paths(source, target)
        return {
            "source": source, "target": target, "path_count": len(found),
            "paths": found,
            "claim_boundary": "Reachability evidence for investigation, not proof of exploitability."
        }
    except Exception as exc:
        raise _db_error(exc) from exc

@router.post("/analyze")
def analyze_paths(payload: AnalyzeRequest):
    try:
        return analyze(payload.source, payload.target)
    except Exception as exc:
        raise _db_error(exc) from exc

@router.post("/verify")
def verify(payload: VerifyRequest):
    try:
        return verify_simulated_cut(payload.source, payload.target, payload.cut_edge_id)
    except Exception as exc:
        raise _db_error(exc) from exc
