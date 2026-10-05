#!/usr/bin/env python3
"""
Polls the stack `tests/compose/smoke.sh` just started with `docker compose
up -d`, until the gateway reports every registered module healthy, or fails
fast if a container is stuck restarting.

Plain polling with a deadline, the same shape as tests/proc.py's
wait_healthy and for the same reason: a service that happens to take longer
to come up on a given run must not turn into a flaky failure. The gateway's
own aggregated `/health` is checked rather than each service's, on purpose
-- that is the one call that actually crosses the chain the frontend
depends on, and the one that would have caught bank-sync starting but
answering every request with `"bank": "unreachable"` (2026-10-04, missing
python-multipart) even though its own container looked "up".
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

TIMEOUT_SECONDS = 120
POLL_SECONDS = 2
GATEWAY_HEALTH_URL = "http://localhost:8080/health"


def restarting_services() -> list[str]:
    """Services docker is stuck restart-looping -- `restart: unless-stopped`
    means a crash never shows up as the container just stopping."""
    out = subprocess.run(
        ["docker", "compose", "ps", "--all", "--format", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    bad = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        container = json.loads(line)
        if container.get("State") == "restarting":
            bad.append(container.get("Service") or container.get("Name", "?"))
    return bad


def gateway_health() -> dict | None:
    try:
        with urllib.request.urlopen(GATEWAY_HEALTH_URL, timeout=3) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return None


def main() -> int:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_health: dict | None = None
    while time.monotonic() < deadline:
        bad = restarting_services()
        if bad:
            print(f"container(s) stuck restarting: {', '.join(bad)}", file=sys.stderr)
            return 1

        last_health = gateway_health()
        if last_health is not None:
            modules = last_health.get("modules", {})
            unhealthy = {k: v for k, v in modules.items() if v != "ok"}
            if last_health.get("gateway") == "ok" and not unhealthy:
                print(f"all modules healthy: {last_health}")
                return 0
        time.sleep(POLL_SECONDS)

    print(
        f"gateway never reported every module healthy within {TIMEOUT_SECONDS}s "
        f"-- last response: {last_health}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
