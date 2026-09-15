"""smtp_stalwart healthcheck must probe the address Docker forwards to.

MEASURED 2026-09-15 on smtp_stalwart (Up 3 days, healthy):

    docker inspect Healthcheck  :>/dev/tcp/127.0.0.1/8080
    /proc/net/tcp               no LISTEN on :25 / :465 / :587 / :993
    /proc/net/tcp6              :::8080 LISTEN  (webadmin only)
    /etc/stalwart               empty — volume never grew a config.json
    in-container /dev/tcp/127.0.0.1/25          FAIL
    in-container /dev/tcp/$(hostname -i …)/25   FAIL
    in-container /dev/tcp/127.0.0.1/8080        OK
    host 127.0.0.1:25 connect                   accepted (Docker proxy)
    host 127.0.0.1:25 EHLO                      EOF, empty recv

Compose `ports: 25:25` is not a listener. A volume config (here: the
absence of one) outranks it. The healthcheck asked container-localhost
:8080, the one socket that was open, so docker-healthy and host-SMTP-dead
coexisted. Paperclip's 47-hour case is the same family: probe `hostname -i`
(the address the forwarder actually hits), first IP only (two networks),
on the published SMTP port — not :8080, which answers without SMTP.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
TPL = ROOT / "roles/pazny.smtp_stalwart/templates/compose.yml.j2"


def _probe() -> str:
    text = TPL.read_text(encoding="utf-8")
    for ln in text.splitlines():
        if ln.strip().startswith("test:"):
            return ln
    raise AssertionError(f"{TPL} has no healthcheck test: line")


def test_smtp_stalwart_healthcheck_probes_the_published_address():
    probe = _probe()
    assert "127.0.0.1" not in probe, (
        "healthcheck still targets container-localhost — that is the address "
        "that answered :8080 while SMTP was unbound; Docker does not forward "
        "host :25 there"
    )
    assert re.search(r"\blocalhost\b", probe) is None, (
        "healthcheck still targets localhost — same trap as 127.0.0.1"
    )
    assert "hostname -i" in probe, (
        "healthcheck must use hostname -i, the address Docker's port forward "
        "actually targets (paperclip pattern)"
    )
    assert "awk" in probe and "$1" in probe, (
        "hostname -i prints two IPs on infra_net+shared_net; without "
        "awk '{print $1}' the /dev/tcp path is malformed"
    )
    assert "/25" in probe, (
        "healthcheck must probe published SMTP :25 — :8080 (webadmin) is up "
        "when /etc/stalwart is empty and SMTP is not listening"
    )
    assert "8080" not in probe, (
        "healthcheck still probes webadmin :8080, which cannot see an unbound SMTP"
    )
