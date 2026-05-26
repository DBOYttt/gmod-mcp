import subprocess
import pytest
from unittest.mock import patch

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
