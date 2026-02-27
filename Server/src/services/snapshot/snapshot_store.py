"""
Snapshot Store: manages snapshot revisions and provides the singleton
ref graph instance used across tools.

Keeps a bounded history of recent snapshots for diffing.
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
    """Singleton store managing the ref graph and snapshot revision history.

    Usage:
        store = SnapshotStore.get_instance()
        rev = store.ingest(scene_name, objects, scope="active")
    """

    _instance: SnapshotStore | None = None

    def __init__(self, *, max_history: int = 50) -> None:
        self._ref_graph = RefGraph()
        self._revisions: list[SnapshotRevision] = []
        self._max_history = max_history

    @classmethod
    def get_instance(cls) -> SnapshotStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (mainly for testing)."""
        cls._instance = None

    @property
    def ref_graph(self) -> RefGraph:
        return self._ref_graph

    @property
    def current_revision(self) -> int:
        return self._ref_graph.current_revision

    @property
    def revisions(self) -> list[SnapshotRevision]:
        return list(self._revisions)

    def get_revision(self, rev: int) -> SnapshotRevision | None:
        """Look up a specific revision's metadata."""
        for r in self._revisions:
            if r.revision == rev:
                return r
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

        # Trim old history
        if len(self._revisions) > self._max_history:
            self._revisions = self._revisions[-self._max_history:]

        return revision

    def diff(self, from_revision: int, to_revision: int | None = None) -> dict[str, Any]:
        """Delegate to ref graph diff."""
        return self._ref_graph.diff(from_revision, to_revision)
