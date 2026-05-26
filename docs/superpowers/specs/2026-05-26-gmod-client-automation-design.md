# GMod Client Automation Design

**Date:** 2026-05-26
**Goal:** Add MCP tools that let an AI agent launch a GMod client, send input (clicks, keypresses), capture screenshots, and run clientside Lua — enabling automated UI testing of the Galaxies Reborn schema.

---

## Section 1: Architecture

New modules mirror the existing server pattern exactly.

### Module structure

```
gr_mcp/
  pty_manager.py      ← unchanged (shared by server + client)
  lua_runner.py       ← unchanged (shared by server + client)
  file_watcher.py     ← unchanged
  client_manager.py   ← NEW: PtyManager wrapper for hl2_linux
  input_controller.py ← NEW: xdotool mouse/keyboard wrapper
  screenshot.py       ← NEW: scrot window capture → file + base64
  server.py           ← +9 new MCP tools wired to above
```

### Key design decision: reuse PtyManager

`client_manager.py` is a thin wrapper that builds the `hl2_linux` launch command and passes it to `PtyManager`. The client gets its own PTY instance, its own ring buffer (2000 lines), and its own `LuaRunner` — identical machinery to the server. No new I/O code.

### input_controller.py

Wraps `xdotool` (available on Fedora via `dnf install xdotool`). Two operations: `click(x, y)` moves the mouse and clicks; `key(name)` sends a keypress. Both target the GMod window by name (`windowfocus --sync`) before acting so focus is guaranteed.

### screenshot.py

Uses `scrot` (available on Fedora via `dnf install scrot`) to capture the GMod window by name into a temp file. Returns the file path and a base64-encoded PNG so the agent can pass it directly to a vision model without a separate file read.

---

## Section 2: New MCP Tools

9 new tools added to `server.py`, each wired to `client_manager`, `input_controller`, or `screenshot`.

| Tool | Arguments | Returns |
|------|-----------|---------|
| `gr_client_start` | — | `{running, pid, window_id}` |
| `gr_client_stop` | — | `{ok}` |
| `gr_client_status` | — | `{running, pid, uptime_s, window_id}` |
| `gr_client_exec` | `command: str` | `{ok}` — fire-and-forget |
| `gr_client_lua_run` | `code: str, timeout: float = 5` | `{output, timed_out}` |
| `gr_client_read_output` | `since_line, limit, pattern` | `{lines, next_line}` |
| `gr_client_screenshot` | `path: str = ""` | `{path, base64_png, width, height}` |
| `gr_client_click` | `x: int, y: int` | `{ok}` |
| `gr_client_key` | `key: str` | `{ok}` |

### Notes

- `gr_client_screenshot` — `path` is optional; if empty, saves to a temp file. Always returns `base64_png` so the agent can pass it directly to a vision model.
- `gr_client_click` — coordinates are screen-absolute. Agent reads them from the screenshot (vision model identifies button location).
- `gr_client_key` — xdotool key names: `"grave"` opens console, `"Return"`, `"Escape"`, `"F1"` etc.
- `gr_client_lua_run` — same token-bracketing as server, same `LuaRunner` class.
- `window_id` — X11 window ID, used internally by `input_controller` and `screenshot` to target the GMod window.

---

## Section 3: Agent Testing Flow

Typical cycle for automated UI testing.

### Screenshot → Identify → Act → Verify loop

```
1. Setup
   gr_server_start()                    ← dedicated server up
   gr_client_start()                    ← GMod client launches, connects to localhost
   sleep(10)                            ← wait for map load

2. Observe
   gr_client_screenshot()               ← base64_png returned
   [vision model] "Character creation button is at (640, 420)"

3. Act
   gr_client_click(640, 420)            ← click the button
   gr_client_key("Return")              ← confirm / navigate

4. Verify
   gr_client_screenshot()               ← capture result
   [vision model] "Faction picker is visible — PASS"

5. Lua assertions (optional deeper check)
   gr_client_lua_run("print(LocalPlayer():GetCharacter():GetData('level'))")
   ← returns "1" — verify game state matches visual
```

### Configuration (env vars)

```
GMOD_CLIENT_DIR    = /path/to/GarrysMod    # auto-detected from install_client.sh path
GMOD_CLIENT_ARGS   = "-windowed -w 1280 -h 720 +connect localhost"
GMOD_CLIENT_WINDOW = "Garry's Mod"         # xdotool window name to target
```

`client_manager.py` builds `LD_LIBRARY_PATH` automatically from `GMOD_CLIENT_DIR`:

```
LD_LIBRARY_PATH={client}/bin/linux64:{client}/bin:...
{client}/hl2_linux -game garrysmod -windowed -w 1280 -h 720
  +connect localhost +developer 1 -condebug
```

Steam is bypassed (direct binary launch), which is fine because:
- Workshop content (LSCS) is already extracted to disk by `install_client.sh`
- The client connects to `localhost:27015`, which needs no VAC auth

### Dependencies

```
xdotool   # dnf install xdotool
scrot     # dnf install scrot
```

Both are available on Fedora.

---

## Implementation Scope

**Files to create:**
- `gr_mcp/client_manager.py` — `ClientManager` class wrapping `PtyManager` + `LuaRunner`
- `gr_mcp/input_controller.py` — `InputController` class with `click(x, y)` and `key(name)`
- `gr_mcp/screenshot.py` — `Screenshot` class with `capture(window_name, path) → {path, base64_png, width, height}`

**Files to modify:**
- `gr_mcp/server.py` — instantiate `ClientManager`, `InputController`, `Screenshot`; wire 9 new `@mcp.tool()` functions

**Tests:**
- `tests/test_client_manager.py` — mock PtyManager; test start/stop/status
- `tests/test_input_controller.py` — mock subprocess; test click/key command construction
- `tests/test_screenshot.py` — mock scrot call; test base64 encoding + path return
