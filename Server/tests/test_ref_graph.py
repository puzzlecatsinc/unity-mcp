"""Unit tests for the RefGraph and SnapshotStore."""

import pytest
import sys
import os
from pathlib import Path

# Ensure src is on the path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from services.snapshot.ref_graph import RefGraph, RefEntry, RefStatus, make_uref, parse_uref
from services.snapshot.snapshot_store import SnapshotStore, SnapshotRevision


# ---------------------------------------------------------------------------
# parse_uref / make_uref
# ---------------------------------------------------------------------------

class TestURefParsing:
    def test_make_uref(self):
        result = make_uref("SampleScene", 12345, 1)
        assert result == "SampleScene:12345:1"

    def test_parse_uref_valid(self):
        parsed = parse_uref("SampleScene:12345:1")
        assert parsed == ("SampleScene", 12345, 1)

    def test_parse_uref_invalid_format(self):
        assert parse_uref("bad") is None
        assert parse_uref("a:b") is None
        assert parse_uref("a:b:c:d") is None

    def test_parse_uref_invalid_types(self):
        assert parse_uref("scene:notanint:1") is None
        assert parse_uref("scene:1:notanint") is None

    def test_roundtrip(self):
        uref = make_uref("MyScene", 999, 42)
        parsed = parse_uref(uref)
        assert parsed == ("MyScene", 999, 42)


# ---------------------------------------------------------------------------
# RefGraph core
# ---------------------------------------------------------------------------

def _sample_objects(count: int = 3, start_id: int = 100) -> list[dict]:
    """Generate sample Unity-like object dicts."""
    objs = []
    for i in range(count):
        iid = start_id + i
        objs.append({
            "instanceId": iid,
            "name": f"Object_{iid}",
            "path": f"/Root/Object_{iid}",
            "active": True,
            "tag": "Untagged",
            "layer": "Default",
            "components": ["Transform"],
            "parentInstanceId": start_id - 1 if i > 0 else None,
        })
    return objs


class TestRefGraph:
    def setup_method(self):
        self.graph = RefGraph()

    def test_initial_state(self):
        assert self.graph.current_revision == 0
        assert self.graph.entry_count == 0

    def test_ingest_snapshot_returns_revision(self):
        objs = _sample_objects(3)
        rev = self.graph.ingest_snapshot("TestScene", objs)
        assert rev == 1
        assert self.graph.current_revision == 1
        assert self.graph.entry_count == 3

    def test_ingest_increments_revision(self):
        self.graph.ingest_snapshot("TestScene", _sample_objects(2))
        self.graph.ingest_snapshot("TestScene", _sample_objects(2))
        assert self.graph.current_revision == 2

    def test_entries_have_correct_urefs(self):
        objs = _sample_objects(2, start_id=50)
        self.graph.ingest_snapshot("MyScene", objs)

        entry = self.graph.get_by_instance_id(50)
        assert entry is not None
        assert entry.uref == "MyScene:50:1"
        assert entry.instance_id == 50
        assert entry.name == "Object_50"
        assert entry.scene_name == "MyScene"

    def test_get_by_uref(self):
        self.graph.ingest_snapshot("S", _sample_objects(1, start_id=10))
        entry = self.graph.get_by_uref("S:10:1")
        assert entry is not None
        assert entry.instance_id == 10

    def test_get_by_uref_not_found(self):
        assert self.graph.get_by_uref("Nope:999:1") is None

    def test_get_by_instance_id_not_found(self):
        assert self.graph.get_by_instance_id(999) is None

    def test_resolve_valid(self):
        self.graph.ingest_snapshot("S", _sample_objects(1, start_id=10))
        status, entry, reason = self.graph.resolve("S:10:1")
        assert status == RefStatus.VALID
        assert entry is not None
        assert entry.instance_id == 10
        assert reason is None

    def test_resolve_stale_after_new_snapshot(self):
        # First snapshot
        self.graph.ingest_snapshot("S", _sample_objects(1, start_id=10))
        old_ref = "S:10:1"

        # Second snapshot with same object (new revision ref)
        self.graph.ingest_snapshot("S", _sample_objects(1, start_id=10))

        status, entry, reason = self.graph.resolve(old_ref)
        assert status == RefStatus.STALE
        assert entry is not None
        # Should point to the newer entry
        assert entry.uref == "S:10:2"
        assert reason is not None
        assert "New uRef" in reason or "newer ref" in reason

    def test_resolve_not_found(self):
        self.graph.ingest_snapshot("S", _sample_objects(1, start_id=10))
        status, entry, reason = self.graph.resolve("S:999:1")
        assert status == RefStatus.NOT_FOUND
        assert entry is None
        assert reason is not None

    def test_resolve_invalid_format(self):
        status, entry, reason = self.graph.resolve("garbage")
        assert status == RefStatus.NOT_FOUND
        assert entry is None
        assert "Invalid uRef format" in reason

    def test_compact_representation(self):
        self.graph.ingest_snapshot("S", [{
            "instanceId": 1,
            "name": "Player",
            "path": "/Player",
            "active": True,
            "tag": "Player",
            "layer": "Default",
            "components": ["Transform", "Rigidbody"],
        }])
        entry = self.graph.get_by_instance_id(1)
        compact = entry.to_compact()
        assert compact["uref"] == "S:1:1"
        assert compact["name"] == "Player"
        assert compact["tag"] == "Player"  # Non-default tag included
        assert "layer" not in compact  # Default layer excluded
        assert compact["components"] == ["Transform", "Rigidbody"]

    def test_compact_excludes_defaults(self):
        self.graph.ingest_snapshot("S", [{
            "instanceId": 1,
            "name": "Obj",
            "path": "/Obj",
            "active": True,
            "tag": "Untagged",
            "layer": "Default",
        }])
        entry = self.graph.get_by_instance_id(1)
        compact = entry.to_compact()
        assert "tag" not in compact
        assert "layer" not in compact

    def test_clear(self):
        self.graph.ingest_snapshot("S", _sample_objects(5))
        assert self.graph.entry_count == 5
        self.graph.clear()
        assert self.graph.entry_count == 0
        assert self.graph.current_revision == 0

    def test_diff_added(self):
        self.graph.ingest_snapshot("S", _sample_objects(2, start_id=10))
        # Add more objects in second snapshot
        all_objs = _sample_objects(2, start_id=10) + _sample_objects(1, start_id=50)
        self.graph.ingest_snapshot("S", all_objs)

        diff = self.graph.diff(1, 2)
        assert diff["fromRevision"] == 1
        assert diff["toRevision"] == 2
        # The new object (50) should be in added
        added_ids = [parse_uref(r)[1] for r in diff["added"] if parse_uref(r)]
        assert 50 in added_ids

    def test_diff_modified(self):
        self.graph.ingest_snapshot("S", _sample_objects(2, start_id=10))

        updated = _sample_objects(2, start_id=10)
        updated[1]["active"] = False
        self.graph.ingest_snapshot("S", updated)

        diff = self.graph.diff(1, 2)
        modified_ids = [parse_uref(r)[1] for r in diff["modified"] if parse_uref(r)]
        assert modified_ids == [11]

    def test_diff_removed_is_correct_and_deterministic(self):
        baseline = _sample_objects(3, start_id=10)
        # Intentionally ingest out of order to verify deterministic diff output.
        self.graph.ingest_snapshot("S", [baseline[2], baseline[0], baseline[1]])

        next_snapshot = [baseline[0], _sample_objects(1, start_id=13)[0]]
        self.graph.ingest_snapshot("S", next_snapshot)

        diff = self.graph.diff(1, 2)
        removed_ids = [parse_uref(r)[1] for r in diff["removed"] if parse_uref(r)]
        added_ids = [parse_uref(r)[1] for r in diff["added"] if parse_uref(r)]

        assert removed_ids == [11, 12]
        assert added_ids == [13]

    def test_skips_objects_without_instance_id(self):
        objs = [{"name": "NoId", "path": "/NoId"}]
        self.graph.ingest_snapshot("S", objs)
        assert self.graph.entry_count == 0


# ---------------------------------------------------------------------------
# SnapshotStore
# ---------------------------------------------------------------------------

class TestSnapshotStore:
    def setup_method(self):
        SnapshotStore.reset()
        self.store = SnapshotStore.get_instance()

    def teardown_method(self):
        SnapshotStore.reset()

    def test_singleton(self):
        s1 = SnapshotStore.get_instance()
        s2 = SnapshotStore.get_instance()
        assert s1 is s2

    def test_scoped_instances_are_isolated(self):
        a = SnapshotStore.get_instance("unity-a")
        b = SnapshotStore.get_instance("unity-b")

        assert a is not b

        a.ingest("SceneA", _sample_objects(1, start_id=1))
        assert a.current_revision == 1
        assert b.current_revision == 0

    def test_reset(self):
        s1 = SnapshotStore.get_instance()
        SnapshotStore.reset()
        s2 = SnapshotStore.get_instance()
        assert s1 is not s2

    def test_ingest_returns_revision(self):
        rev = self.store.ingest("TestScene", _sample_objects(3))
        assert isinstance(rev, SnapshotRevision)
        assert rev.revision == 1
        assert rev.scene_name == "TestScene"
        assert rev.object_count == 3

    def test_revision_history(self):
        self.store.ingest("S1", _sample_objects(2))
        self.store.ingest("S1", _sample_objects(3))
        assert len(self.store.revisions) == 2
        assert self.store.revisions[0].revision == 1
        assert self.store.revisions[1].revision == 2

    def test_get_revision(self):
        self.store.ingest("S", _sample_objects(1))
        rev = self.store.get_revision(1)
        assert rev is not None
        assert rev.scene_name == "S"

    def test_get_revision_not_found(self):
        assert self.store.get_revision(999) is None

    def test_history_bounded(self):
        store = SnapshotStore(max_history=5)
        for i in range(10):
            store.ingest("S", _sample_objects(1, start_id=i * 10))

        assert len(store.revisions) == 5
        assert store.revisions[0].revision == 6  # oldest kept
        # RefGraph entries from trimmed revisions should also be pruned.
        assert store.ref_graph.entry_count == 5
        assert store.has_revision(5) is False
        assert store.has_revision(6) is True

    def test_diff_delegates(self):
        self.store.ingest("S", _sample_objects(2, start_id=10))
        self.store.ingest("S", _sample_objects(3, start_id=10))
        diff = self.store.diff(1, 2)
        assert "added" in diff
        assert "modified" in diff
        assert "removed" in diff

    def test_diff_raises_when_revision_pruned(self):
        store = SnapshotStore(max_history=2)
        store.ingest("S", _sample_objects(1, start_id=1))
        store.ingest("S", _sample_objects(1, start_id=2))
        store.ingest("S", _sample_objects(1, start_id=3))

        with pytest.raises(ValueError):
            store.diff(1, 3)

    def test_revision_to_dict(self):
        rev = self.store.ingest("S", _sample_objects(1))
        d = rev.to_dict()
        assert d["revision"] == 1
        assert d["sceneName"] == "S"
        assert d["objectCount"] == 1
        assert "capturedAt" in d

    def test_ingest_with_scope_and_root(self):
        rev = self.store.ingest(
            "S",
            _sample_objects(1),
            scope="subtree",
            root_ref="S:100:0",
        )
        assert rev.scope == "subtree"
        assert rev.root_ref == "S:100:0"
