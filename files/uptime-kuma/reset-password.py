#!/usr/bin/env python3
"""
Uptime Kuma — admin password reconverge helper.

Idempotent state-declarative password update. Tries current password first
(already converged), falls back to previous password + change_password.

Usage:
  python3 reset-password.py <URL> <USER> <NEW_PW> <OLD_PW>

Exit codes:
  0 — password is converged (either unchanged or successfully updated)
  1 — drift detected, neither new nor old password works (manual intervention)
"""

import sys


def main():
    if len(sys.argv) < 5:
        print("Usage: reset-password.py <URL> <USER> <NEW_PW> <OLD_PW>", file=sys.stderr)
        sys.exit(2)

    url, user, new_pw, old_pw = sys.argv[1:5]

    try:
        from uptime_kuma_api import UptimeKumaApi
    except ImportError:
        print("SKIP: uptime-kuma-api not installed")
        sys.exit(0)

    api = UptimeKumaApi(url)

    # 1) Current password already converged?
    try:
        api.login(user, new_pw)
        print("CONVERGED: current password accepted")
        api.disconnect()
        sys.exit(0)
    except Exception:
        pass

    # 2) Fall back to previous password → rotate to new
    try:
        api.login(user, old_pw)
        api.change_password(old_pw, new_pw)
        print("UPDATED: rotated from previous password")
        api.disconnect()
        sys.exit(0)
    except Exception as e:
        print(f"DRIFT: neither current nor previous password works ({e})",
              file=sys.stderr)
        api.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    main()
