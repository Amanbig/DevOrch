import logging

from rich.console import Console
from rich.markdown import Markdown
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
    console.print(f"[bold red]  Error: {msg}[/bold red]")


def print_warning(msg: str):
    """Prints a warning message in bold yellow."""
    console.print(f"[bold yellow]  Warning: {msg}[/bold yellow]")


def print_success(msg: str):
    """Prints a success message in bold green."""
    console.print(f"[bold green]  {msg}[/bold green]")


def print_info(msg: str):
    """Prints an info message in blue."""
    console.print(f"[blue]  {msg}[/blue]")


def print_response(content: str):
    """Print an AI response with markdown rendering and a cyan-tinted border."""
    console.print()
    try:
        md = Markdown(content)
        console.print(
            Panel(
                md,
                border_style="#3a6a8a",
                padding=(1, 2),
                expand=True,
            )
        )
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
