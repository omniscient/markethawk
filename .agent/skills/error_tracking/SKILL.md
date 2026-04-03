---
name: Error Tracking System
description: Instructions on how to use and interact with the centralized server-side error tracking system (Seq).
---

# Server-Side Error Tracking via Seq

The application routes all unhandled backend exceptions through a global FastAPI handler that:
1. Hashes the Python stack trace with MD5 to produce a **deterministic** `ErrorId` (e.g., `ERR-cf2b39ad`).
   - *Same bug → same ID* – avoids duplicate tickets / duplicate noise.
2. Ships a structured log event (including the full traceback) to the local **Seq** container via its HTTP ingestion API.
3. Simultaneously writes to Python's `stdlib.logging` as a fallback so nothing is ever lost.
4. Returns a JSON body to the frontend:
   - **Development / DEBUG** →  `{ message, error_id, detail, stack_trace }`
   - **Production** →  `{ message, error_id }` (internals hidden)

The React `GlobalErrorToast` component listens for the `server-error` window event that the shared Axios client fires on every HTTP 5xx response.  
Clicking **"Trace in Seq"** opens the Seq event search pre-filtered to that exact `ErrorId`.

---

## Infrastructure Details

| Service | URL | Notes |
|---------|-----|-------|
| Seq UI  | `http://localhost:5380` | Web search/browse UI |
| Seq Ingestion API | `http://localhost:5341` (or `http://seq:5341` from within Docker) | Raw Events REST API |
| Seq Data Volume | `seq_data` Docker named volume | Persistent across restarts |

### Switching the Tracking Backend
Set `SEQ_URL` env var to `disabled` (or leave it empty) to fall back to stdout-only.  
To add a **new** backend (Sentry, Loki, Datadog, etc.):
1. Create a class satisfying the `ErrorTracker` Protocol in `backend/app/core/error_tracking.py`.
2. Update `ErrorTrackerFactory._build()` to instantiate it based on a new env var.
3. The `error_id` API contract stays unchanged – no frontend changes needed.

---

## AI Agent: How to Debug a Reported Error

When the user pastes an `ErrorId` or reports "the UI showed error `ERR-xxxxxxxx`":

### Step 1 – Query Seq REST API

```bash
curl -s "http://localhost:5380/api/events?filter=ErrorId%3D%27ERR-xxxxxxxx%27&count=5" \
  | python -m json.tool
```

Each event returned is a JSON object. Key fields to extract:

| JSON field | Meaning |
|-----------|---------|
| `Properties.ErrorId` | Confirms the match |
| `Properties.Path` | The exact API route that failed |
| `Properties.ExceptionType` | Python exception class name |
| `Properties.ExceptionDetail` | `str(exc)` – the exception message |
| `Exception` | Full multi-line Python traceback |
| `Timestamp` | UTC time of the error |

### Step 2 – Analyse the Traceback

Look at the `Exception` field. It is a verbatim Python traceback:
```
Traceback (most recent call last):
  File ".../routers/scanner.py", line 42, in run_scan
    result = await scanner_service.run(...)
  File ".../services/scanner.py", line 87, in run
    df['volume_ratio'] = df['volume'] / df['avg_vol']   # <-- ZeroDivisionError
ZeroDivisionError: float division by zero
```

Use the file path + line number to open the failing module and apply a fix.

### Step 3 – Verify the Fix

After fixing and restarting the backend:
- Trigger the same operation again.
- A new `ErrorId` (or no error at all) means the original bug is resolved.
- Because the `ErrorId` is derived from the **stack trace text**, the same `ERR-xxxxxxxx` will only reappear if the identical unpatched code path runs again.

### Step 4 – Fallback: Read Backend Logs Directly

If the Seq container is offline:
```bash
# From the host with Docker running
docker logs stockscanner-api --tail 100 | grep "ERR-"
```
The `StdoutErrorTracker` always mirrors output there.

---

## Changing the Seq Search URL in the Frontend

The "Trace in Seq" button URL is built in `GlobalErrorToast.tsx`:

```ts
const SEQ_UI_BASE = import.meta.env.VITE_SEQ_UI_URL ?? 'http://localhost:5380';
```

Change `VITE_SEQ_UI_URL` in `.env` or in the `frontend` Docker service environment to point at a remote Seq instance.
