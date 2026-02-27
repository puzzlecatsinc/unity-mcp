"""
Tests for wait_for tools (wait_for_editor_state, wait_for_gameobject, wait_for_console).

Covers:
  - success paths (condition met)
  - timeout paths (condition never met)
  - invalid-arg validation
  - deterministic poll-interval / timeout clamping
"""

import asyncio
import os
import time

import pytest

from .test_helpers import DummyContext


# =========================================================================
# wait_for_editor_state
# =========================================================================


class TestWaitForEditorState:
    """Tests for wait_for_editor_state tool."""

    @pytest.mark.asyncio
    async def test_no_conditions_returns_invalid_args(self):
        """Calling with no conditions is an error."""
        from services.tools.wait_for import wait_for_editor_state

        ctx = DummyContext()
        result = await wait_for_editor_state(ctx)
        assert result["success"] is False
        assert result["error"] == "invalid_args"
        assert "At least one condition" in result["message"]

    @pytest.mark.asyncio
    async def test_success_in_pytest_mode(self):
        """In pytest mode (PYTEST_CURRENT_TEST set), returns immediately."""
        from services.tools.wait_for import wait_for_editor_state

        ctx = DummyContext()
        result = await wait_for_editor_state(ctx, is_playing=True)
        assert result["success"] is True
        assert result["data"]["elapsed_s"] == 0.0

    @pytest.mark.asyncio
    async def test_condition_met_immediately(self, monkeypatch):
        """When editor already matches, returns success on first poll."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod

        async def fake_get_editor_state(ctx):
            return {
                "success": True,
                "data": {
                    "schema_version": "v2",
                    "observed_at_unix_ms": 0,
                    "sequence": 0,
                    "editor": {"play_mode": {"is_playing": True, "is_paused": False}},
                    "compilation": {"is_compiling": False},
                },
            }

        # Patch at the module level where it's imported
        import services.resources.editor_state as es_mod
        monkeypatch.setattr(es_mod, "get_editor_state", fake_get_editor_state)

        ctx = DummyContext()
        result = await mod.wait_for_editor_state(ctx, is_playing=True, timeout_seconds=5)
        assert result["success"] is True
        assert result["data"]["state"]["is_playing"] is True

    @pytest.mark.asyncio
    async def test_waits_then_succeeds(self, monkeypatch):
        """Polls until condition is met, then returns success."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod

        call_count = 0

        async def fake_get_editor_state(ctx):
            nonlocal call_count
            call_count += 1
            is_compiling = call_count < 3
            return {
                "success": True,
                "data": {
                    "schema_version": "v2",
                    "observed_at_unix_ms": 0,
                    "sequence": 0,
                    "editor": {"play_mode": {"is_playing": False, "is_paused": False}},
                    "compilation": {"is_compiling": is_compiling},
                },
            }

        import services.resources.editor_state as es_mod
        monkeypatch.setattr(es_mod, "get_editor_state", fake_get_editor_state)

        ctx = DummyContext()
        result = await mod.wait_for_editor_state(
            ctx, is_compiling=False, timeout_seconds=10, poll_interval_seconds=0.05
        )
        assert result["success"] is True
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_timeout(self, monkeypatch):
        """Returns timeout when condition never met."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod

        async def fake_get_editor_state(ctx):
            return {
                "success": True,
                "data": {
                    "schema_version": "v2",
                    "observed_at_unix_ms": 0,
                    "sequence": 0,
                    "editor": {"play_mode": {"is_playing": False, "is_paused": False}},
                    "compilation": {"is_compiling": True},
                },
            }

        import services.resources.editor_state as es_mod
        monkeypatch.setattr(es_mod, "get_editor_state", fake_get_editor_state)

        ctx = DummyContext()
        result = await mod.wait_for_editor_state(
            ctx, is_compiling=False, timeout_seconds=0.3, poll_interval_seconds=0.05
        )
        assert result["success"] is False
        assert result["error"] == "timeout"
        assert result["data"]["elapsed_s"] >= 0.2

    @pytest.mark.asyncio
    async def test_multiple_conditions(self, monkeypatch):
        """All specified conditions must be met simultaneously."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod

        call_count = 0

        async def fake_get_editor_state(ctx):
            nonlocal call_count
            call_count += 1
            # First call: playing but compiling. Second: playing and done.
            return {
                "success": True,
                "data": {
                    "schema_version": "v2",
                    "observed_at_unix_ms": 0,
                    "sequence": 0,
                    "editor": {"play_mode": {"is_playing": True, "is_paused": False}},
                    "compilation": {"is_compiling": call_count < 2},
                },
            }

        import services.resources.editor_state as es_mod
        monkeypatch.setattr(es_mod, "get_editor_state", fake_get_editor_state)

        ctx = DummyContext()
        result = await mod.wait_for_editor_state(
            ctx,
            is_playing=True,
            is_compiling=False,
            timeout_seconds=5,
            poll_interval_seconds=0.05,
        )
        assert result["success"] is True
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_string_boolean_coercion(self):
        """String booleans like 'true'/'false' are accepted."""
        from services.tools.wait_for import wait_for_editor_state

        ctx = DummyContext()
        # In pytest mode, should succeed immediately with string bools
        result = await wait_for_editor_state(ctx, is_playing="true")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_string_timeout_coercion(self):
        """String-typed timeout/interval are coerced to float."""
        from services.tools.wait_for import wait_for_editor_state

        ctx = DummyContext()
        result = await wait_for_editor_state(
            ctx, is_playing=True, timeout_seconds="10", poll_interval_seconds="0.5"
        )
        assert result["success"] is True


# =========================================================================
# wait_for_gameobject
# =========================================================================


class TestWaitForGameobject:
    """Tests for wait_for_gameobject tool."""

    @pytest.mark.asyncio
    async def test_missing_selector_returns_invalid_args(self):
        """Calling without selector returns error."""
        from services.tools.wait_for import wait_for_gameobject

        ctx = DummyContext()
        result = await wait_for_gameobject(ctx, selector="")
        assert result["success"] is False
        assert result["error"] == "invalid_args"

    @pytest.mark.asyncio
    async def test_none_selector_returns_invalid_args(self):
        """Calling with None selector returns error."""
        from services.tools.wait_for import wait_for_gameobject

        ctx = DummyContext()
        result = await wait_for_gameobject(ctx, selector=None)
        assert result["success"] is False
        assert result["error"] == "invalid_args"

    @pytest.mark.asyncio
    async def test_success_in_pytest_mode(self):
        """In pytest mode, returns immediately."""
        from services.tools.wait_for import wait_for_gameobject

        ctx = DummyContext()
        result = await wait_for_gameobject(ctx, selector="Player")
        assert result["success"] is True
        assert result["data"]["elapsed_s"] == 0.0

    @pytest.mark.asyncio
    async def test_object_found_immediately(self, monkeypatch):
        """When object exists on first poll, returns success."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        async def fake_send(send_fn, instance, command, params):
            if command == "find_gameobjects":
                return {"success": True, "data": {"instanceIds": [12345]}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_gameobject(
            ctx, selector="Player", timeout_seconds=5, poll_interval_seconds=0.05
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_object_not_exists_wait(self, monkeypatch):
        """Waits for object to disappear (exists=false)."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        call_count = 0

        async def fake_send(send_fn, instance, command, params):
            nonlocal call_count
            call_count += 1
            if command == "find_gameobjects":
                if call_count < 3:
                    return {"success": True, "data": {"instanceIds": [123]}}
                return {"success": True, "data": {"instanceIds": []}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_gameobject(
            ctx, selector="Enemy", exists=False, timeout_seconds=5, poll_interval_seconds=0.05
        )
        assert result["success"] is True
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_timeout_object_never_found(self, monkeypatch):
        """Times out when object never appears."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        async def fake_send(send_fn, instance, command, params):
            if command == "find_gameobjects":
                return {"success": True, "data": {"instanceIds": []}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_gameobject(
            ctx, selector="NonExistent", timeout_seconds=0.3, poll_interval_seconds=0.05
        )
        assert result["success"] is False
        assert result["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_with_component_check(self, monkeypatch):
        """Waits until object has a specific component."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        call_count = 0

        async def fake_send(send_fn, instance, command, params):
            nonlocal call_count
            if command == "find_gameobjects":
                call_count += 1
                return {"success": True, "data": {"instanceIds": [100]}}
            if command == "manage_gameobject":
                components = []
                if call_count >= 2:
                    components = [{"type": "Rigidbody"}]
                return {"success": True, "data": {"activeSelf": True, "components": components}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_gameobject(
            ctx,
            selector="Player",
            component="Rigidbody",
            timeout_seconds=5,
            poll_interval_seconds=0.05,
        )
        assert result["success"] is True
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_with_active_check(self, monkeypatch):
        """Waits until object is active."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        call_count = 0

        async def fake_send(send_fn, instance, command, params):
            nonlocal call_count
            if command == "find_gameobjects":
                call_count += 1
                return {"success": True, "data": {"instanceIds": [200]}}
            if command == "manage_gameobject":
                active = call_count >= 3
                return {"success": True, "data": {"activeSelf": active, "components": []}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_gameobject(
            ctx,
            selector="Player",
            active=True,
            timeout_seconds=5,
            poll_interval_seconds=0.05,
        )
        assert result["success"] is True
        assert call_count >= 3


# =========================================================================
# wait_for_console
# =========================================================================


class TestWaitForConsole:
    """Tests for wait_for_console tool."""

    @pytest.mark.asyncio
    async def test_no_text_returns_invalid_args(self):
        """Neither text nor text_gone specified."""
        from services.tools.wait_for import wait_for_console

        ctx = DummyContext()
        result = await wait_for_console(ctx)
        assert result["success"] is False
        assert result["error"] == "invalid_args"
        assert "at least one" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_both_text_and_text_gone_returns_invalid_args(self):
        """Specifying both text and text_gone is invalid."""
        from services.tools.wait_for import wait_for_console

        ctx = DummyContext()
        result = await wait_for_console(ctx, text="foo", text_gone="bar")
        assert result["success"] is False
        assert result["error"] == "invalid_args"
        assert "not both" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_empty_text_returns_invalid_args(self):
        """Empty text string is invalid."""
        from services.tools.wait_for import wait_for_console

        ctx = DummyContext()
        result = await wait_for_console(ctx, text="")
        assert result["success"] is False
        assert result["error"] == "invalid_args"

    @pytest.mark.asyncio
    async def test_success_in_pytest_mode(self):
        """In pytest mode, returns immediately."""
        from services.tools.wait_for import wait_for_console

        ctx = DummyContext()
        result = await wait_for_console(ctx, text="Hello")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_text_appears(self, monkeypatch):
        """Waits for a console message to appear."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        call_count = 0

        async def fake_send(send_fn, instance, command, params):
            nonlocal call_count
            call_count += 1
            if command == "read_console":
                if call_count < 3:
                    return {"success": True, "data": {"lines": []}}
                return {"success": True, "data": {"lines": [{"message": "Error: NullRef"}]}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_console(
            ctx, text="NullRef", timeout_seconds=5, poll_interval_seconds=0.05
        )
        assert result["success"] is True
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_text_gone(self, monkeypatch):
        """Waits for a console message to disappear."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        call_count = 0

        async def fake_send(send_fn, instance, command, params):
            nonlocal call_count
            call_count += 1
            if command == "read_console":
                if call_count < 3:
                    return {"success": True, "data": {"lines": [{"message": "warning: unused"}]}}
                return {"success": True, "data": {"lines": []}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_console(
            ctx, text_gone="unused", timeout_seconds=5, poll_interval_seconds=0.05
        )
        assert result["success"] is True
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_timeout_text_never_appears(self, monkeypatch):
        """Times out when expected text never appears."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        async def fake_send(send_fn, instance, command, params):
            if command == "read_console":
                return {"success": True, "data": {"lines": []}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_console(
            ctx, text="Expected Error", timeout_seconds=0.3, poll_interval_seconds=0.05
        )
        assert result["success"] is False
        assert result["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_with_level_filter(self, monkeypatch):
        """Level filter is passed through to read_console."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        from services.tools import wait_for as mod
        import transport.unity_transport as ut_mod

        captured_params = {}

        async def fake_send(send_fn, instance, command, params):
            if command == "read_console":
                captured_params.update(params)
                return {"success": True, "data": {"lines": [{"message": "err"}]}}
            return {"success": True, "data": {}}

        monkeypatch.setattr(ut_mod, "send_with_unity_instance", fake_send)

        ctx = DummyContext()
        result = await mod.wait_for_console(
            ctx, text="err", level="error", timeout_seconds=5, poll_interval_seconds=0.05
        )
        assert result["success"] is True
        assert captured_params.get("types") == ["error"]


# =========================================================================
# Timeout/interval clamping
# =========================================================================


class TestParameterClamping:
    """Tests for timeout and poll interval boundary clamping."""

    def test_clamp_helper(self):
        from services.tools.wait_for import _clamp

        assert _clamp(5.0, 0.0, 10.0) == 5.0
        assert _clamp(-1.0, 0.0, 10.0) == 0.0
        assert _clamp(100.0, 0.0, 10.0) == 10.0

    def test_parse_timeout_defaults(self):
        from services.tools.wait_for import _parse_timeout

        assert _parse_timeout(None) == 30.0
        assert _parse_timeout("invalid") == 30.0

    def test_parse_timeout_clamps(self):
        from services.tools.wait_for import _parse_timeout

        assert _parse_timeout(-5) == 0.0
        assert _parse_timeout(999) == 300.0
        assert _parse_timeout("15") == 15.0

    def test_parse_poll_interval_defaults(self):
        from services.tools.wait_for import _parse_poll_interval

        assert _parse_poll_interval(None) == 0.5
        assert _parse_poll_interval("bad") == 0.5

    def test_parse_poll_interval_clamps(self):
        from services.tools.wait_for import _parse_poll_interval

        assert _parse_poll_interval(0.01) == 0.1
        assert _parse_poll_interval(99) == 10.0
        assert _parse_poll_interval("1.0") == 1.0
