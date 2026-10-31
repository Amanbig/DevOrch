"""Layout tests for the boxed prompt, checked on a virtual terminal screen."""

import pytest

from cli.constants import PROMPT_STYLE, SlashCommandCompleter
from cli.prompt_ui import (
    create_prompt_keybindings,
    placeholder_for,
    prompt_continuation,
    prompt_message,
    toolbar_text,
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


def _rgb(hex6: str) -> tuple[int, int, int]:
    return int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)


def _is_greyish(hex6: str, tolerance: int = 24) -> bool:
    r, g, b = _rgb(hex6)
    return max(r, g, b) - min(r, g, b) <= tolerance


def _brightness(hex6: str) -> int:
    return sum(_rgb(hex6)) // 3


def test_border_is_grey_and_only_the_label_carries_the_mode_colour():
    borders, labels = set(), {}
    for mode in AgentMode:
        screen = render_screen("x", **common(Holder(mode)))
        assert screen.display[0].startswith(f"╭─ {mode.value.upper()} ─")
        borders.add(screen.buffer[0][0].fg)  # the "╭"
        labels[mode] = screen.buffer[0][3].fg  # first letter of the label
        rule = screen.buffer[0][20].fg  # a cell in the rule
        assert rule == screen.buffer[0][0].fg, "rule and corner should share the border colour"
    # (the virtual terminal is 256-colour, so exact hex values are mapped to the nearest palette entry)
    assert len(borders) == 1, borders  # one border colour for every mode...
    assert _is_greyish(borders.pop())  # ...and it is a quiet grey, not blue
    assert len(set(labels.values())) == 3, labels  # the mode is still told apart by its label
    assert not any(_is_greyish(c) for c in labels.values()), labels  # labels are coloured


def test_multiline_input_keeps_the_gutter_and_alignment():
    lines = render_live("first\x0asecond\x0athird", **common(Holder()))
    assert lines[1:4] == ["│ > first", "│   second", "│   third"]


def test_wrapped_long_line_keeps_the_gutter():
    lines = render_live("word " * 18, **common(Holder()))
    assert lines[1].startswith("│ > word") and lines[2].startswith("│   ")


def test_toolbar_is_a_dark_bar_not_a_bright_reversed_one():
    # regression: prompt_toolkit's default bottom-toolbar style is `reverse`, which turned the dark
    # background/grey text into a bright blue-grey bar with dark text
    screen = render_screen("hello", **common(Holder()))
    cell = screen.buffer[13][5]
    assert not cell.reverse
    assert _brightness(cell.bg) < 60, cell.bg  # dark bar
    assert 90 < _brightness(cell.fg) < 190, cell.fg  # legible muted text
    assert _is_greyish(cell.bg, 30)


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
    assert [style for style, _ in msg][:2] == ["class:border", "class:label-auto bold"]
    assert "".join(t for _, t in msg).startswith("╭─ AUTO ─")
    assert "".join(t for _, t in msg).endswith("\n│ > ")


@pytest.mark.parametrize("mode", list(AgentMode))
def test_continuation_width_matches_prompt_width(mode):
    cont = prompt_continuation(mode)(4, 1, 0)
    assert sum(len(t) for _, t in cont) == 4


# ── regression: the screenshot from a real 80-column terminal ───────────────

REAL = {
    "cwd": "~/Documents/DevOrch",
    "branch": "feat/boxed-input",
    "provider_model": "mistral/ministral-3b-latest",
    "mode": "ask",
    "tokens": 0,
    "context_pct": 0,
}


@pytest.mark.parametrize("cols", [40, 60, 80, 120])
def test_empty_prompt_is_one_line_and_toolbar_shows_the_mode(cols):
    holder = Holder()
    lines = render_live(
        "",
        **{
            **common(holder),
            "cols": cols,
            "message": lambda c=cols: prompt_message(AgentMode.ASK, c),
            "placeholder": lambda c=cols: [("class:placeholder", placeholder_for(c))],
            "bottom_toolbar": lambda c=cols: toolbar_text(**REAL, columns=c),
        },
    )
    assert lines[1].startswith("│ > Ask anything")
    assert lines[2] == "", "placeholder wrapped onto a second line"  # the reported bug
    assert "[ASK]" in lines[-1], "mode clipped off the toolbar"  # the reported bug
    if cols >= 60:
        assert "tok" in lines[-1]


def test_dropdown_stays_open_when_the_command_is_fully_typed():
    # regression: typing `/cos` showed the dropdown but `/cost` hid it
    for text in ("/cos", "/cost", "/models"):
        lines = render_live(
            text,
            rows=12,
            wait=0.5,
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            **common(Holder()),
        )
        menu = [line for line in lines[2:] if line.strip()]
        assert menu, f"dropdown vanished at {text!r}"
        assert menu[0].strip().startswith(text[1:]), menu
