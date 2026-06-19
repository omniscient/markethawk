# AI Narrative UI Controls Design

**Date:** 2026-06-19
**Issue:** #482 — Add UI controls for optional AI narrative layers
**Parent Epic:** #450 — Optional LLM Narrative and Semantic Intelligence
**Status:** Spec — pending review
**Blocked by:** #473 (cached event narrative), #475 (AI alert copy), #476 (post-mortems), #481 (cost/latency/observability)

---

## Overview

Scanner signals in MarketHawk produce two classes of content:

1. **Deterministic** — explanations, criteria pass/fail, signal briefs, indicators. Always available, free, fast, and grounded in raw data. Already rendered in `ScannerResults.tsx` event cards.
2. **AI-generated** — event narratives (#473), AI-assisted alert copy (#475), signal post-mortems (#476). Feature-flagged, cost-bearing, cached, and optional per the parent epic design rule: _"Epic 3 is optional. MarketHawk must remain explainable and insight-rich without LLM calls."_

This spec defines the UI controls and affordances that let users enable/disable the three AI narrative layers, observe their per-item state (disabled / loading / cached / stale / failed), and distinguish AI-generated content from deterministic facts at a glance.

---

## Requirements

Distilled from the issue acceptance criteria and Q&A:

1. **Three individual per-layer enable/disable toggles** in a new "AI Narratives" section in Settings — one for event narratives, one for AI alert copy, one for post-mortems. A single global toggle is insufficient because the three blocking issues each produce independent backend enabled/disabled states.

2. **Inline per-event state indicators** on every event card where AI content can appear: disabled (collapsed placeholder), loading (spinner), cached-fresh (narrative text), cached-stale (text + stale marker + refresh), failed (error icon + refresh button).

3. **Visual distinction** between deterministic and AI-generated content: AI sections use `bg-purple-900/20 border-purple-700/30` container + `Sparkles` icon + "AI-generated" badge label. Deterministic content keeps the standard `bg-gray-800/40 border-gray-700/50` styling. Purple is the codebase's "derived/computed" accent (used in `MetricCard.tsx`, `EdgeExplorer.tsx`) and does not collide with severity or regime semantics.

4. **Staleness is backend-owned.** A `stale: boolean` field on the narrative API response determines whether a narrative is stale. The frontend renders the flag — it does not compute staleness from wall-clock time, because staleness means the cached narrative no longer matches the current deterministic brief (facts changed, or model/version bumped), which only the backend knows.

5. **No provider internals exposed.** The toggles control visibility/enablement of the generated layer in the UI. Provider/model configuration stays in the backend settings managed by #481.

6. **Toggle state persisted in backend SystemConfig** (PostgreSQL key/value store, same pattern as `signal_ranker_enabled` and `AUTO_TRADING_ENABLED`). All sessions and browser tabs see the same state.

7. **Frontend tests** covering enabled, disabled, cached (fresh), cached (stale), and failure states for the inline `AiNarrativeSection` component.

---

## Architecture

### Settings layer — enable/disable toggles

Add a new **"AI Narratives"** tab to `frontend/src/pages/Settings.tsx`:

```typescript
// Add to the `tabs` array in Settings.tsx
{ id: 'ai-narratives', name: 'AI Narratives', icon: Sparkles }
```

The tab renders three `ToggleField` controls (reusing `ToggleField` from `frontend/src/pages/AutoTrading/components.tsx`) reading/writing SystemConfig keys:

| Toggle label | SystemConfig key | Default |
|---|---|---|
| Event Narratives | `event_narrative_enabled` | `"false"` |
| AI Alert Copy | `ai_alert_copy_enabled` | `"false"` |
| Post-mortems | `post_mortem_enabled` | `"false"` |

The tab reads via the existing `getSystemConfig()` / `['systemConfig']` React Query key and writes via `updateSystemConfig()` mutation — the same pattern used for `polygon_crawl_delay` in the Data & Storage tab. No new API routes needed for the toggle controls.

If #481 exposes a provider degraded/status field on the system config response, display a read-only status indicator (e.g., a yellow "degraded" badge) in the AI Narratives tab. Do not expose model/provider selection controls here.

**Backend seed (Alembic migration, coordinated with #472/#481):** Insert default rows into `system_config`:

```python
# In the migration upgrade():
op.execute("INSERT INTO system_config (key, value) VALUES "
           "('event_narrative_enabled', 'false'), "
           "('ai_alert_copy_enabled', 'false'), "
           "('post_mortem_enabled', 'false') "
           "ON CONFLICT (key) DO NOTHING")
```

Key names should be coordinated with whatever naming convention #472 (LLM feature flags) establishes when it lands.

### Shared narrative payload type

Add to `frontend/src/api/scanner/types.ts`:

```typescript
export interface NarrativePayload {
  text: string;
  generated_at: string;
  stale: boolean;
  model?: string;    // optional, shown only in debug/admin — never exposed to non-admin UI
  version?: string;  // narrative schema version
}
```

The blocking issues (#473/#475/#476) define the actual API endpoints. Spec them as placeholders; update when the blockers land.

### Shared hook — `useAiNarrative`

New file: `frontend/src/hooks/useAiNarrative.ts`

```typescript
// Pseudocode — paths are placeholders until blocking issues land
export function useAiNarrative(
  eventUuid: string,
  type: 'event_narrative' | 'alert_copy' | 'post_mortem',
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['ai-narrative', type, eventUuid],
    queryFn: () => apiClient.get(`/scanner/events/${eventUuid}/narrative/${type}`).then(r => r.data),
    enabled,
    staleTime: Infinity,  // never auto-refetch; user must explicitly refresh
  });
}
```

The `enabled` flag comes from the SystemConfig toggle value: `sysConfig?.event_narrative_enabled === 'true'` (etc.). When disabled, the hook does not fire any network request.

### `AiNarrativeSection` component

New file: `frontend/src/components/AiNarrativeSection.tsx`

Props:
```typescript
interface AiNarrativeSectionProps {
  eventUuid: string;
  type: 'event_narrative' | 'alert_copy' | 'post_mortem';
  label: string;           // e.g., "Event Narrative", "AI Alert Copy"
  enabled: boolean;        // from SystemConfig toggle
  onRefresh: () => void;   // calls queryClient.invalidateQueries
}
```

State machine rendering:

| State | Condition | Rendered output |
|---|---|---|
| **disabled** | `!enabled` | Nothing (component returns null) |
| **loading** | `enabled && isPending` | Spinner + "Generating narrative…" |
| **failed** | `enabled && isError` | Error icon + "Generation failed" + Refresh button |
| **cached-fresh** | `data && !data.stale` | Purple container + Sparkles + "AI-generated" badge + `data.text` |
| **cached-stale** | `data && data.stale` | Purple container + Sparkles + "AI-generated" + stale marker ("⚠ Stale") + Refresh button + `data.text` in subdued style |

Visual structure for cached-fresh state:

```
┌─ bg-purple-900/20 border border-purple-700/30 rounded-lg px-3 py-2.5 ─────┐
│ [Sparkles icon, h-3 w-3, text-purple-400]  AI-generated                    │
│                                             [small badge label text-xs]     │
│ <narrative text — text-gray-300 text-sm leading-relaxed>                    │
└────────────────────────────────────────────────────────────────────────────-┘
```

### Placement

**Event narratives** (`event_narrative_enabled`): render `AiNarrativeSection` inside each event card in `ScannerResults.tsx` and `StockDetailPage/ScannerHistoryPanel.tsx`.

**Post-mortems** (`post_mortem_enabled`): render `AiNarrativeSection` in `StockDetailPage/ScannerHistoryPanel.tsx` when the event has outcome data (i.e., a `ScannerOutcomeSummary` is present).

**AI alert copy** (`ai_alert_copy_enabled`): render `AiNarrativeSection` in `Alerts/AlertLogsPanel.tsx` alongside each alert delivery log row that references a scanner event.

---

## Alternatives Considered

### 1. Single global on/off toggle
**Rejected.** The three blocking issues (#473/#475/#476) each produce independent backend enabled/disabled states. A single toggle forces "all or nothing" and contradicts the independent feature-flag semantics the backend establishes. Individual toggles are also still within the size: M budget since the ToggleField component and SystemConfig pattern are both pre-built.

### 2. localStorage for toggle state
**Rejected.** AI narrative generation is a cost-bearing backend operation (LLM calls, caching, provider usage). A browser-local toggle cannot prevent the backend from generating content for other sessions. This is the same class of concern as `AUTO_TRADING_ENABLED` — a global operational flag, not a per-browser display preference.

### 3. Client-side staleness by time threshold
**Rejected.** "Stale" means the cached narrative no longer matches the current deterministic brief (facts changed, or model/version bumped). Only the backend can compute this. A 24-hour client-side timer would diverge from real cache validity, and #481 explicitly owns cache semantics.

---

## Open Questions (non-blocking)

- **Key name coordination with #472**: The three SystemConfig keys proposed here (`event_narrative_enabled`, `ai_alert_copy_enabled`, `post_mortem_enabled`) should be reviewed against whatever naming convention #472 (LLM feature flags) introduces when it lands. Conflicts should be resolved before implementing the Settings tab.

- **Narrative API endpoint paths**: The exact REST paths for fetching narrative content from #473/#475/#476 are not yet determined. The `useAiNarrative` hook is spec'd against placeholder paths; update before implementation.

- **Provider degraded status surface**: If #481 exposes a `provider_status` or `llm_degraded` field on the system config response, what does it look like? The AI Narratives tab should display it as a read-only status badge, but the schema is pending #481's spec.

---

## Assumptions

- **[ASSUMPTION]** #473, #475, and #476 each expose a REST endpoint for fetching their narrative type for a given event UUID. The placeholder pattern `GET /scanner/events/{uuid}/narrative/{type}` is used here; actual paths may differ.
- **[ASSUMPTION]** `NarrativePayload.stale: boolean` will be present on narrative API responses from the blocking issues. If a blocking issue lands without this field, file a follow-up against that issue — the frontend must not paper over missing staleness with a local timer.
- **[ASSUMPTION]** The installed version of lucide-react includes `Sparkles`. It is not currently imported in any frontend file; add it to component imports wherever the icon is used.
- **[ASSUMPTION]** The AI Narratives tab in Settings is the correct home for the three toggles. If a future admin/system page is introduced by #481, the toggles may migrate there — but Settings is the established pattern today.
