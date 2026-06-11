#!/usr/bin/env node
// Headless render smoke test for docs/pipeline-report.html.
//
// Loads the vendored (offline) ECharts and replays every chart's setOption with
// real ECharts via SSR, over the committed metrics.json. Exits non-zero if any
// chart throws — the failure mode the stubbed Python unit tests cannot see (a bad
// chart option throws inside ECharts, halts the page script, and blanks every
// chart after it plus the table).
//
// Run directly: `node tests/scripts/render_smoke.cjs`
// Invoked by tests/scripts/test_render_report.py (skipped when node is absent).
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const echartsPath = path.join(ROOT, "scripts", "echarts.min.js");
const templatePath = path.join(ROOT, "scripts", "template.html");
const metricsPath = path.join(ROOT, "metrics.json");
const scorecardPath = path.join(ROOT, "scorecard.json");

for (const p of [echartsPath, templatePath, metricsPath]) {
  if (!fs.existsSync(p)) {
    console.log("SKIP: missing " + path.relative(ROOT, p));
    process.exit(0);
  }
}

// Load ECharts in a clean sandbox (no navigator/window/document) so its env
// detection takes the Node/SSR path; give it timers (setOption schedules work).
const mod = { exports: {} };
const loadBox = { module: mod, exports: mod.exports, console, setTimeout, clearTimeout, setInterval, clearInterval };
vm.createContext(loadBox);
vm.runInContext(fs.readFileSync(echartsPath, "utf8"), loadBox, { filename: "echarts.min.js" });
const echarts = mod.exports;
if (!echarts || !echarts.init) {
  console.log("FAIL: ECharts failed to load");
  process.exit(1);
}

const template = fs.readFileSync(templatePath, "utf8");
const metricsObj = JSON.parse(fs.readFileSync(metricsPath, "utf8"));
if (fs.existsSync(scorecardPath)) {
  metricsObj.scorecard = JSON.parse(fs.readFileSync(scorecardPath, "utf8"));
}
const scripts = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = scripts[1].replace("{{METRICS_JSON}}", JSON.stringify(metricsObj));

let lastId = null;
const fakeEl = () => ({
  innerHTML: "", textContent: "", style: {}, dataset: {},
  addEventListener() {}, appendChild() {},
  classList: { add() {}, remove() {} }, querySelectorAll() { return []; },
});
const document = {
  getElementById(id) { lastId = id; return fakeEl(); },
  querySelectorAll() { return []; },
  createElement() { return fakeEl(); },
};
const window = { addEventListener() {} };

const results = [];
const wrapped = {
  graphic: echarts.graphic,
  init() {
    const id = lastId;
    const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: 400, height: 300 });
    return {
      setOption(opt) {
        try {
          chart.setOption(opt);
          chart.renderToSVGString();
          results.push({ id, ok: true });
        } catch (e) {
          results.push({ id, ok: false, err: e.message });
        }
      },
      resize() {},
    };
  },
};

let halted = null;
try {
  vm.runInNewContext(code, { echarts: wrapped, document, window, console }, { filename: "page.js" });
} catch (e) {
  halted = e.message;
}

const throws = results.filter((r) => !r.ok);
for (const r of throws) console.log("THROW " + r.id + " → " + r.err);
console.log(`Rendered ${results.length} charts, ${throws.length} threw` + (halted ? `; script halted: ${halted}` : ""));
process.exit(throws.length === 0 && !halted ? 0 : 1);
