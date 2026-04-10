"""
Static UI constants for DevOrch CLI.

Centralises VERSION, banners, slash-command registry, prompt/questionary
styles, and the slash-command autocompleter so main.py stays focused on
app wiring and REPL logic.
"""

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from questionary import Style as QStyle

from utils.logger import get_console

console = get_console()

# ── Version ──────────────────────────────────────────────────────────────────

VERSION = "0.2.1"

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
    "/help": "Show available commands",
    "/mode": "Show or change mode (plan/auto/ask)",
    "/plan": "Switch to plan mode",
    "/auto": "Switch to auto mode",
    "/ask": "Switch to ask mode (default)",
    "/clear": "Clear conversation history",
    "/session": "Show current session info",
    "/config": "Show configuration settings",
    "/permissions": "Show permission settings",
    "/compact": "Summarize and compact history",
    "/models": "Browse and switch models (interactive)",
    "/model": "Switch model (/model <name> or interactive)",
    "/providers": "Browse and switch providers (interactive)",
    "/provider": "Switch provider (/provider <name> or interactive)",
    "/history": "Show conversation history",
    "/undo": "Undo last message",
    "/save": "Save conversation to file",
    "/status": "Show current provider, model, and mode",
    "/tasks": "Show current task list",
    "/memory": "Show saved memories",
    "/remember": "Save something to memory",
    "/forget": "Delete a memory",
    "/skills": "List available skills",
    "/skill": "Run a skill (e.g. /skill commit)",
    "/mcp": "Show MCP servers | add/stop/start servers inline",
    "/auth": "Set or update API key for current/specified provider",
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
        "prompt-arrow": "#55cc55 bold",
        "": "#ffffff bold",
        "command": "#66ccff bold",
        "description": "#888888",
        "completion-menu": "bg:#252530",
        "completion-menu.completion": "bg:#252530 #cccccc",
        "completion-menu.completion.current": "bg:#334466 #ffffff bold",
        "completion-menu.meta": "bg:#252530 #555555",
        "completion-menu.meta.current": "bg:#334466 #99bbdd",
        "scrollbar.background": "bg:#2a2a3a",
        "scrollbar.button": "bg:#5588bb",
        "bottom-toolbar": "bg:#0e0e18 #556677",
        "bottom-toolbar.text": "bg:#0e0e18 #556677",
    }
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _xml_escape(text: str) -> str:
    """Escape text for use in prompt_toolkit HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands and skill shortcuts in the REPL."""

    def __init__(self, skill_manager=None):
        self._skill_manager = skill_manager

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

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


def print_banner(small: bool = False) -> None:
    """Print the DevOrch banner."""
    if small:
        console.print(f"\n  {BANNER_SMALL} [dim]v{VERSION}[/dim]\n")
    else:
        console.print(BANNER)
        console.print(f"  [dim]v{VERSION}[/dim]")
        console.print()
