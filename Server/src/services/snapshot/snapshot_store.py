"""
Snapshot Store: manages snapshot revisions and per-unity-instance stores.

Each Unity instance gets an isolated SnapshotStore (and RefGraph) to avoid
cross-instance leakage of refs/revisions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .ref_graph import RefGraph


@dataclass
class SnapshotRevision:
    """Metadata for a single captured snapshot."""

    revision: int
    scene_name: str
    object_count: int
    captured_at: float = field(default_factory=time.time)
    scope: str = "active"  # "active" | "subtree"
    root_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "sceneName": self.scene_name,
            "objectCount": self.object_count,
            "capturedAt": self.captured_at,
            "scope": self.scope,
            "rootRef": self.root_ref,
        }


class SnapshotStore:
    """Store managing ref graph + revision history for a Unity instance.

    Usage:
        store = SnapshotStore.get_instance(unity_instance)
        rev = store.ingest(scene_name, objects, scope="active")
    """

    _instances: dict[str, "SnapshotStore"] = {}
    _DEFAULT_INSTANCE_KEY = "__default__"

    def __init__(self, *, max_history: int = 50) -> None:
        self._ref_graph = RefGraph()
        self._revisions: list[SnapshotRevision] = []
        self._max_history = max(1, max_history)

    @classmethod
    def _normalize_instance_key(cls, unity_instance: str | None) -> str:
        if unity_instance is None:
            return cls._DEFAULT_INSTANCE_KEY

        key = str(unity_instance).strip()
        if key == "":
            return cls._DEFAULT_INSTANCE_KEY
        return key

    @classmethod
    def get_instance(cls, unity_instance: str | None = None) -> "SnapshotStore":
        key = cls._normalize_instance_key(unity_instance)
        if key not in cls._instances:
            cls._instances[key] = cls()
        return cls._instances[key]

    @classmethod
    def reset(cls, unity_instance: str | None = None) -> None:
        """Reset stores (all by default, or one specific instance)."""
        if unity_instance is None:
            cls._instances = {}
            return

        key = cls._normalize_instance_key(unity_instance)
        cls._instances.pop(key, None)

    @property
    def ref_graph(self) -> RefGraph:
        return self._ref_graph

    @property
    def current_revision(self) -> int:
        return self._ref_graph.current_revision

    @property
    def oldest_revision(self) -> int:
        if not self._revisions:
            return 0
        return self._revisions[0].revision

    @property
    def revisions(self) -> list[SnapshotRevision]:
        return list(self._revisions)

    def has_revision(self, revision: int) -> bool:
        if revision == 0:
            return True
        return self._ref_graph.has_revision(revision)

    def get_revision(self, rev: int) -> SnapshotRevision | None:
        """Look up a specific revision's metadata."""
        for revision in self._revisions:
            if revision.revision == rev:
                return revision
        return None

    def ingest(
        self,
        scene_name: str,
        objects: list[dict[str, Any]],
        *,
        scope: str = "active",
        root_ref: str | None = None,
    ) -> SnapshotRevision:
        """Ingest a new snapshot and return its revision metadata."""
        rev_num = self._ref_graph.ingest_snapshot(scene_name, objects)

        revision = SnapshotRevision(
            revision=rev_num,
            scene_name=scene_name,
            object_count=len(objects),
            scope=scope,
            root_ref=root_ref,
        )

        self._revisions.append(revision)

        # Trim old history + corresponding graph entries.
        if len(self._revisions) > self._max_history:
            self._revisions = self._revisions[-self._max_history:]
            oldest_kept = self._revisions[0].revision
            self._ref_graph.prune_before_revision(oldest_kept)

        return revision

    def diff(self, from_revision: int, to_revision: int | None = None) -> dict[str, Any]:
        """Compute a deterministic diff between two retained revisions."""
        return self._ref_graph.diff(from_revision, to_revision)
