"""
Logging filter that redacts known-secret patterns from log records before
they reach stdout (and thus the Seq GELF bridge).

Two pattern families:
  - Key-value env var names (*_KEY, *_PASSWORD, *_SECRET, DATABASE_URL, access_token)
  - URL-embedded passwords (postgresql/redis/amqp/mysql://user:<password>@...)
"""
import logging
import re

_PATTERNS = [
    # Key-value: POLYGON_API_KEY=abc123  ->  POLYGON_API_KEY=[REDACTED]
    (
        re.compile(
            r"(?i)((?:\w*_KEY|\w*_PASSWORD|\w*_SECRET|DATABASE_URL|access_token)"
            r"\s*[=:]\s*)\S+"
        ),
        r"\1[REDACTED]",
    ),
    # URL-embedded password: postgresql://user:pass@host  ->  postgresql://user:[REDACTED]@host
    # Username is optional (`*` not `+`) so the no-user form redis://:pass@host
    # — exactly how REDIS_URL is built — is also redacted.
    (
        re.compile(
            r"((?:postgresql|redis|amqp|mysql)://[^:@\s/]*:)[^@\s]+(@)"
        ),
        r"\1[REDACTED]\2",
    ),
]


def _redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs secret patterns from every log record before it reaches any handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = _redact(msg)
        record.args = None
        return True


def install_redacting_filter() -> None:
    """Install RedactingFilter on the root logger (idempotent)."""
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
