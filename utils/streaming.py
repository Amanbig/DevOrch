"""Live rendering of streamed model output."""

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from utils.logger import mark_streamed, response_panel


class StreamRenderer:
    """Shows a spinner until the first token arrives, then renders the text live as Markdown.

    Usage::

        with StreamRenderer(console, "[bold blue]DevOrch is thinking...") as r:
            response = provider.generate(messages, on_text=r.write)
        r.finish(is_final_answer=not response.tool_calls)
    """

    def __init__(self, console: Console, status_msg: str = "[bold blue]DevOrch is thinking..."):
        self.console = console
        self.status_msg = status_msg
        self.text = ""
        self._status = None
        self._live: Live | None = None

    def __enter__(self) -> "StreamRenderer":
        self._status = self.console.status(self.status_msg, spinner="dots")
        self._status.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _stop_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def write(self, delta: str) -> None:
        if not delta:
            return
        if self._live is None:
            self._stop_status()
            self.console.print()
            self._live = Live(
                self._render(delta),
                console=self.console,
                refresh_per_second=10,
                vertical_overflow="visible",
                transient=False,
            )
            self._live.start()
        self.text += delta
        self._live.update(self._render(self.text))

    def _render(self, text: str) -> Panel:
        try:
            body = Markdown(text)
        except Exception:
            body = text
        return response_panel(body)

    def close(self) -> None:
        self._stop_status()
        if self._live is not None:
            self._live.update(self._render(self.text))
            self._live.stop()
            self._live = None
            self.console.print()

    def finish(self, is_final_answer: bool) -> None:
        """Call after the response is complete. Final answers were already shown live, so tell
        ``print_response`` not to print them a second time."""
        self.close()
        if is_final_answer and self.text.strip():
            mark_streamed(self.text)
