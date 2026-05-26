import asyncio
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from gr_mcp.client_manager import ClientManager
from gr_mcp.file_watcher import FileWatcher
from gr_mcp.input_controller import InputController
from gr_mcp.lua_runner import LuaRunner
from gr_mcp.pty_manager import PtyManager
from gr_mcp.screenshot import Screenshot

# Configurable via env vars; defaults target the sibling gmod repo.
_GMOD_ROOT = Path(
    os.environ.get("GMOD_ROOT", str(Path.home() / "Documents/projects/gmod"))
)
_SRCDS_CMD = os.environ.get("GMOD_SRCDS_CMD", "bash server/start.sh").split()
_SRCDS_CWD = str(_GMOD_ROOT)
_SCHEMA_PATH = str(_GMOD_ROOT / "garrysmod/schema")

_pty = PtyManager(_SRCDS_CMD, _SRCDS_CWD)
_lua = LuaRunner(_pty)
_watcher = FileWatcher(_SCHEMA_PATH)

_client = ClientManager()
_input = InputController(_client.window_name)
_screen = Screenshot(_client.window_name)

mcp = FastMCP("gmod")


@mcp.tool()
async def gr_server_start() -> dict:
    """Start the GMod dedicated server. Returns {running, pid, uptime_s}."""
    result = await _pty.start()
    if result["running"] and not _watcher._observer.is_alive():
        _watcher.start()
    return result


@mcp.tool()
async def gr_server_stop() -> dict:
    """Stop the GMod dedicated server. The file watcher keeps running. Returns {ok}."""
    return await _pty.stop()


@mcp.tool()
async def gr_server_restart() -> dict:
    """Restart the GMod dedicated server. Clears dirty-file list. Returns {running, pid, uptime_s}."""
    await _pty.stop()
    _watcher.clear()
    return await _pty.start()


@mcp.tool()
def gr_server_status() -> dict:
    """
    Get server status.
    Returns {running, pid, uptime_s, dirty_files}.
    dirty_files lists Lua files changed since the last restart (persists across stop/start).
    Call gr_server_restart to clear dirty_files.
    """
    status = _pty.status()
    status["dirty_files"] = _watcher.dirty_files
    return status


@mcp.tool()
def gr_server_exec(command: str) -> dict:
    """
    Send a raw console command to the GMod server (fire-and-forget).
    Output appears in the ring buffer; read it with gr_read_output.
    Returns {ok}.
    """
    return _pty.exec_command(command)


@mcp.tool()
async def gr_lua_run(code: str, timeout: float = 5.0) -> dict:
    """
    Execute Lua on the server and return only its output.
    Uses token-bracketing so unrelated server noise is excluded.
    Returns {output, timed_out} or {output, timed_out, error}.
    """
    return await _lua.run(code, timeout)


@mcp.tool()
def gr_read_output(
    since_line: int = 0,
    limit: int = 200,
    pattern: str = "",
) -> dict:
    """
    Read server console output from the ring buffer (last 2000 lines).
    since_line: return only lines with n > since_line (use next_line from previous call to paginate).
    limit: max lines to return.
    pattern: optional Python regex to filter lines.
    Returns {lines: [{n, ts, text}], next_line}.
    """
    return _pty.read_output(since_line, limit, pattern or None)


@mcp.tool()
async def gr_client_start() -> dict:
    """
    Launch the GMod client (hl2_linux, bypassing Steam).
    Reads GMOD_CLIENT_DIR, GMOD_CLIENT_ARGS, GMOD_CLIENT_WINDOW from env.
    Returns {running, pid, uptime_s, window_id}.
    """
    return await _client.start()


@mcp.tool()
async def gr_client_stop() -> dict:
    """Stop the GMod client. Returns {ok}."""
    return await _client.stop()


@mcp.tool()
def gr_client_status() -> dict:
    """
    Get GMod client status.
    Returns {running, pid, uptime_s, window_id}.
    window_id is the X11 window ID (string) or null if the window is not visible yet.
    """
    return _client.status()


@mcp.tool()
def gr_client_exec(command: str) -> dict:
    """
    Send a raw console command to the GMod client (fire-and-forget).
    Output appears in the ring buffer; read it with gr_client_read_output.
    Returns {ok}.
    """
    return _client.exec_command(command)


@mcp.tool()
async def gr_client_lua_run(code: str, timeout: float = 5.0) -> dict:
    """
    Execute Lua on the GMod client and return only its output.
    Uses the same token-bracketing as gr_lua_run (server-side).
    Returns {output, timed_out} or {output, timed_out, error}.
    """
    return await _client.lua_run(code, timeout)


@mcp.tool()
def gr_client_read_output(
    since_line: int = 0,
    limit: int = 200,
    pattern: str = "",
) -> dict:
    """
    Read GMod client console output from the ring buffer (last 2000 lines).
    since_line: return only lines with n > since_line.
    limit: max lines to return.
    pattern: optional Python regex to filter lines.
    Returns {lines: [{n, ts, text}], next_line}.
    """
    return _client.read_output(since_line, limit, pattern or None)


@mcp.tool()
async def gr_client_screenshot(path: str = "") -> dict:
    """
    Capture the GMod client window.
    Tries the game's native JPEG screenshot first (works on Wayland),
    then falls back to X11 window capture.
    path: optional file path for X11 fallback; ignored for native capture.
    Returns {path, base64_jpeg, width, height} or {path, base64_png, width, height}.
    """
    result = await _client.screenshot_native()
    if result.get("ok") is not False:
        return result
    return await asyncio.to_thread(_screen.capture, path)


@mcp.tool()
async def gr_client_click(x: int, y: int) -> dict:
    """
    Click at screen-absolute coordinates (x, y) in the GMod client window.
    Focuses the window with xdotool before clicking.
    Returns {ok} or {ok, error}.
    """
    return await asyncio.to_thread(_input.click, x, y)


@mcp.tool()
async def gr_client_key(key: str) -> dict:
    """
    Send a keypress to the GMod client window.
    key: xdotool key name — e.g. "Return", "Escape", "grave" (opens console), "F1".
    Returns {ok} or {ok, error}.
    """
    return await asyncio.to_thread(_input.key, key)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
