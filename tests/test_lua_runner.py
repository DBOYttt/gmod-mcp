import asyncio
import re
import pytest
from gr_mcp.lua_runner import LuaRunner


class MockPty:
    def __init__(self):
        self._ring: list[dict] = []
        self._n = 0
        self.cmds: list[str] = []

    def exec_command(self, cmd: str) -> dict:
        self.cmds.append(cmd)
        return {"ok": True}

    def last_line_n(self) -> int:
        return self._ring[-1]["n"] if self._ring else 0

    def lines_since(self, n: int) -> list[dict]:
        return [l for l in self._ring if l["n"] > n]

    def inject(self, text: str) -> None:
        self._n += 1
        self._ring.append({"n": self._n, "ts": 0.0, "text": text})

    def is_running(self) -> bool:
        return True

    def find_token(self) -> str:
        """Extract the hex token from the start-marker command."""
        for cmd in self.cmds:
            m = re.search(r'GR_([0-9a-f]+)_START', cmd)
            if m:
                return m.group(1)
        return ""


async def test_captures_output_between_tokens():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        tok = pty.find_token()
        pty.inject(f"GR_{tok}_START")
        pty.inject("42")
        pty.inject(f"GR_{tok}_END")

    task = asyncio.create_task(_inject())
    result = await runner.run("print(6*7)", timeout=2.0)
    await task

    assert result["output"] == "42"
    assert result["timed_out"] is False


async def test_captures_multiline_output():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        tok = pty.find_token()
        pty.inject(f"GR_{tok}_START")
        pty.inject("line1")
        pty.inject("line2")
        pty.inject(f"GR_{tok}_END")

    task = asyncio.create_task(_inject())
    result = await runner.run("print('line1')\nprint('line2')", timeout=2.0)
    await task

    assert result["output"] == "line1\nline2"
    assert result["timed_out"] is False


async def test_timeout_when_no_output():
    pty = MockPty()
    runner = LuaRunner(pty)
    result = await runner.run("print('never')", timeout=0.15)
    assert result["timed_out"] is True
    assert result["output"] == ""


async def test_error_when_server_not_running():
    class StoppedPty(MockPty):
        def exec_command(self, cmd):
            return {"ok": False, "error": "Server not running"}

        def is_running(self):
            return False

    runner = LuaRunner(StoppedPty())
    result = await runner.run("print(1)", timeout=1.0)
    assert "error" in result


async def test_noise_before_start_token_is_ignored():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        tok = pty.find_token()
        pty.inject("unrelated server noise")
        pty.inject(f"GR_{tok}_START")
        pty.inject("result")
        pty.inject(f"GR_{tok}_END")

    task = asyncio.create_task(_inject())
    result = await runner.run("print('result')", timeout=2.0)
    await task

    assert result["output"] == "result"


async def test_code_with_newlines_is_sanitized():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        tok = pty.find_token()
        pty.inject(f"GR_{tok}_START")
        pty.inject("ok")
        pty.inject(f"GR_{tok}_END")

    task = asyncio.create_task(_inject())
    result = await runner.run("print('first')\nprint('second')", timeout=2.0)
    await task

    # Newlines collapsed to spaces — no command should have a literal newline
    assert all("\n" not in cmd for cmd in pty.cmds)
    assert result["timed_out"] is False


async def test_code_with_quotes_works():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        tok = pty.find_token()
        pty.inject(f"GR_{tok}_START")
        pty.inject("hello")
        pty.inject(f"GR_{tok}_END")

    task = asyncio.create_task(_inject())
    result = await runner.run('print("hello")', timeout=2.0)
    await task

    assert result["timed_out"] is False
    assert result["output"] == "hello"


async def test_three_separate_commands_sent():
    """Verify runner sends start-token, code, end-token as separate lua_run calls."""
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        tok = pty.find_token()
        pty.inject(f"GR_{tok}_START")
        pty.inject(f"GR_{tok}_END")

    task = asyncio.create_task(_inject())
    await runner.run("print(1)", timeout=2.0)
    await task

    assert len(pty.cmds) == 3
    assert "GR_" in pty.cmds[0] and "_START" in pty.cmds[0]
    assert pty.cmds[1].startswith("lua_run ")
    assert "GR_" in pty.cmds[2] and "_END" in pty.cmds[2]
