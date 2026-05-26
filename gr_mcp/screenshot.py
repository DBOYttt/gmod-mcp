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
        _tmp = not path
        if _tmp:
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)

        try:
            ids = subprocess.check_output(
                ["xdotool", "search", "--name", self._window_name],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode().split()
            if not ids:
                raise OSError(f"window '{self._window_name}' not found")
            wid = ids[0]
            subprocess.run(
                ["scrot", "-w", wid, path],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            if _tmp:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return {"ok": False, "error": (e.stderr or b"").decode()}
        except subprocess.TimeoutExpired:
            if _tmp:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return {"ok": False, "error": "screenshot timed out"}
        except OSError as e:
            if _tmp:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return {"ok": False, "error": str(e)}

        with open(path, "rb") as f:
            data = f.read()

        try:
            width = struct.unpack(">I", data[16:20])[0]
            height = struct.unpack(">I", data[20:24])[0]
        except struct.error:
            return {"ok": False, "error": f"invalid PNG data in {path}"}

        return {
            "path": path,
            "base64_png": base64.b64encode(data).decode(),
            "width": width,
            "height": height,
        }
