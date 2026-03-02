"""
Permission management for tool execution safety.

Supports:
- Tool-level permissions (allow/deny/ask)
- Command pattern matching (e.g., "git *" always allowed)
- Session-only vs persistent permissions
- Safe command categories
"""

import fnmatch
import re
from pathlib import Path
from typing import Dict, List, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

CONFIG_DIR = Path.home() / ".devpilot"
PERMISSIONS_FILE = CONFIG_DIR / "permissions.yaml"


class PermissionLevel(str, Enum):
    ALLOW = "allow"      # Always allow without asking
    DENY = "deny"        # Always deny
    ASK = "ask"          # Ask every time (default)


class PermissionChoice(str, Enum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


# Commands that are generally safe (read-only or low risk)
SAFE_COMMANDS = [
    # Version/info commands
    "git --version", "git status", "git log*", "git diff*", "git branch*",
    "git remote -v", "git show*",
    "python --version", "python3 --version", "pip --version", "pip list",
    "node --version", "npm --version", "npm list*",
    "cargo --version", "rustc --version",
    "go version",

    # List/read commands
    "ls*", "dir*", "pwd", "cd*", "echo*", "cat*", "head*", "tail*",
    "which*", "where*", "type*", "file*",
    "wc*", "grep*", "find*", "tree*",

    # Environment
    "env", "printenv*", "hostname", "whoami", "date", "uptime",
]

# Commands that are potentially dangerous
DANGEROUS_PATTERNS = [
    "rm -rf *", "rm -r *", "rmdir*",
    "del /s*", "rd /s*",
    "format*",
    "mkfs*",
    "dd if=*",
    "> /dev/*",
    "chmod 777*",
    "sudo*",
    "curl*|*sh", "wget*|*sh",  # Pipe to shell
    "*; rm*", "*&& rm*",  # Chained destructive
]


@dataclass
class ToolPermission:
    """Permission settings for a specific tool."""
    level: PermissionLevel = PermissionLevel.ASK
    allowed_patterns: List[str] = field(default_factory=list)
    denied_patterns: List[str] = field(default_factory=list)


@dataclass
class Permissions:
    """Global permission settings."""
    tools: Dict[str, ToolPermission] = field(default_factory=dict)

    # Session-only permissions (not persisted)
    session_allowed: List[str] = field(default_factory=list)
    session_denied: List[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Permissions":
        """Load permissions from config file."""
        permissions = cls()

        # Set defaults
        permissions.tools = {
            "shell": ToolPermission(
                level=PermissionLevel.ASK,
                allowed_patterns=SAFE_COMMANDS.copy(),
                denied_patterns=DANGEROUS_PATTERNS.copy()
            ),
            "filesystem": ToolPermission(level=PermissionLevel.ASK),
            "search": ToolPermission(level=PermissionLevel.ALLOW),  # Search is safe
        }

        # Load from file if exists
        if YAML_AVAILABLE and PERMISSIONS_FILE.exists():
            try:
                with open(PERMISSIONS_FILE, "r") as f:
                    data = yaml.safe_load(f) or {}

                for tool_name, tool_data in data.get("tools", {}).items():
                    if tool_name not in permissions.tools:
                        permissions.tools[tool_name] = ToolPermission()

                    perm = permissions.tools[tool_name]
                    perm.level = PermissionLevel(tool_data.get("level", "ask"))
                    perm.allowed_patterns = tool_data.get("allowed_patterns", perm.allowed_patterns)
                    perm.denied_patterns = tool_data.get("denied_patterns", perm.denied_patterns)

            except Exception:
                pass  # Use defaults on error

        return permissions

    def save(self):
        """Save permissions to config file."""
        if not YAML_AVAILABLE:
            return

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        data = {"tools": {}}

        for tool_name, perm in self.tools.items():
            data["tools"][tool_name] = {
                "level": perm.level.value,
                "allowed_patterns": perm.allowed_patterns,
                "denied_patterns": perm.denied_patterns,
            }

        with open(PERMISSIONS_FILE, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    def check_permission(
        self,
        tool_name: str,
        command: Optional[str] = None
    ) -> tuple[PermissionLevel, Optional[str]]:
        """
        Check if a tool/command is allowed.

        Returns:
            (PermissionLevel, reason) - The permission level and optional reason
        """
        tool_perm = self.tools.get(tool_name, ToolPermission())

        # Check session permissions first (for commands)
        if command:
            # Session denied takes priority
            for pattern in self.session_denied:
                if self._match_command(command, pattern):
                    return PermissionLevel.DENY, f"Denied this session: {pattern}"

            # Session allowed
            for pattern in self.session_allowed:
                if self._match_command(command, pattern):
                    return PermissionLevel.ALLOW, f"Allowed this session: {pattern}"

            # Check denied patterns (dangerous commands)
            for pattern in tool_perm.denied_patterns:
                if self._match_command(command, pattern):
                    return PermissionLevel.DENY, f"Matches dangerous pattern: {pattern}"

            # Check allowed patterns (safe commands)
            for pattern in tool_perm.allowed_patterns:
                if self._match_command(command, pattern):
                    return PermissionLevel.ALLOW, f"Matches safe pattern: {pattern}"

        # Fall back to tool-level permission
        return tool_perm.level, None

    def _match_command(self, command: str, pattern: str) -> bool:
        """Check if a command matches a pattern."""
        command = command.strip().lower()
        pattern = pattern.strip().lower()

        # Handle wildcard patterns
        if "*" in pattern:
            # Convert glob to regex
            regex = fnmatch.translate(pattern)
            return bool(re.match(regex, command))

        # Exact match or prefix match
        return command == pattern or command.startswith(pattern + " ")

    def add_allowed_pattern(self, tool_name: str, pattern: str, session_only: bool = False):
        """Add a pattern to the allowed list."""
        if session_only:
            if pattern not in self.session_allowed:
                self.session_allowed.append(pattern)
        else:
            if tool_name not in self.tools:
                self.tools[tool_name] = ToolPermission()
            if pattern not in self.tools[tool_name].allowed_patterns:
                self.tools[tool_name].allowed_patterns.append(pattern)
                self.save()

    def add_denied_pattern(self, tool_name: str, pattern: str, session_only: bool = False):
        """Add a pattern to the denied list."""
        if session_only:
            if pattern not in self.session_denied:
                self.session_denied.append(pattern)
        else:
            if tool_name not in self.tools:
                self.tools[tool_name] = ToolPermission()
            if pattern not in self.tools[tool_name].denied_patterns:
                self.tools[tool_name].denied_patterns.append(pattern)
                self.save()

    def set_tool_permission(self, tool_name: str, level: PermissionLevel):
        """Set the default permission level for a tool."""
        if tool_name not in self.tools:
            self.tools[tool_name] = ToolPermission()
        self.tools[tool_name].level = level
        self.save()

    def clear_session_permissions(self):
        """Clear session-only permissions."""
        self.session_allowed.clear()
        self.session_denied.clear()


# Global permissions instance
_permissions: Optional[Permissions] = None


def get_permissions() -> Permissions:
    """Get the global permissions instance."""
    global _permissions
    if _permissions is None:
        _permissions = Permissions.load()
    return _permissions


def reset_permissions():
    """Reset permissions to defaults."""
    global _permissions
    _permissions = None
    if PERMISSIONS_FILE.exists():
        PERMISSIONS_FILE.unlink()
