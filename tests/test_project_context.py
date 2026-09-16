import tempfile
from pathlib import Path

import pytest

from core.project_context import ProjectContextLoader


class TestProjectContextLoader:
    def test_find_and_load_devorch_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            devorch_md = tmppath / "DEVORCH.md"
            devorch_md.write_text("# Test Project Guidelines\nRun `pytest` to test.", encoding="utf-8")

            loader = ProjectContextLoader()
            ctx = loader.load(start_dir=tmppath)

            assert ctx is not None
            assert ctx.file_name == "DEVORCH.md"
            assert "Test Project Guidelines" in ctx.content
            assert ctx.estimated_tokens > 0
            prompt_block = ctx.to_system_prompt_block()
            assert "=== PROJECT GUIDELINES" in prompt_block

    def test_fallback_to_claude_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            claude_md = tmppath / "CLAUDE.md"
            claude_md.write_text("# Claude Rules\nFollow these guidelines.", encoding="utf-8")

            loader = ProjectContextLoader()
            ctx = loader.load(start_dir=tmppath)

            assert ctx is not None
            assert ctx.file_name == "CLAUDE.md"
            assert "Claude Rules" in ctx.content

    def test_devorch_precedes_claude(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "CLAUDE.md").write_text("Claude rules", encoding="utf-8")
            (tmppath / "DEVORCH.md").write_text("DevOrch rules", encoding="utf-8")

            loader = ProjectContextLoader()
            ctx = loader.load(start_dir=tmppath)

            assert ctx is not None
            assert ctx.file_name == "DEVORCH.md"
            assert "DevOrch rules" in ctx.content

    def test_init_project_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            target = ProjectContextLoader.init_project_file(tmppath)
            assert target.is_file()
            assert target.name == "DEVORCH.md"
            content = target.read_text(encoding="utf-8")
            assert "DevOrch Project Guidelines" in content

            # Check that re-init without overwrite raises FileExistsError
            with pytest.raises(FileExistsError):
                ProjectContextLoader.init_project_file(tmppath, overwrite=False)
