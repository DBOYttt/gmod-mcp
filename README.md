# gmod-mcp

MCP server for controlling a Garry's Mod dedicated server and client from Claude Code. Exposes tools for starting/stopping the server, running Lua, capturing screenshots, and sending input — all without touching Steam.

## Requirements

- Linux (x86-64)
- Python ≥ 3.11
- `xdotool` — for window focus and key/click input
- `gcc` with 32-bit support (`glibc-devel.i686` on Fedora, `gcc-multilib` on Debian/Ubuntu) — to compile the locale shim
- GMod dedicated server and/or a local GMod client install

## Installation

```bash
pip install -e .
```

## Configuration

All settings are passed as environment variables (set them in your `.mcp.json`):

| Variable | Default | Description |
|----------|---------|-------------|
| `GMOD_ROOT` | `~/Documents/projects/gmod` | Root of the GMod schema repo (used by server tools) |
| `GMOD_SRCDS_CMD` | `bash server/start.sh` | Command to start the dedicated server |
| `GMOD_CLIENT_DIR` | `~/.steam/steam/steamapps/common/GarrysMod` | Path to GMod client installation |
| `GMOD_CLIENT_ARGS` | `-windowed -w 1280 -h 720 +developer 1 -condebug +map gm_flatgrass` | Launch args for the client |
| `GMOD_CLIENT_WINDOW` | `Garry's Mod` | X11 window title used by input/screenshot tools |
| `LANG` / `LC_ALL` | — | Set to `en_US.UTF-8` to enable UTF-8 locale |
| `LOCPATH` | — | Set to `/usr/lib/locale` for directory-based locale lookup |
| `LD_PRELOAD` | — | Set to `~/.local/lib/locale_fix.so` (see Locale Fix below) |

### Example `.mcp.json`

```json
{
  "mcpServers": {
    "gmod": {
      "command": "/usr/bin/python",
      "args": ["-m", "gr_mcp.server"],
      "cwd": "/path/to/gmod-mcp",
      "env": {
        "GMOD_CLIENT_DIR": "/path/to/SteamLibrary/steamapps/common/GarrysMod",
        "DISPLAY": ":0",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "LOCPATH": "/usr/lib/locale",
        "LD_PRELOAD": "/home/<user>/.local/lib/locale_fix.so"
      }
    }
  }
}
```

## Locale Fix

The Source engine shows a *"SetLocale('en_US.UTF-8') failed"* warning on Linux because glibc normalises the locale name to `en_US.utf8` (no hyphen) while the engine expects the hyphenated form.

Build the 32-bit LD_PRELOAD shim once:

```bash
mkdir -p ~/.local/lib
gcc -m32 -shared -fPIC -O2 -o ~/.local/lib/locale_fix.so server/locale_fix.c -ldl
```

Then set `LD_PRELOAD=~/.local/lib/locale_fix.so` in your env. The shim forces UTF-8 locale at load time and patches the return value so the engine's check passes.

> If you're using the [galaxies-reborn](https://github.com/DBOYttt/galaxies-reborn) schema repo, `bash server/install_client.sh` builds this automatically.

## Tools

### Dedicated server

| Tool | Description |
|------|-------------|
| `gr_server_start` | Start the server |
| `gr_server_stop` | Stop the server |
| `gr_server_restart` | Restart and clear dirty-file list |
| `gr_server_status` | `{running, pid, uptime_s, dirty_files}` |
| `gr_server_exec` | Fire-and-forget console command |
| `gr_lua_run` | Execute Lua, return output |
| `gr_read_output` | Read server console ring buffer (2000 lines) |

### GMod client

| Tool | Description |
|------|-------------|
| `gr_client_start` | Launch `hl2_linux` (bypasses Steam) |
| `gr_client_stop` | Kill the client |
| `gr_client_status` | `{running, pid, uptime_s, window_id}` |
| `gr_client_exec` | Fire-and-forget console command |
| `gr_client_lua_run` | Execute Lua on the client via file bridge, return output |
| `gr_client_read_output` | Read client console ring buffer |
| `gr_client_screenshot` | Capture via `render.Capture()` (Wayland-safe, returns base64 PNG) |
| `gr_client_click` | Click at absolute screen coordinates |
| `gr_client_key` | Send a keypress (xdotool key name) |

### How the client Lua bridge works

At startup `gr_client_start` writes `gr_mcp_bridge.lua` into the client's `garrysmod/lua/autorun/` directory. The bridge polls `garrysmod/data/gr_mcp/cmd.txt` every 100 ms from a `Think` hook and writes results to `result.txt`. Commands: `lua:<code>`, `screenshot`, or any console command.

## Running tests

```bash
pytest
```
