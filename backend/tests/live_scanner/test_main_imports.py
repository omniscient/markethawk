import ast
import inspect
import pathlib


def test_no_ib_insync_imports_in_main():
    """main.py must not import IB, Stock, ContFuture, or util from ib_insync."""
    src_path = pathlib.Path(__file__).parent.parent.parent / "live_scanner" / "main.py"
    source = src_path.read_text()
    tree = ast.parse(source)
    forbidden = {"IB", "Stock", "ContFuture", "util"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "ib_insync":
            imported = {alias.name for alias in node.names}
            overlap = imported & forbidden
            assert not overlap, f"main.py imports {overlap} from ib_insync — move to ibkr_adapter.py"
        if isinstance(node, ast.Import):
            names = {alias.name for alias in node.names}
            assert "ib_insync" not in names, "main.py must not import ib_insync directly"


def test_run_accepts_provider_with_default():
    """run() must accept an optional LiveDataProvider (default None) for injection."""
    import live_scanner.main as main_mod
    sig = inspect.signature(main_mod.run)
    assert "provider" in sig.parameters, "run() must accept a 'provider' parameter"
    defaults = [
        p.default for p in sig.parameters.values()
        if p.default is not inspect.Parameter.empty
    ]
    # provider must have a default (None) so it's optional
    assert len(defaults) >= 1, "run(provider) must have a default value (None)"


def test_run_does_not_reference_database_url():
    """After publisher.py no longer takes db_url, main.py must not pass DATABASE_URL."""
    src_path = pathlib.Path(__file__).parent.parent.parent / "live_scanner" / "main.py"
    source = src_path.read_text()
    assert "DATABASE_URL" not in source, \
        "main.py must not pass DATABASE_URL — LivePublisher no longer accepts it"
