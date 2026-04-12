#!/usr/bin/env python3
"""devBoxNOS Heartbeat — reports box status to central management."""
import json
import os
import platform
import re
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone

SERVICE_REGISTRY = os.environ.get(
    "SERVICE_REGISTRY",
    os.path.expanduser("~/projects/default/service-registry.json")
)
HEARTBEAT_ENDPOINT = os.environ.get("HEARTBEAT_ENDPOINT", "")
HEARTBEAT_API_KEY = os.environ.get("HEARTBEAT_API_KEY", "")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "300"))
VERSION_FILE = os.environ.get(
    "VERSION_FILE",
    os.path.expanduser("~/projects/mac-dev-playbook/VERSION")
)


def get_version():
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "unknown"


def get_uptime():
    try:
        result = subprocess.run(
            ["sysctl", "-n", "kern.boottime"],
            capture_output=True, text=True, timeout=5
        )
        m = re.search(r"sec = (\d+)", result.stdout)
        if m:
            boot = int(m.group(1))
            return int(time.time() - boot)
    except Exception:
        pass
    return 0


def get_services():
    try:
        with open(SERVICE_REGISTRY) as f:
            data = json.load(f)
            return data.get("services", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def check_service_health(service):
    url = service.get("health_url") or f"http://127.0.0.1:{service.get('port', 0)}/"
    try:
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status in (200, 301, 302, 401, 403)
    except Exception:
        return False


def build_report():
    services = get_services()
    service_status = []
    for svc in services:
        if svc.get("enabled", True):
            healthy = check_service_health(svc)
            service_status.append({
                "name": svc.get("name", "unknown"),
                "healthy": healthy,
                "port": svc.get("port"),
            })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instance_name": os.environ.get("INSTANCE_NAME", "devboxnos"),
        "hostname": platform.node(),
        "version": get_version(),
        "uptime_seconds": get_uptime(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "services_total": len(service_status),
        "services_healthy": sum(1 for s in service_status if s["healthy"]),
        "services": service_status,
    }


def send_heartbeat(report):
    if not HEARTBEAT_ENDPOINT:
        return
    data = json.dumps(report).encode("utf-8")
    req = urllib.request.Request(
        HEARTBEAT_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {HEARTBEAT_API_KEY}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.URLError as e:
        print(f"Heartbeat send failed: {e}")


def main():
    print(f"devBoxNOS Heartbeat starting (interval={HEARTBEAT_INTERVAL}s)")
    while True:
        try:
            report = build_report()
            if HEARTBEAT_ENDPOINT:
                send_heartbeat(report)
                print(f"Heartbeat sent: {report['services_healthy']}/{report['services_total']} healthy")
            else:
                print(f"Status: {report['services_healthy']}/{report['services_total']} healthy (no endpoint configured)")
        except Exception as e:
            print(f"Heartbeat error: {e}")
        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
