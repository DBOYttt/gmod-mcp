import time
import pytest
from gr_mcp.file_watcher import FileWatcher


@pytest.fixture
def watcher(tmp_path):
    w = FileWatcher(str(tmp_path))
    w.start()
    yield w, tmp_path
    w.stop()


def test_dirty_files_empty_initially(watcher):
    w, _ = watcher
    assert w.dirty_files == []


def test_detects_lua_file_creation(watcher):
    w, tmp = watcher
    (tmp / "test.lua").write_text("print('hi')")
    time.sleep(0.4)
    assert any("test.lua" in f for f in w.dirty_files)


def test_detects_lua_file_modification(watcher):
    w, tmp = watcher
    f = tmp / "mod.lua"
    f.write_text("v1")
    time.sleep(0.4)
    w.clear()
    f.write_text("v2")
    time.sleep(0.4)
    assert any("mod.lua" in p for p in w.dirty_files)


def test_ignores_non_lua_files(watcher):
    w, tmp = watcher
    (tmp / "readme.txt").write_text("nope")
    time.sleep(0.4)
    assert w.dirty_files == []


def test_clear_resets_dirty_list(watcher):
    w, tmp = watcher
    (tmp / "x.lua").write_text("x")
    time.sleep(0.4)
    assert w.dirty_files
    w.clear()
    assert w.dirty_files == []


def test_dirty_files_returns_sorted_list(watcher):
    w, tmp = watcher
    (tmp / "b.lua").write_text("b")
    (tmp / "a.lua").write_text("a")
    time.sleep(0.4)
    files = w.dirty_files
    assert files == sorted(files)
