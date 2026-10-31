"""`devorch doctor`: a read-only health report you can paste into a bug report.

Each check returns one or more ``Check`` rows and never prints a secret (API keys are only reported as
"set" or "missing"). A check that raises becomes a failed row instead of crashing the report.
"""

import locale
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
KEYLESS_PROVIDERS = {"local", "lmstudio"}  # run locally, no API key needed


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | info
    detail: str
    hint: str = ""


def check_runtime() -> list[Check]:
    from cli.constants import VERSION

    return [
        Check("DevOrch", INFO, f"v{VERSION}"),
        Check(
            "Python",
            OK if sys.version_info >= (3, 10) else FAIL,
            f"{platform.python_version()} on {platform.system()} {platform.release()} "
            f"({platform.machine()})",
            "" if sys.version_info >= (3, 10) else "DevOrch needs Python 3.10 or newer",
        ),
    ]


def check_config_dir() -> list[Check]:
    from config.settings import CONFIG_DIR, CONFIG_FILE

    if not CONFIG_DIR.exists():
        return [Check("Config folder", INFO, f"{CONFIG_DIR} (created on first run)")]
    writable = os.access(CONFIG_DIR, os.W_OK)
    return [
        Check(
            "Config folder",
            OK if writable else FAIL,
            f"{CONFIG_DIR}" + ("" if writable else " is not writable"),
            "" if writable else "DevOrch cannot save settings, sessions or memory there",
        ),
        Check("Config file", OK if CONFIG_FILE.exists() else INFO, str(CONFIG_FILE)),
    ]


def check_providers(settings) -> list[Check]:
    configured, missing_default = [], None
    for name, cfg in settings.providers.items():
        if name in KEYLESS_PROVIDERS:
            continue
        if cfg.api_key:
            configured.append(f"{name} ({'keychain' if cfg.key_encrypted else 'env/config'})")
    default = settings.default_provider
    rows = [
        Check(
            "API keys",
            OK if configured else WARN,
            ", ".join(configured) if configured else "none found",
            "" if configured else "run `devorch set-key <provider>` or set e.g. OPENAI_API_KEY",
        )
    ]
    if default not in KEYLESS_PROVIDERS and not (
        settings.providers.get(default) and settings.providers[default].api_key
    ):
        missing_default = default
    model = settings.get_default_model(default)
    rows.append(
        Check(
            "Default provider",
            FAIL if missing_default else OK,
            f"{default}"
            + (f" / {model}" if model else "")
            + (" has no API key" if missing_default else ""),
            f"run `devorch set-key {default}` or pick another with `devorch -p <provider>`"
            if missing_default
            else "",
        )
    )
    return rows


def check_keyring() -> list[Check]:
    from config.settings import keyring_available

    ok = keyring_available()
    return [
        Check(
            "OS keychain",
            OK if ok else WARN,
            "available" if ok else "not available",
            "" if ok else "API keys can only come from environment variables on this machine",
        )
    ]


def check_git(cwd: Path) -> list[Check]:
    exe = shutil.which("git")
    if not exe:
        return [Check("git", WARN, "not installed", "the `git` tool and branch display need it")]
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
        branch = res.stdout.strip() if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        branch = None
    return [
        Check(
            "git", OK, f"{exe}" + (f" (branch: {branch})" if branch else " (not in a repository)")
        )
    ]


def check_clipboard() -> list[Check]:
    for tool in ("pbcopy", "wl-copy", "xclip", "xsel", "clip"):
        if shutil.which(tool):
            return [Check("Clipboard", OK, f"{tool} (used by /copy)")]
    return [
        Check(
            "Clipboard",
            INFO,
            "no clipboard tool found",
            "/copy needs xclip, xsel or wl-copy on Linux",
        )
    ]


def check_images() -> list[Check]:
    try:
        import PIL  # noqa: F401

        return [Check("Image downscaling", OK, "Pillow installed")]
    except ImportError:
        return [
            Check(
                "Image downscaling",
                INFO,
                "Pillow not installed",
                'optional: `pip install "devorch[images]"` shrinks large screenshots before sending',
            )
        ]


def check_project(cwd: Path) -> list[Check]:
    from config.project_settings import is_trusted, project_trust_files

    rows = []
    found = [n for n in ("DEVORCH.md", "CLAUDE.md", "AGENTS.md") if (cwd / n).is_file()]
    rows.append(
        Check(
            "Project instructions",
            OK if found else INFO,
            ", ".join(found) if found else "none (create one with `devorch init`)",
        )
    )
    pairs = project_trust_files(cwd)
    if not pairs:
        rows.append(
            Check("Project settings/hooks", INFO, "no .devorch/settings.yaml or hooks.yaml")
        )
    for root in dict.fromkeys(r for r, _ in pairs):
        trusted = is_trusted(root)
        rows.append(
            Check(
                "Project settings/hooks",
                OK if trusted else WARN,
                f"{root}: {'trusted' if trusted else 'NOT trusted (its MCP servers, allow rules, auto mode and hooks are ignored)'}",
                "" if trusted else "review the files, then run `devorch trust`",
            )
        )
    return rows


def check_permissions() -> list[Check]:
    from config.permissions import PermissionLevel, Permissions

    perms = Permissions.load(include_project=False)
    risky = [
        name
        for name in ("shell", "edit", "filesystem", "git")
        if name in perms.tools and perms.tools[name].level == PermissionLevel.ALLOW
    ]
    if risky:
        return [
            Check(
                "Permissions",
                WARN,
                f"{', '.join(risky)} set to allow: DevOrch will not ask before using them",
                "intended? if not, run `devorch permissions reset`",
            )
        ]
    return [
        Check("Permissions", OK, "file edits and commands ask first (unless you choose AUTO mode)")
    ]


def check_mcp(settings) -> list[Check]:
    n = len(settings.mcp_servers)
    return [
        Check(
            "MCP servers",
            INFO,
            f"{n} configured" + (f": {', '.join(settings.mcp_servers)}" if n else ""),
        )
    ]


def check_sessions() -> list[Check]:
    from core.sessions import DB_PATH, SessionManager

    if not DB_PATH.exists():
        return [Check("Sessions", INFO, "no session database yet")]
    sm = SessionManager()
    return [Check("Sessions", OK, f"{sm.count_sessions(include_empty=True)} saved ({DB_PATH})")]


def check_terminal() -> list[Check]:
    enc = (
        getattr(sys.stdout, "encoding", None) or locale.getpreferredencoding(False) or ""
    ).lower()
    utf8 = "utf" in enc
    cols = shutil.get_terminal_size((80, 24)).columns
    color = "off (NO_COLOR set)" if os.environ.get("NO_COLOR") else "on"
    return [
        Check(
            "Terminal",
            OK if sys.stdout.isatty() else INFO,
            f"{'interactive' if sys.stdout.isatty() else 'not a terminal'}, {cols} columns, "
            f"TERM={os.environ.get('TERM', '-')}, colour {color}",
        ),
        Check(
            "Text encoding",
            OK if utf8 else WARN,
            enc or "unknown",
            ""
            if utf8
            else "box-drawing characters and symbols may render as garbage; use a UTF-8 terminal",
        ),
    ]


def run_checks(cwd: Path | None = None, settings=None) -> list[Check]:
    """Run every check; a check that raises becomes a failed row."""
    from config.settings import Settings

    cwd = cwd or Path.cwd()
    settings = settings or Settings.load()
    plan: list[tuple[str, Callable[[], list[Check]]]] = [
        ("Runtime", check_runtime),
        ("Config", check_config_dir),
        ("Providers", lambda: check_providers(settings)),
        ("Keychain", check_keyring),
        ("Permissions", check_permissions),
        ("Project", lambda: check_project(cwd)),
        ("MCP", lambda: check_mcp(settings)),
        ("Sessions", check_sessions),
        ("git", lambda: check_git(cwd)),
        ("Clipboard", check_clipboard),
        ("Images", check_images),
        ("Terminal", check_terminal),
    ]
    rows: list[Check] = []
    for label, fn in plan:
        try:
            rows.extend(fn())
        except Exception as e:  # a broken check must not hide the rest of the report
            rows.append(Check(label, FAIL, f"check crashed: {type(e).__name__}: {e}"))
    return rows


def exit_code(rows: list[Check]) -> int:
    return 1 if any(r.status == FAIL for r in rows) else 0
