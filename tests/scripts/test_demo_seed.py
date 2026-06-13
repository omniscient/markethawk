from pathlib import Path

import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "demo" / "seed" / "seed_demo.py"


def load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_demo_credentials_are_documented_and_nonempty():
    seed = load_seed_module()

    assert seed.DEMO_USERNAME == "demo"
    assert seed.DEMO_PASSWORD == "markethawk-demo"
    assert len(seed.DEMO_PASSWORD) >= 12


def test_demo_dataset_covers_workflow_surfaces():
    seed = load_seed_module()
    dataset = seed.build_dataset()

    assert {ticker["ticker"] for ticker in dataset["tickers"]} >= {
        "NVDA",
        "AMD",
        "MSFT",
        "TSLA",
        "AMZN",
    }
    assert len(dataset["scanner_events"]) >= 5
    assert len(dataset["watchlist"]) >= 3
    assert len(dataset["reviews"]) >= 3
    assert len(dataset["outcomes"]) >= 3
    assert len(dataset["news"]) >= 3
    assert len(dataset["journal_entries"]) >= 1
    assert len(dataset["trades"]) >= 1


def test_every_review_and_outcome_references_seeded_event():
    seed = load_seed_module()
    dataset = seed.build_dataset()
    event_keys = {event["key"] for event in dataset["scanner_events"]}

    assert all(review["event_key"] in event_keys for review in dataset["reviews"])
    assert all(outcome["event_key"] in event_keys for outcome in dataset["outcomes"])
