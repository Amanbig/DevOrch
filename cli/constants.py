"""
Static UI constants for DevOrch CLI.

Centralises VERSION, banners, slash-command registry, prompt/questionary
styles, and the slash-command autocompleter so main.py stays focused on
app wiring and REPL logic.
"""

import os
import re

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from questionary import Style as QStyle

from utils.logger import get_console

console = get_console()

# ── Version ──────────────────────────────────────────────────────────────────

VERSION = "0.4.0"

# ── Banners ───────────────────────────────────────────────────────────────────

BANNER = """
[bold cyan]  ╔╦╗┌─┐┬  ┬╔═╗┬─┐┌─┐┬ ┬
   ║║├┤ └┐┌┘║ ║├┬┘│  ├─┤
  ═╩╝└─┘ └┘ ╚═╝┴└─└─┘┴ ┴[/bold cyan]"""

BANNER_SMALL = "[bold cyan]DevOrch[/bold cyan]"

# ── Slash commands registry ───────────────────────────────────────────────────
# Add new slash commands here — the REPL and autocompleter pick them up
# automatically.

SLASH_COMMANDS: dict[str, str] = {
    "/help": "Show categorized help and command shortcuts",
    "/mode": "Show or switch mode: /mode [plan|auto|ask]",
    "/plan": "Switch to plan mode (requires approval before tool execution)",
    "/auto": "Switch to auto mode (executes approved tools autonomously)",
    "/ask": "Switch to ask mode (default: read and suggest only)",
    "/clear": "Clear conversation history (saves accomplishments to project memory)",
    "/session": "Show current session ID, model, and message count",
    "/config": "Show configuration settings and provider status",
    "/permissions": "Show and manage tool permission settings",
    "/compact": "Summarize and compact conversation history to save tokens",
    "/models": "Search, browse, and switch models (interactive 15/page pagination)",
    "/model": "Switch model directly (/model <name>) or open interactive search",
    "/providers": "Search, browse, and switch providers (interactive pagination)",
    "/provider": "Switch provider directly (/provider <name>) or open interactive search",
    "/history": "Show full conversation history in this session",
    "/undo": "Undo last message and agent turn (also restores files it edited)",
    "/checkpoints": "List files changed by the agent this session, per turn",
    "/save": "Save conversation history to a file",
    "/status": "Show active provider, model, execution mode, and loaded context",
    "/tasks": "Show active multi-step task list and execution progress",
    "/memory": "Show project memory (/memory add <dec>, /memory pref <p>, /memory clear)",
    "/remember": "Save something to global memory (/remember <note>)",
    "/forget": "Delete a memory (/forget or /forget <name>)",
    "/skills": "List available built-in and custom skills",
    "/skill": "Run a skill directly (/skill <name>)",
    "/mcp": "Show MCP servers (/mcp add, /mcp stop, /mcp start)",
    "/auth": "Set or update API key for current or specified provider",
    "/tokens": "Show session token usage, prompt/completion split, and compaction stats",
    "/cost": "Show estimated session cost per model (prices are approximate, overridable)",
    "/copy": "Copy the last assistant response to clipboard",
    "/paste": "Enter multi-line paste mode to input large text or code",
    "/init": "Generate or update a DEVORCH.md project context file",
}

# ── Questionary style (provider/model selection prompts) ─────────────────────

QUESTIONARY_STYLE = QStyle(
    [
        ("qmark", "fg:#55aaff bold"),
        ("question", "fg:#ffffff bold"),
        ("answer", "fg:#44ddaa bold"),
        ("pointer", "fg:#55ccff bold"),
        ("highlighted", "fg:#55ccff bold"),
        ("selected", "fg:#55ccff"),
        ("text", "fg:#bbbbbb"),
        ("disabled", "fg:#555555"),
        ("instruction", "fg:#666666 italic"),
        ("separator", "fg:#444444"),
    ]
)

# ── prompt_toolkit style (REPL input + completion menu) ──────────────────────

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "#55cc55 bold",
        "prompt-mode": "#55aaff bold",
        "prompt-arrow": "#55cc55 bold",
        "placeholder": "#555566 italic",
        "border": "#4b5160",
        "label-ask": "#6a9fd8",
        "label-auto": "#d98e3a",
        "label-plan": "#c9b24a",
        "": "#ffffff bold",
        "command": "#66ccff bold",
        "description": "#888888",
        "completion-menu": "bg:#262626",
        "completion-menu.completion": "bg:#262626 #cccccc",
        "completion-menu.completion.current": "bg:#3c3c3c #ffffff bold",
        "completion-menu.meta": "bg:#262626 #707070",
        "completion-menu.meta.current": "bg:#3c3c3c #b0b0b0",
        "scrollbar.background": "bg:#2e2e2e",
        "scrollbar.button": "bg:#707070",
        # `noreverse` is needed: prompt_toolkit's default bottom-toolbar style is `reverse`, which
        # swapped these colours into a bright blue-grey bar with dark text.
        "bottom-toolbar": "bg:#14141c #7d8494 noreverse",
        "bottom-toolbar.text": "bg:#14141c #7d8494 noreverse",
    }
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _xml_escape(text: str) -> str:
    """Escape text for use in prompt_toolkit HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands, skill shortcuts and @file mentions in the REPL."""

    @staticmethod
    def _path_completions(partial: str):
        for comp, is_dir in _path_completions_for(partial):
            yield Completion(
                comp,
                start_position=-len(partial),
                display_meta="directory" if is_dir else "file",
            )

    def __init__(self, skill_manager=None):
        self._skill_manager = skill_manager

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        at = re.search(r"(?<![\w@])@([^\s@]*)$", text)
        if at:
            yield from self._path_completions(at.group(1))
            return

        if not text.startswith("/"):
            return

        partial = text.lower()

        for cmd, desc in SLASH_COMMANDS.items():
            if cmd.startswith(partial):
                padded_cmd = cmd[1:].ljust(16)
                safe_desc = _xml_escape(desc)
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=HTML(
                        f"<command>{padded_cmd}</command><description>{safe_desc}</description>"
                    ),
                    display_meta=desc,
                )

        if self._skill_manager:
            for skill in self._skill_manager.list_skills():
                skill_cmd = f"/{skill['name']}"
                if skill_cmd.startswith(partial) and skill_cmd not in SLASH_COMMANDS:
                    padded_cmd = skill["name"].ljust(16)
                    safe_desc = _xml_escape(skill["description"])
                    yield Completion(
                        skill_cmd,
                        start_position=-len(text),
                        display=HTML(
                            f"<command>{padded_cmd}</command><description>{safe_desc}</description>"
                        ),
                        display_meta=f"skill: {skill['description']}",
                    )


def _path_completions_for(partial: str, limit: int = 30):
    """Yield (completion_text, is_dir) for paths matching a partial @mention."""
    base = os.path.dirname(partial)
    prefix = os.path.basename(partial)
    directory = os.path.expanduser(base) if base else "."
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    count = 0
    for name in names:
        if not name.startswith(prefix) or (name.startswith(".") and not prefix.startswith(".")):
            continue
        full = os.path.join(directory, name)
        is_dir = os.path.isdir(full)
        yield os.path.join(base, name) + ("/" if is_dir else ""), is_dir
        count += 1
        if count >= limit:
            return


def print_banner(small: bool = False) -> None:
    """Print the DevOrch banner."""
    if small:
        console.print(f"\n  {BANNER_SMALL} [dim]v{VERSION}[/dim]\n")
    else:
        console.print(BANNER)
        console.print(f"  [dim]v{VERSION}[/dim]")
        console.print()
