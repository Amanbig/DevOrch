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


# ── image mentions ──────────────────────────────────────────────────────────

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_image_mention_attaches_image_not_text(tmp_path):
    (tmp_path / "shot.png").write_bytes(PNG)
    r = expand_mentions("what is wrong in @shot.png ?", tmp_path)
    assert len(r.images) == 1 and r.images[0].media_type == "image/png"
    assert r.images[0].name == "shot.png"
    assert r.attached == ["shot.png (image)"]
    assert "<file" not in r.prompt and r.prompt == "what is wrong in @shot.png ?"


def test_image_type_sniffed_from_bytes(tmp_path):
    (tmp_path / "actually.png").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8)  # JPEG bytes
    r = expand_mentions("@actually.png", tmp_path)
    assert r.images[0].media_type == "image/jpeg"


def test_oversized_image_skipped(tmp_path, monkeypatch):
    import core.images as images

    monkeypatch.setattr(images, "MAX_IMAGE_BYTES", 10)
    (tmp_path / "big.png").write_bytes(PNG)
    r = expand_mentions("@big.png", tmp_path)
    assert r.images == [] and r.warnings


def test_image_and_text_file_together(tmp_path):
    (tmp_path / "shot.png").write_bytes(PNG)
    (tmp_path / "a.py").write_text("x = 1")
    r = expand_mentions("@shot.png and @a.py", tmp_path)
    assert len(r.images) == 1 and '<file path="a.py">' in r.prompt
