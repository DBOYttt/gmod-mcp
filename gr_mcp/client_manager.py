import os
import subprocess
from pathlib import Path
from typing import Optional

from gr_mcp.lua_runner import LuaRunner
from gr_mcp.pty_manager import PtyManager

_DEFAULT_CLIENT_DIR = str(Path.home() / ".steam/steam/steamapps/common/GarrysMod")
_DEFAULT_ARGS = "-windowed -w 1280 -h 720 +connect localhost +developer 1 -condebug"


class ClientManager:
    def __init__(self) -> None:
        client_dir = os.environ.get("GMOD_CLIENT_DIR", _DEFAULT_CLIENT_DIR)
        args = os.environ.get("GMOD_CLIENT_ARGS", _DEFAULT_ARGS).split()
        self.window_name = os.environ.get("GMOD_CLIENT_WINDOW", "Garry's Mod")

        lib_path = ":".join([
            f"{client_dir}/bin/linux64",
            f"{client_dir}/bin",
            f"{client_dir}/garrysmod/bin",
        ])
        env = {**os.environ, "LD_LIBRARY_PATH": lib_path}
        command = [f"{client_dir}/hl2_linux", "-game", "garrysmod"] + args

        self._pty = PtyManager(command, client_dir, env=env)
        self._lua = LuaRunner(self._pty)

    async def start(self) -> dict:
        result = await self._pty.start()
        result["window_id"] = self._window_id()
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
            return out.split("\n")[0] if out else None
        except Exception:
            return None
