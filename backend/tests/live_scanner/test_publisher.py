import inspect

import live_scanner.publisher as pub_mod


def test_live_publisher_init_does_not_accept_db_url():
    """LivePublisher.__init__ must no longer have a db_url parameter."""
    sig = inspect.signature(pub_mod.LivePublisher.__init__)
    params = list(sig.parameters.keys())
    assert "db_url" not in params, (
        "db_url parameter must be removed from LivePublisher.__init__"
    )


def test_publisher_does_not_import_create_engine():
    """publisher.py must not import create_engine (uses SessionLocal instead)."""
    import ast
    import pathlib

    src = pathlib.Path(pub_mod.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            assert "create_engine" not in names, (
                "publisher.py must not import create_engine — use SessionLocal from app.core.database"
            )
    # Also assert Session import from sqlalchemy.orm is removed
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "sqlalchemy.orm":
                names = [alias.name for alias in node.names]
                assert "Session" not in names, (
                    "publisher.py must not import Session from sqlalchemy.orm (dead import)"
                )
