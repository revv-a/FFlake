
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from falkordb import FalkorDB
from pydantic import BaseModel, Field

from fflake_graph.router import router as graph_hacks_router


app = FastAPI(
    title="FFlake API",
    description="Capability-path security investigation engine",
    version="0.2.0",
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


@app.get("/")
def root():
    return {"message": "FFlake API is running"}


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
        result = graph.query(
            """
            MATCH p = (s:UntrustedSource)-[*1..8]->(d:DataStore)
            RETURN
                [n IN nodes(p) |
                    {id: n.id, name: n.name, labels: labels(n)}
                ] AS path_nodes,
                [r IN relationships(p) | type(r)] AS path_edges
            LIMIT 100
            """
        )

        findings = []

        for row in result.result_set:
            nodes = row[0]
            edges = row[1]

            labels = [
                label
                for node in nodes
                for label in node["labels"]
            ]

            source_score = 25 if "UntrustedSource" in labels else 0
            sink_score = 25 if "DataStore" in labels else 0
            credential_score = 25 if "Credential" in labels else 0
            hop_score = min(15, len(edges) * 2)
            policy_protection = 0

            score = min(
                100,
                source_score
                + sink_score
                + credential_score
                + hop_score
                - policy_protection,
            )

            findings.append(
                {
                    "finding_id": f"FF-{len(findings) + 1:03d}",
                    "title": "Untrusted source can reach sensitive data",
                    "risk_score": score,
                    "severity": (
                        "critical" if score >= 80
                        else "high" if score >= 60
                        else "medium" if score >= 35
                        else "low"
                    ),
                    "path": {"nodes": nodes, "edges": edges},
                    "score_breakdown": {
                        "source_untrustedness": source_score,
                        "sink_sensitivity": sink_score,
                        "credential_privilege": credential_score,
                        "hop_count": hop_score,
                        "policy_protection_credit": policy_protection,
                    },
                    "interpretation": (
                        "A modeled capability path was found. "
                        "This does not prove exploitability."
                    ),
                }
            )

        return {
            "investigation_id": datetime.now(timezone.utc).strftime(
                "INV-%Y%m%dT%H%M%SZ"
            ),
            "graph": "fflake",
            "paths_found": len(findings),
            "findings": findings,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Investigation failed: {exc}",
        ) from exc


@app.get("/rank-chokepoints")
def rank_chokepoints():
    try:
        result = graph.query(
            """
            MATCH p = (s:UntrustedSource)-[*1..8]->(d:DataStore)
            RETURN
                [n IN nodes(p) |
                    {
                        id: n.id,
                        name: n.name,
                        labels: labels(n)
                    }
                ] AS path_nodes
            LIMIT 100
            """
        )

        path_count = len(result.result_set)
        counts = {}
        node_details = {}

        for row in result.result_set:
            path_nodes = row[0]

            # Exclude the untrusted source and final data sink.
            for node in path_nodes[1:-1]:
                node_id = node["id"]

                if node_id not in counts:
                    counts[node_id] = 0
                    node_details[node_id] = node

                counts[node_id] += 1

        ranked = sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        chokepoints = []

        for node_id, count in ranked:
            node = node_details[node_id]

            chokepoints.append(
                {
                    "rank": len(chokepoints) + 1,
                    "node_id": node_id,
                    "name": node["name"],
                    "labels": node["labels"],
                    "paths_containing_node": count,
                    "total_paths": path_count,
                    "path_participation_percent": (
                        round(100 * count / path_count, 2)
                        if path_count
                        else 0
                    ),
                    "interpretation": (
                        "Candidate chokepoint; evaluate the impact "
                        "of restricting this component."
                    ),
                }
            )

        return {
            "graph": "fflake",
            "paths_analyzed": path_count,
            "ranking_method": "dangerous_path_participation",
            "chokepoints": chokepoints,
            "limitations": (
                "This ranks nodes by their participation in the "
                "enumerated paths. It is not a minimum-cut result "
                "or proof that removing a node is safe."
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
