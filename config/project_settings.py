"""
Per-project settings — ``<project>/.devorch/settings.yaml`` — so a team can commit shared defaults.

    default_mode: ask            # ask | auto | plan
    default_provider: anthropic
    providers:
      anthropic:
        default_model: claude-sonnet-4-20250514
    mcp_servers:                 # merged over ~/.devorch/config.yaml, project wins by name
      github:
        command: npx
        args: ["-y", "@modelcontextprotocol/server-github"]
    permissions:
      shell:
        allow: ["pytest*", "ruff *"]
        deny: ["git push*"]

The same trust gates ``<project>/.devorch/hooks.yaml``: project hooks run arbitrary shell commands,
so they are ignored until trusted. Trust covers settings.yaml and hooks.yaml together.

Precedence: CLI flags > project settings > ~/.devorch config.

A cloned repository must not be able to silently grant itself power, so some keys need *trust*
(``devorch trust``). Trust is bound to a hash of the file, so any later change requires trusting
again. Without trust:
    - ``deny`` patterns, ``default_provider``, models and ``default_mode: ask|plan`` still apply
    - ``mcp_servers`` (they launch programs), ``allow`` patterns and ``default_mode: auto`` are ignored
API keys are never read from project files.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SETTINGS_REL = Path(".devorch") / "settings.yaml"
HOOKS_REL = Path(".devorch") / "hooks.yaml"
VALID_MODES = ("ask", "auto", "plan")


def trust_file() -> Path:
    return Path.home() / ".devorch" / "trusted_projects.yaml"


@dataclass
class ProjectSettings:
    path: Path
    root: Path
    digest: str
    trusted: bool = False
    default_mode: str | None = None
    default_provider: str | None = None
    models: dict[str, str] = field(default_factory=dict)
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    allow: dict[str, list[str]] = field(default_factory=dict)
    deny: dict[str, list[str]] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)

    def effective_mode(self) -> str | None:
        """Mode requested by the project, downgraded to ``ask`` if ``auto`` is untrusted."""
        if self.default_mode == "auto" and not self.trusted:
            return "ask"
        return self.default_mode


def find_settings_file(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` looking for ``.devorch/settings.yaml`` (stops at the home dir)."""
    current = (start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for directory in [current, *current.parents]:
        candidate = directory / SETTINGS_REL
        if candidate.is_file():
            return candidate
        if directory == home:
            break
    return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def project_files_digest(root: Path) -> str:
    """Hash of everything in a project that needs trust: settings.yaml + hooks.yaml.

    A missing file contributes nothing, so a project with only settings.yaml keeps the same
    digest as before hooks were covered.
    """
    return _digest(_read(root / SETTINGS_REL) + _read(root / HOOKS_REL))


def find_hooks_root(start: Path | None = None) -> Path | None:
    """Nearest directory (walking up, stopping at home) that has ``.devorch/hooks.yaml``."""
    current = (start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for directory in [current, *current.parents]:
        if (directory / HOOKS_REL).is_file():
            return directory
        if directory == home:
            break
    return None


def is_trusted(root: Path) -> bool:
    return _load_trust().get(str(root)) == project_files_digest(root)


def trust_root(root: Path) -> None:
    trusted = _load_trust()
    trusted[str(root)] = project_files_digest(root)
    _save_trust(trusted)


def _load_trust() -> dict[str, str]:
    path = trust_file()
    if yaml is None or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return {str(k): str(v) for k, v in (data.get("trusted") or {}).items()}
    except Exception:
        return {}


def _save_trust(trusted: dict[str, str]) -> None:
    path = trust_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"trusted": trusted}, default_flow_style=False))


def trust_project(settings: ProjectSettings) -> None:
    trust_root(settings.root)


def untrust_project(root: Path) -> bool:
    trusted = _load_trust()
    if str(root) not in trusted:
        return False
    del trusted[str(root)]
    _save_trust(trusted)
    return True


def _str_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str | int | float)]
    return []


def load_project_settings(start: Path | None = None) -> ProjectSettings | None:
    path = find_settings_file(start)
    if path is None or yaml is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except Exception as e:
        ps = ProjectSettings(path=path, root=path.parent.parent, digest="")
        ps.notices.append(f"could not read {path}: {e}")
        return ps
    if not isinstance(data, dict):
        data = {}

    root = path.parent.parent
    digest = project_files_digest(root)
    ps = ProjectSettings(path=path, root=root, digest=digest, trusted=is_trusted(root))

    mode = data.get("default_mode")
    if mode is not None:
        if str(mode).lower() in VALID_MODES:
            ps.default_mode = str(mode).lower()
        else:
            ps.notices.append(f"ignored invalid default_mode {mode!r}")

    if isinstance(data.get("default_provider"), str):
        ps.default_provider = data["default_provider"]

    for name, cfg in (data.get("providers") or {}).items():
        if isinstance(cfg, dict) and cfg.get("default_model"):
            ps.models[str(name)] = str(cfg["default_model"])
        if isinstance(cfg, dict) and ("api_key" in cfg):
            ps.notices.append(f"ignored api_key for {name}: keys are never read from project files")

    for name, cfg in (data.get("mcp_servers") or {}).items():
        if isinstance(cfg, dict) and cfg.get("command"):
            ps.mcp_servers[str(name)] = cfg

    for tool, rules in (data.get("permissions") or {}).items():
        if not isinstance(rules, dict):
            continue
        allow, deny = _str_list(rules.get("allow")), _str_list(rules.get("deny"))
        if allow:
            ps.allow[str(tool)] = allow
        if deny:
            ps.deny[str(tool)] = deny

    if not ps.trusted:
        ignored = []
        if ps.mcp_servers:
            ignored.append("mcp_servers")
        if ps.allow:
            ignored.append("permission allow rules")
        if ps.default_mode == "auto":
            ignored.append("default_mode: auto (using ask)")
        if ignored:
            ps.notices.append(
                f"project settings ({path}): ignored {', '.join(ignored)} — "
                f"review the file, then run `devorch trust` to enable"
            )
    return ps
