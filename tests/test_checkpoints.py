"""Tests for file checkpoints / undo."""

from core.checkpoints import CheckpointManager, tracked_path
from core.executor import ToolExecutor
from tools.edit import EditTool
from tools.filesystem import FilesystemTool


def test_tracked_path():
    assert tracked_path("filesystem", {"action": "write", "path": "a"}) == "a"
    assert tracked_path("filesystem", {"action": "read", "path": "a"}) is None
    assert tracked_path("edit", {"action": "replace", "path": "a"}) == "a"
    assert tracked_path("edit", {"action": "replace", "path": "a", "dry_run": True}) is None
    assert tracked_path("shell", {"path": "a"}) is None


def test_rewind_restores_and_deletes(tmp_path):
    existing = tmp_path / "a.txt"
    existing.write_text("orig")
    new = tmp_path / "b.txt"
    cm = CheckpointManager()
    cm.begin_turn("do things")
    cm.snapshot(str(existing))
    cm.snapshot(str(new))
    existing.write_text("changed")
    new.write_text("created")
    cm.rewind_turn()
    assert existing.read_text() == "orig"
    assert not new.exists()
    assert cm.summary() == []


def test_snapshot_once_per_turn(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("v1")
    cm = CheckpointManager()
    cm.begin_turn("t")
    assert cm.snapshot(str(f))
    f.write_text("v2")
    assert not cm.snapshot(str(f))
    cm.rewind_turn()
    assert f.read_text() == "v1"


def test_only_latest_turn_rewound(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("v0")
    cm = CheckpointManager()
    cm.begin_turn("one")
    cm.snapshot(str(f))
    f.write_text("v1")
    cm.begin_turn("two")
    cm.snapshot(str(f))
    f.write_text("v2")
    cm.rewind_turn()
    assert f.read_text() == "v1"
    cm.rewind_turn()
    assert f.read_text() == "v0"


def test_turn_without_edits_does_not_touch_files(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("v0")
    cm = CheckpointManager()
    cm.begin_turn("edit")
    cm.snapshot(str(f))
    f.write_text("v1")
    cm.begin_turn("chat only")
    assert cm.rewind_turn() == []
    assert f.read_text() == "v1"


def test_executor_snapshots_edit_and_write(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world")
    ex = ToolExecutor([EditTool(), FilesystemTool()], require_confirmation=False)
    ex.checkpoints.begin_turn("t")
    ex.execute(
        "edit", {"action": "replace", "path": str(f), "find": "hello", "replace_with": "bye"}
    )
    ex.execute("filesystem", {"action": "write", "path": str(tmp_path / "n.txt"), "content": "x"})
    assert f.read_text() == "bye world"
    ex.checkpoints.rewind_turn()
    assert f.read_text() == "hello world"
    assert not (tmp_path / "n.txt").exists()
