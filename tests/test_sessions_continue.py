"""Sessions remember their directory; --continue / picker / /resume build on that."""

import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from cli import repl_commands as rc
from cli.repl_commands import (
    ALL_DIRECTORIES,
    PICK_SESSION,
    handle_resume,
    last_exchange_preview,
    pick_session,
    resolve_startup_session,
)
from core import sessions as sessions_mod
from core.sessions import SessionManager, normalize_dir
from schemas.message import Message


@pytest.fixture
def sm():
    return SessionManager()


def talk(sm, sid, *texts):
    """Add alternating user/assistant messages to a session."""
    for i, t in enumerate(texts):
        sm.save_message(
            Message(role="user" if i % 2 == 0 else "assistant", content=t), session_id=sid
        )


@pytest.fixture
def dirs(tmp_path):
    a, b = tmp_path / "proj_a", tmp_path / "proj_b"
    a.mkdir()
    b.mkdir()
    return a, b


# ── storage ─────────────────────────────────────────────────────────────────


def test_old_database_is_migrated_and_old_sessions_have_no_directory():
    sessions_mod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sessions_mod.DB_PATH)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, provider TEXT NOT NULL, model TEXT NOT NULL,"
        " parent_session_id TEXT, summary TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO sessions (id, name, provider, model) VALUES ('old1', 'legacy', 'openai', 'gpt-4o')"
    )
    conn.commit()
    conn.close()
    sm = SessionManager()  # must not crash on the old schema
    (row,) = sm.list_sessions()
    assert row["id"] == "old1" and row["cwd"] is None
    new = sm.create_session("openai", "gpt-4o")
    assert any(s["id"] == new and s["cwd"] for s in sm.list_sessions())


def test_session_records_a_normalized_directory(sm, dirs):
    a, _ = dirs
    sid = sm.create_session("openai", "gpt-4o", cwd=a)
    (row,) = [s for s in sm.list_sessions() if s["id"] == sid]
    assert row["cwd"] == normalize_dir(a)


def test_default_directory_is_the_current_one(sm, dirs, monkeypatch):
    a, _ = dirs
    monkeypatch.chdir(a)
    sid = sm.create_session("openai", "gpt-4o")
    assert [s["cwd"] for s in sm.list_sessions() if s["id"] == sid] == [normalize_dir(a)]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_directory_counts_as_the_same_place(sm, dirs, tmp_path):
    a, _ = dirs
    link = tmp_path / "link_to_a"
    os.symlink(a, link)
    sid = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, sid, "hi")
    assert sm.latest_session_id(link) == sid


def test_listing_filters_by_directory_and_hides_empty_sessions(sm, dirs):
    a, b = dirs
    empty = sm.create_session("openai", "gpt-4o", cwd=a)
    used_a = sm.create_session("openai", "gpt-4o", cwd=a)
    used_b = sm.create_session("openai", "gpt-4o", cwd=b)
    talk(sm, used_a, "hello")
    talk(sm, used_b, "hello")
    ids = lambda **kw: {s["id"] for s in sm.list_sessions(**kw)}  # noqa: E731
    assert ids(cwd=a) == {empty, used_a}
    assert ids(cwd=a, include_empty=False) == {used_a}
    assert ids(include_empty=False) == {used_a, used_b}
    assert sm.count_sessions(cwd=a) == 1 and sm.count_sessions() == 2
    assert sm.count_sessions(include_empty=True) == 3


def test_latest_session_ignores_a_newer_empty_one(sm, dirs):
    # DevOrch creates a session at startup even if nothing is typed; --continue must skip those
    a, _ = dirs
    real = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, real, "real work")
    sm.create_session("openai", "gpt-4o", cwd=a)  # opened and closed again: empty and newer
    assert sm.latest_session_id(a) == real


def test_latest_session_is_per_directory_and_skips_unknown_directories(sm, dirs):
    a, b = dirs
    in_a = sm.create_session("openai", "gpt-4o", cwd=a)
    in_b = sm.create_session("openai", "gpt-4o", cwd=b)
    talk(sm, in_a, "x")
    talk(sm, in_b, "y")
    conn = sqlite3.connect(sessions_mod.DB_PATH)
    conn.execute("INSERT INTO sessions (id, provider, model, cwd) VALUES ('nodir','p','m',NULL)")
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES ('nodir','user','legacy')"
    )
    conn.commit()
    conn.close()
    assert sm.latest_session_id(a) == in_a and sm.latest_session_id(b) == in_b
    assert sm.latest_session_id(a / "nowhere") is None


def test_most_recently_used_wins(sm, dirs):
    a, _ = dirs
    first = sm.create_session("openai", "gpt-4o", cwd=a)
    second = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, first, "a")
    talk(sm, second, "b")
    assert sm.latest_session_id(a) == second
    sm.save_message(Message(role="user", content="more"), session_id=first)  # touch the older one
    assert sm.latest_session_id(a) == first


def test_continuation_sessions_keep_the_directory(sm, dirs, monkeypatch):
    a, _ = dirs
    monkeypatch.chdir(a)
    sm.create_session("openai", "gpt-4o")
    new = sm.create_continuation_session("openai", "gpt-4o", "summary")
    assert [s["cwd"] for s in sm.list_sessions() if s["id"] == new] == [normalize_dir(a)]


def test_messages_load_in_the_order_they_were_saved(sm):
    sid = sm.create_session("openai", "gpt-4o")
    texts = [f"m{i}" for i in range(30)]  # all saved within the same second
    talk(sm, sid, *texts)
    _, messages = sm.load_session(sid)
    assert [m.content for m in messages] == texts


def test_first_user_message_is_a_flat_title(sm):
    sid = sm.create_session("openai", "gpt-4o")
    talk(sm, sid, "fix the\nlogin   bug in @auth.py\n\nAttached context:\n\n<file>...</file>", "ok")
    assert sm.first_user_message(sid) == "fix the login bug in @auth.py"
    assert sm.first_user_message("missing") == ""
    long = sm.create_session("openai", "gpt-4o")
    talk(sm, long, "word " * 100)
    assert len(sm.first_user_message(long, limit=30)) == 30 and sm.first_user_message(
        long, limit=30
    ).endswith("…")


# ── choosing a session ──────────────────────────────────────────────────────


class Chooser:
    """Records what the picker offered and answers with a scripted choice."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.offered = []

    def __call__(self, title, choices):
        self.offered.append((title, choices))
        answer = self.answers.pop(0)
        return answer(choices) if callable(answer) else answer


def first(choices):
    return choices[0][1]


def test_picker_shows_this_directory_with_an_option_for_all(sm, dirs):
    a, b = dirs
    s1 = sm.create_session("openai", "gpt-4o", cwd=a)
    s2 = sm.create_session("openai", "gpt-4o", cwd=b)
    talk(sm, s1, "in a")
    talk(sm, s2, "in b")
    chooser = Chooser(first)
    assert pick_session(sm, a, chooser) == s1
    title, choices = chooser.offered[0]
    assert "this directory" in title
    values = [v for _, v in choices]
    assert values == [s1, ALL_DIRECTORIES]
    assert "in a" in choices[0][0] and "in b" not in choices[0][0]


def test_picker_can_widen_to_all_directories(sm, dirs):
    a, b = dirs
    s1 = sm.create_session("openai", "gpt-4o", cwd=a)
    s2 = sm.create_session("openai", "gpt-4o", cwd=b)
    talk(sm, s1, "in a")
    talk(sm, s2, "in b")
    chooser = Chooser(ALL_DIRECTORIES, lambda choices: choices[-1][1])
    picked = pick_session(sm, a, chooser)
    assert picked in (s1, s2)
    widened = [v for _, v in chooser.offered[1][1]]
    assert set(widened) == {s1, s2} and ALL_DIRECTORIES not in widened
    assert "this directory" not in chooser.offered[1][0]
    assert "proj_" in chooser.offered[1][1][0][0]  # labels show where each session lives


def test_no_all_option_when_everything_is_already_here(sm, dirs):
    a, _ = dirs
    s1 = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, s1, "x")
    chooser = Chooser(first)
    pick_session(sm, a, chooser)
    assert ALL_DIRECTORIES not in [v for _, v in chooser.offered[0][1]]


def test_picker_falls_back_to_all_when_this_directory_has_none(sm, dirs):
    a, b = dirs
    s2 = sm.create_session("openai", "gpt-4o", cwd=b)
    talk(sm, s2, "elsewhere")
    chooser = Chooser(first)
    assert pick_session(sm, a, chooser) == s2
    assert "this directory" not in chooser.offered[0][0]


def test_picker_with_nothing_saved_or_cancelled(sm, dirs):
    a, _ = dirs
    never = Chooser()
    assert pick_session(sm, a, never) is None and never.offered == []
    sm.create_session("openai", "gpt-4o", cwd=a)  # empty sessions do not count
    assert pick_session(sm, a, never) is None
    s1 = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, s1, "x")
    assert pick_session(sm, a, Chooser(None)) is None


def test_startup_explicit_id_beats_continue(sm, dirs):
    a, _ = dirs
    other = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, other, "x")
    assert resolve_startup_session(sm, "abc123", True, a).session_id == "abc123"


def test_startup_continue(sm, dirs):
    a, _ = dirs
    none = resolve_startup_session(sm, None, True, a)
    assert none.session_id is None and "starting a new session" in none.notice
    s1 = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, s1, "x")
    assert resolve_startup_session(sm, None, True, a).session_id == s1
    assert (
        resolve_startup_session(sm, None, False, a).session_id is None
    )  # plain start: new session


def test_startup_bare_resume_opens_the_picker(sm, dirs):
    a, _ = dirs
    s1 = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, s1, "x")
    assert resolve_startup_session(sm, PICK_SESSION, False, a, Chooser(first)).session_id == s1
    cancelled = resolve_startup_session(sm, PICK_SESSION, False, a, Chooser(None))
    assert cancelled.cancelled and cancelled.session_id is None


def test_startup_bare_resume_with_no_sessions_just_starts_fresh(sm, dirs):
    a, _ = dirs
    choice = resolve_startup_session(sm, PICK_SESSION, False, a, Chooser())
    assert choice.session_id is None and not choice.cancelled and choice.notice


# ── /resume inside the REPL ─────────────────────────────────────────────────


class FakeAgent:
    def __init__(self):
        self.history = [Message(role="user", content="current conversation")]
        self.summary = "unchanged"
        self.provider = SimpleNamespace(name="openai", model="gpt-4o")

    def set_history(self, messages):
        self.history = messages

    def set_context_summary(self, summary):
        self.summary = summary


@pytest.fixture
def repl(sm, dirs):
    a, _ = dirs
    from core.checkpoints import CheckpointManager

    agent = FakeAgent()
    executor = SimpleNamespace(checkpoints=CheckpointManager())
    executor.checkpoints.begin_turn("old")
    executor.checkpoints.snapshot(str(a / "f.txt"))
    return sm, agent, executor, a


def test_resume_switches_history_session_and_resets_per_conversation_state(repl, capsys):
    sm, agent, executor, a = repl
    target = sm.create_session("openai", "gpt-4o", cwd=a, summary="earlier summary")
    talk(sm, target, "first question", "first answer")
    current = sm.create_session("openai", "gpt-4o", cwd=a)
    old_checkpoints = executor.checkpoints
    assert handle_resume(target, sm, agent, executor) is True
    assert sm.current_session_id == target
    assert [m.content for m in agent.history] == ["first question", "first answer"]
    assert agent.summary == "earlier summary"
    assert executor.checkpoints is not old_checkpoints and executor.checkpoints.summary() == []
    assert current != target


def test_resume_notes_a_different_provider_and_keeps_the_current_one(repl, capsys, monkeypatch):
    sm, agent, executor, a = repl
    buf = []
    monkeypatch.setattr(rc, "print_info", buf.append)
    other = sm.create_session("anthropic", "claude", cwd=a)
    talk(sm, other, "hi", "hello")
    sm.create_session("openai", "gpt-4o", cwd=a)  # we are currently in a different session
    handle_resume(other, sm, agent, executor)
    assert any("anthropic/claude" in m and "still using openai/gpt-4o" in m for m in buf)
    assert agent.provider.name == "openai"


def test_resume_errors(repl, monkeypatch):
    sm, agent, executor, a = repl
    errors, infos = [], []
    monkeypatch.setattr(rc, "print_error", errors.append)
    monkeypatch.setattr(rc, "print_info", infos.append)
    before = list(agent.history)
    assert handle_resume("nope", sm, agent, executor) is False and errors
    assert agent.history == before  # a failed resume changes nothing
    cur = sm.create_session("openai", "gpt-4o", cwd=a)
    assert handle_resume(cur, sm, agent, executor) is False and any("Already" in m for m in infos)
    assert handle_resume(None, sm, agent, executor, select=Chooser()) is False  # nothing to pick


def test_resume_without_an_id_uses_the_picker(repl):
    sm, agent, executor, a = repl
    target = sm.create_session("openai", "gpt-4o", cwd=a)
    talk(sm, target, "q", "a")
    sm.create_session("openai", "gpt-4o", cwd=a)
    assert handle_resume("", sm, agent, executor, select=Chooser(first)) is True
    assert sm.current_session_id == target
    assert handle_resume(None, sm, agent, executor, select=Chooser(None)) is False


def test_last_exchange_preview():
    msgs = [
        Message(role="user", content="old"),
        Message(role="user", content="fix @a.py\n\nAttached context:\n\n<file>x</file>"),
        Message(role="assistant", content="Calling tool..."),
        Message(role="tool", content="output"),
        Message(role="assistant", content="Done: fixed it"),
        Message(role="assistant", content="[The user interrupted this turn before it finished.]"),
    ]
    assert last_exchange_preview(msgs) == ["You: fix @a.py", "DevOrch: Done: fixed it"]
    assert last_exchange_preview([]) == []
    long = last_exchange_preview([Message(role="user", content="x" * 500)], limit=40)
    assert len(long[0]) == len("You: ") + 40 and long[0].endswith("…")


def test_sessions_table_lists_here_only(sm, dirs, monkeypatch, capsys):
    a, b = dirs
    sa = sm.create_session("openai", "gpt-4o", cwd=a)
    sb = sm.create_session("openai", "gpt-4o", cwd=b)
    import io

    from rich.console import Console

    buf = io.StringIO()
    monkeypatch.setattr(rc, "console", Console(file=buf, width=200, color_system=None))
    monkeypatch.chdir(a)
    rc.print_sessions_table(sm, here=True)
    assert sa in buf.getvalue() and sb not in buf.getvalue()
    buf.truncate(0)
    buf.seek(0)
    rc.print_sessions_table(sm)
    assert sa in buf.getvalue() and sb in buf.getvalue() and "Directory" in buf.getvalue()


def test_slash_sessions_list_here_argument(sm, dirs, monkeypatch):
    a, b = dirs
    sm.create_session("openai", "gpt-4o", cwd=a)
    seen = []
    monkeypatch.setattr(rc, "print_sessions_table", lambda *args, **kw: seen.append(kw.get("here")))
    rc.handle_sessions("list here", sm, None)
    rc.handle_sessions("list 5", sm, None)
    rc.handle_sessions("list 5 here", sm, None)
    assert seen == [True, False, True]
    errors = []
    monkeypatch.setattr(rc, "print_error", errors.append)
    rc.handle_sessions("list abc", sm, None)
    assert errors and "Usage" in errors[0]
