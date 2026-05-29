# Dark Factory GELF Logging to Seq

**Date**: 2026-05-29
**Issue**: Observability gap — dark factory containers are ephemeral (`--rm`) so logs are lost on exit, making post-mortem debugging impossible.

## Problem

The dark factory and backlog scheduler run as Docker containers with `--rm`. When a container exits (success, failure, or host crash), Docker's default JSON log driver discards all logs immediately. There is no way to determine why a workflow failed after the fact.

Real incident: issue #105 completed implementation (PR #121 created) but crashed before posting the cost report or transitioning the board to "In Review". The failure reason is unrecoverable because the container was removed.

## Decision

Use Docker's built-in GELF log driver to ship all stdout/stderr from both `dark-factory` and `backlog-scheduler` containers to the existing Seq instance. GELF ships each log line to Seq over UDP before Docker removes the container, so logs survive container deletion.

## Scope

### Seq GELF input sidecar

Seq does not have a built-in GELF listener. The official approach is a lightweight sidecar container (`datalust/seq-input-gelf`) that accepts GELF on UDP 12201 and forwards events to Seq's HTTP ingestion API.

- Add a `seq-gelf` service using `datalust/seq-input-gelf:latest`
- Configure `SEQ_ADDRESS: "http://seq:5341"` to forward to the existing Seq instance
- Publish the GELF port to localhost: `127.0.0.1:12201:12201/udp`
- Place on `stockscanner-network` (same as Seq)
- No host-external exposure (same policy as the existing Seq UI and HTTP ports)

### Docker logging driver

Both `dark-factory` and `backlog-scheduler` services get:

```yaml
logging:
  driver: gelf
  options:
    gelf-address: "udp://host.docker.internal:12201"
    tag: "<service-name>"
```

The `tag` field enables filtering in Seq: `tag = 'dark-factory'` vs `tag = 'backlog-scheduler'`. Docker automatically adds `container_name`, `image_name`, and `container_id` as structured GELF fields.

### Network connectivity

Both factory services add `stockscanner-network` as a second network (they keep `factory-network` for Docker socket access). This allows future direct-network approaches if GELF driver limitations become blocking.

### What gets captured

**Dark factory runs:**
- entrypoint.sh output (git clone, pip install, board transitions, cost report)
- Archon workflow engine (node execution, node failures, timing)
- Claude Code CLI sessions (full output from implement/validate/refine nodes)
- Preview stack lifecycle (docker compose up, health checks)

**Backlog scheduler:**
- Poll loop decisions (dispatch, skip reasons, WIP state)
- Comment classification (Haiku verdicts: MERGE/CONTINUE/SKIP)
- Rate limit checks and board state snapshots

### Files changed

| File | Change |
|------|--------|
| `docker-compose.yml` — new `seq-gelf` service | `datalust/seq-input-gelf` sidecar, UDP 12201, forwards to Seq |
| `docker-compose.yml` — `dark-factory` | Add GELF `logging:` block, add `stockscanner-network` |
| `docker-compose.yml` — `backlog-scheduler` | Add GELF `logging:` block, add `stockscanner-network` |
| `Docs/adr/0010-dark-factory-gelf-logging.md` | ADR documenting the decision and trade-offs |

No changes to `entrypoint.sh`, `scheduler.sh`, `Dockerfile`, or application code.

## Known limitations

- **Line splitting**: GELF is line-oriented. Multi-line output (Python tracebacks, large diffs) gets split across Seq events. Readable via Seq's time-grouped UI but not ideal.
- **UDP delivery**: UDP can theoretically drop messages under extreme load. Acceptable for the current single-factory-at-a-time model.
- **Startup dependency**: Docker's GELF driver fails container startup if it can't resolve the log endpoint. If Seq is down, the factory won't start. This is acceptable — Seq should be running whenever the factory is.
- **No offline fallback**: If Seq is unreachable mid-run, log lines for that period are dropped (UDP fire-and-forget). A volume-backed fallback (Fluent Bit sidecar) is the path forward for a production system.

## Assumptions

- `datalust/seq-input-gelf:latest` is the official GELF-to-Seq bridge (maintained by Datalust)
- `host.docker.internal` resolves inside Linux containers on Docker Desktop (standard on Docker Desktop for Windows/Mac; on native Linux, may require `--add-host`)
- Only one dark factory container runs at a time (existing concurrency guard), so log volume is bounded
