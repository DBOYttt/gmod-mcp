import asyncio
import fcntl
import os
import pty
import re
import signal
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class _Line:
    n: int
    ts: float
    text: str


class PtyManager:
    RING_SIZE = 2000

    def __init__(self, command: list[str], cwd: str, env: Optional[dict] = None) -> None:
        self._command = command
        self._cwd = cwd
        self._env = env
        self._proc: Optional[subprocess.Popen] = None
        self._master_fd: Optional[int] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._start_time: Optional[float] = None
        self._ring: deque[_Line] = deque(maxlen=self.RING_SIZE)
        self._line_counter = 0
        self._read_buf = b""

    async def start(self) -> dict:
        if self._proc is not None and self._proc.poll() is None:
            return self.status()

        master_fd, slave_fd = pty.openpty()
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                cwd=self._cwd,
                env=self._env,
                preexec_fn=os.setsid,
            )
        finally:
            os.close(slave_fd)

        # Fix 1: set O_NONBLOCK on master_fd so add_reader doesn't stall the loop
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._master_fd = master_fd
        self._start_time = time.time()
        self._ring.clear()
        self._line_counter = 0
        self._read_buf = b""

        loop = asyncio.get_running_loop()
        # Fix 2: store loop reference for use in _cleanup()
        self._loop = loop
        loop.add_reader(master_fd, self._on_readable)
        return self.status()

    def _on_readable(self) -> None:
        try:
            data = os.read(self._master_fd, 4096)
        except OSError:
            self._cleanup()
            return
        self._read_buf += data
        while b"\n" in self._read_buf:
            line_bytes, self._read_buf = self._read_buf.split(b"\n", 1)
            text = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
            self._line_counter += 1
            # Fix 5: deque with maxlen handles overflow automatically
            self._ring.append(_Line(n=self._line_counter, ts=time.time(), text=text))

    def _cleanup(self) -> None:
        if self._master_fd is not None:
            # Fix 2: use stored loop reference instead of get_event_loop()
            if self._loop is not None:
                try:
                    self._loop.remove_reader(self._master_fd)
                except Exception:
                    pass
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
            self._loop = None
        self._proc = None

    # Fix 3: async stop() using asyncio.to_thread for blocking wait
    async def stop(self) -> dict:
        if self._proc is None:
            return {"ok": True}
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._proc.wait),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except Exception:
                pass
            await asyncio.to_thread(self._proc.wait)
        self._cleanup()
        return {"ok": True}

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "pid": self._proc.pid if self._proc else None,
            "uptime_s": int(time.time() - self._start_time)
            if self._start_time and self.is_running()
            else 0,
        }

    def exec_command(self, command: str) -> dict:
        if self._master_fd is None:
            return {"ok": False, "error": "Server not running"}
        try:
            os.write(self._master_fd, (command + "\n").encode())
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def last_line_n(self) -> int:
        return self._ring[-1].n if self._ring else 0

    def lines_since(self, n: int) -> list[dict]:
        return [{"n": l.n, "ts": l.ts, "text": l.text} for l in self._ring if l.n > n]

    def read_output(
        self,
        since_line: int = 0,
        limit: int = 200,
        pattern: Optional[str] = None,
    ) -> dict:
        lines = [l for l in self._ring if l.n > since_line]
        if pattern:
            # Fix 6: return error dict on invalid regex instead of silently ignoring
            try:
                rx = re.compile(pattern)
                lines = [l for l in lines if rx.search(l.text)]
            except re.error as e:
                return {"lines": [], "next_line": since_line, "error": f"Invalid regex: {e}"}
        lines = lines[:limit]
        next_line = lines[-1].n + 1 if lines else since_line
        return {
            "lines": [{"n": l.n, "ts": l.ts, "text": l.text} for l in lines],
            "next_line": next_line,
        }
