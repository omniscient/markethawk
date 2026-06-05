from pathlib import Path
import yaml

CONFIG = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "refinement" / "config.yaml"

def test_code_review_block_present_with_defaults():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cr = cfg.get("code_review")
    assert cr is not None, "config.yaml is missing the code_review block"
    assert cr["enabled"] is True
    assert cr["block_threshold"] == "high"
    assert cr["fail_open"] is True
    assert cr["max_findings"] == 50
