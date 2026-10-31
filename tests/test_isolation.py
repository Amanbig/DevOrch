"""The suite must never read or write the developer's real ~/.devorch."""

import os
from pathlib import Path

from config import permissions as perm_mod
from config import settings as settings_mod
from core import sessions as sessions_mod
from core.memory import MEMORY_DIR


def test_home_is_a_throwaway_directory():
    home = Path.home()
    assert "devorch-test-home-" in home.name
    assert home == Path(os.environ["HOME"])


def test_application_paths_resolve_under_the_test_home():
    home = Path.home()
    for path in (
        perm_mod.PERMISSIONS_FILE,
        settings_mod.CONFIG_FILE,
        sessions_mod.DB_PATH,
        MEMORY_DIR,
    ):
        assert home in path.parents, f"{path} is outside the test HOME"


def test_saving_permissions_does_not_touch_the_real_file():
    from config.permissions import PermissionLevel, Permissions

    Permissions().set_tool_permission("edit", PermissionLevel.ALLOW)  # saves to PERMISSIONS_FILE
    assert perm_mod.PERMISSIONS_FILE.exists()
    assert Path.home() in perm_mod.PERMISSIONS_FILE.parents


def test_keyring_is_the_null_backend():
    import keyring

    assert keyring.get_password("devorch", "openai") is None
    assert type(keyring.get_keyring()).__module__ == "keyring.backends.null"
