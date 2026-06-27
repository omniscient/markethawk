# Feature Timeline Decks

Dark-Factory-styled slide decks that visualize the system's major features as a **master
rail** — subsystem lanes across a time axis — with an era ribbon, epic bands, an interactive
subsystem filter, optional inline labels, and hover tooltips. Same deck engine and palette as
the other `docs/presentations/` decks (arrow-key nav, `O` overview, `N` speaker notes, `F`
fullscreen).

## Decks

| Deck | Dataset | Scope |
|------|---------|-------|
| [`../dark-factory-timeline.html`](../dark-factory-timeline.html) | `df-timeline-master.json` | Dark Factory pipeline & scheduler infrastructure (54 features, May 2 – Jun 26 2026) |
| _MarketHawk product timeline_ | _(planned)_ | The trading product's user-facing features (separate dataset, same renderer) |

The split rule: a feature is **Dark Factory** if it adds a capability to the autonomous
factory/scheduler itself; it is **MarketHawk** if it adds a capability to the trading product.
Tie-breaker — the in-pipeline quality/scope gate wiring is Dark Factory; the data-quality-gate
*as a product feature* is MarketHawk.

## Regenerate

```bash
python docs/presentations/timeline/build_timeline.py \
  --data docs/presentations/timeline/df-timeline-master.json \
  --out  docs/presentations/dark-factory-timeline.html
```

The output HTML is fully self-contained (no external JS/CSS). The generator is pure Python
stdlib — no dependencies.

## Dataset schema (`*-timeline-master.json`)

- `meta` — title, subtitle, date range, scope rule, excluded-borderline notes
- `subsystems` — `{ key: { label, color } }`; each pins a palette color used for that lane/node
- `eras` — narrative buckets (`id`, `name`, `span`, `blurb`)
- `epics` — the planning spine (`ref`, `name`, `closed`, `theme`, `children[]`)
- `features` — one record per feature: `date` (authoritative = git merge date), `title`,
  `refs[]`, `subsystem`, `significance` (`foundational`|`major`|`hardening`), `era`, `marquee`,
  `one_line`
- `scars` — self-inflicted regressions the system fixed (`date`, `title`, `refs[]`, `one_line`)
- `in_flight` — open roadmap tickets (`created`, `title`, `ref`, `subsystem`, `one_line`)

> **Reuse note:** era boundary dates and epic-band spans are currently hardcoded in
> `build_timeline.py` (Dark-Factory-specific). When the MarketHawk dataset lands, lift those
> into the dataset `meta`/`eras` so the renderer is fully data-driven.
