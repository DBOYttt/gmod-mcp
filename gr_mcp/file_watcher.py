from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _LuaHandler(FileSystemEventHandler):
    def __init__(self, dirty: set) -> None:
        self._dirty = dirty

    def _record(self, path: str) -> None:
        if not path.endswith(".lua"):
            return
        self._dirty.add(path)

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._record(event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._record(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._record(event.dest_path)


class FileWatcher:
    def __init__(self, path: str) -> None:
        self._path = path
        self._dirty: set[str] = set()
        self._observer = Observer()
        self._observer.schedule(_LuaHandler(self._dirty), path, recursive=True)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()

    @property
    def dirty_files(self) -> list[str]:
        return sorted(self._dirty)

    def clear(self) -> None:
        self._dirty.clear()
