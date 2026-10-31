import logging

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel

# Global rich console instance
console = Console()


def setup_logger(name: str) -> logging.Logger:
    """Sets up a standard python logger if needed for file logging, etc."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def print_error(msg: str):
    """Prints an error message in bold red."""
    console.print(f"[bold red]  Error: {escape(str(msg))}[/bold red]")


def print_warning(msg: str):
    """Prints a warning message in bold yellow."""
    console.print(f"[bold yellow]  Warning: {escape(str(msg))}[/bold yellow]")


def print_success(msg: str):
    """Prints a success message in bold green."""
    console.print(f"[bold green]  {escape(str(msg))}[/bold green]")


def print_info(msg: str):
    """Prints an info message in blue."""
    console.print(f"[blue]  {escape(str(msg))}[/blue]")


# Neutral grey (no blue tint) behind assistant replies
RESPONSE_BG = "#262626"

_streamed_text: str | None = None


def mark_streamed(text: str) -> None:
    """Record text that was already shown live, so print_response doesn't repeat it."""
    global _streamed_text
    _streamed_text = text.strip()


def response_panel(body) -> Panel:
    """The panel used for assistant responses (grey background, invisible border)."""
    return Panel(
        body,
        style=f"on {RESPONSE_BG}",
        border_style=RESPONSE_BG,  # invisible border, blends with the panel
        padding=(1, 2),
        expand=True,
    )


def print_response(content: str):
    """Print an AI response with a subtle grey background, no border."""
    global _streamed_text
    if _streamed_text is not None:
        already_shown = content.strip() == _streamed_text
        _streamed_text = None
        if already_shown:
            return
    console.print()
    try:
        console.print(response_panel(Markdown(content)))
    except Exception:
        console.print(f"  {content}")
    console.print()


def print_panel(content, title: str = "", border_style: str = "blue", fit: bool = False):
    """Prints a rich Panel."""
    if fit:
        console.print(Panel.fit(content, title=title, border_style=border_style))
    else:
        console.print(Panel(content, title=title, border_style=border_style))


def get_console() -> Console:
    """Returns the global rich Console instance to be used for status spinners, etc."""
    return console
