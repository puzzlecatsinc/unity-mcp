"""
MCP tool for resolving uRef identifiers to current object metadata.

Provides staleness detection so agents know when a ref has drifted
and can obtain the updated ref.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from services.registry import mcp_for_unity_tool
from services.snapshot import SnapshotStore, RefStatus


@mcp_for_unity_tool(
    name="ref_resolve",
    description=(
        "Resolve a uRef to its current object metadata. "
        "Returns the object's current state if the ref is still valid, "
        "provides the updated ref if the object moved/changed, "
        "or reports not_found if the object no longer exists. "
        "Use this to validate refs before performing operations."
    ),
)
async def ref_resolve(
    ctx: Context,
    ref: Annotated[
        str,
        Field(description="The uRef string to resolve (format: sceneName:instanceId:revision)."),
    ],
) -> dict[str, Any]:
    """
    Resolve a uRef to current object metadata with staleness detection.

    Returns:
        - status: "valid" | "stale" | "not_found"
        - entry: object metadata (if found)
        - reason: explanation (if stale or not_found)
        - currentRevision: latest snapshot revision
    """
    if not ref or not ref.strip():
        return {
            "success": False,
            "message": "Missing required parameter 'ref'. Provide a uRef string.",
        }

    store = SnapshotStore.get_instance()
    status, entry, reason = store.ref_graph.resolve(ref.strip())

    result: dict[str, Any] = {
        "success": True,
        "message": _status_message(status, ref, reason),
        "data": {
            "status": status.value,
            "currentRevision": store.current_revision,
        },
    }

    if entry is not None:
        result["data"]["entry"] = entry.to_full()

    if reason is not None:
        result["data"]["reason"] = reason

    return result


def _status_message(status: RefStatus, ref: str, reason: str | None) -> str:
    if status == RefStatus.VALID:
        return f"Ref {ref} is valid and current."
    if status == RefStatus.STALE:
        return f"Ref {ref} is stale. {reason or ''}"
    return f"Ref {ref} not found. {reason or ''}"
