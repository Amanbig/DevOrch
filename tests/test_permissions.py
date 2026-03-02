"""Tests for permission management."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from config.permissions import (
    DANGEROUS_PATTERNS,
    SAFE_COMMANDS,
    PermissionChoice,
    PermissionLevel,
    Permissions,
    ToolPermission,
)


class TestPermissionLevel:
    """Tests for PermissionLevel enum."""

    def test_permission_level_values(self):
        """Test PermissionLevel enum values."""
        assert PermissionLevel.ALLOW.value == "allow"
        assert PermissionLevel.DENY.value == "deny"
        assert PermissionLevel.ASK.value == "ask"

    def test_permission_level_is_string(self):
        """Test PermissionLevel is a string enum."""
        assert PermissionLevel.ALLOW == "allow"


class TestPermissionChoice:
    """Tests for PermissionChoice enum."""

    def test_permission_choice_values(self):
        """Test PermissionChoice enum values."""
        assert PermissionChoice.ALLOW_ONCE.value == "allow_once"
        assert PermissionChoice.ALLOW_SESSION.value == "allow_session"
        assert PermissionChoice.ALLOW_ALWAYS.value == "allow_always"
        assert PermissionChoice.DENY.value == "deny"


class TestToolPermission:
    """Tests for ToolPermission dataclass."""

    def test_default_permission(self):
        """Test default tool permission."""
        perm = ToolPermission()
        assert perm.level == PermissionLevel.ASK
        assert perm.allowed_patterns == []
        assert perm.denied_patterns == []

    def test_custom_permission(self):
        """Test custom tool permission."""
        perm = ToolPermission(
            level=PermissionLevel.ALLOW, allowed_patterns=["ls*", "pwd"], denied_patterns=["rm*"]
        )
        assert perm.level == PermissionLevel.ALLOW
        assert "ls*" in perm.allowed_patterns
        assert "rm*" in perm.denied_patterns


class TestPermissions:
    """Tests for Permissions class."""

    @pytest.fixture
    def permissions(self):
        """Create fresh permissions instance with defaults."""
        return Permissions.load()

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            permissions_file = config_dir / "permissions.yaml"
            with patch("config.permissions.CONFIG_DIR", config_dir):
                with patch("config.permissions.PERMISSIONS_FILE", permissions_file):
                    yield config_dir

    def test_default_permissions(self, permissions):
        """Test default permissions setup."""
        # Shell should have ASK level with safe/dangerous patterns
        assert "shell" in permissions.tools
        assert permissions.tools["shell"].level == PermissionLevel.ASK

        # Search should be allowed by default
        assert "search" in permissions.tools
        assert permissions.tools["search"].level == PermissionLevel.ALLOW

    def test_check_safe_command(self, permissions):
        """Test checking a safe command."""
        level, reason = permissions.check_permission("shell", "git status")
        assert level == PermissionLevel.ALLOW
        assert reason is not None

    def test_check_dangerous_command(self, permissions):
        """Test checking a dangerous command."""
        level, reason = permissions.check_permission("shell", "rm -rf /")
        assert level == PermissionLevel.DENY
        assert "dangerous" in reason.lower()

    def test_check_neutral_command(self, permissions):
        """Test checking a neutral command (not safe or dangerous)."""
        level, reason = permissions.check_permission("shell", "some_custom_script.sh")
        assert level == PermissionLevel.ASK
        assert reason is None

    def test_check_allowed_tool(self, permissions):
        """Test checking an allowed tool."""
        level, reason = permissions.check_permission("search", "*.py")
        assert level == PermissionLevel.ALLOW

    def test_check_unknown_tool(self, permissions):
        """Test checking an unknown tool."""
        level, reason = permissions.check_permission("unknown_tool", "some_command")
        assert level == PermissionLevel.ASK

    def test_match_wildcard_pattern(self, permissions):
        """Test wildcard pattern matching."""
        # Test glob patterns
        level, _ = permissions.check_permission("shell", "git log --oneline")
        assert level == PermissionLevel.ALLOW  # Matches "git log*"

        level, _ = permissions.check_permission("shell", "ls -la")
        assert level == PermissionLevel.ALLOW  # Matches "ls*"

    def test_session_allowed_pattern(self, permissions):
        """Test session-specific allowed patterns."""
        # Add session-only permission
        permissions.session_allowed.append("custom_command*")

        level, reason = permissions.check_permission("shell", "custom_command --flag")
        assert level == PermissionLevel.ALLOW
        assert "session" in reason.lower()

    def test_session_denied_pattern(self, permissions):
        """Test session-specific denied patterns."""
        # Add session-only deny
        permissions.session_denied.append("npm*")

        level, reason = permissions.check_permission("shell", "npm install")
        assert level == PermissionLevel.DENY
        assert "session" in reason.lower()

    def test_session_denied_takes_priority(self, permissions):
        """Test that session denied overrides allowed."""
        # Add to both allowed and denied
        permissions.session_allowed.append("test_cmd*")
        permissions.session_denied.append("test_cmd*")

        level, _ = permissions.check_permission("shell", "test_cmd arg")
        assert level == PermissionLevel.DENY

    def test_add_allowed_pattern_session(self, permissions):
        """Test adding allowed pattern for session only."""
        permissions.add_allowed_pattern("shell", "allowed_cmd*", session_only=True)

        assert "allowed_cmd*" in permissions.session_allowed
        assert "allowed_cmd*" not in permissions.tools["shell"].allowed_patterns

    def test_add_allowed_pattern_persistent(self, permissions, temp_config_dir):
        """Test adding persistent allowed pattern."""
        with patch("config.permissions.CONFIG_DIR", temp_config_dir):
            with patch("config.permissions.PERMISSIONS_FILE", temp_config_dir / "permissions.yaml"):
                permissions.add_allowed_pattern("shell", "my_safe_cmd*", session_only=False)

        assert "my_safe_cmd*" in permissions.tools["shell"].allowed_patterns

    def test_add_denied_pattern_session(self, permissions):
        """Test adding denied pattern for session only."""
        permissions.add_denied_pattern("shell", "blocked_cmd*", session_only=True)

        assert "blocked_cmd*" in permissions.session_denied

    def test_add_denied_pattern_persistent(self, permissions, temp_config_dir):
        """Test adding persistent denied pattern."""
        with patch("config.permissions.CONFIG_DIR", temp_config_dir):
            with patch("config.permissions.PERMISSIONS_FILE", temp_config_dir / "permissions.yaml"):
                permissions.add_denied_pattern("shell", "dangerous_cmd*", session_only=False)

        assert "dangerous_cmd*" in permissions.tools["shell"].denied_patterns

    def test_set_tool_permission(self, permissions, temp_config_dir):
        """Test setting tool permission level."""
        with patch("config.permissions.CONFIG_DIR", temp_config_dir):
            with patch("config.permissions.PERMISSIONS_FILE", temp_config_dir / "permissions.yaml"):
                permissions.set_tool_permission("filesystem", PermissionLevel.ALLOW)

        assert permissions.tools["filesystem"].level == PermissionLevel.ALLOW

    def test_clear_session_permissions(self, permissions):
        """Test clearing session permissions."""
        permissions.session_allowed.append("cmd1")
        permissions.session_denied.append("cmd2")

        permissions.clear_session_permissions()

        assert permissions.session_allowed == []
        assert permissions.session_denied == []

    def test_load_saves_roundtrip(self, temp_config_dir):
        """Test loading and saving permissions."""
        with patch("config.permissions.CONFIG_DIR", temp_config_dir):
            with patch("config.permissions.PERMISSIONS_FILE", temp_config_dir / "permissions.yaml"):
                # Create and save
                perms = Permissions.load()
                perms.add_allowed_pattern("shell", "custom_pattern*", session_only=False)
                perms.save()

                # Load again
                perms2 = Permissions.load()
                assert "custom_pattern*" in perms2.tools["shell"].allowed_patterns


class TestSafeCommands:
    """Tests for safe command patterns."""

    def test_git_commands_safe(self):
        """Test that read-only git commands are safe."""
        safe_git = ["git status", "git log", "git diff", "git branch"]
        for cmd in safe_git:
            assert any(
                cmd.startswith(pattern.rstrip("*"))
                for pattern in SAFE_COMMANDS
                if pattern.startswith("git")
            ), f"{cmd} should be safe"

    def test_version_commands_safe(self):
        """Test that version commands are safe."""
        assert "python --version" in SAFE_COMMANDS
        assert "node --version" in SAFE_COMMANDS
        assert "pip --version" in SAFE_COMMANDS


class TestDangerousPatterns:
    """Tests for dangerous command patterns."""

    def test_rm_rf_dangerous(self):
        """Test that rm -rf is dangerous."""
        assert any("rm -rf" in pattern for pattern in DANGEROUS_PATTERNS)

    def test_sudo_dangerous(self):
        """Test that sudo is dangerous."""
        assert any("sudo" in pattern for pattern in DANGEROUS_PATTERNS)

    def test_curl_pipe_sh_dangerous(self):
        """Test that curl | sh is dangerous."""
        assert any("curl" in pattern and "sh" in pattern for pattern in DANGEROUS_PATTERNS)
