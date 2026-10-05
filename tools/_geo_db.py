"""The one "is there a geo database here" check, shared by the geo tools.

Pulse registers every manifest's jobs whatever the install flags say, so a geo
job on an estate without PostGIS must idle (exit 0), like crm-hydrate does. A
container that exists but is not running is NOT idle — that is an outage.
"""
from __future__ import annotations

import subprocess


def geo_db_state(container: str, db: str) -> str:
    """'present' | 'absent' (no container or no db: nothing to do) | 'down'."""
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container],
                       capture_output=True, text=True)
    if r.returncode:
        return "absent"
    if r.stdout.strip() != "true":
        return "down"
    q = subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", "postgres", "-tAc",
                        f"SELECT 1 FROM pg_database WHERE datname = '{db}'"], capture_output=True, text=True)
    if q.returncode:
        return "down"
    return "present" if q.stdout.strip() == "1" else "absent"
