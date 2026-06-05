#!/usr/bin/env python3
"""Stage 2: metrics.json + template.html → self-contained pipeline-report.html

Injects the (vendored) ECharts bundle and the metrics data blob into the
template, producing a single offline-viewable HTML file. ECharts is cached to
``scripts/echarts.min.js`` on first run and committed so the report regenerates
without a network dependency.
"""
import json
import sys
import urllib.request
from pathlib import Path

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"
ECHARTS_CACHE = Path(__file__).parent / "echarts.min.js"


def _get_echarts_js() -> str:
    """Return vendored ECharts JS, downloading once if not cached."""
    if ECHARTS_CACHE.exists():
        return ECHARTS_CACHE.read_text(encoding="utf-8")
    print(f"Downloading ECharts from {ECHARTS_URL} …", file=sys.stderr)
    with urllib.request.urlopen(ECHARTS_URL, timeout=30) as resp:
        js = resp.read().decode("utf-8")
    ECHARTS_CACHE.write_text(js, encoding="utf-8")
    print(f"Cached to {ECHARTS_CACHE}", file=sys.stderr)
    return js


def render(metrics_path: str, template_path: str, output_path: str) -> None:
    """Render the pipeline report.

    Reads metrics JSON, injects ECharts (vendored) and metrics data into the
    template, writes a single self-contained HTML file.
    """
    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    template = Path(template_path).read_text(encoding="utf-8")
    echarts_js = _get_echarts_js()

    html = template.replace("{{ECHARTS_JS}}", echarts_js, 1)
    html = html.replace(
        "{{METRICS_JSON}}", json.dumps(metrics, indent=2, default=str), 1
    )

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({len(html) // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="metrics.json")
    parser.add_argument("--template", default="scripts/template.html")
    parser.add_argument("--output", default="docs/pipeline-report.html")
    args = parser.parse_args()

    render(args.metrics, args.template, args.output)
