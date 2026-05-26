import asyncio
import secrets
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gr_mcp.pty_manager import PtyManager


class LuaRunner:
    POLL_INTERVAL = 0.05  # seconds between ring buffer scans

    def __init__(self, pty: "PtyManager") -> None:
        self._pty = pty

    async def run(self, code: str, timeout: float = 5.0) -> dict:
        if not self._pty.is_running():
            return {"output": "", "timed_out": False, "error": "Server not running"}

        token = secrets.token_hex(4)
        start_tok = f"[[GR_{token}]]"
        end_tok = f"[[GR_{token}_END]]"

        cmd = f'lua_run print("{start_tok}"); {code}; print("{end_tok}")'
        result = self._pty.exec_command(cmd)
        if not result["ok"]:
            return {"output": "", "timed_out": False, "error": result.get("error", "exec failed")}

        deadline = time.monotonic() + timeout
        seen_start = False
        captured: list[str] = []
        last_n = self._pty.last_line_n()

        while time.monotonic() < deadline:
            for line in self._pty.lines_since(last_n):
                last_n = line["n"]
                text = line["text"]
                if start_tok in text:
                    seen_start = True
                    continue
                if seen_start:
                    if end_tok in text:
                        return {"output": "\n".join(captured), "timed_out": False}
                    captured.append(text)
            await asyncio.sleep(self.POLL_INTERVAL)

        return {"output": "\n".join(captured), "timed_out": True}
