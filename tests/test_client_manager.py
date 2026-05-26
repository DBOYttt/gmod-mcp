import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gr_mcp.lua_runner import LuaRunner


class FakePty:
    """Minimal PtyManager stand-in — no subprocess."""

    async def start(self):
        return {"running": True, "pid": 99, "uptime_s": 0}

    async def stop(self):
        return {"ok": True}

    def status(self):
        return {"running": True, "pid": 99, "uptime_s": 5}

    def exec_command(self, cmd):
        return {"ok": True}

    def read_output(self, since_line=0, limit=200, pattern=None):
        return {"lines": [], "next_line": 0}

    def is_running(self):
        return True

    def last_line_n(self):
        return 0

    def lines_since(self, n):
        return []


@pytest.fixture
def manager():
    from gr_mcp.client_manager import ClientManager
    m = ClientManager()
    # Replace internal pty and lua with fakes so no subprocess is spawned.
    fake = FakePty()
    m._pty = fake
    m._lua = LuaRunner(fake)
    return m


async def test_start_includes_window_id(manager):
    with patch("subprocess.check_output", return_value=b"12345\n"):
        result = await manager.start()
    assert result["running"] is True
    assert result["window_id"] == "12345"


async def test_start_window_id_none_when_xdotool_fails(manager):
    with patch("subprocess.check_output", side_effect=Exception("not found")):
        result = await manager.start()
    assert result["window_id"] is None


async def test_stop_returns_ok(manager):
    result = await manager.stop()
    assert result["ok"] is True


def test_status_includes_window_id(manager):
    with patch("subprocess.check_output", return_value=b"99\n"):
        result = manager.status()
    assert result["running"] is True
    assert result["window_id"] == "99"


def test_exec_command_delegates(manager):
    result = manager.exec_command("status")
    assert result["ok"] is True


def test_read_output_delegates(manager):
    result = manager.read_output()
    assert "lines" in result
    assert "next_line" in result


async def test_lua_run_delegates(manager):
    manager._lua = MagicMock()
    manager._lua.run = AsyncMock(return_value={"output": "42", "timed_out": False})
    result = await manager.lua_run("print(6*7)")
    assert result["output"] == "42"
    manager._lua.run.assert_called_once_with("print(6*7)", 5.0)
