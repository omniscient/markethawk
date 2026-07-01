"""Pure-stdlib token estimation helpers for Dark Factory context budget telemetry."""
import hashlib

CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def hash_file(path: str) -> "str | None":
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except (FileNotFoundError, OSError):
        return None


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
