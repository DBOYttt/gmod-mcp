# gmod-mcp

MCP server that lets Claude Code control a Garry's Mod server and client — start/stop, run Lua, take screenshots, send input. No Steam required.

## Setup

```bash
pip install -e .
```

Needs `xdotool` and a 32-bit gcc (`glibc-devel.i686` on Fedora, `gcc-multilib` on Debian) for the locale shim below.

Add to your `.mcp.json`:

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
        "LD_PRELOAD": "/home/<you>/.local/lib/locale_fix.so"
      }
    }
  }
}
```

Other env vars: `GMOD_ROOT` (schema repo root, default `~/Documents/projects/gmod`), `GMOD_SRCDS_CMD` (server start command, default `bash server/start.sh`), `GMOD_CLIENT_ARGS`, `GMOD_CLIENT_WINDOW`.

## Locale fix

GMod on Linux shows a *"SetLocale('en_US.UTF-8') failed"* dialog and falls back to the C locale, breaking UTF-8 rendering. The fix is a small LD_PRELOAD shim:

```bash
mkdir -p ~/.local/lib
gcc -m32 -shared -fPIC -O2 -o ~/.local/lib/locale_fix.so server/locale_fix.c -ldl
```

Set `LD_PRELOAD` to that path in your env and the dialog goes away.

## Tools

**Server:** `gr_server_start`, `gr_server_stop`, `gr_server_restart`, `gr_server_status`, `gr_server_exec`, `gr_lua_run`, `gr_read_output`

**Client:** `gr_client_start`, `gr_client_stop`, `gr_client_status`, `gr_client_exec`, `gr_client_lua_run`, `gr_client_read_output`, `gr_client_screenshot`, `gr_client_click`, `gr_client_key`

The client Lua bridge (`gr_client_lua_run`, `gr_client_screenshot`) works by writing a `Think` hook script into the client's autorun on first start. It polls `garrysmod/data/gr_mcp/cmd.txt` every 100 ms and writes results to `result.txt`.

## Tests

```bash
pytest
```
