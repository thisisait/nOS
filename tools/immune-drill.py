#!/usr/bin/env python3
"""The immune drill: plant known, inert samples, run the estate's own detector, record caught / missed.

Row immune-drill-known-samples (operator 2026-11-11). Defensive: it measures whether the detectors
fire. Scope, enforced here: only a temp tree this run creates (never the live estate's data, config or
repo), no network, no exploit code, no third-party target; the samples are removed on exit whatever
happens. A MISSED sample is the finding; a sample with no detector is said so, never counted as caught.

Each sample is drilled end to end, or named honestly:
  secret-canary   a GitHub-PAT-shaped string built at RUN time (never in the repo) in a temp file,
                  scanned by gitleaks with THIS repo's .gitleaks.toml — the estate's real config and
                  allowlist, so an allowlist entry that swallowed a real-looking secret would show as missed
  eicar           not drilled: no anti-malware detector is declared in state/immune/indicators.yml
  advisory-pin    a fixture npm lockfile pinning lodash 4.17.20 (GHSA-35jh-r3h4-6jhm, fixed 4.17.21), judged
                  by advisory-status's own collect() and OSV re-match; only its one fetch seam is answered,
                  from the vendored record below, so no request leaves the host
  exposed-port-role  a role compose.yml.j2 publishing 0.0.0.0:<port>, judged by the CI gate's own
                  lan_ports() + EDGE (tests/anatomy/test_lan_access_is_behind_the_edge.py)
  exposed-port-app   a manifest app (apps/_template.yml) publishing 0.0.0.0, judged by the parser's
                  validate(): the apps_runner refuses to deploy it (host-port-not-loopback)
  The live door (a listener nobody declared) is undeclared-status's: it reads the host, not drilled.

    tools/immune-drill.py            # run, print, write ~/.nos/immune/drill/<stamp>.json
    tools/immune-drill.py --json     # the record on stdout only
Exit 0 always (a drill reports). Refused inside an agent run (NOS_AGENT_NAME set): the operator drills.
"""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("NOS_IMMUNE_DRILL_DIR") or Path.home() / ".nos" / "immune" / "drill")


def _canary() -> str:
    """A GitHub classic PAT shape (ghp_ + 36 alnum), assembled now so no literal ever sits in a file."""
    alnum = string.ascii_letters + string.digits
    return "gh" + "p_" + "".join(secrets.choice(alnum) for _ in range(36))


def drill_secret(tmp: Path) -> dict:
    gl = shutil.which("gitleaks")
    if not gl:
        return {"sample": "secret-canary", "result": "UNKNOWN", "why": "gitleaks not on PATH"}
    (tmp / "settings.env").write_text(f"GITHUB_TOKEN={_canary()}\n")
    report = tmp / "report.json"
    t0 = time.monotonic()
    try:
        subprocess.run([gl, "dir", str(tmp), "--config", str(REPO / ".gitleaks.toml"), "--no-banner",
                        "--redact", "--exit-code", "0", "--report-format", "json", "--report-path", str(report)],
                       capture_output=True, text=True, timeout=120, check=False)
        hits = json.loads(report.read_text() or "[]") if report.exists() else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"sample": "secret-canary", "result": "UNKNOWN", "why": f"gitleaks did not answer: {type(exc).__name__}"}
    secs = round(time.monotonic() - t0, 2)
    if hits is None:
        return {"sample": "secret-canary", "result": "UNKNOWN", "why": "gitleaks wrote no report"}
    caught = [h for h in hits if str(h.get("File", "")).endswith("settings.env")]
    return {"sample": "secret-canary", "result": "caught" if caught else "missed", "detector": "gitleaks",
            "rule": caught[0].get("RuleID") if caught else None, "seconds": secs}


_LAN = {"ports": ["0.0.0.0:8081:80"]}   # beside the edge's 80/443: every interface, past Traefik


def _timed(sample: str, detector: str, judge) -> dict:
    """judge() -> bool caught; an import or render failure is UNKNOWN, never caught or missed."""
    t0 = time.monotonic()
    try:
        caught = judge()
    except Exception as exc:  # noqa: BLE001 — a blind detector is UNKNOWN, not green
        return {"sample": sample, "result": "UNKNOWN", "why": f"{detector} did not answer: {type(exc).__name__}"}
    return {"sample": sample, "result": "caught" if caught else "missed", "detector": detector,
            "seconds": round(time.monotonic() - t0, 2)}


def drill_port_role(tmp: Path) -> dict:
    def judge() -> bool:
        sys.path[:0] = [str(REPO / "tests" / "anatomy"), str(REPO / "tools")]
        gate = __import__("test_lan_access_is_behind_the_edge")
        f = tmp / "roles" / "pazny.drill_sample" / "templates" / "compose.yml.j2"
        f.parent.mkdir(parents=True)
        f.write_text(yaml.safe_dump({"services": {"drill-sample": _LAN}}))
        seen = gate.lan_ports(f.read_text(), "Darwin", absent=False)
        return any(("pazny.drill_sample", gate._container_port(p)) not in gate.EDGE for _, p in seen)
    # The gate's judge only (lan_ports + EDGE, Darwin, toggle off), not its discovery glob.
    return _timed("exposed-port-role", "lan_ports()+EDGE of test_lan_access_is_behind_the_edge", judge)


def drill_port_app(tmp: Path) -> dict:
    def judge() -> bool:
        sys.path.insert(0, str(REPO / "files" / "anatomy"))
        from module_utils import nos_app_parser as nap
        rec = yaml.safe_load((REPO / "apps" / "_template.yml").read_text())
        rec["meta"]["name"] = "drill-sample"
        svc = next(iter(rec["compose"]["services"].values()))
        svc.update(_LAN)
        f = tmp / "apps" / "drill-sample.yml"
        f.parent.mkdir(parents=True)
        f.write_text(yaml.safe_dump(rec))
        try:
            nap.validate(nap.load_app_file(str(f)), app_name="drill-sample")
        except nap.AppParseError as e:
            if not any(v.startswith("standard ") for v in e.violations):
                raise   # refused before the standards ran (template drift): UNKNOWN, not missed
            return any(v.startswith("standard host-port-not-loopback") for v in e.violations)
        return False
    return _timed("exposed-port-app", "nos_app_parser.validate", judge)


# The published advisory, vendored as OSV serves it (trimmed to the fields the matcher reads). Inert data.
_ADVISORY = {"id": "GHSA-35jh-r3h4-6jhm", "aliases": ["CVE-2021-23337"],
             "affected": [{"package": {"name": "lodash", "ecosystem": "npm"},
                           "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}]}],
             "database_specific": {"severity": "HIGH"}}


def drill_advisory_pin(tmp: Path, version: str = "4.17.20") -> dict:
    def judge() -> bool:
        spec = importlib.util.spec_from_file_location("advisory_status", REPO / "tools" / "advisory-status.py")
        adv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adv)
        lock = tmp / "drill-lock" / "package-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"packages": {"": {}, "node_modules/lodash": {"version": version}}}))

        def offline(url, body=None):   # the seam: answered here, never the network
            if url == adv.OSV_BATCH:
                n = len(json.loads(body)["queries"])
                return {"results": [{"vulns": [{"id": _ADVISORY["id"]}]} for _ in range(n)]}
            if url == adv.OSV_VULN.format(id=_ADVISORY["id"]):
                return _ADVISORY
            raise OSError("offline drill: no network")   # cve.now enrichment: UNKNOWN, the match stands
        rep = adv.collect(pin_values={}, receptor_map={}, lockfiles={"drill": (lock, "npm")}, fetch=offline)
        return any(m.get("id") == _ADVISORY["id"] for lf in rep["lockfiles"] for m in lf.get("matches") or [])
    return _timed("advisory-pin", "advisory-status collect() + OSV re-match", judge)


NOT_DRILLED = [
    {"sample": "eicar", "result": "no detector", "why": "no anti-malware indicator in state/immune/indicators.yml"},
]


def run() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="nos-immune-drill-"))
    try:
        rows = [drill_secret(tmp), drill_port_role(tmp), drill_port_app(tmp), drill_advisory_pin(tmp)] + NOT_DRILLED
    finally:
        shutil.rmtree(tmp, ignore_errors=True)   # every sample goes, whatever happened
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "samples": rows,
            "missed": [r["sample"] for r in rows if r["result"] == "missed"], "cleaned": not tmp.exists()}


def main() -> int:
    if os.environ.get("NOS_AGENT_NAME"):
        print("immune-drill: refused inside an agent run — the operator drills (Tier 1)")
        return 0
    rec = run()
    if "--json" in sys.argv:
        print(json.dumps(rec, indent=2))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (rec["at"].replace(":", "") + ".json")
    path.write_text(json.dumps(rec, indent=2) + "\n")
    for r in rec["samples"]:
        print(f"  {r['sample']:<14} {r['result']:<12} {r.get('rule') or r.get('why') or ''}")
    print(f"immune-drill: {len(rec['missed'])} missed · samples removed: {rec['cleaned']} · {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
