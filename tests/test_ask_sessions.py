"""`devorch ask` sessions (--save-session / --resume / --continue) and the JSON session commands.

These are what the VS Code extension drives: a chat is a series of `ask` runs sharing a session.
"""

import json

import pytest
from typer.testing import CliRunner

from devorch.cli.commands import ask as ask_module
from devorch.cli.main import app
from devorch.core.sessions import SessionManager
from devorch.schemas.message import LLMResponse, Message
from devorch.utils.logger import get_console

runner = CliRunner()


class Replying:
    """A provider that answers 'reply N' and records what history it was sent."""

    name = "fakeprov"
    supports_images = False
    supports_streaming = False

    def __init__(self, model="fake-model"):
        self.model = model
        self.seen: list[list[Message]] = []

    def generate(self, messages, tools=None, stream=False):
        self.seen.append(list(messages))
        n = sum(1 for m in messages if m.role == "assistant") + 1
        return LLMResponse(message=Message(role="assistant", content=f"reply {n}"))


@pytest.fixture(autouse=True)
def _restore_console():
    # `--output json` points the shared Rich console at the runner's stderr, which closes after each call
    console = get_console()
    before = console._file  # None means 'whatever sys.stdout is right now'
    yield
    console._file = before


@pytest.fixture()
def provider(monkeypatch):
    p = Replying()
    monkeypatch.setattr(ask_module, "create_provider", lambda name, model, settings: p)
    monkeypatch.setattr(ask_module, "build_tools", lambda *a, **k: [])
    return p


def ask(*args):
    result = runner.invoke(app, ["ask", "--output", "json", "--mode", "auto", *args])
    return result, (json.loads(result.stdout) if result.stdout.strip() else None)


def test_a_plain_ask_saves_nothing_and_has_no_session_id(provider):
    result, data = ask("hello")
    assert result.exit_code == 0 and data["result"] == "reply 1"
    assert data["session_id"] is None


def test_save_session_returns_an_id_that_resume_continues(provider):
    _, first = ask("--save-session", "first question")
    sid = first["session_id"]
    assert sid and SessionManager().session_exists(sid)

    result, second = ask("--resume", sid, "second question")
    assert result.exit_code == 0
    assert second["session_id"] == sid
    assert second["result"] == "reply 2"  # it saw the earlier assistant reply
    sent = [m.content for m in provider.seen[-1] if m.role == "user"]
    assert "first question" in " ".join(sent) and "second question" in " ".join(sent)


def test_resume_uses_the_sessions_provider_and_model(provider, monkeypatch):
    _, first = ask("--save-session", "hi")
    seen = {}

    def spy(name, model, settings):
        seen.update(name=name, model=model)
        return provider

    monkeypatch.setattr(ask_module, "create_provider", spy)
    ask("--resume", first["session_id"], "again")
    assert seen == {"name": "fakeprov", "model": "fake-model"}


def test_an_unknown_session_is_a_clear_error(provider, capsys):
    result = runner.invoke(app, ["ask", "--resume", "nope1234", "hi"])
    assert result.exit_code == 1
    assert "not found" in capsys.readouterr().out + result.output + result.stderr


def test_continue_picks_up_the_latest_session_in_this_directory(provider):
    _, first = ask("--save-session", "remember me")
    _, second = ask("--continue", "and now?")
    assert second["session_id"] == first["session_id"]


def test_continue_with_nothing_to_continue_starts_a_session(provider, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # a directory with no history
    _, data = ask("--continue", "hello")
    assert data["session_id"] and data["result"] == "reply 1"


def test_sessions_list_and_messages_as_json(provider):
    _, first = ask("--save-session", "what is a monad")
    ask("--resume", first["session_id"], "explain simpler")

    listed = runner.invoke(app, ["sessions", "list", "--output", "json"])
    rows = json.loads(listed.stdout)
    row = next(r for r in rows if r["id"] == first["session_id"])
    assert row["title"].startswith("what is a monad")
    assert row["provider"] == "fakeprov" and row["messages"] >= 4

    shown = runner.invoke(app, ["sessions", "messages", first["session_id"]])
    msgs = json.loads(shown.stdout)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "what is a monad" and msgs[3]["content"] == "reply 2"


def test_sessions_messages_for_an_unknown_id_fails():
    result = runner.invoke(app, ["sessions", "messages", "nope1234"])
    assert result.exit_code == 1


def test_skills_as_json():
    result = runner.invoke(app, ["skills", "--output", "json"])
    rows = json.loads(result.stdout)
    assert result.exit_code == 0 and rows
    assert {"name", "description", "source"} <= set(rows[0])
    assert "commit" in [r["name"] for r in rows]


def test_text_mode_tells_you_how_to_continue(provider, capsys):
    result = runner.invoke(app, ["ask", "--mode", "auto", "--save-session", "hello"])
    out = capsys.readouterr().out + result.output
    sid = SessionManager().latest_session_id()
    assert result.exit_code == 0 and f"devorch ask --resume {sid}" in out
