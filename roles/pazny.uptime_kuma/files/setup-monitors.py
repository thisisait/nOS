#!/usr/bin/env python3
"""
Uptime Kuma – automatická konfigurace monitorů.
Volá se z Ansible po startu Uptime Kuma kontejneru.

Použití:
  python3 setup-monitors.py <URL> <USER> <PASS> '<MONITORS_JSON>'

Příklad:
  python3 setup-monitors.py http://127.0.0.1:3001 admin heslo '[{"name":"Grafana","type":"http","url":"http://127.0.0.1:3000/api/health"}]'
"""

import sys
import json


def main():
    if len(sys.argv) < 5:
        print("Usage: setup-monitors.py <URL> <USER> <PASS> '<MONITORS_JSON>'")
        sys.exit(1)

    kuma_url = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]
    monitors = json.loads(sys.argv[4])

    try:
        from uptime_kuma_api import UptimeKumaApi, MonitorType
    except ImportError:
        print("SKIP: uptime-kuma-api not installed (pip install uptime-kuma-api)")
        sys.exit(0)

    api = UptimeKumaApi(kuma_url)

    try:
        # Setup or login
        try:
            api.setup(username, password)
            print(f"[+] Initial setup complete (user: {username})")
        except Exception:
            api.login(username, password)
            print(f"[+] Logged in as {username}")

        # Get existing monitors
        existing = {m["name"] for m in api.get_monitors()}
        created = 0

        for mon in monitors:
            if mon["name"] in existing:
                print(f"[=] {mon['name']} already exists")
                continue

            try:
                if mon.get("type") == "tcp":
                    api.add_monitor(
                        type=MonitorType.TCP,
                        name=mon["name"],
                        hostname=mon.get("hostname", "127.0.0.1"),
                        port=mon["port"],
                        interval=60,
                        maxretries=2,
                    )
                else:
                    api.add_monitor(
                        type=MonitorType.HTTP,
                        name=mon["name"],
                        url=mon["url"],
                        interval=60,
                        maxretries=2,
                        accepted_statuscodes=["200-299", "301", "302", "401", "403"],
                    )
                print(f"[+] Created: {mon['name']}")
                created += 1
            except Exception as e:
                print(f"[-] Failed: {mon['name']} — {e}")

        print(f"\nDone: {created} created, {len(existing)} existing")

    finally:
        api.disconnect()


if __name__ == "__main__":
    main()
