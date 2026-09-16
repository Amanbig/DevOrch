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
    "/undo": "Undo last message and agent turn",
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
    "/tokens": "Show session token usage, prompt/completion split, and costs",
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
