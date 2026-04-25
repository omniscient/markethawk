# Stock Universe Tags — Design Spec

**Date:** 2026-04-25  
**Feature:** Display universe membership as informational tags on the Stock Detail page

---

## Overview

When viewing a stock's detail page, show which universes that ticker belongs to as small pill tags in the page header, immediately alongside the existing sector badge. A stock may belong to zero, one, or many universes. Tags are informational only — not clickable.

---

## Backend

### New endpoint

```
GET /api/universe/by-ticker/{ticker}
```

**Location:** `backend/app/routers/universe.py`

**Logic:**
1. Query `StockUniverseTicker` for all rows where `ticker == ticker` (case-insensitive match).
2. For each matching `universe_id`, fetch the corresponding `StockUniverse` record.
3. Filter to `is_active = True` universes only.
4. Return the list sorted by universe name.

**Response shape:**
```json
[
  { "id": 1, "name": "My Watchlist" },
  { "id": 3, "name": "Momentum Plays" }
]
```

**Empty response:** Returns `[]` when the ticker is in no active universes — not a 404.

**Pydantic schema:** A small inline schema `UniverseSummary(id: int, name: str)` defined in the router or in `backend/app/schemas/`.

---

## Frontend — API Layer

**File:** `frontend/src/api/scanner.ts` (where all other universe API functions live)

Add:
```ts
export interface UniverseSummary {
  id: number;
  name: string;
}

export const fetchUniversesForTicker = async (ticker: string): Promise<UniverseSummary[]> => {
  const response = await apiClient.get(`/universe/by-ticker/${ticker}`);
  return response.data;
};
```

---

## Frontend — UI

**File:** `frontend/src/pages/StockDetailPage.tsx`

**Data fetching:**
```ts
const { data: tickerUniverses = [] } = useQuery({
  queryKey: ['tickerUniverses', symbol],
  queryFn: () => fetchUniversesForTicker(symbol),
  enabled: !!symbol,
  staleTime: 300_000,  // universes change rarely
});
```

**Rendering:** Tags appear in the header row immediately after the existing sector badge. Each tag is a small pill using purple tones to visually distinguish it from the gray sector badge:

```tsx
{tickerUniverses.map((u) => (
  <div key={u.id} className="px-2 py-0.5 bg-purple-900/50 border border-purple-700/50 rounded text-xs font-bold text-purple-300 uppercase">
    {u.name}
  </div>
))}
```

Tags flow inline and wrap naturally if many are present. No tag is shown when `tickerUniverses` is empty (zero-state is silent).

---

## Error Handling

- Network error fetching universes: React Query retries silently; tags section simply stays empty. No error state shown to the user — this is supplementary info.
- Ticker not found in any universe: empty array response, no tags rendered.

---

## Out of Scope

- Clickable tags / navigation to universe page
- Adding/removing a stock from a universe via the tags
- Showing inactive universes
