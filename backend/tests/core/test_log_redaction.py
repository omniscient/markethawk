"""Unit tests for RedactingFilter and install_redacting_filter."""
import logging

from app.core.log_filters import RedactingFilter, install_redacting_filter

# ── _redact internals via filter ──────────────────────────────────────────────

def _emit(filter_: logging.Filter, msg: str, *args) -> str:
    """Run a log record through the filter and return the formatted message."""
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=args, exc_info=None,
    )
    filter_.filter(record)
    return record.msg


def test_url_password_redacted():
    f = RedactingFilter()
    result = _emit(f, "conn: postgresql://user:s3cr3t@db:5432/mydb")
    assert "s3cr3t" not in result
    assert "[REDACTED]" in result
    assert "user" in result
    assert "db:5432" in result


def test_key_value_redacted():
    f = RedactingFilter()
    result = _emit(f, "POLYGON_API_KEY=abc123xyz")
    assert "abc123xyz" not in result
    assert "POLYGON_API_KEY=[REDACTED]" in result


def test_database_url_key_value_redacted():
    f = RedactingFilter()
    result = _emit(f, "DATABASE_URL=postgresql://u:p@h/db")
    assert "=postgresql" not in result
    assert "[REDACTED]" in result


def test_password_field_redacted():
    f = RedactingFilter()
    result = _emit(f, "SMTP_PASSWORD=hunter2")
    assert "hunter2" not in result
    assert "SMTP_PASSWORD=[REDACTED]" in result


def test_access_token_redacted():
    f = RedactingFilter()
    result = _emit(f, "access_token=eyJhbGciOiJSUzI1NiJ9.payload.sig")
    assert "eyJhbGciOiJSUzI1NiJ9" not in result
    assert "[REDACTED]" in result


def test_normal_message_passes_through():
    f = RedactingFilter()
    result = _emit(f, "Scanner run complete: 5 signals found")
    assert result == "Scanner run complete: 5 signals found"


def test_percent_args_interpolated_before_redact():
    f = RedactingFilter()
    # The secret lives in args, not in msg — filter must call getMessage() first.
    result = _emit(f, "key=%s", "DATABASE_URL=postgresql://u:p@h/db")
    assert "p@h" not in result
    assert "[REDACTED]" in result


def test_filter_clears_args():
    """After filter(), record.args must be None so the formatter doesn't re-interpolate."""
    f = RedactingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="val=%s", args=("secret",), exc_info=None,
    )
    f.filter(record)
    assert record.args is None


def test_filter_always_returns_true():
    """RedactingFilter must never suppress records."""
    f = RedactingFilter()
    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    assert f.filter(record) is True


def test_redis_url_password_redacted():
    f = RedactingFilter()
    result = _emit(f, "broker: redis://:mypassword@redis:6379/0")
    assert "mypassword" not in result
    assert "[REDACTED]" in result


# ── install_redacting_filter wiring ───────────────────────────────────────────

def test_install_adds_filter_to_root_logger():
    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        install_redacting_filter()
        assert any(isinstance(f, RedactingFilter) for f in root.filters)
    finally:
        root.filters = original_filters


def test_install_idempotent_single_instance():
    """Calling install twice must not double-add the filter."""
    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        install_redacting_filter()
        install_redacting_filter()
        count = sum(1 for f in root.filters if isinstance(f, RedactingFilter))
        assert count == 1
    finally:
        root.filters = original_filters


# ── Settings repr protection ───────────────────────────────────────────────

def test_settings_repr_hides_database_url():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:s3cr3t@h/db",
        POLYGON_API_KEY="poly-key-123",
        JWT_SECRET_KEY="a" * 32,
    )
    r = repr(s)
    assert "s3cr3t" not in r


def test_settings_repr_hides_polygon_api_key():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-secret-key",
        JWT_SECRET_KEY="a" * 32,
    )
    assert "poly-secret-key" not in repr(s)


def test_settings_repr_hides_jwt_secret_key():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-key",
        JWT_SECRET_KEY="super-secret-jwt-key-aaaaaaaaaaaaaaa",
    )
    assert "super-secret-jwt-key" not in repr(s)


def test_settings_repr_hides_smtp_password():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-key",
        JWT_SECRET_KEY="a" * 32,
        SMTP_PASSWORD="mail-secret",
    )
    assert "mail-secret" not in repr(s)


def test_settings_repr_hides_vapid_private_key():
    from app.core.config import Settings
    s = Settings(
        DATABASE_URL="postgresql://u:p@h/db",
        POLYGON_API_KEY="poly-key",
        JWT_SECRET_KEY="a" * 32,
        VAPID_PRIVATE_KEY="vapid-priv-key-abc",
    )
    assert "vapid-priv-key-abc" not in repr(s)


# ── FastAPI wiring smoke-test ──────────────────────────────────────────────

def test_create_app_installs_redacting_filter():
    """create_app() must install RedactingFilter on the root logger."""
    from app.core.log_filters import RedactingFilter

    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        # Remove any existing RedactingFilter so create_app() installs a fresh one.
        root.filters = [f for f in root.filters if not isinstance(f, RedactingFilter)]

        from app.main import create_app
        create_app()

        assert any(isinstance(f, RedactingFilter) for f in root.filters), (
            "RedactingFilter not found on root logger after create_app()"
        )
    finally:
        root.filters = original_filters


# ── Celery signal wiring smoke-test ───────────────────────────────────────

def test_celery_signal_handler_installs_redacting_filter():
    """The after_setup_logger signal handler must install RedactingFilter."""
    from app.core.log_filters import RedactingFilter

    root = logging.getLogger()
    original_filters = root.filters[:]
    try:
        root.filters = [f for f in root.filters if not isinstance(f, RedactingFilter)]

        # Import the handler directly and call it as Celery would.
        from app.core.celery_app import _install_log_redaction
        _install_log_redaction(logger=root)

        assert any(isinstance(f, RedactingFilter) for f in root.filters), (
            "RedactingFilter not installed by Celery signal handler"
        )
    finally:
        root.filters = original_filters
