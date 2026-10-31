"""Tests for per-project settings and trust."""

from pathlib import Path

import pytest

from config import permissions as perm_mod
from config import settings as settings_mod
from config.permissions import PermissionLevel, Permissions
from config.project_settings import (
    load_project_settings,
    trust_project,
    untrust_project,
)
from config.settings import Settings, save_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    proj = home / "work" / "proj"
    (proj / ".devorch").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(settings_mod, "CONFIG_DIR", home / ".devorch")
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", home / ".devorch" / "config.yaml")
    monkeypatch.setattr(perm_mod, "CONFIG_DIR", home / ".devorch")
    monkeypatch.setattr(perm_mod, "PERMISSIONS_FILE", home / ".devorch" / "permissions.yaml")
    monkeypatch.setattr(settings_mod, "KEYRING_AVAILABLE", False)
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(proj)
    return proj


def write(proj: Path, text: str):
    (proj / ".devorch" / "settings.yaml").write_text(text)


FULL = """
default_mode: auto
default_provider: anthropic
providers:
  anthropic:
    default_model: proj-model
    api_key: sk-should-be-ignored
mcp_servers:
  gh:
    command: npx
    args: [-y, server]
permissions:
  shell:
    allow: ["pytest*"]
    deny: ["git push*"]
"""


def test_no_file(env):
    assert load_project_settings() is None
    assert Settings.load().project_notices == []


def test_found_from_subdirectory(env):
    write(env, "default_mode: plan\n")
    sub = env / "a" / "b"
    sub.mkdir(parents=True)
    assert load_project_settings(sub).default_mode == "plan"


def test_untrusted_applies_only_safe_keys(env):
    write(env, FULL)
    ps = load_project_settings()
    assert not ps.trusted
    assert ps.effective_mode() == "ask"  # auto downgraded
    s = Settings.load()
    assert s.default_provider == "anthropic"
    assert s.providers["anthropic"].default_model == "proj-model"
    assert s.providers["anthropic"].api_key is None
    assert "gh" not in s.mcp_servers
    assert s.project_default_mode == "ask"
    assert any("devorch trust" in n for n in s.project_notices)
    assert any("api_key" in n for n in s.project_notices)

    p = Permissions.load()
    assert p.check_permission("shell", "git push origin main")[0] == PermissionLevel.DENY
    assert p.check_permission("shell", "pytest -q")[0] == PermissionLevel.ASK  # allow ignored


def test_trusted_enables_everything(env):
    write(env, FULL)
    trust_project(load_project_settings())
    ps = load_project_settings()
    assert ps.trusted and ps.effective_mode() == "auto"
    s = Settings.load()
    assert "gh" in s.mcp_servers
    p = Permissions.load()
    assert p.check_permission("shell", "pytest -q")[0] == PermissionLevel.ALLOW


def test_editing_file_revokes_trust(env):
    write(env, FULL)
    trust_project(load_project_settings())
    write(env, FULL + "\n# sneaky change\n")
    assert not load_project_settings().trusted


def test_untrust(env):
    write(env, FULL)
    ps = load_project_settings()
    trust_project(ps)
    assert untrust_project(ps.root)
    assert not load_project_settings().trusted
    assert not untrust_project(ps.root)


def test_project_values_not_saved_to_global(env):
    write(env, FULL)
    trust_project(load_project_settings())
    s = Settings.load()
    save_config(s)
    saved = settings_mod.CONFIG_FILE.read_text()
    assert "proj-model" not in saved and "gh" not in saved
    assert "anthropic" in saved  # provider entry exists, but with its own default model

    p = Permissions.load()
    p.save()
    saved = perm_mod.PERMISSIONS_FILE.read_text()
    assert "pytest*" not in saved and "git push*" not in saved


def test_user_change_survives_save(env):
    write(env, "providers:\n  anthropic:\n    default_model: proj-model\n")
    s = Settings.load()
    s.providers["anthropic"].default_model = "user-picked"
    save_config(s)
    assert "user-picked" in settings_mod.CONFIG_FILE.read_text()


def test_invalid_mode_and_garbage(env):
    write(env, "default_mode: yolo\n")
    ps = load_project_settings()
    assert ps.default_mode is None and ps.notices
    write(env, "- just\n- a list\n")
    assert load_project_settings().default_mode is None
    write(env, "key: [unclosed")
    assert load_project_settings().notices


def test_cli_flag_beats_project_mode(env):
    from cli.commands._shared import resolve_mode
    from core.modes import AgentMode

    write(env, "default_mode: plan\n")
    assert resolve_mode(None) == AgentMode.PLAN
    assert resolve_mode("auto") == AgentMode.AUTO
