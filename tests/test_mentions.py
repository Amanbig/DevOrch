"""Tests for @file mentions."""

from prompt_toolkit.document import Document

from cli.constants import SlashCommandCompleter
from core.mentions import MAX_CHARS_PER_FILE, expand_mentions


def test_attaches_file(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    r = expand_mentions("explain @a.py please", tmp_path)
    assert r.attached == ["a.py"]
    assert r.prompt.startswith("explain @a.py please")
    assert '<file path="a.py">' in r.prompt and "x = 1" in r.prompt


def test_line_range(tmp_path):
    (tmp_path / "a.py").write_text("\n".join(f"line{i}" for i in range(1, 11)))
    r = expand_mentions("see @a.py:3-4", tmp_path)
    assert "line3" in r.prompt and "line4" in r.prompt
    assert "line5" not in r.prompt and "line2" not in r.prompt
    assert r.attached == ["a.py:3-4"]


def test_single_line(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree")
    r = expand_mentions("@a.py:2", tmp_path)
    assert "two" in r.prompt and "three" not in r.prompt


def test_nonexistent_and_email_untouched(tmp_path):
    text = "mail me at bob@example.com or ask @nobody about @missing.py"
    r = expand_mentions(text, tmp_path)
    assert r.prompt == text and r.attached == []


def test_directory_listing(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("hi")
    (tmp_path / "sub" / ".hidden").write_text("x")
    r = expand_mentions("list @sub/", tmp_path)
    assert "f.txt" in r.prompt and ".hidden" not in r.prompt


def test_binary_skipped_with_warning(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"\x00\x01\x02")
    r = expand_mentions("@b.bin", tmp_path)
    assert r.attached == [] and r.warnings and r.prompt == "@b.bin"


def test_truncates_large_file(tmp_path):
    (tmp_path / "big.txt").write_text("x" * (MAX_CHARS_PER_FILE * 2))
    r = expand_mentions("@big.txt", tmp_path)
    assert "[truncated]" in r.prompt


def test_dedupes_and_trailing_punctuation(tmp_path):
    (tmp_path / "a.py").write_text("hi")
    r = expand_mentions("compare @a.py, with @a.py.", tmp_path)
    assert r.attached == ["a.py"]


def test_completer_suggests_paths(tmp_path, monkeypatch):
    (tmp_path / "alpha.py").write_text("")
    (tmp_path / "adir").mkdir()
    monkeypatch.chdir(tmp_path)
    c = SlashCommandCompleter()
    texts = [x.text for x in c.get_completions(Document("look at @a"), None)]
    assert "alpha.py" in texts and "adir/" in texts
