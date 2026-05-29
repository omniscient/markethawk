# ADR-0010: GELF Log Shipping for Dark Factory Containers

**Date**: 2026-05-29
**Status**: Accepted
**Issue**: [#105 — post-mortem debugging gap](https://github.com/omniscient/markethawk/issues/105) _(incident that motivated this)_

## Context

Dark factory containers run with `--rm` (the scheduler dispatches via `docker compose run -d --rm`). Docker's default JSON log driver keeps logs only while the container exists — once removed, they're gone. This makes post-mortem debugging impossible.

Real incident: issue #105 completed implementation (PR created, CI passed) but the workflow crashed before posting the cost report or transitioning the board to "In Review". The failure reason is unrecoverable. A "RAG failed" error was briefly visible in the scrolling terminal output but was lost when the container exited.

Three approaches were considered:

1. **Docker GELF log driver → Seq** — Docker ships every stdout/stderr line to Seq over UDP. Zero code changes to entrypoint or scheduler scripts.
2. **`tee` to mounted volume + periodic ingestion** — Write logs to host disk, ship to Seq on a schedule. Logs survive even if Seq is down, but adds a shipping delay and log rotation burden.
3. **Custom HTTP shipper wrapper** — A shell script that reads stdin and POSTs to Seq's Raw Events API. Richer structured events, but a hard kill loses the pipe buffer (same problem as today).

## Decision

Use Docker's built-in GELF log driver (Approach 1) to ship all stdout/stderr from `dark-factory` and `backlog-scheduler` to Seq via a `datalust/seq-input-gelf` sidecar on UDP port 12201. The sidecar receives GELF and forwards to Seq's HTTP ingestion API. The GELF port is bound to `127.0.0.1` only (not externally exposed).

GELF was chosen because:
- It captures logs at the Docker level, before `--rm` removes the container
- Zero code changes to entrypoint or scheduler scripts — all configuration lives in `docker-compose.yml`
- Structured metadata (container name, image, tag) is added automatically
- Seq already runs in the stack; the GELF sidecar is Datalust's official bridge

## Consequences

- **Logs survive container removal.** Every factory and scheduler run is searchable in Seq (`:5380`), filterable by `tag` (`dark-factory` vs `backlog-scheduler`), `container_name`, and time range.
- **Multi-line output is split.** GELF is line-oriented — Python tracebacks and large diffs become multiple Seq events. Readable via time-grouped view but not ideal. Acceptable for current usage.
- **UDP can drop messages.** Under extreme load, UDP log lines may be lost. With only one factory container running at a time, this is not a practical concern.
- **The GELF sidecar must be running for the factory to start.** Docker's GELF driver fails container startup if it can't connect to the log endpoint. This is an acceptable coupling — the sidecar and Seq should be running whenever the factory is.
- **No offline fallback.** If Seq becomes unreachable mid-run, log lines for that period are silently dropped. For a production system, a Fluent Bit sidecar with disk buffering would be the next step.
- **Host networking assumption.** `host.docker.internal` must resolve inside containers. This works on Docker Desktop (Windows/Mac). On native Linux hosts, an `extra_hosts` entry may be needed.
