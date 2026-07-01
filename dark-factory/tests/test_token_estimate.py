import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import token_estimate as te


def test_chars_per_token_constant():
    assert te.CHARS_PER_TOKEN == 4.0


def test_estimate_tokens_empty():
    assert te.estimate_tokens("") == 0


def test_estimate_tokens_basic():
    # "hello" = 5 chars → int(5 / 4.0) = 1
    assert te.estimate_tokens("hello") == 1


def test_estimate_tokens_exact_multiple():
    assert te.estimate_tokens("a" * 400) == 100


def test_hash_file_missing_returns_none():
    assert te.hash_file("/nonexistent/path/file.txt") is None


def test_hash_file_returns_12_hex_chars(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = te.hash_file(str(f))
    assert result is not None
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_file_same_content_same_hash(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("identical content")
    f2.write_text("identical content")
    assert te.hash_file(str(f1)) == te.hash_file(str(f2))


def test_hash_text_returns_12_hex_chars():
    result = te.hash_text("hello")
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_text_deterministic():
    assert te.hash_text("hello") == te.hash_text("hello")
