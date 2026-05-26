import asyncio
import base64
import os
import shlex
import struct
import subprocess
import time
from pathlib import Path
from typing import Optional

from gr_mcp.lua_runner import LuaRunner
from gr_mcp.pty_manager import PtyManager

_DEFAULT_CLIENT_DIR = str(Path.home() / ".steam/steam/steamapps/common/GarrysMod")


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Parse width/height from a JPEG by scanning SOF markers."""
    i = 2  # skip FF D8
    while i + 3 < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        # SOF markers that carry image dimensions
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = struct.unpack(">H", data[i + 5: i + 7])[0]
            w = struct.unpack(">H", data[i + 7: i + 9])[0]
            return w, h
        length = struct.unpack(">H", data[i + 2: i + 4])[0]
        i += 2 + length
    return 0, 0
_DEFAULT_ARGS = "-windowed -w 1280 -h 720 +developer 1 -condebug"


class ClientManager:
    def __init__(self) -> None:
        client_dir = os.environ.get("GMOD_CLIENT_DIR", _DEFAULT_CLIENT_DIR)
        self._screenshots_dir = Path(client_dir) / "garrysmod" / "screenshots"
        args = shlex.split(os.environ.get("GMOD_CLIENT_ARGS", _DEFAULT_ARGS))
        self.window_name = os.environ.get("GMOD_CLIENT_WINDOW", "Garry's Mod")

        lib_path = ":".join([
            f"{client_dir}/bin/linux64",
            f"{client_dir}/bin",
            f"{client_dir}/garrysmod/bin",
        ])
        # Prepend GMod paths to any existing LD_LIBRARY_PATH (e.g. Steam runtime
        # paths set via env in .mcp.json) so legacy 32-bit libs are found.
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        full_lib_path = lib_path + (":" + existing if existing else "")
        env = {**os.environ, "LD_LIBRARY_PATH": full_lib_path}
        command = [f"{client_dir}/hl2_linux", "-game", "garrysmod"] + args

        self._pty = PtyManager(command, client_dir, env=env)
        self._lua = LuaRunner(self._pty)

    async def start(self) -> dict:
        result = await self._pty.start()
        result["window_id"] = await asyncio.to_thread(self._window_id)
        return result

    async def stop(self) -> dict:
        return await self._pty.stop()

    def status(self) -> dict:
        result = self._pty.status()
        result["window_id"] = self._window_id()
        return result

    def exec_command(self, command: str) -> dict:
        return self._pty.exec_command(command)

    async def lua_run(self, code: str, timeout: float = 5.0) -> dict:
        return await self._lua.run(code, timeout)

    async def screenshot_native(self, timeout: float = 5.0) -> dict:
        """Ask GMod to save a JPEG screenshot, then read and return it."""
        if not self._pty.is_running():
            return {"ok": False, "error": "client not running"}
        before = {p.name for p in self._screenshots_dir.glob("*.jpg")} if self._screenshots_dir.exists() else set()
        self._pty.exec_command("jpeg")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            current = {p for p in self._screenshots_dir.glob("*.jpg") if p.name not in before}
            if current:
                path = max(current, key=lambda p: p.stat().st_mtime)
                data = path.read_bytes()
                w, h = _jpeg_dimensions(data)
                return {
                    "path": str(path),
                    "base64_jpeg": base64.b64encode(data).decode(),
                    "width": w,
                    "height": h,
                }
        return {"ok": False, "error": "screenshot not saved within timeout"}

    def read_output(
        self,
        since_line: int = 0,
        limit: int = 200,
        pattern: Optional[str] = None,
    ) -> dict:
        return self._pty.read_output(since_line, limit, pattern)

    def _window_id(self) -> Optional[str]:
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--name", self.window_name],
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip()
            return out.split("\n")[0].strip() or None
        except Exception:
            return None
