import asyncio
import re
import pytest
from gr_mcp.lua_runner import LuaRunner


class MockPty:
    def __init__(self):
        self._ring: list[dict] = []
        self._n = 0
        self.last_cmd: str = ""

    def exec_command(self, cmd: str) -> dict:
        self.last_cmd = cmd
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


async def test_captures_output_between_tokens():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        m = re.search(r'\[\[GR_([0-9a-f]+)\]\]', pty.last_cmd)
        tok = m.group(1)
        pty.inject(f"[[GR_{tok}]]")
        pty.inject("42")
        pty.inject(f"[[GR_{tok}_END]]")

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
        m = re.search(r'\[\[GR_([0-9a-f]+)\]\]', pty.last_cmd)
        tok = m.group(1)
        pty.inject(f"[[GR_{tok}]]")
        pty.inject("line1")
        pty.inject("line2")
        pty.inject(f"[[GR_{tok}_END]]")

    task = asyncio.create_task(_inject())
    result = await runner.run("print('line1'); print('line2')", timeout=2.0)
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
        m = re.search(r'\[\[GR_([0-9a-f]+)\]\]', pty.last_cmd)
        tok = m.group(1)
        pty.inject("unrelated server noise")
        pty.inject(f"[[GR_{tok}]]")
        pty.inject("result")
        pty.inject(f"[[GR_{tok}_END]]")

    task = asyncio.create_task(_inject())
    result = await runner.run("print('result')", timeout=2.0)
    await task

    assert result["output"] == "result"


async def test_code_with_newlines_is_sanitized():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        m = re.search(r'\[\[GR_([0-9a-f]+)\]\]', pty.last_cmd)
        tok = m.group(1)
        pty.inject(f"[[GR_{tok}]]")
        pty.inject("ok")
        pty.inject(f"[[GR_{tok}_END]]")

    task = asyncio.create_task(_inject())
    result = await runner.run("print('first')\nprint('second')", timeout=2.0)
    await task

    # Verify newlines were replaced — command must be single-line
    assert "\n" not in pty.last_cmd
    assert result["timed_out"] is False


async def test_code_with_quotes_works():
    pty = MockPty()
    runner = LuaRunner(pty)

    async def _inject():
        await asyncio.sleep(0.05)
        m = re.search(r'\[\[GR_([0-9a-f]+)\]\]', pty.last_cmd)
        tok = m.group(1)
        pty.inject(f"[[GR_{tok}]]")
        pty.inject("hello")
        pty.inject(f"[[GR_{tok}_END]]")

    task = asyncio.create_task(_inject())
    result = await runner.run('print("hello")', timeout=2.0)
    await task

    assert result["timed_out"] is False
    assert result["output"] == "hello"
