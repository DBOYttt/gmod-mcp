import asyncio
import base64
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional

from gr_mcp.pty_manager import PtyManager

_DEFAULT_CLIENT_DIR = str(Path.home() / ".steam/steam/steamapps/common/GarrysMod")
_DEFAULT_ARGS = "-windowed -w 1280 -h 720 +developer 1 -condebug +map gm_flatgrass"

_BRIDGE_LUA = """\
if not CLIENT then return end

local DIR = "gr_mcp"
local CMD_FILE = DIR .. "/cmd.txt"
local RESULT_FILE = DIR .. "/result.txt"
local BEAT_FILE = DIR .. "/heartbeat.txt"
local POLL_INTERVAL = 0.1

if not file.IsDir(DIR, "DATA") then
    file.CreateDir(DIR)
end

file.Write(DIR .. "/startup.txt", "v10:" .. tostring(CurTime()))

local _next = 0

hook.Add("Think", "GR_MCP_Bridge", function()
    local t = CurTime()
    if t < _next then return end
    _next = t + POLL_INTERVAL

    file.Write(BEAT_FILE, tostring(t))

    local raw = file.Read(CMD_FILE, "DATA")
    if not raw or #raw == 0 then return end
    file.Write(CMD_FILE, "")
    local cmd = string.Trim(raw)
    if cmd == "" then return end

    if string.sub(cmd, 1, 4) == "lua:" then
        local code = string.sub(cmd, 5)
        local ok, res = pcall(function()
            local fn, err = CompileString(code, "gr_mcp", false)
            if not fn then error(err) end
            return fn()
        end)
        local out = ok and ("ok:" .. tostring(res ~= nil and res or "")) or ("err:" .. tostring(res))
        file.Write(RESULT_FILE, out)
    elseif cmd == "screenshot" then
        hook.Add("PostRender", "GR_MCP_Screenshot", function()
            hook.Remove("PostRender", "GR_MCP_Screenshot")
            local w, h = ScrW(), ScrH()
            local data = render.Capture({ x = 0, y = 0, w = w, h = h, format = "png" })
            if data then
                file.Write(DIR .. "/screenshot.png", data)
                file.Write(RESULT_FILE, "screenshot:" .. w .. ":" .. h)
            else
                file.Write(RESULT_FILE, "err:render.Capture returned nil")
            end
        end)
    else
        local parts = string.Explode(" ", cmd, false)
        RunConsoleCommand(table.remove(parts, 1), unpack(parts))
        file.Write(RESULT_FILE, "ok:")
    end
end)

print("[GR MCP Bridge] v10 loaded")
"""


class ClientManager:
    def __init__(self) -> None:
        client_dir = os.environ.get("GMOD_CLIENT_DIR", _DEFAULT_CLIENT_DIR)
        self._data_dir = Path(client_dir) / "garrysmod" / "data" / "gr_mcp"
        self._cmd_file = self._data_dir / "cmd.txt"
        self._result_file = self._data_dir / "result.txt"
        self._heartbeat_file = self._data_dir / "heartbeat.txt"
        self._screenshot_file = self._data_dir / "screenshot.png"
        args = shlex.split(os.environ.get("GMOD_CLIENT_ARGS", _DEFAULT_ARGS))
        self.window_name = os.environ.get("GMOD_CLIENT_WINDOW", "Garry's Mod")

        lib_path = ":".join([
            f"{client_dir}/bin/linux64",
            f"{client_dir}/bin",
            f"{client_dir}/garrysmod/bin",
        ])
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        full_lib_path = lib_path + (":" + existing if existing else "")
        env = {**os.environ, "LD_LIBRARY_PATH": full_lib_path,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
               "LOCPATH": "/usr/lib/locale",
               "LD_PRELOAD": "/home/diboy/.local/lib/locale_fix.so"}
        command = [f"{client_dir}/hl2_linux", "-game", "garrysmod"] + args

        self._pty = PtyManager(command, client_dir, env=env)
        self._install_bridge(Path(client_dir))

    def _install_bridge(self, client_dir: Path) -> None:
        autorun_dir = client_dir / "garrysmod" / "lua" / "autorun"
        autorun_dir.mkdir(parents=True, exist_ok=True)
        (autorun_dir / "gr_mcp_bridge.lua").write_text(_BRIDGE_LUA)

    async def start(self) -> dict:
        result = await self._pty.start()
        result["window_id"] = await asyncio.to_thread(self._window_id)
        # Dismiss the locale Warning dialog that appears during map load.
        # The dialog is always centered in the 1280x720 window; OK button is at
        # roughly (514, 541) within the client area.
        asyncio.ensure_future(self._dismiss_locale_warning())
        return result

    async def _dismiss_locale_warning(self) -> None:
        """Wait for the GMod window to appear, then click away the locale Warning dialog."""
        display = os.environ.get("DISPLAY", ":0")
        # Wait up to 60s for the window to appear
        for _ in range(60):
            await asyncio.sleep(1)
            if self._window_id():
                break
        else:
            return
        # Dialog appears ~3-5s after the window shows up (during map load)
        await asyncio.sleep(4)
        wid = self._window_id()
        if not wid:
            return
        try:
            geo = subprocess.check_output(
                ["xdotool", "getwindowgeometry", wid],
                env={**os.environ, "DISPLAY": display},
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode()
            for line in geo.splitlines():
                if "Position:" in line:
                    parts = line.split(":")[1].strip().split(",")
                    wx = int(parts[0].strip())
                    wy = int(parts[1].split()[0].strip())
                    # OK button is at ~(514, 541) within the 1280x720 window
                    # (confirmed by earlier manual click that succeeded)
                    sx, sy = wx + 514, wy + 541
                    subprocess.run(
                        ["xdotool", "mousemove", str(sx), str(sy), "click", "1"],
                        env={**os.environ, "DISPLAY": display},
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    return
        except Exception:
            pass

    async def stop(self) -> dict:
        return await self._pty.stop()

    def status(self) -> dict:
        result = self._pty.status()
        result["window_id"] = self._window_id()
        return result

    def _delete_file(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def exec_command(self, command: str) -> dict:
        if not self._pty.is_running():
            return {"ok": False, "error": "client not running"}
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._delete_file(self._result_file)
            self._cmd_file.write_text(command)
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    async def lua_run(self, code: str, timeout: float = 5.0) -> dict:
        if not self._pty.is_running():
            return {"output": "", "timed_out": False, "error": "client not running"}
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            # Delete result so GMod creates it fresh (GMod can't overwrite Python-owned files)
            self._delete_file(self._result_file)
            self._cmd_file.write_text("lua:" + code)
        except OSError as e:
            return {"output": "", "timed_out": False, "error": str(e)}

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            try:
                result = self._result_file.read_text()
            except OSError:
                continue
            if not result:
                continue
            # Got result — delete cmd so GMod doesn't re-process it
            self._delete_file(self._cmd_file)
            if result.startswith("ok:"):
                return {"output": result[3:], "timed_out": False}
            if result.startswith("err:"):
                return {"output": "", "timed_out": False, "error": result[4:]}
        # Timeout — delete cmd to cancel
        self._delete_file(self._cmd_file)
        return {"output": "", "timed_out": True}

    async def screenshot_native(self, timeout: float = 5.0) -> dict:
        if not self._pty.is_running():
            return {"ok": False, "error": "client not running"}
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._delete_file(self._result_file)
            self._delete_file(self._screenshot_file)
            self._cmd_file.write_text("screenshot")
        except OSError as e:
            return {"ok": False, "error": str(e)}

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            try:
                result = self._result_file.read_text()
            except OSError:
                continue
            if not result:
                continue
            if result.startswith("screenshot:"):
                self._delete_file(self._cmd_file)
                try:
                    parts = result.split(":")
                    w = int(parts[1]) if len(parts) > 1 else 0
                    h = int(parts[2]) if len(parts) > 2 else 0
                    data = self._screenshot_file.read_bytes()
                    return {
                        "path": str(self._screenshot_file),
                        "base64_png": base64.b64encode(data).decode(),
                        "width": w,
                        "height": h,
                    }
                except (OSError, ValueError) as e:
                    return {"ok": False, "error": str(e)}
            if result.startswith("err:"):
                self._delete_file(self._cmd_file)
                return {"ok": False, "error": result[4:]}
        self._delete_file(self._cmd_file)
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
