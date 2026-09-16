"""Tests for ProjectMemory and ProjectMemoryManager."""

import tempfile
from pathlib import Path

from core.project_memory import (
    ProjectMemoryManager,
    get_project_id,
)
from schemas.message import Message


class TestProjectMemoryId:
    """Tests for project ID generation."""

    def test_deterministic_id(self):
        p1 = "/path/to/my_project"
        p2 = "/path/to/my_project"
        assert get_project_id(p1) == get_project_id(p2)
        assert get_project_id(p1).startswith("my_project_")

    def test_case_and_slash_insensitivity(self):
        # Forward and backslashes should map to same ID
        p1 = "c:/projects/devorch"
        p2 = "c:\\projects\\devorch"
        assert get_project_id(p1) == get_project_id(p2)


class TestProjectMemoryManager:
    """Tests for ProjectMemoryManager persistence and operations."""

    def test_init_creates_default_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            mgr = ProjectMemoryManager(project_path=tmppath, base_dir=tmppath / "storage")

            assert mgr.memory.project_name == tmppath.name
            assert isinstance(mgr.memory.tech_stack, list)
            assert mgr.memory.decisions == []
            assert mgr.to_prompt_context() == ""

    def test_add_decision_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            storage = tmppath / "storage"
            mgr = ProjectMemoryManager(project_path=tmppath, base_dir=storage)

            mgr.add_decision("Standardized TokenUsage across all LLM providers")
            assert len(mgr.memory.decisions) == 1
            assert "Standardized TokenUsage across all LLM providers" in mgr.memory.decisions

            # Verify files were created on disk
            assert mgr.memory_file.exists()
            assert mgr.markdown_file.exists()

            # Reload fresh instance from disk
            mgr2 = ProjectMemoryManager(project_path=tmppath, base_dir=storage)
            assert len(mgr2.memory.decisions) == 1
            assert "Standardized TokenUsage across all LLM providers" in mgr2.memory.decisions

    def test_add_preference_and_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            storage = tmppath / "storage"
            mgr = ProjectMemoryManager(project_path=tmppath, base_dir=storage)

            mgr.add_preference("Prefers pytest over unittest")
            assert len(mgr.memory.preferences) == 1

            prompt_block = mgr.to_prompt_context()
            assert "Prefers pytest over unittest" in prompt_block
            assert "User Preferences:" in prompt_block

            mgr.clear()
            assert len(mgr.memory.preferences) == 0
            assert mgr.to_prompt_context() == ""

    def test_update_from_session_no_command_leakage(self):
        """Verify session summary extraction captures high level goal & outcome,

        strictly omitting raw shell commands, tool logs, and large code dumps.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            storage = tmppath / "storage"
            mgr = ProjectMemoryManager(project_path=tmppath, base_dir=storage)

            messages = [
                Message(role="user", content="Add pagination to the models list in cli/main.py"),
                Message(role="tool", content="STDOUT:\nC:\\Users\\ROGST\\DevOrch\nfile1\nfile2\n"),
                Message(
                    role="assistant",
                    content="```python\ndef test(): pass\n```\nSuccessfully added 15-item pagination with Next/Prev controls.",
                ),
            ]

            summary = mgr.update_from_session("sess-1234", messages)
            assert summary is not None
            assert "Add pagination" in summary
            assert "Successfully added 15-item pagination" in summary
            # Verify no raw tool logs or commands leaked
            assert "STDOUT:" not in summary
            assert "def test():" not in summary

            # Check recent_sessions list
            assert len(mgr.memory.recent_sessions) == 1
            assert mgr.memory.recent_sessions[0]["session_id"] == "sess-1234"

            # Check prompt block
            ctx = mgr.to_prompt_context()
            assert "[PROJECT MEMORY (Persistent Cross-Session Context)]" in ctx
            assert "sess-1234" in mgr.markdown_file.read_text(encoding="utf-8")

    def test_recent_sessions_capped(self):
        """Ensure older sessions are capped so token usage remains bounded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            storage = tmppath / "storage"
            mgr = ProjectMemoryManager(
                project_path=tmppath, base_dir=storage, max_recent_sessions=2
            )

            for i in range(5):
                messages = [
                    Message(role="user", content=f"Task number {i}"),
                    Message(role="assistant", content=f"Finished task {i}"),
                ]
                mgr.update_from_session(f"sess-{i}", messages)

            # Only the last 2 sessions should be kept
            assert len(mgr.memory.recent_sessions) == 2
            assert mgr.memory.recent_sessions[0]["session_id"] == "sess-3"
            assert mgr.memory.recent_sessions[1]["session_id"] == "sess-4"
