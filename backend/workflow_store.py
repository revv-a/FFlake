
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "data" / "fflake_workflow.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_store() -> None:
    """Create workflow tables without changing existing graph data."""
    with _connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS investigation_runs (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                request TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS fix_proposals (
                proposal_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                edge_id TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN (
                        'pending', 'approved', 'rejected', 'verified'
                    )),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                verification_json TEXT,
                FOREIGN KEY (run_id)
                    REFERENCES investigation_runs(run_id)
            )
        """)


def save_investigation(run: dict[str, Any]) -> None:
    """Persist an agent run and its result as JSON."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO investigation_runs
                (run_id, timestamp, request, status, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run["run_id"],
                run["timestamp"],
                run.get("request", ""),
                run.get("status", "unknown"),
                json.dumps(run, default=str),
            ),
        )


def list_investigations(limit: int = 50) -> list[dict[str, Any]]:
    """Return the newest saved investigations."""
    limit = max(1, min(limit, 200))

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT run_id, timestamp, request, status, result_json
            FROM investigation_runs
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "run_id": row["run_id"],
            "timestamp": row["timestamp"],
            "request": row["request"],
            "status": row["status"],
            "result": json.loads(row["result_json"]),
        }
        for row in rows
    ]


def create_proposal(
    proposal_id: str,
    run_id: str,
    source: str,
    target: str,
    edge_id: str,
    description: str,
) -> dict[str, Any]:
    """Create a proposal that always starts pending."""
    now = datetime.now(timezone.utc).isoformat()

    with _connect() as connection:
        run = connection.execute(
            "SELECT run_id FROM investigation_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

        if run is None:
            raise ValueError("Investigation run was not found")

        connection.execute(
            """
            INSERT INTO fix_proposals (
                proposal_id, run_id, source, target, edge_id,
                description, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                proposal_id, run_id, source, target, edge_id,
                description, now, now,
            ),
        )

    return {
        "proposal_id": proposal_id,
        "run_id": run_id,
        "source": source,
        "target": target,
        "edge_id": edge_id,
        "description": description,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "real_changes_performed": False,
    }


def list_proposals() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT proposal_id, run_id, source, target, edge_id,
                   description, status, created_at, updated_at,
                   verification_json
            FROM fix_proposals
            ORDER BY created_at DESC
            """
        ).fetchall()

    return [
        {
            **dict(row),
            "verification": (
                json.loads(row["verification_json"])
                if row["verification_json"] else None
            ),
            "verification_json": None,
        }
        for row in rows
    ]


def set_proposal_status(
    proposal_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Require an explicit decision for a pending proposal."""
    if new_status not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected")

    now = datetime.now(timezone.utc).isoformat()

    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE fix_proposals
            SET status = ?, updated_at = ?
            WHERE proposal_id = ? AND status = 'pending'
            """,
            (new_status, now, proposal_id),
        )

        if cursor.rowcount == 0:
            exists = connection.execute(
                "SELECT status FROM fix_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()

            if exists is None:
                raise ValueError("Proposal was not found")

            raise ValueError(
                f"Proposal is already {exists['status']}; "
                "only pending proposals can be decided"
            )

        row = connection.execute(
            "SELECT * FROM fix_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

    return dict(row)


def save_verification(
    proposal_id: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Record a simulation only for an explicitly approved proposal."""
    if not verification.get("simulation_only"):
        raise ValueError("Only simulation results may be recorded")

    if not verification.get("verified_in_simulation"):
        raise ValueError("The proposed fix was not verified in simulation")

    now = datetime.now(timezone.utc).isoformat()

    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE fix_proposals
            SET status = 'verified',
                updated_at = ?,
                verification_json = ?
            WHERE proposal_id = ? AND status = 'approved'
              AND source = ? AND target = ? AND edge_id = ?
            """,
            (
                now,
                json.dumps(verification, default=str),
                proposal_id,
                verification.get("source"),
                verification.get("target"),
                verification.get("cut_edge_id"),
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Proposal must be approved and its source, target, "
                "and edge must match the verification result"
            )

        row = connection.execute(
            "SELECT * FROM fix_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

    return dict(row)


initialize_store()
