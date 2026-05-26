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
