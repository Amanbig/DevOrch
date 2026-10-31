"""Test helper: render a live prompt_toolkit prompt into a virtual terminal (pyte).

This lets tests assert on what the user would actually see (layout, gutters, wrapping, colours),
not just on strings handed to prompt_toolkit.
"""

import asyncio
import io

import pyte
from prompt_toolkit import PromptSession
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output


def render_screen(keys: str, cols=60, rows=14, wait=0.15, **kwargs) -> pyte.Screen:
    """Type ``keys`` (without Enter) and snapshot the screen while the prompt is still active."""

    class Buf(io.StringIO):
        encoding = "utf-8"

    buf = Buf()
    snap = []
    with create_pipe_input() as inp:
        inp.send_text("\x1b[1;1R" + keys)  # a real terminal answers the cursor-position query
        out = Vt100_Output(buf, lambda: Size(rows=rows, columns=cols), term="xterm-256color")
        with create_app_session(input=inp, output=out):
            session = PromptSession(**{k: v for k, v in kwargs.items() if k != "message"})

            def pre_run():
                app = session.app
                loop = asyncio.get_event_loop()

                def finish():
                    snap.append(buf.getvalue())
                    app.exit(result="")

                loop.call_later(wait, finish)

            session.prompt(kwargs.get("message", "> "), pre_run=pre_run)
    screen = pyte.Screen(cols, rows)
    pyte.Stream(screen).feed(snap[0])
    return screen


def render_live(keys: str, **kwargs) -> list[str]:
    """Visible lines (right-stripped, trailing blanks dropped)."""
    screen = render_screen(keys, **kwargs)
    lines = [row.rstrip() for row in screen.display]
    while lines and not lines[-1]:
        lines.pop()
    return lines
