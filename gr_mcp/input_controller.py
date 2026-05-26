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
