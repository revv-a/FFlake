
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "data" / "fflake_workflow.db"


class NotFoundError(ValueError):
    """Raised when a referenced record does not exist."""


class ConflictError(ValueError):
    """Raised when an operation conflicts with the current record state."""


class NotFoundError(ValueError):
    """Raised when a referenced record does not exist."""


class ConflictError(ValueError):
    """Raised when an operation conflicts with the current record state."""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    # WAL keeps readers (listing endpoints) from blocking writers (decisions).
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection



def _record_event(
    connection: sqlite3.Connection,
    proposal_id: str,
    event: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append an audit event within the caller's database transaction."""
    connection.execute(
        """
        INSERT INTO proposal_events (proposal_id, event, detail, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            proposal_id,
            event,
            json.dumps(detail, default=str) if detail is not None else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


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

        # Immutable audit trail of human decisions and simulations.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS proposal_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_proposal_events_proposal
            ON proposal_events (proposal_id, event_id)
            """
        )
        connection.commit()


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
            raise NotFoundError("Investigation run was not found")

        duplicate = connection.execute(
            """
            SELECT proposal_id, status FROM fix_proposals
            WHERE source = ? AND target = ? AND edge_id = ?
              AND status IN ('pending', 'approved')
            """,
            (source, target, edge_id),
        ).fetchone()

        if duplicate is not None:
            raise ConflictError(
                f"An active proposal {duplicate['proposal_id']} already "
                f"exists for edge '{edge_id}' on {source} -> {target} "
                f"(status: {duplicate['status']})"
            )

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
        _record_event(
            connection,
            proposal_id,
            "created",
            {
                "run_id": run_id,
                "source": source,
                "target": target,
                "edge_id": edge_id,
            },
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
        "verification": None,
        "real_changes_performed": False,
    }



def _row_to_proposal(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite proposal row into the API response structure."""
    proposal = dict(row)
    raw_verification = proposal.pop("verification_json", None)
    if raw_verification:
        try:
            proposal["verification"] = json.loads(raw_verification)
        except (json.JSONDecodeError, TypeError):
            proposal["verification"] = None
    else:
        proposal["verification"] = None
    return proposal



def list_events(proposal_id: str) -> list[dict[str, Any]]:
    """Return the audit trail for a proposal in chronological order."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT event_id, proposal_id, event, detail, created_at
            FROM proposal_events
            WHERE proposal_id = ?
            ORDER BY event_id ASC
            """,
            (proposal_id,),
        ).fetchall()

    events = []
    for row in rows:
        item = dict(row)
        raw_detail = item.get("detail")
        if raw_detail:
            try:
                item["detail"] = json.loads(raw_detail)
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            item["detail"] = None
        events.append(item)

    return events


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

    proposals = [_row_to_proposal(row) for row in rows]
    for proposal in proposals:
        proposal["audit_trail"] = list_events(proposal["proposal_id"])
    return proposals


def get_proposal(proposal_id: str) -> dict[str, Any]:
    """Fetch one proposal, or raise NotFoundError."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT proposal_id, run_id, source, target, edge_id,
                   description, status, created_at, updated_at,
                   verification_json
            FROM fix_proposals
            WHERE proposal_id = ?
            """,
            (proposal_id,),
        ).fetchone()

    if row is None:
        raise NotFoundError("Proposal was not found")

    proposal = _row_to_proposal(row)
    proposal["audit_trail"] = list_events(proposal_id)
    return proposal


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
                raise NotFoundError("Proposal was not found")

            raise ConflictError(
                f"Proposal is already {exists['status']}; "
                "only pending proposals can be decided"
            )

        _record_event(connection, proposal_id, new_status)

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
            raise ConflictError(
                "Proposal must be approved and its source, target, "
                "and edge must match the verification result"
            )

        _record_event(
            connection,
            proposal_id,
            "simulation_verified",
            verification,
        )

        row = connection.execute(
            "SELECT * FROM fix_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

    return dict(row)


def record_simulation(
    proposal_id: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Persist a simulation result for an approved proposal.

    A successful simulation (all enumerated paths blocked) promotes the
    proposal to 'verified'. An unsuccessful simulation is recorded in the
    audit trail and attached as evidence, but the proposal stays 'approved'
    so it can be reconsidered or re-simulated later.
    """
    if not verification.get("simulation_only"):
        raise ValueError("Only simulation results may be recorded")

    if verification.get("verified_in_simulation"):
        return save_verification(proposal_id, verification)

    now = datetime.now(timezone.utc).isoformat()

    with _connect() as connection:
        exists = connection.execute(
            "SELECT status FROM fix_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

        if exists is None:
            raise NotFoundError("Proposal was not found")

        if exists["status"] != "approved":
            raise ConflictError(
                "Only approved proposals can be verified; current "
                f"status is '{exists['status']}'"
            )

        connection.execute(
            """
            UPDATE fix_proposals
            SET updated_at = ?, verification_json = ?
            WHERE proposal_id = ? AND status = 'approved'
            """,
            (now, json.dumps(verification, default=str), proposal_id),
        )
        _record_event(
            connection,
            proposal_id,
            "simulation_inconclusive",
            verification,
        )

        row = connection.execute(
            "SELECT * FROM fix_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

    return dict(row)


initialize_store()
