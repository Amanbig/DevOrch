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


def render_screen(
    keys: str,
    cols=60,
    rows=14,
    wait=0.15,
    limit=8.0,
    poll=0.02,
    quiet_polls=8,
    **kwargs,
) -> pyte.Screen:
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

                async def settle():
                    # A fixed sleep is racy on slow CI runners (the snapshot can land before the
                    # first frame is drawn). Wait at least `wait`, then until the output has stopped
                    # changing for a while, and give up (clearly) after `limit` seconds.
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + limit
                    await asyncio.sleep(wait)
                    last, quiet = -1, 0
                    while loop.time() < deadline:
                        size = len(buf.getvalue())
                        quiet = quiet + 1 if size and size == last else 0
                        last = size
                        if quiet >= quiet_polls:
                            break
                        await asyncio.sleep(poll)
                    snap.append(buf.getvalue())
                    app.exit(result="")

                asyncio.ensure_future(settle())

            session.prompt(kwargs.get("message", "> "), pre_run=pre_run)
    if not snap or not snap[0]:
        raise AssertionError(f"nothing was rendered within {limit}s (keys={keys!r})")
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
