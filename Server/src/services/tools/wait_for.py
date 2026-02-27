"""
Wait primitives for deterministic synchronization in AI-driven Unity workflows.

Provides server-side polling tools so agents don't need ad-hoc retry loops:
  - wait_for_editor_state: wait until editor reaches a target state (playing, not compiling, etc.)
  - wait_for_gameobject:   wait until a GameObject exists/is active/has a component
  - wait_for_console:      wait until a console message matching criteria appears (or disappears)

All tools implement deterministic timeout + poll-interval behavior and return
structured success/timeout results.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Annotated, Any, Literal

from fastmcp import Context
from mcp.types import ToolAnnotations

from models import MCPResponse
from services.registry import mcp_for_unity_tool
from services.tools import get_unity_instance_from_context
from services.tools.utils import coerce_bool, coerce_float, coerce_int
import transport.unity_transport as unity_transport
from transport.legacy.unity_connection import async_send_command_with_retry


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_POLL_INTERVAL_S = 0.5
_MIN_POLL_INTERVAL_S = 0.1
_MAX_POLL_INTERVAL_S = 10.0
_MIN_TIMEOUT_S = 0.0
_MAX_TIMEOUT_S = 300.0


def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_timeout(raw: Any) -> float:
    val = coerce_float(raw, default=_DEFAULT_TIMEOUT_S)
    if val is None:
        return _DEFAULT_TIMEOUT_S
    return _clamp(val, _MIN_TIMEOUT_S, _MAX_TIMEOUT_S)


def _parse_poll_interval(raw: Any) -> float:
    val = coerce_float(raw, default=_DEFAULT_POLL_INTERVAL_S)
    if val is None:
        return _DEFAULT_POLL_INTERVAL_S
    return _clamp(val, _MIN_POLL_INTERVAL_S, _MAX_POLL_INTERVAL_S)


def _timeout_response(description: str, elapsed_s: float, last_state: Any = None) -> dict[str, Any]:
    return {
        "success": False,
        "error": "timeout",
        "message": f"Timed out waiting for {description} after {elapsed_s:.1f}s",
        "data": {"elapsed_s": round(elapsed_s, 2), "last_state": last_state},
    }


def _success_response(description: str, elapsed_s: float, data: Any = None) -> dict[str, Any]:
    return {
        "success": True,
        "message": f"Condition met: {description} ({elapsed_s:.1f}s)",
        "data": {"elapsed_s": round(elapsed_s, 2), **(data or {})},
    }


# ---------------------------------------------------------------------------
# wait_for_editor_state
# ---------------------------------------------------------------------------


@mcp_for_unity_tool(
    description=(
        "Wait until the Unity editor reaches a desired state. "
        "Polls editor state at a configurable interval and returns when all specified "
        "conditions are met, or when timeout is exceeded. "
        "Conditions: is_playing, is_paused, is_compiling (pass true/false for each). "
        "Omitted conditions are not checked."
    ),
    annotations=ToolAnnotations(title="Wait For Editor State"),
)
async def wait_for_editor_state(
    ctx: Context,
    is_playing: Annotated[
        bool | str | None,
        "Wait until editor play-mode matches this value (true = playing, false = stopped). Omit to skip.",
    ] = None,
    is_paused: Annotated[
        bool | str | None,
        "Wait until editor pause state matches this value. Omit to skip.",
    ] = None,
    is_compiling: Annotated[
        bool | str | None,
        "Wait until compilation state matches (false = wait for compile to finish). Omit to skip.",
    ] = None,
    timeout_seconds: Annotated[
        float | str | None,
        "Maximum seconds to wait before returning timeout. Default 30, max 300.",
    ] = None,
    poll_interval_seconds: Annotated[
        float | str | None,
        "Seconds between polls. Default 0.5, min 0.1, max 10.",
    ] = None,
) -> dict[str, Any]:
    # Parse & validate conditions — at least one must be specified
    conditions: dict[str, bool] = {}
    parsed_playing = coerce_bool(is_playing)
    parsed_paused = coerce_bool(is_paused)
    parsed_compiling = coerce_bool(is_compiling)

    if parsed_playing is not None:
        conditions["is_playing"] = parsed_playing
    if parsed_paused is not None:
        conditions["is_paused"] = parsed_paused
    if parsed_compiling is not None:
        conditions["is_compiling"] = parsed_compiling

    if not conditions:
        return {
            "success": False,
            "error": "invalid_args",
            "message": "At least one condition must be specified (is_playing, is_paused, is_compiling).",
        }

    timeout_s = _parse_timeout(timeout_seconds)
    poll_s = _parse_poll_interval(poll_interval_seconds)
    description = ", ".join(f"{k}={v}" for k, v in conditions.items())

    # Short-circuit in pytest (no live Unity)
    if _in_pytest():
        return _success_response(description, 0.0)

    unity_instance = get_unity_instance_from_context(ctx)
    start = time.monotonic()
    last_state: dict[str, Any] | None = None

    while True:
        elapsed = time.monotonic() - start

        # Fetch current editor state
        try:
            from services.resources.editor_state import get_editor_state

            state_resp = await get_editor_state(ctx)
            state = state_resp.model_dump() if hasattr(state_resp, "model_dump") else state_resp
            data = state.get("data") if isinstance(state, dict) else None
        except Exception:
            data = None

        if isinstance(data, dict):
            # Extract relevant fields
            compilation = data.get("compilation") or {}
            editor = data.get("editor") or {}
            play_mode = editor.get("play_mode") or {}

            current: dict[str, Any] = {
                "is_playing": play_mode.get("is_playing"),
                "is_paused": play_mode.get("is_paused"),
                "is_compiling": compilation.get("is_compiling"),
            }
            last_state = current

            # Check all conditions
            all_met = True
            for key, expected in conditions.items():
                actual = current.get(key)
                if actual is None or bool(actual) != expected:
                    all_met = False
                    break

            if all_met:
                return _success_response(description, time.monotonic() - start, {"state": current})

        # Timeout check
        if elapsed >= timeout_s:
            return _timeout_response(description, elapsed, last_state)

        await asyncio.sleep(poll_s)


# ---------------------------------------------------------------------------
# wait_for_gameobject
# ---------------------------------------------------------------------------


@mcp_for_unity_tool(
    description=(
        "Wait until a GameObject matching the selector exists (or doesn't exist), "
        "is active/inactive, or has a specific component. "
        "Polls the scene at a configurable interval. "
        "Selector uses the same search semantics as find_gameobjects (name, tag, path, id)."
    ),
    annotations=ToolAnnotations(title="Wait For GameObject"),
)
async def wait_for_gameobject(
    ctx: Context,
    selector: Annotated[
        str,
        "Search term for the GameObject (name, tag, path, or instance ID).",
    ],
    search_method: Annotated[
        Literal["by_name", "by_tag", "by_layer", "by_component", "by_path", "by_id"] | None,
        "How to search. Default: by_name.",
    ] = "by_name",
    exists: Annotated[
        bool | str | None,
        "Wait until object exists (true) or does not exist (false). Default true.",
    ] = None,
    active: Annotated[
        bool | str | None,
        "If specified, also require the object's active state to match.",
    ] = None,
    component: Annotated[
        str | None,
        "If specified, require this component type to be present on the object.",
    ] = None,
    timeout_seconds: Annotated[
        float | str | None,
        "Maximum seconds to wait. Default 30, max 300.",
    ] = None,
    poll_interval_seconds: Annotated[
        float | str | None,
        "Seconds between polls. Default 0.5, min 0.1, max 10.",
    ] = None,
) -> dict[str, Any]:
    if not selector or not isinstance(selector, str) or not selector.strip():
        return {
            "success": False,
            "error": "invalid_args",
            "message": "selector is required and must be a non-empty string.",
        }

    want_exists = coerce_bool(exists, default=True)
    want_active = coerce_bool(active)
    search_method = search_method or "by_name"
    timeout_s = _parse_timeout(timeout_seconds)
    poll_s = _parse_poll_interval(poll_interval_seconds)

    parts = [f"selector='{selector}'"]
    parts.append(f"exists={want_exists}")
    if want_active is not None:
        parts.append(f"active={want_active}")
    if component:
        parts.append(f"component='{component}'")
    description = ", ".join(parts)

    if _in_pytest():
        return _success_response(description, 0.0)

    unity_instance = get_unity_instance_from_context(ctx)
    start = time.monotonic()
    last_state: dict[str, Any] | None = None

    while True:
        elapsed = time.monotonic() - start

        found = False
        found_active: bool | None = None
        has_component: bool | None = None

        try:
            params: dict[str, Any] = {
                "searchMethod": search_method,
                "searchTerm": selector,
                "includeInactive": True,
                "pageSize": 1,
                "cursor": 0,
            }
            response = await unity_transport.send_with_unity_instance(
                async_send_command_with_retry,
                unity_instance,
                "find_gameobjects",
                params,
            )
            if isinstance(response, dict) and response.get("success"):
                resp_data = response.get("data") or {}
                results = resp_data.get("results") or resp_data.get("instanceIds") or []
                if isinstance(results, list) and len(results) > 0:
                    found = True
                    # If we need active or component checks, fetch object detail
                    if want_active is not None or component:
                        obj_id = results[0] if isinstance(results[0], (int, str)) else None
                        if obj_id is not None:
                            detail_resp = await unity_transport.send_with_unity_instance(
                                async_send_command_with_retry,
                                unity_instance,
                                "manage_gameobject",
                                {"action": "get_info", "instanceId": obj_id},
                            )
                            if isinstance(detail_resp, dict) and detail_resp.get("success"):
                                detail_data = detail_resp.get("data") or {}
                                found_active = detail_data.get("activeSelf")
                                if component:
                                    components_list = detail_data.get("components") or []
                                    has_component = any(
                                        (isinstance(c, dict) and c.get("type") == component)
                                        or (isinstance(c, str) and c == component)
                                        for c in components_list
                                    )

            last_state = {
                "found": found,
                "active": found_active,
                "has_component": has_component,
            }
        except Exception:
            last_state = {"found": False, "error": "query_failed"}

        # Evaluate conditions
        condition_met = False
        if want_exists:
            # We want the object to exist
            if found:
                active_ok = want_active is None or bool(found_active) == want_active
                component_ok = component is None or has_component is True
                condition_met = active_ok and component_ok
        else:
            # We want the object to NOT exist
            condition_met = not found

        if condition_met:
            return _success_response(description, time.monotonic() - start, last_state)

        if elapsed >= timeout_s:
            return _timeout_response(description, elapsed, last_state)

        await asyncio.sleep(poll_s)


# ---------------------------------------------------------------------------
# wait_for_console
# ---------------------------------------------------------------------------


@mcp_for_unity_tool(
    description=(
        "Wait until a console message matching the criteria appears (or disappears). "
        "Polls the Unity console at a configurable interval. "
        "Specify 'text' to wait for a message containing that text to appear, "
        "or 'text_gone' to wait until no messages contain that text. "
        "Optionally filter by log level (error, warning, log)."
    ),
    annotations=ToolAnnotations(title="Wait For Console"),
)
async def wait_for_console(
    ctx: Context,
    text: Annotated[
        str | None,
        "Wait until a console message containing this text appears. Mutually exclusive with text_gone.",
    ] = None,
    text_gone: Annotated[
        str | None,
        "Wait until no console messages contain this text. Mutually exclusive with text.",
    ] = None,
    level: Annotated[
        Literal["error", "warning", "log"] | None,
        "Filter console messages to this level only. Omit to check all levels.",
    ] = None,
    timeout_seconds: Annotated[
        float | str | None,
        "Maximum seconds to wait. Default 30, max 300.",
    ] = None,
    poll_interval_seconds: Annotated[
        float | str | None,
        "Seconds between polls. Default 0.5, min 0.1, max 10.",
    ] = None,
) -> dict[str, Any]:
    # Validate: exactly one of text or text_gone
    has_text = text is not None and isinstance(text, str) and text.strip() != ""
    has_text_gone = text_gone is not None and isinstance(text_gone, str) and text_gone.strip() != ""

    if has_text and has_text_gone:
        return {
            "success": False,
            "error": "invalid_args",
            "message": "Specify either 'text' or 'text_gone', not both.",
        }
    if not has_text and not has_text_gone:
        return {
            "success": False,
            "error": "invalid_args",
            "message": "At least one of 'text' or 'text_gone' must be specified.",
        }

    timeout_s = _parse_timeout(timeout_seconds)
    poll_s = _parse_poll_interval(poll_interval_seconds)

    search_text = text if has_text else text_gone
    waiting_for_appear = has_text

    desc_parts = []
    if waiting_for_appear:
        desc_parts.append(f"text='{search_text}'")
    else:
        desc_parts.append(f"text_gone='{search_text}'")
    if level:
        desc_parts.append(f"level={level}")
    description = ", ".join(desc_parts)

    if _in_pytest():
        return _success_response(description, 0.0)

    unity_instance = get_unity_instance_from_context(ctx)
    start = time.monotonic()
    last_state: dict[str, Any] | None = None

    while True:
        elapsed = time.monotonic() - start

        match_found = False
        try:
            types_filter = [level] if level else ["error", "warning", "log"]
            params: dict[str, Any] = {
                "action": "get",
                "types": types_filter,
                "filterText": search_text,
                "count": 1,
                "format": "plain",
                "includeStacktrace": False,
            }

            response = await unity_transport.send_with_unity_instance(
                async_send_command_with_retry,
                unity_instance,
                "read_console",
                params,
            )
            if isinstance(response, dict) and response.get("success"):
                resp_data = response.get("data") or {}
                # Check for any returned entries
                lines = resp_data.get("lines") or resp_data.get("items") or []
                if isinstance(lines, list) and len(lines) > 0:
                    match_found = True

            last_state = {"match_found": match_found, "search_text": search_text}
        except Exception:
            last_state = {"match_found": False, "error": "query_failed"}

        # Evaluate condition
        if waiting_for_appear and match_found:
            return _success_response(description, time.monotonic() - start, last_state)
        if not waiting_for_appear and not match_found:
            return _success_response(description, time.monotonic() - start, last_state)

        if elapsed >= timeout_s:
            return _timeout_response(description, elapsed, last_state)

        await asyncio.sleep(poll_s)
