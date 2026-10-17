import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import workflow_store as store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Give each test its own temporary SQLite database."""
    db_path = tmp_path / "workflow_test.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.initialize_store()
    return store


def sample_investigation(run_id="run-1"):
    return {
        "run_id": run_id,
        "timestamp": "2026-10-17T10:00:00+00:00",
        "request": "investigate path",
        "status": "completed",
        "result": {"risk_score": 24},
    }


def sample_proposal(store_module, run_id="run-1", proposal_id="proposal-1"):
    store_module.save_investigation(sample_investigation(run_id))
    return store_module.create_proposal(
        proposal_id=proposal_id,
        run_id=run_id,
        source="external-bot",
        target="prod-secrets",
        edge_id="edge-deploy-secrets",
        description="Block the modeled risky path",
    )


def test_investigation_is_saved_and_restored(isolated_store):
    isolated_store.save_investigation(sample_investigation())

    runs = isolated_store.list_investigations()

    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"
    assert runs[0]["request"] == "investigate path"
    assert runs[0]["result"]["result"]["risk_score"] == 24


def test_proposal_starts_pending(isolated_store):
    proposal = sample_proposal(isolated_store)

    assert proposal["status"] == "pending"
    assert proposal["real_changes_performed"] is False


def test_proposal_requires_existing_investigation(isolated_store):
    with pytest.raises(ValueError, match="Investigation run was not found"):
        isolated_store.create_proposal(
            proposal_id="proposal-missing-run",
            run_id="missing-run",
            source="external-bot",
            target="prod-secrets",
            edge_id="edge-deploy-secrets",
            description="Invalid proposal",
        )


def test_pending_proposal_can_be_approved_once(isolated_store):
    sample_proposal(isolated_store)

    approved = isolated_store.set_proposal_status("proposal-1", "approved")

    assert approved["status"] == "approved"

    with pytest.raises(ValueError, match="only pending proposals can be decided"):
        isolated_store.set_proposal_status("proposal-1", "rejected")


def test_rejected_proposal_cannot_be_approved(isolated_store):
    sample_proposal(isolated_store)

    rejected = isolated_store.set_proposal_status("proposal-1", "rejected")

    assert rejected["status"] == "rejected"

    with pytest.raises(ValueError, match="only pending proposals can be decided"):
        isolated_store.set_proposal_status("proposal-1", "approved")


def test_verification_requires_successful_simulation(isolated_store):
    sample_proposal(isolated_store)

    with pytest.raises(ValueError, match="Only simulation results may be recorded"):
        isolated_store.save_verification(
            "proposal-1",
            {"verified_in_simulation": True},
        )

    with pytest.raises(ValueError, match="not verified in simulation"):
        isolated_store.save_verification(
            "proposal-1",
            {"simulation_only": True, "verified_in_simulation": False},
        )


def test_verification_requires_approval(isolated_store):
    sample_proposal(isolated_store)

    verification = {
        "source": "external-bot",
        "target": "prod-secrets",
        "cut_edge_id": "edge-deploy-secrets",
        "simulation_only": True,
        "verified_in_simulation": True,
    }

    with pytest.raises(ValueError, match="must be approved"):
        isolated_store.save_verification("proposal-1", verification)


def test_successful_verification_is_persisted(isolated_store):
    sample_proposal(isolated_store)
    isolated_store.set_proposal_status("proposal-1", "approved")

    verification = {
        "source": "external-bot",
        "target": "prod-secrets",
        "cut_edge_id": "edge-deploy-secrets",
        "baseline_path_count": 1,
        "remaining_path_count": 0,
        "simulation_only": True,
        "verified_in_simulation": True,
    }

    saved = isolated_store.save_verification("proposal-1", verification)
    listed = isolated_store.list_proposals()

    assert saved["status"] == "verified"
    assert len(listed) == 1
    assert listed[0]["verification"] == verification
