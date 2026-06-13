"""Postgres discovery helpers for the test infrastructure.

Locates a running PostgreSQL instance in environments where testcontainers
exec is blocked (e.g. docker-socket-proxy with EXEC:0).
"""

import os


def probe_running_postgres() -> str | None:
    """Return a postgres URL if a running instance is reachable, else None.

    Priority:
    1. TEST_DATABASE_URL env var (explicit override)
    2. Docker API scan via DOCKER_HOST (factory/DinD environments)
    3. Well-known hostnames (postgres, stockscanner-db, localhost)

    For each candidate host the function tries common_creds in order and
    returns on the first successful psycopg2.connect().
    """
    import psycopg2
    import requests

    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    candidate_ips: list[str] = []
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        try:
            r = requests.get(
                f"http://{docker_host[6:]}/containers/json",
                timeout=3,
            )
            for c in r.json():
                if "postgres" not in c.get("Image", "").lower():
                    continue
                for net_info in (
                    c.get("NetworkSettings", {}).get("Networks", {}).values()
                ):
                    ip = net_info.get("IPAddress", "")
                    if ip:
                        candidate_ips.append(ip)
        except Exception:
            pass

    for hostname in ["postgres", "stockscanner-db", "localhost"]:
        candidate_ips.append(hostname)

    common_creds = [
        ("postgres", "postgres", "postgres"),
        ("postgres", "postgres", "stockscanner"),
        ("onecli", "onecli", "onecli"),
    ]
    for ip in candidate_ips:
        for user, pw, db in common_creds:
            try:
                psycopg2.connect(
                    host=ip,
                    port=5432,
                    user=user,
                    password=pw,
                    dbname=db,
                    connect_timeout=1,
                ).close()
                return f"postgresql://{user}:{pw}@{ip}:5432/{db}"
            except Exception:
                pass
    return None
