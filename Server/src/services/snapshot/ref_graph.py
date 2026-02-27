"""
Ref Graph: stable reference system for Unity scene objects.

Provides Playwright-style stable refs (uRef) that survive hierarchy changes
and allow agents to target objects deterministically across tool calls.

uRef format: <scene_name>:<instance_id>:<revision>
  - scene_name: active scene name (short, human-readable)
  - instance_id: Unity instanceId (stable within a session)
  - revision: snapshot revision that created/last-confirmed this ref
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class RefStatus(str, enum.Enum):
    """Status of a ref resolution attempt."""
    VALID = "valid"
    STALE = "stale"
    NOT_FOUND = "not_found"


@dataclass
class RefEntry:
    """A single ref entry tracking a Unity GameObject."""
    uref: str
    instance_id: int
    scene_name: str
    name: str
    path: str
    parent_instance_id: int | None = None
    active: bool = True
    layer: str | None = None
    tag: str | None = None
    components: list[str] = field(default_factory=list)
    revision: int = 0
    last_seen_revision: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_compact(self) -> dict[str, Any]:
        """Compact representation for snapshot responses (minimise payload)."""
        result: dict[str, Any] = {
            "uref": self.uref,
            "instanceId": self.instance_id,
            "name": self.name,
            "path": self.path,
            "active": self.active,
        }
        if self.parent_instance_id is not None:
            result["parentInstanceId"] = self.parent_instance_id
        if self.tag and self.tag != "Untagged":
            result["tag"] = self.tag
        if self.layer and self.layer != "Default":
            result["layer"] = self.layer
        if self.components:
            result["components"] = self.components
        return result

    def to_full(self) -> dict[str, Any]:
        """Full representation including metadata."""
        result = self.to_compact()
        result["sceneName"] = self.scene_name
        result["revision"] = self.revision
        result["lastSeenRevision"] = self.last_seen_revision
        return result


def make_uref(scene_name: str, instance_id: int, revision: int) -> str:
    """Construct a uRef string."""
    return f"{scene_name}:{instance_id}:{revision}"


def parse_uref(uref: str) -> tuple[str, int, int] | None:
    """Parse a uRef string into (scene_name, instance_id, revision).

    Returns None if the format is invalid.
    """
    parts = uref.split(":")
    if len(parts) != 3:
        return None
    try:
        return (parts[0], int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


class RefGraph:
    """In-memory ref graph tracking all known scene objects.

    Thread-safety: This is single-threaded (asyncio). No locks needed.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RefEntry] = {}  # uref -> entry
        self._instance_index: dict[int, str] = {}  # instanceId -> latest (current snapshot) uref
        self._revision_index: dict[int, dict[int, str]] = {}  # revision -> instanceId -> uref
        self._current_revision: int = 0

    @property
    def current_revision(self) -> int:
        return self._current_revision

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def has_revision(self, revision: int) -> bool:
        """Return True when a revision snapshot is still retained.

        Revision 0 is a synthetic empty baseline and is always available.
        """
        return revision == 0 or revision in self._revision_index

    def get_by_uref(self, uref: str) -> RefEntry | None:
        """Look up a ref entry by its uRef."""
        return self._entries.get(uref)

    def get_by_instance_id(self, instance_id: int) -> RefEntry | None:
        """Look up the latest ref entry for an instance ID."""
        uref = self._instance_index.get(instance_id)
        if uref is None:
            return None
        return self._entries.get(uref)

    def resolve(self, uref: str) -> tuple[RefStatus, RefEntry | None, str | None]:
        """Resolve a uRef to its entry with staleness detection.

        Returns:
            (status, entry_or_None, reason_or_None)
        """
        parsed = parse_uref(uref)
        if parsed is None:
            return (RefStatus.NOT_FOUND, None, f"Invalid uRef format: {uref}")

        _, instance_id, ref_revision = parsed

        entry = self._entries.get(uref)
        if entry is not None:
            # Exact match — check if it's still current
            if entry.last_seen_revision == self._current_revision:
                return (RefStatus.VALID, entry, None)

            # Entry exists but wasn't in the latest snapshot
            latest = self.get_by_instance_id(instance_id)
            if latest is not None and latest.uref != uref:
                return (
                    RefStatus.STALE,
                    latest,
                    f"Object moved/updated. Old ref revision {ref_revision}, "
                    f"current revision {self._current_revision}. "
                    f"New uRef: {latest.uref}",
                )
            return (
                RefStatus.STALE,
                entry,
                f"Ref from revision {ref_revision}, current revision "
                f"{self._current_revision}. Object may have been removed.",
            )

        # Not found by exact uRef — try instance_id lookup for helpful error
        latest = self.get_by_instance_id(instance_id)
        if latest is not None:
            return (
                RefStatus.STALE,
                latest,
                f"uRef not found but instanceId {instance_id} exists with "
                f"newer ref: {latest.uref}",
            )

        return (RefStatus.NOT_FOUND, None, f"No object found for uRef: {uref}")

    def ingest_snapshot(
        self,
        scene_name: str,
        objects: list[dict[str, Any]],
    ) -> int:
        """Ingest a raw snapshot from Unity and update the ref graph.

        Args:
            scene_name: Name of the scene.
            objects: List of dicts with at least 'instanceId', 'name', 'path'.
                     Optional: 'parentInstanceId', 'active', 'layer', 'tag', 'components'.

        Returns:
            The new revision number.
        """
        self._current_revision += 1
        rev = self._current_revision
        now = time.time()

        # Stable processing order => deterministic diff output.
        normalized: list[tuple[int, dict[str, Any]]] = []
        for obj in objects:
            raw_instance_id = obj.get("instanceId")
            try:
                instance_id = int(raw_instance_id)
            except (TypeError, ValueError):
                continue
            normalized.append((instance_id, obj))
        normalized.sort(key=lambda pair: pair[0])

        seen_instance_ids: set[int] = set()
        snapshot_index: dict[int, str] = {}

        for instance_id, obj in normalized:
            seen_instance_ids.add(instance_id)
            uref = make_uref(scene_name, instance_id, rev)

            # Check if this instance already had a ref
            existing = self.get_by_instance_id(instance_id)

            raw_components = obj.get("components")
            components: list[str] = []
            if isinstance(raw_components, list):
                components = [str(component) for component in raw_components if component is not None]

            entry = RefEntry(
                uref=uref,
                instance_id=instance_id,
                scene_name=scene_name,
                name=str(obj.get("name", "")),
                path=str(obj.get("path", "")),
                parent_instance_id=obj.get("parentInstanceId"),
                active=bool(obj.get("active", True)),
                layer=str(obj.get("layer")) if obj.get("layer") is not None else None,
                tag=str(obj.get("tag")) if obj.get("tag") is not None else None,
                components=components,
                revision=rev,
                last_seen_revision=rev,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )

            self._entries[uref] = entry
            self._instance_index[instance_id] = uref
            snapshot_index[instance_id] = uref

        # Current snapshot membership must reflect *only* currently seen objects.
        for instance_id in list(self._instance_index.keys()):
            if instance_id not in seen_instance_ids:
                del self._instance_index[instance_id]

        self._revision_index[rev] = snapshot_index
        return rev

    @staticmethod
    def _entry_signature(entry: RefEntry) -> tuple[Any, ...]:
        """Fields that define object-diff identity (excluding revision metadata)."""
        return (
            entry.name,
            entry.path,
            entry.parent_instance_id,
            entry.active,
            entry.layer,
            entry.tag,
            tuple(entry.components),
        )

    def _snapshot_for_revision(self, revision: int) -> dict[int, str]:
        if revision == 0:
            return {}
        snapshot = self._revision_index.get(revision)
        if snapshot is None:
            raise ValueError(f"Revision {revision} is no longer available (history pruned).")
        return snapshot

    def diff(self, from_revision: int, to_revision: int | None = None) -> dict[str, Any]:
        """Compute deterministic changes between two revisions.

        Returns dict with 'added', 'modified', 'removed' lists of uRefs.
        """
        to_rev = to_revision if to_revision is not None else self._current_revision

        if to_rev < from_revision:
            raise ValueError("to_revision must be >= from_revision")

        from_snapshot = self._snapshot_for_revision(from_revision)
        to_snapshot = self._snapshot_for_revision(to_rev)

        from_ids = set(from_snapshot.keys())
        to_ids = set(to_snapshot.keys())

        added_ids = sorted(to_ids - from_ids)
        removed_ids = sorted(from_ids - to_ids)
        common_ids = sorted(from_ids & to_ids)

        added = [to_snapshot[iid] for iid in added_ids]
        removed = [from_snapshot[iid] for iid in removed_ids]

        modified: list[str] = []
        for instance_id in common_ids:
            from_uref = from_snapshot[instance_id]
            to_uref = to_snapshot[instance_id]

            from_entry = self._entries.get(from_uref)
            to_entry = self._entries.get(to_uref)
            if from_entry is None or to_entry is None:
                continue

            if self._entry_signature(from_entry) != self._entry_signature(to_entry):
                modified.append(to_uref)

        return {
            "fromRevision": from_revision,
            "toRevision": to_rev,
            "added": added,
            "modified": modified,
            "removed": removed,
        }

    def prune_before_revision(self, min_revision: int) -> None:
        """Drop entries/snapshot indices older than min_revision to bound memory growth."""
        if min_revision <= 1:
            return

        for revision in list(self._revision_index.keys()):
            if revision < min_revision:
                del self._revision_index[revision]

        for uref, entry in list(self._entries.items()):
            if entry.revision < min_revision:
                del self._entries[uref]

        for instance_id, uref in list(self._instance_index.items()):
            if uref not in self._entries:
                del self._instance_index[instance_id]

    def clear(self) -> None:
        """Reset the entire ref graph."""
        self._entries.clear()
        self._instance_index.clear()
        self._revision_index.clear()
        self._current_revision = 0
