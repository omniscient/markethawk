# Dark Factory GELF Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship all dark factory and backlog scheduler stdout/stderr to Seq via Docker's GELF log driver so logs survive container removal.

**Architecture:** A new `seq-gelf` sidecar container (`datalust/seq-input-gelf`) receives GELF over UDP 12201 and forwards to Seq's HTTP ingestion API. Both `dark-factory` and `backlog-scheduler` use Docker's built-in GELF logging driver to ship logs to this sidecar. Both factory services join `stockscanner-network` as a second network.

**Tech Stack:** Docker Compose, GELF protocol, Seq, `datalust/seq-input-gelf`

**Spec:** [`Docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md`](../specs/2026-05-29-dark-factory-gelf-logging-design.md)
**ADR:** [`Docs/adr/0010-dark-factory-gelf-logging.md`](../../adr/0010-dark-factory-gelf-logging.md)
**Issue:** [#122](https://github.com/omniscient/markethawk/issues/122)

---

### Task 1: Add the `seq-gelf` sidecar service

**Files:**
- Modify: `docker-compose.yml:329` (insert after the `seq` service block)

- [ ] **Step 1: Add `seq-gelf` service to `docker-compose.yml`**

Insert the following block after the `seq` service (after line 329, before the `# Prometheus` comment on line 330):

```yaml

  # GELF input sidecar — receives GELF from Docker log driver and forwards to Seq
  seq-gelf:
    image: datalust/seq-input-gelf:latest
    container_name: stockscanner-seq-gelf
    environment:
      SEQ_ADDRESS: "http://seq:5341"
    ports:
      - "127.0.0.1:12201:12201/udp"
    depends_on:
      - seq
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 128M
```

Key details:
- `SEQ_ADDRESS` points to the Seq container's internal ingestion port on the Docker network
- Port `12201/udp` is bound to localhost only (not externally exposed), consistent with all other management ports
- `depends_on: seq` ensures the Seq container starts first
- `restart: unless-stopped` matches other infrastructure services (prometheus, grafana)
- 128M memory limit is generous for a log forwarder

- [ ] **Step 2: Verify the service definition is valid YAML**

Run:
```bash
docker compose config --services
```

Expected: Output includes `seq-gelf` in the list of services (along with all existing services). No YAML parse errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(logging): add seq-gelf sidecar for GELF log ingestion (#122)"
```

---

### Task 2: Configure GELF logging on `dark-factory` and `backlog-scheduler`

**Files:**
- Modify: `docker-compose.yml` — `dark-factory` service (lines 367-381)
- Modify: `docker-compose.yml` — `backlog-scheduler` service (lines 383-400)

- [ ] **Step 1: Add GELF logging driver and `stockscanner-network` to `dark-factory`**

The `dark-factory` service currently looks like this (lines 367-381):

```yaml
  # Dark Factory — autonomous development agent (run on demand)
  dark-factory:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: markethawk-dark-factory
    env_file:
      - path: .archon/.env
        required: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - factory-network
    profiles:
      - factory
```

Replace it with:

```yaml
  # Dark Factory — autonomous development agent (run on demand)
  dark-factory:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: markethawk-dark-factory
    env_file:
      - path: .archon/.env
        required: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - factory-network
      - stockscanner-network
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "dark-factory"
    profiles:
      - factory
```

Changes:
- Added `stockscanner-network` to `networks` (for future direct-network approaches)
- Added `logging:` block with GELF driver targeting `host.docker.internal:12201`
- `tag: "dark-factory"` enables filtering in Seq

- [ ] **Step 2: Add GELF logging driver and `stockscanner-network` to `backlog-scheduler`**

The `backlog-scheduler` service currently looks like this (lines 383-400):

```yaml
  # Backlog Scheduler — polls GitHub board and dispatches dark factory runs
  backlog-scheduler:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: backlog-scheduler
    restart: unless-stopped
    entrypoint: ["/opt/dark-factory/scheduler.sh"]
    env_file:
      - path: .archon/.env
        required: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace/project:ro
    networks:
      - factory-network
    profiles:
      - scheduler
```

Replace it with:

```yaml
  # Backlog Scheduler — polls GitHub board and dispatches dark factory runs
  backlog-scheduler:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: backlog-scheduler
    restart: unless-stopped
    entrypoint: ["/opt/dark-factory/scheduler.sh"]
    env_file:
      - path: .archon/.env
        required: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace/project:ro
    networks:
      - factory-network
      - stockscanner-network
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "backlog-scheduler"
    profiles:
      - scheduler
```

Changes are identical to `dark-factory` except `tag: "backlog-scheduler"`.

- [ ] **Step 3: Verify the full compose file is valid**

Run:
```bash
docker compose config --services
```

Expected: All services listed, no YAML errors.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(logging): add GELF log driver to dark-factory and backlog-scheduler (#122)"
```

---

### Task 3: Commit spec and ADR

**Files:**
- Already on disk: `Docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md`
- Already on disk: `Docs/adr/0010-dark-factory-gelf-logging.md`

These files were written during the brainstorming/design phase but not yet committed.

- [ ] **Step 1: Commit spec and ADR**

```bash
git add Docs/superpowers/specs/2026-05-29-dark-factory-gelf-logging-design.md Docs/adr/0010-dark-factory-gelf-logging.md
git commit -m "docs: add spec and ADR-0010 for dark factory GELF logging (#122)"
```

---

### Task 4: Validate end-to-end logging

**Files:** None (manual verification)

**Prerequisites:** The main stack must be running (`docker compose up -d` — this starts Seq). The `seq-gelf` sidecar is on the default profile so it starts with the main stack.

- [ ] **Step 1: Start the main stack (if not already running)**

Run:
```bash
docker compose up -d
```

Verify Seq and seq-gelf are running:
```bash
docker compose ps seq seq-gelf
```

Expected: Both show `running` (or `Up`).

- [ ] **Step 2: Verify GELF sidecar can reach Seq**

Run:
```bash
docker compose logs seq-gelf --tail=10
```

Expected: Startup log indicating it's listening on port 12201 and connected to Seq. No connection errors.

- [ ] **Step 3: Send a test GELF message**

Use `ncat` or PowerShell to send a raw GELF UDP message to localhost:12201:

```powershell
$bytes = [System.Text.Encoding]::UTF8.GetBytes('{"version":"1.1","host":"test","short_message":"GELF logging test from dark factory plan","level":6}')
$client = New-Object System.Net.Sockets.UdpClient
$client.Send($bytes, $bytes.Length, "127.0.0.1", 12201)
$client.Close()
```

- [ ] **Step 4: Verify the test message appears in Seq**

Open Seq UI at http://localhost:5380. Search for the message:
- Filter: `@Message like '%GELF logging test%'`

Expected: The test message appears with the short_message text visible.

- [ ] **Step 5: Test with a real dark factory container**

Run a quick dark factory invocation that will fail fast (no valid issue):

```bash
docker compose --profile factory run --rm dark-factory "Fix issue #999999"
```

This will fail (issue doesn't exist), but the entrypoint output should appear in Seq.

- [ ] **Step 6: Verify dark factory logs in Seq**

Open Seq UI at http://localhost:5380. Filter:
- `tag = 'dark-factory'`

Expected: Entrypoint output lines from the #999999 run appear — git clone attempt, error messages, etc. Each line is a separate Seq event with `container_name`, `tag`, and `image_name` properties.

- [ ] **Step 7: Update the CLAUDE.md service ports table**

Add the GELF port to the Service Ports table in `CLAUDE.md`:

| Service      | URL                          |
|-------------|------------------------------|
| Seq GELF    | udp://localhost:12201        |

This is informational — helps future developers know the port is in use.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add GELF port to service ports table (#122)"
```
