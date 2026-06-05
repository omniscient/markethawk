from pathlib import Path
import yaml

WF = Path(__file__).resolve().parents[2] / ".archon" / "workflows" / "archon-dark-factory.yaml"


def _nodes():
    data = yaml.safe_load(WF.read_text(encoding="utf-8"))
    return {n["id"]: n for n in data["nodes"]}


def test_code_review_node_exists_and_is_wired():
    nodes = _nodes()
    assert "code-review" in nodes, "workflow is missing the code-review node"
    cr = nodes["code-review"]
    assert cr["command"] == "dark-factory-code-review"
    assert "push-and-pr" in cr["depends_on"]
    assert "new" in cr["when"] and "continue" in cr["when"]


def test_status_in_review_depends_on_code_review():
    nodes = _nodes()
    assert "code-review" in nodes["status-in-review"]["depends_on"]


def test_report_depends_on_code_review():
    nodes = _nodes()
    assert "code-review" in nodes["report"]["depends_on"]
