"""Layout tests for the boxed prompt, checked on a virtual terminal screen."""

import pytest

from cli.constants import PROMPT_STYLE, SlashCommandCompleter
from cli.prompt_ui import (
    create_prompt_keybindings,
    prompt_continuation,
    prompt_message,
)
from core.modes import AgentMode
from tests._screen import render_live, render_screen

COLS = 50


class Holder:
    def __init__(self, mode=AgentMode.ASK):
        self.mode = mode


def common(holder: Holder, **extra):
    return {
        "cols": COLS,
        "style": PROMPT_STYLE,
        "message": lambda: prompt_message(holder.mode, COLS),
        "prompt_continuation": lambda w, n, c: prompt_continuation(holder.mode)(w, n, c),
        "key_bindings": create_prompt_keybindings(lambda: setattr(holder, "mode", AgentMode.AUTO)),
        "bottom_toolbar": lambda: " status bar",
        **extra,
    }


def test_single_line_layout():
    lines = render_live("hello", **common(Holder()))
    assert lines[0].startswith("╭─ ASK ─")
    assert lines[1] == "│ > hello"
    assert lines[-1] == " status bar"


def test_top_rule_never_reaches_the_last_column():
    # filling the full width would wrap the rule onto an extra blank line
    for cols in (20, 50, 80):
        top = render_live(
            "x",
            **{
                **common(Holder()),
                "cols": cols,
                "message": lambda c=cols: prompt_message(AgentMode.ASK, c),
            },
        )[0]
        assert len(top) == cols - 1


def test_each_mode_has_its_own_label_and_colour():
    colours = {}
    for mode in AgentMode:
        screen = render_screen("x", **common(Holder(mode)))
        assert screen.display[0].startswith(f"╭─ {mode.value.upper()} ─")
        colours[mode] = screen.buffer[0][0].fg  # colour of the "╭"
    assert len(set(colours.values())) == 3, colours  # visibly different per mode
    assert all(c != "default" for c in colours.values())


def test_multiline_input_keeps_the_gutter_and_alignment():
    lines = render_live("first\x0asecond\x0athird", **common(Holder()))
    assert lines[1:4] == ["│ > first", "│   second", "│   third"]


def test_wrapped_long_line_keeps_the_gutter():
    lines = render_live("word " * 18, **common(Holder()))
    assert lines[1].startswith("│ > word") and lines[2].startswith("│   ")


def test_gutter_colour_matches_border_colour():
    screen = render_screen("a\x0ab", **common(Holder(AgentMode.PLAN)))
    assert screen.buffer[0][0].fg == screen.buffer[2][0].fg  # "╭" and the continuation "│"


def test_shift_tab_updates_the_box():
    holder = Holder(AgentMode.ASK)
    lines = render_live("hi\x1b[Z", **common(holder))
    assert holder.mode == AgentMode.AUTO
    assert lines[0].startswith("╭─ AUTO ─")


def test_completion_menu_renders_under_the_box():
    lines = render_live(
        "/m\t",
        rows=16,
        wait=0.6,
        completer=SlashCommandCompleter(),
        complete_while_typing=False,
        **common(Holder()),
    )
    assert lines[1] == "│ > /m"
    assert any(line.strip().startswith("mode") for line in lines[2:])


def test_toolbar_stays_at_the_bottom():
    lines = render_live("hello", **common(Holder()))
    assert lines[-1] == " status bar" and len(lines) == 14


def test_placeholder_shown_when_empty():
    from cli.prompt_ui import PLACEHOLDER

    lines = render_live("", **common(Holder(), placeholder=PLACEHOLDER))
    assert lines[1].startswith("│ > Ask anything")


def test_tiny_terminal_does_not_crash():
    lines = render_live(
        "hi", **{**common(Holder()), "cols": 8, "message": lambda: prompt_message(AgentMode.ASK, 8)}
    )
    assert lines[0].startswith("╭─ ASK")


def test_prompt_message_is_plain_formatted_text():
    msg = prompt_message(AgentMode.AUTO, 40)
    assert [style for style, _ in msg][0] == "class:border-auto"
    assert "".join(t for _, t in msg).startswith("╭─ AUTO ─")
    assert "".join(t for _, t in msg).endswith("\n│ > ")


@pytest.mark.parametrize("mode", list(AgentMode))
def test_continuation_width_matches_prompt_width(mode):
    cont = prompt_continuation(mode)(4, 1, 0)
    assert sum(len(t) for _, t in cont) == 4
