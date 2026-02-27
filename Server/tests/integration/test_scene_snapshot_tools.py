"""Integration tests for scene_snapshot and ref_resolve tools.

These tests run without a live Unity connection by directly exercising
the SnapshotStore / RefGraph that the tools build upon, then calling
the tool functions with test-mode behavior.
"""

import pytest
import sys
import os
from pathlib import Path

# Ensure src is on the path (integration conftest.py handles this too)
src_path = Path(__file__).resolve().parents[2] / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from services.snapshot import SnapshotStore, RefStatus
from services.snapshot.ref_graph import RefGraph, make_uref, parse_uref


def _sample_objects(count=3, start_id=100, scene="TestScene"):
    """Generate sample Unity-like object dicts."""
    return [
        {
            "instanceId": start_id + i,
            "name": f"GO_{start_id + i}",
            "path": f"/Root/GO_{start_id + i}",
            "active": True,
            "tag": "Untagged",
            "layer": "Default",
            "components": ["Transform"],
        }
        for i in range(count)
    ]


@pytest.fixture(autouse=True)
def reset_snapshot_store():
    """Ensure clean state for each test."""
    SnapshotStore.reset()
    yield
    SnapshotStore.reset()


# ---------------------------------------------------------------------------
# Snapshot capture returns refs
# ---------------------------------------------------------------------------

class TestSnapshotReturnsRefs:
    """Verify that ingesting a snapshot produces correct refs."""

    def test_capture_produces_refs_for_all_objects(self):
        store = SnapshotStore.get_instance()
        objs = _sample_objects(5, start_id=200)
        rev = store.ingest("SampleScene", objs)

        assert rev.revision == 1
        assert rev.object_count == 5

        # Every object should be reachable by instance ID
        for obj in objs:
            entry = store.ref_graph.get_by_instance_id(obj["instanceId"])
            assert entry is not None, f"Missing entry for instanceId {obj['instanceId']}"
            assert entry.scene_name == "SampleScene"
            assert entry.name == obj["name"]
            assert entry.revision == 1

    def test_refs_have_correct_uref_format(self):
        store = SnapshotStore.get_instance()
        objs = _sample_objects(1, start_id=42)
        store.ingest("MyScene", objs)

        entry = store.ref_graph.get_by_instance_id(42)
        assert entry.uref == "MyScene:42:1"
        parsed = parse_uref(entry.uref)
        assert parsed == ("MyScene", 42, 1)

    def test_successive_snapshots_increment_revision(self):
        store = SnapshotStore.get_instance()
        r1 = store.ingest("S", _sample_objects(2, start_id=10))
        r2 = store.ingest("S", _sample_objects(2, start_id=10))

        assert r1.revision == 1
        assert r2.revision == 2
        assert store.current_revision == 2

    def test_snapshot_metadata_correct(self):
        store = SnapshotStore.get_instance()
        rev = store.ingest("Level1", _sample_objects(3), scope="active")
        assert rev.scene_name == "Level1"
        assert rev.scope == "active"
        assert rev.object_count == 3


# ---------------------------------------------------------------------------
# Ref resolve: success / failure / stale
# ---------------------------------------------------------------------------

class TestRefResolve:
    """Verify ref resolution behavior across valid, stale, and not_found cases."""

    def test_resolve_valid_ref(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(1, start_id=10))

        status, entry, reason = store.ref_graph.resolve("S:10:1")
        assert status == RefStatus.VALID
        assert entry is not None
        assert entry.instance_id == 10
        assert reason is None

    def test_resolve_stale_ref_after_update(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(1, start_id=10))
        old_ref = "S:10:1"

        # Take a new snapshot (same object, new revision)
        store.ingest("S", _sample_objects(1, start_id=10))

        status, entry, reason = store.ref_graph.resolve(old_ref)
        assert status == RefStatus.STALE
        assert entry is not None
        # The returned entry should be the newer one
        assert entry.uref == "S:10:2"
        assert reason is not None

    def test_resolve_not_found(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(1, start_id=10))

        status, entry, reason = store.ref_graph.resolve("S:999:1")
        assert status == RefStatus.NOT_FOUND
        assert entry is None
        assert reason is not None
        assert "not found" in reason.lower() or "No object" in reason

    def test_resolve_invalid_format(self):
        store = SnapshotStore.get_instance()
        status, entry, reason = store.ref_graph.resolve("not-a-valid-ref")
        assert status == RefStatus.NOT_FOUND
        assert entry is None
        assert "Invalid uRef format" in reason

    def test_resolve_empty_string(self):
        store = SnapshotStore.get_instance()
        status, entry, reason = store.ref_graph.resolve("")
        assert status == RefStatus.NOT_FOUND
        assert entry is None

    def test_resolve_stale_with_object_gone(self):
        """Object was in rev 1 but not in rev 2 -> stale."""
        store = SnapshotStore.get_instance()
        # Rev 1: object 10 exists
        store.ingest("S", _sample_objects(1, start_id=10))
        ref_v1 = "S:10:1"

        # Rev 2: only object 20 exists (10 is gone)
        store.ingest("S", _sample_objects(1, start_id=20))

        status, entry, reason = store.ref_graph.resolve(ref_v1)
        # Object 10 still has its old entry but wasn't re-seen
        assert status == RefStatus.STALE
        assert reason is not None

    def test_resolve_returns_full_entry_data(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", [{
            "instanceId": 7,
            "name": "Player",
            "path": "/Player",
            "active": True,
            "tag": "Player",
            "layer": "Gameplay",
            "components": ["Transform", "Rigidbody", "PlayerController"],
        }])

        status, entry, _ = store.ref_graph.resolve("S:7:1")
        assert status == RefStatus.VALID
        full = entry.to_full()
        assert full["name"] == "Player"
        assert full["tag"] == "Player"
        assert full["layer"] == "Gameplay"
        assert "Rigidbody" in full["components"]
        assert full["revision"] == 1
        assert full["sceneName"] == "S"


# ---------------------------------------------------------------------------
# Diff behavior
# ---------------------------------------------------------------------------

class TestSnapshotDiff:
    def test_diff_detects_added_objects(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(2, start_id=10))
        store.ingest("S", _sample_objects(2, start_id=10) + _sample_objects(1, start_id=50))

        diff = store.diff(1, 2)
        added_ids = [parse_uref(r)[1] for r in diff["added"] if parse_uref(r)]
        assert 50 in added_ids

    def test_diff_detects_modified_objects(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(2, start_id=10))

        updated = _sample_objects(2, start_id=10)
        updated[0]["path"] = "/Root/Renamed"
        store.ingest("S", updated)

        diff = store.diff(1, 2)
        modified_ids = [parse_uref(r)[1] for r in diff["modified"] if parse_uref(r)]
        assert modified_ids == [10]

    def test_diff_detects_removed_objects(self):
        store = SnapshotStore.get_instance()
        first = _sample_objects(3, start_id=10)
        store.ingest("S", first)
        store.ingest("S", [first[0]])

        diff = store.diff(1, 2)
        removed_ids = [parse_uref(r)[1] for r in diff["removed"] if parse_uref(r)]
        assert removed_ids == [11, 12]

    def test_diff_defaults_to_current_revision(self):
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(2, start_id=10))
        store.ingest("S", _sample_objects(3, start_id=10))

        diff = store.diff(1)
        assert diff["toRevision"] == 2

    def test_diff_from_zero(self):
        """Diffing from 0 should show everything as added."""
        store = SnapshotStore.get_instance()
        store.ingest("S", _sample_objects(3, start_id=10))

        diff = store.diff(0, 1)
        assert len(diff["added"]) == 3
