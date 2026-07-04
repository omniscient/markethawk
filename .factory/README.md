# .factory/ — Dark Factory adapter for MarketHawk

Target-repo adapter read by the extracted Dark Factory
([omniscient/dark-factory](https://github.com/omniscient/dark-factory)) from its
fresh clone of this repo (clone-read: changes take effect on the next run, no
image rebuild). The in-repo factory (`dark-factory/`, pre-extraction) ignores
this directory entirely.

- `adapter.yaml` — data: components map, safety patterns, memory routing,
  deconflict paths, token-optimization budgets. Explicit mirror of the factory
  defaults; see the header comment for the sync rule.
- `hooks/` — behavior: `smoke-gate` (check-only gate), `validate`,
  `preview-up`/`preview-down`. Env contract and gate semantics:
  dark-factory `README.md` → "Adapter contract".
- `bench/suite.json` — replay-benchmark corpus for this target.

Spec: `docs/superpowers/specs/2026-07-03-dark-factory-extraction-design.md`.
Cutover status: P2 (parity) — in-repo factory still authoritative.
