# GMod Client Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 9 MCP tools that let an AI agent launch a GMod client, send input (clicks, keypresses), capture screenshots, and run clientside Lua — enabling automated UI testing of the Galaxies Reborn schema.

**Architecture:** Three new modules (`client_manager.py`, `input_controller.py`, `screenshot.py`) reuse existing `PtyManager` and `LuaRunner` machinery. `PtyManager` gains an optional `env` dict so `ClientManager` can inject `LD_LIBRARY_PATH` for the direct `hl2_linux` binary launch. Nine new `@mcp.tool()` functions wire everything into `server.py`.

**Tech Stack:** FastMCP, Python `subprocess`, `xdotool` (window focus + input), `scrot` (screenshot), existing `PtyManager`/`LuaRunner`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `gr_mcp/pty_manager.py` | Add optional `env` dict to `__init__` + `Popen` |
| Create | `gr_mcp/client_manager.py` | Launch `hl2_linux` via PTY, expose start/stop/status/exec/lua/read |
| Create | `gr_mcp/input_controller.py` | `click(x,y)` and `key(name)` via `xdotool` |
| Create | `gr_mcp/screenshot.py` | Capture GMod window via `scrot`, return path + base64 PNG |
| Modify | `gr_mcp/server.py` | Instantiate 3 new objects, add 9 `@mcp.tool()` functions |
| Create | `tests/test_client_manager.py` | Unit tests for ClientManager |
| Create | `tests/test_input_controller.py` | Unit tests for InputController |
| Create | `tests/test_screenshot.py` | Unit tests for Screenshot |
| Modify | `tests/test_pty_manager.py` | Test that env dict is passed to subprocess |

---

## Task 1: Extend PtyManager with optional env dict

`subprocess.Popen` accepts an `env` kwarg. Currently `PtyManager` always inherits the parent environment. `ClientManager` needs to inject `LD_LIBRARY_PATH` for `hl2_linux`.

**Files:**
- Modify: `gr_mcp/pty_manager.py`
- Modify: `tests/test_pty_manager.py`

- [ ] **Step 1: Write the failing test**

Add this test to the bottom of `tests/test_pty_manager.py`:

```python
import os as _os

async def test_custom_env_is_visible_to_subprocess():
    """PtyManager passes custom env dict to the child process."""
    env = {**_os.environ, "GR_PTY_TEST_VAR": "sentinel_value"}
    mgr = PtyManager(
        ["python3", "-c",
         "import os; print(os.environ.get('GR_PTY_TEST_VAR', 'missing'))"],
        "/tmp",
        env=env,
    )
    await mgr.start()
    result = await _wait_for_output(mgr, "sentinel_value", timeout=3.0)
    texts = [l["text"] for l in result["lines"]]
    assert any("sentinel_value" in t for t in texts)
    await mgr.stop()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/diboy/Documents/projects/tools/gmod-mcp
pytest tests/test_pty_manager.py::test_custom_env_is_visible_to_subprocess -v
```

Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'env'`

- [ ] **Step 3: Add `env` parameter to `PtyManager.__init__` and pass it to `Popen`**

In `gr_mcp/pty_manager.py`, change the `__init__` signature (line 24):

```python
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
```

Then in `start()`, add `env=self._env` to the `subprocess.Popen(...)` call (around line 41):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_pty_manager.py::test_custom_env_is_visible_to_subprocess -v
```

Expected: PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
pytest tests/test_pty_manager.py -v
```

Expected: all tests PASS (the new `env=None` default keeps existing behaviour)

- [ ] **Step 6: Commit**

```bash
git add gr_mcp/pty_manager.py tests/test_pty_manager.py
git commit -m "feat: add optional env dict to PtyManager for custom subprocess environment"
```

---

## Task 2: ClientManager — launch hl2_linux via PTY

`ClientManager` is a thin wrapper around `PtyManager` that builds the correct `hl2_linux` command and `LD_LIBRARY_PATH` from env vars. It owns a `LuaRunner` instance for clientside Lua execution. It also resolves the GMod X11 window ID via `xdotool search`.

**Files:**
- Create: `gr_mcp/client_manager.py`
- Create: `tests/test_client_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_client_manager.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gr_mcp.lua_runner import LuaRunner


class FakePty:
    """Minimal PtyManager stand-in — no subprocess."""

    async def start(self):
        return {"running": True, "pid": 99, "uptime_s": 0}

    async def stop(self):
        return {"ok": True}

    def status(self):
        return {"running": True, "pid": 99, "uptime_s": 5}

    def exec_command(self, cmd):
        return {"ok": True}

    def read_output(self, since_line=0, limit=200, pattern=None):
        return {"lines": [], "next_line": 0}

    def is_running(self):
        return True

    def last_line_n(self):
        return 0

    def lines_since(self, n):
        return []


@pytest.fixture
def manager():
    from gr_mcp.client_manager import ClientManager
    m = ClientManager()
    # Replace internal pty and lua with fakes so no subprocess is spawned.
    fake = FakePty()
    m._pty = fake
    m._lua = LuaRunner(fake)
    return m


async def test_start_includes_window_id(manager):
    with patch("subprocess.check_output", return_value=b"12345\n"):
        result = await manager.start()
    assert result["running"] is True
    assert result["window_id"] == "12345"


async def test_start_window_id_none_when_xdotool_fails(manager):
    with patch("subprocess.check_output", side_effect=Exception("not found")):
        result = await manager.start()
    assert result["window_id"] is None


async def test_stop_returns_ok(manager):
    result = await manager.stop()
    assert result["ok"] is True


def test_status_includes_window_id(manager):
    with patch("subprocess.check_output", return_value=b"99\n"):
        result = manager.status()
    assert result["running"] is True
    assert result["window_id"] == "99"


def test_exec_command_delegates(manager):
    result = manager.exec_command("status")
    assert result["ok"] is True


def test_read_output_delegates(manager):
    result = manager.read_output()
    assert "lines" in result
    assert "next_line" in result


async def test_lua_run_delegates(manager):
    manager._lua = MagicMock()
    manager._lua.run = AsyncMock(return_value={"output": "42", "timed_out": False})
    result = await manager.lua_run("print(6*7)")
    assert result["output"] == "42"
    manager._lua.run.assert_called_once_with("print(6*7)", 5.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_client_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gr_mcp.client_manager'`

- [ ] **Step 3: Create `gr_mcp/client_manager.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_client_manager.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add gr_mcp/client_manager.py tests/test_client_manager.py
git commit -m "feat: add ClientManager — PTY wrapper for hl2_linux client"
```

---

## Task 3: InputController — xdotool mouse and keyboard

`InputController` wraps `xdotool` to click and send keypresses to the GMod window. It focuses the window with `windowfocus --sync` before each action to guarantee input reaches the right target.

**Files:**
- Create: `gr_mcp/input_controller.py`
- Create: `tests/test_input_controller.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_input_controller.py`:

```python
import subprocess
import pytest
from unittest.mock import patch, call, MagicMock

from gr_mcp.input_controller import InputController


@pytest.fixture
def ctrl():
    return InputController("Garry's Mod")


def test_click_focuses_window_then_moves_and_clicks(ctrl):
    with patch("subprocess.run") as mock_run:
        result = ctrl.click(640, 420)

    assert result == {"ok": True}
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls[0] == ["xdotool", "search", "--name", "Garry's Mod", "windowfocus", "--sync"]
    assert calls[1] == ["xdotool", "mousemove", "640", "420", "click", "1"]


def test_key_focuses_window_then_sends_key(ctrl):
    with patch("subprocess.run") as mock_run:
        result = ctrl.key("Return")

    assert result == {"ok": True}
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls[0] == ["xdotool", "search", "--name", "Garry's Mod", "windowfocus", "--sync"]
    assert calls[1] == ["xdotool", "key", "Return"]


def test_click_returns_error_when_xdotool_fails(ctrl):
    err = subprocess.CalledProcessError(1, "xdotool", stderr=b"window not found")
    with patch("subprocess.run", side_effect=err):
        result = ctrl.click(0, 0)

    assert result["ok"] is False
    assert "window not found" in result["error"]


def test_key_returns_error_when_xdotool_fails(ctrl):
    err = subprocess.CalledProcessError(1, "xdotool", stderr=b"no window")
    with patch("subprocess.run", side_effect=err):
        result = ctrl.key("Escape")

    assert result["ok"] is False
    assert "no window" in result["error"]


def test_click_returns_error_on_timeout(ctrl):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("xdotool", 5)):
        result = ctrl.click(100, 200)

    assert result["ok"] is False
    assert "timed out" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_input_controller.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gr_mcp.input_controller'`

- [ ] **Step 3: Create `gr_mcp/input_controller.py`**

```python
import subprocess


class InputController:
    def __init__(self, window_name: str) -> None:
        self._window_name = window_name

    def _focus(self) -> None:
        subprocess.run(
            ["xdotool", "search", "--name", self._window_name, "windowfocus", "--sync"],
            check=True,
            capture_output=True,
            timeout=5,
        )

    def click(self, x: int, y: int) -> dict:
        try:
            self._focus()
            subprocess.run(
                ["xdotool", "mousemove", str(x), str(y), "click", "1"],
                check=True,
                capture_output=True,
                timeout=5,
            )
            return {"ok": True}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": e.stderr.decode()}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "xdotool timed out"}

    def key(self, key: str) -> dict:
        try:
            self._focus()
            subprocess.run(
                ["xdotool", "key", key],
                check=True,
                capture_output=True,
                timeout=5,
            )
            return {"ok": True}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": e.stderr.decode()}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "xdotool timed out"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_input_controller.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add gr_mcp/input_controller.py tests/test_input_controller.py
git commit -m "feat: add InputController — xdotool click and key for GMod window"
```

---

## Task 4: Screenshot — scrot window capture to base64 PNG

`Screenshot.capture()` focuses the GMod window with `xdotool`, then runs `scrot -u <path>` to capture the active window. It reads the resulting PNG and returns the file path plus a base64-encoded copy so the agent can pass it directly to a vision model. PNG dimensions are parsed from the file header (bytes 16–23).

**Files:**
- Create: `gr_mcp/screenshot.py`
- Create: `tests/test_screenshot.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screenshot.py`:

```python
import base64
import struct
import pytest
from unittest.mock import patch

from gr_mcp.screenshot import Screenshot


def _png(width: int, height: int) -> bytes:
    """Minimal PNG header bytes with correct width/height fields."""
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 4-byte length + "IHDR" + 13 data bytes + 4-byte CRC
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr = b"\x00\x00\x00\rIHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return sig + ihdr + b"\x00" * 12


@pytest.fixture
def screen():
    return Screenshot("Garry's Mod")


def test_capture_returns_path_base64_and_dimensions(screen, tmp_path):
    png_data = _png(1280, 720)
    out_path = str(tmp_path / "shot.png")
    with open(out_path, "wb") as f:
        f.write(png_data)

    with patch("subprocess.run"):  # suppress xdotool + scrot calls
        result = screen.capture(out_path)

    assert result["path"] == out_path
    assert result["width"] == 1280
    assert result["height"] == 720
    assert base64.b64decode(result["base64_png"]) == png_data


def test_capture_creates_temp_file_when_no_path(screen):
    png_data = _png(800, 600)

    def fake_run(args, **kwargs):
        if args[0] == "scrot":
            path = args[-1]  # scrot -u <path>
            with open(path, "wb") as f:
                f.write(png_data)

    with patch("subprocess.run", side_effect=fake_run):
        result = screen.capture()

    assert result["path"].endswith(".png")
    assert result["width"] == 800
    assert result["height"] == 600


def test_capture_returns_error_on_xdotool_failure(screen):
    import subprocess
    err = subprocess.CalledProcessError(1, "xdotool", stderr=b"no window")
    with patch("subprocess.run", side_effect=err):
        result = screen.capture("/tmp/x.png")

    assert result.get("ok") is False
    assert "no window" in result["error"]


def test_capture_returns_error_on_timeout(screen):
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("scrot", 10)):
        result = screen.capture("/tmp/x.png")

    assert result.get("ok") is False
    assert "timed out" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_screenshot.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gr_mcp.screenshot'`

- [ ] **Step 3: Create `gr_mcp/screenshot.py`**

```python
import base64
import os
import struct
import subprocess
import tempfile
from typing import Optional


class Screenshot:
    def __init__(self, window_name: str) -> None:
        self._window_name = window_name

    def capture(self, path: str = "") -> dict:
        if not path:
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)

        try:
            subprocess.run(
                ["xdotool", "search", "--name", self._window_name, "windowfocus", "--sync"],
                check=True,
                capture_output=True,
                timeout=5,
            )
            subprocess.run(
                ["scrot", "-u", path],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": e.stderr.decode()}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "screenshot timed out"}

        with open(path, "rb") as f:
            data = f.read()

        width = struct.unpack(">I", data[16:20])[0]
        height = struct.unpack(">I", data[20:24])[0]

        return {
            "path": path,
            "base64_png": base64.b64encode(data).decode(),
            "width": width,
            "height": height,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_screenshot.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add gr_mcp/screenshot.py tests/test_screenshot.py
git commit -m "feat: add Screenshot — scrot window capture returning path and base64 PNG"
```

---

## Task 5: Wire 9 new MCP tools in server.py

Add the 9 client tools to `server.py` by instantiating `ClientManager`, `InputController`, and `Screenshot` at module level (same pattern as the existing `_pty`, `_lua`, `_watcher`).

**Files:**
- Modify: `gr_mcp/server.py`

There are no new unit tests for this task — the wiring is mechanical and the underlying classes are already tested. The integration is validated by running the MCP server manually (see verification step).

- [ ] **Step 1: Add imports and module-level instances to `gr_mcp/server.py`**

At the top of the file, after the existing imports (line 7):

```python
from gr_mcp.client_manager import ClientManager
from gr_mcp.input_controller import InputController
from gr_mcp.screenshot import Screenshot
```

After `_watcher = FileWatcher(_SCHEMA_PATH)` (line 20), add:

```python
_client = ClientManager()
_input = InputController(_client.window_name)
_screen = Screenshot(_client.window_name)
```

- [ ] **Step 2: Append the 9 tool functions to `server.py` before `def main()`**

Add these functions between the last existing `@mcp.tool()` function and `def main()`:

```python
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
def gr_client_screenshot(path: str = "") -> dict:
    """
    Capture the GMod client window.
    path: optional file path; if empty, a temp file is created.
    Returns {path, base64_png, width, height}.
    base64_png can be passed directly to a vision model.
    """
    return _screen.capture(path)


@mcp.tool()
def gr_client_click(x: int, y: int) -> dict:
    """
    Click at screen-absolute coordinates (x, y) in the GMod client window.
    Focuses the window with xdotool before clicking.
    Returns {ok} or {ok, error}.
    """
    return _input.click(x, y)


@mcp.tool()
def gr_client_key(key: str) -> dict:
    """
    Send a keypress to the GMod client window.
    key: xdotool key name — e.g. "Return", "Escape", "grave" (opens console), "F1".
    Returns {ok} or {ok, error}.
    """
    return _input.key(key)
```

- [ ] **Step 3: Run the full test suite**

```bash
cd /home/diboy/Documents/projects/tools/gmod-mcp
pytest tests/ -v
```

Expected: all existing + new tests PASS. The `server.py` changes import at module level, so any import error will surface here.

- [ ] **Step 4: Verify the MCP server starts cleanly**

```bash
python -m gr_mcp.server &
sleep 2
kill %1
```

Expected: process starts without errors (no `ImportError`, no `AttributeError`).

- [ ] **Step 5: Commit**

```bash
git add gr_mcp/server.py
git commit -m "feat: wire 9 gr_client_* MCP tools — client start/stop/status/exec/lua/read/screenshot/click/key"
```

---

## Verification Checklist

After all tasks are complete, restart the Claude Code MCP session and confirm these tools appear:

```
gr_client_start      gr_client_stop       gr_client_status
gr_client_exec       gr_client_lua_run    gr_client_read_output
gr_client_screenshot gr_client_click      gr_client_key
```

Manual smoke test (requires `xdotool` and `scrot` installed, GMod client running):

```bash
# Install dependencies if needed
sudo dnf install xdotool scrot

# In Claude Code, after gr_client_start():
# 1. gr_client_screenshot() — verify base64_png is non-empty
# 2. gr_client_key("grave") — opens GMod console
# 3. gr_client_screenshot() — verify console is visible
# 4. gr_client_key("grave") — close console
```
