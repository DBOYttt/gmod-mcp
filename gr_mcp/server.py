import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from gr_mcp.file_watcher import FileWatcher
from gr_mcp.lua_runner import LuaRunner
from gr_mcp.pty_manager import PtyManager

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
