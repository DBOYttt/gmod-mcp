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


def test_capture_returns_error_on_corrupt_png(screen, tmp_path):
    corrupt_path = str(tmp_path / "corrupt.png")
    with open(corrupt_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")  # valid signature but no IHDR (only 8 bytes)

    with patch("subprocess.run"):  # suppress xdotool + scrot calls
        result = screen.capture(corrupt_path)

    assert result.get("ok") is False
    assert "invalid PNG" in result["error"]
