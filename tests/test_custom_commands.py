"""Tests for Markdown custom slash commands."""

from pathlib import Path

from core.skills import SkillManager, parse_markdown_command, render_prompt


def _mgr(tmp_path: Path, *dirs: Path) -> SkillManager:
    return SkillManager(skills_dir=tmp_path / "skills", commands_dirs=list(dirs))


def test_parse_frontmatter():
    meta, body = parse_markdown_command("---\ndescription: Hi there\n---\nDo the thing\n")
    assert meta == {"description": "Hi there"}
    assert body == "Do the thing"


def test_parse_without_frontmatter():
    meta, body = parse_markdown_command("Just a prompt\n")
    assert meta == {} and body == "Just a prompt"


def test_parse_unterminated_frontmatter_kept_as_body():
    _, body = parse_markdown_command("---\nno end here")
    assert body.startswith("---")


def test_loads_markdown_command(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    (d / "pr.md").write_text("---\ndescription: Review PR\n---\nReview PR $ARGUMENTS")
    skill = _mgr(tmp_path, d).get("pr")
    assert skill["description"] == "Review PR"
    assert skill["source"].endswith("pr.md")


def test_default_description(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    (d / "x.md").write_text("body")
    assert "x" in _mgr(tmp_path, d).get("x")["description"]


def test_project_overrides_global_and_builtin(tmp_path):
    g, p = tmp_path / "g", tmp_path / "p"
    g.mkdir()
    p.mkdir()
    (g / "review.md").write_text("global review")
    (g / "deploy.md").write_text("global deploy")
    (p / "deploy.md").write_text("project deploy")
    m = _mgr(tmp_path, g, p)
    assert m.get("deploy")["prompt"] == "project deploy"
    assert m.get("review")["prompt"] == "global review"  # overrides built-in
    assert any(s["name"] == "commit" for s in m.list_skills())


def test_empty_file_ignored(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    (d / "empty.md").write_text("---\ndescription: x\n---\n")
    assert _mgr(tmp_path, d).get("empty") is None


def test_render_prompt():
    assert render_prompt({"prompt": "PR $ARGUMENTS now"}, "12") == "PR 12 now"
    assert render_prompt({"prompt": "PR $ARGUMENTS"}, None) == "PR "
    assert render_prompt({"prompt": "base"}, "extra") == "base\n\nextra"
    assert render_prompt({"prompt": "base"}, "") == "base"
