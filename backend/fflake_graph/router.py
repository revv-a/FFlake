from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .db import run_query
from .demo import DEMO_PRESETS, seed_demo_graph
from .engine import analyze, find_paths, list_entities, rank_chokepoints, verify_simulated_cut

router = APIRouter(prefix="/graph-hacks", tags=["FFlake GraphHacks"])

# Entity and relationship ids are short slugs such as "external-bot".
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"


class AnalyzeRequest(BaseModel):
    source: str = Field(min_length=1, max_length=160, pattern=ID_PATTERN)
    target: str = Field(min_length=1, max_length=160, pattern=ID_PATTERN)


class VerifyRequest(AnalyzeRequest):
    cut_edge_id: str = Field(min_length=1, max_length=200, pattern=ID_PATTERN)


@router.get("/health")
def graph_health():
    rows = run_query("RETURN 1 AS ok")
    return {"ok": bool(rows), "database": "FalkorDB", "graph": "configured"}


@router.get("/entities")
def graph_entities():
    """Real node list from the graph, for entity pickers."""
    entities = list_entities()
    return {
        "count": len(entities),
        "entities": entities,
        "note": (
            "Ids come from the live FalkorDB graph. Seed the demo data "
            "if this list is empty."
        ),
    }


@router.get("/presets")
def list_demo_presets():
    """Selectable demo scenarios; presets are optional, not mandatory."""
    return {
        "presets": DEMO_PRESETS,
        "note": (
            "Presets only label convenient entity pairs; every analysis "
            "runs against the entities you select."
        ),
    }


@router.post("/demo/seed")
def seed_demo():
    return seed_demo_graph()


@router.get("/paths")
def paths(
    source: str = Query(min_length=1, max_length=160, pattern=ID_PATTERN),
    target: str = Query(min_length=1, max_length=160, pattern=ID_PATTERN),
):
    found = find_paths(source, target)
    return {
        "source": source,
        "target": target,
        "path_count": len(found),
        "paths": found,
        "claim_boundary": (
            "Reachability evidence for investigation, not proof of "
            "exploitability."
        ),
    }


@router.post("/analyze")
def analyze_paths(payload: AnalyzeRequest):
    return analyze(payload.source, payload.target)


@router.get("/chokepoints")
def chokepoints(
    source: str = Query(min_length=1, max_length=160, pattern=ID_PATTERN),
    target: str = Query(min_length=1, max_length=160, pattern=ID_PATTERN),
):
    return rank_chokepoints(source, target)


@router.post("/verify")
def verify(payload: VerifyRequest):
    return verify_simulated_cut(payload.source, payload.target, payload.cut_edge_id)
