import asyncio
import pytest
from gr_mcp.pty_manager import PtyManager


async def _wait_for_output(mgr, text, timeout=2.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = mgr.read_output(since_line=0, limit=100)
        if any(text in l["text"] for l in result["lines"]):
            return result
        await asyncio.sleep(0.05)
    pytest.fail(f"Timed out waiting for '{text}' in output")


@pytest.fixture
async def echo_mgr(tmp_path):
    mgr = PtyManager(
        ["python3", "-c",
         "import sys, time; print('hello'); print('world'); sys.stdout.flush(); time.sleep(60)"],
        str(tmp_path),
    )
    yield mgr
    await mgr.stop()


def test_status_when_stopped():
    mgr = PtyManager(["echo", "hi"], "/tmp")
    s = mgr.status()
    assert s["running"] is False
    assert s["pid"] is None
    assert s["uptime_s"] == 0


async def test_start_returns_running(echo_mgr):
    result = await echo_mgr.start()
    assert result["running"] is True
    assert isinstance(result["pid"], int)


async def test_stop_returns_ok(echo_mgr):
    await echo_mgr.start()
    result = await echo_mgr.stop()
    assert result["ok"] is True
    assert not echo_mgr.is_running()


async def test_ring_buffer_captures_output(echo_mgr):
    await echo_mgr.start()
    result = await _wait_for_output(echo_mgr, "hello")
    texts = [l["text"] for l in result["lines"]]
    assert any("hello" in t for t in texts)
    assert any("world" in t for t in texts)


async def test_read_output_since_line_pagination(echo_mgr):
    await echo_mgr.start()
    await _wait_for_output(echo_mgr, "world")
    first = echo_mgr.read_output(since_line=0, limit=50)
    assert first["lines"]
    next_line = first["next_line"]
    second = echo_mgr.read_output(since_line=next_line, limit=50)
    assert second["lines"] == []


async def test_read_output_pattern_filter(echo_mgr):
    await echo_mgr.start()
    await _wait_for_output(echo_mgr, "world")
    result = echo_mgr.read_output(since_line=0, pattern="world")
    texts = [l["text"] for l in result["lines"]]
    assert texts
    assert all("world" in t for t in texts)


async def test_exec_command_ok(echo_mgr):
    await echo_mgr.start()
    await _wait_for_output(echo_mgr, "hello")
    result = echo_mgr.exec_command("echo testcmd")
    assert result["ok"] is True


def test_exec_command_when_stopped():
    mgr = PtyManager(["echo", "hi"], "/tmp")
    result = mgr.exec_command("anything")
    assert result["ok"] is False
    assert "error" in result


async def test_double_start_is_idempotent(echo_mgr):
    r1 = await echo_mgr.start()
    r2 = await echo_mgr.start()
    assert r1["pid"] == r2["pid"]
