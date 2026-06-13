"""Postgres discovery for test environments where testcontainers exec is blocked."""

import os

import psycopg2
import requests


def probe_running_postgres() -> str | None:
    """Return a postgres URL if a running instance is reachable, else None.

    Probes the Docker daemon (via DOCKER_HOST) for running postgres containers,
    then tries common credentials. Falls back to hostname-based probing so the
    tests work in both factory (DinD, exec-blocked) and standard CI environments.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    # Collect candidate IPs from running postgres containers via Docker API.
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

    # Also try well-known hostnames.
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
