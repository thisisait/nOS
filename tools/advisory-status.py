#!/usr/bin/env python3
"""Which pinned versions sit inside a published advisory range, right now.

WHY THIS EXISTS. The estate ran FrankenPHP 1.13.1 for two days after
php/frankenphp published GHSA-6q3j-62j9-f9hh (high), GHSA-ccgp-ch9h-533f,
GHSA-fq24-r53r-xcx3 and GHSA-4gfw-9v29-gp9h, all fixed in 1.13.2, and nothing
noticed. The nightly scan (files/vuln-scan) is a model doing web searches; it
never reads a pin. Measured 2026-10-23: only GitHub repo advisories carried all
four, OSV had one old id, and cve.now 404s GHSA-only ids.

WHAT IT READS.
  inventory  every `*_version` / `*_tag` pin of the committed defaults
             (nos_identity.default_layers()), each routed by its row in
             state/genome/advisory-receptors.yml; plus the organ lockfiles
             (thalamus Cargo.lock, wing composer.lock, face + cortex
             package-lock.json).
  sources    github   api.github.com/repos/<o>/<r>/security-advisories
             osv      api.osv.dev querybatch for lockfiles and `osv:` pins, then
                      each hit's record, re-matched here exactly
             cve.now  /api/v1/entries/<CVE> for KEV and EPSS, by CVE id only

MATCHING is exact: introduced <= v < fixed, last_affected inclusive; a
prerelease sorts before its release; an image variant ("16.15-alpine",
"-ce.0") and a digest ("@sha256:...") are not part of the version.

WHAT IT DOES NOT DO. It writes nothing and exits 0 whatever it finds. Each
source is UNKNOWN on its own: an unreachable source makes its pins UNKNOWN,
never clean, and the report never says "no findings" — a pin is `clear` only
when its source was read, and the line says how many advisories were read.
`tech:` receptors are declared but no source reads them yet, so those pins are
UNKNOWN and say so.

    tools/advisory-status.py
    tools/advisory-status.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import tomllib
import urllib.parse
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

RECEPTORS = REPO / "state" / "genome" / "advisory-receptors.yml"
KINDS = ("github", "osv", "tech", "none")
PIN = re.compile(r"_(version|tag)$")

#: organ -> (lockfile, OSV ecosystem). The organs nOS builds itself.
LOCKFILES = {
    "thalamus": (REPO / "files/anatomy/thalamus/Cargo.lock", "crates.io"),
    "wing": (REPO / "files/anatomy/wing/composer.lock", "Packagist"),
    "face": (REPO / "files/anatomy/face/package-lock.json", "npm"),
    "cortex": (REPO / "files/anatomy/cortex/package-lock.json", "npm"),
}

GITHUB = "https://api.github.com/repos/{repo}/security-advisories?per_page=100&page={page}"
OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/{id}"
CVE_NOW = "https://cve.now/api/v1/entries/{id}"
TIMEOUT = 20
GITHUB_MAX_PAGES = 10
OSV_BATCH_SIZE = 1000


# --- versions ----------------------------------------------------------------

#: Prerelease words, lowest first. A suffix that is none of these is an image
#: variant (alpine, ce.0, hotfix3) and does not move the version.
_PRE = {"dev": 0, "snapshot": 0, "canary": 0, "next": 0, "nightly": 0,
        "a": 1, "alpha": 1, "b": 2, "beta": 2, "pre": 3, "preview": 3, "c": 4, "rc": 4}
_VERSION = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")
_PRE_SUFFIX = re.compile(r"^[-.]?([a-z]+)[-.]?(\d*)", re.I)


def parse_version(raw: str) -> tuple:
    """A sortable key for `raw`, or ValueError when it names no release."""
    s = str(raw).strip().split("@", 1)[0].split("+", 1)[0]
    if s[:1] in ("v", "V"):
        s = s[1:]
    m = _VERSION.match(s)
    if not m:
        raise ValueError(f"not a version: {raw!r}")
    nums = [int(x) for x in m.group(1).split(".")]
    nums += [0] * (6 - len(nums))
    pre = (1, 0, 0)  # a release sorts after every prerelease of it
    p = _PRE_SUFFIX.match(m.group(2))
    if p and p.group(1).lower() in _PRE:
        pre = (0, _PRE[p.group(1).lower()], int(p.group(2) or 0))
    return (tuple(nums[:6]), pre)


def in_range(v: str, introduced: str | None = None, fixed: str | None = None,
             last_affected: str | None = None) -> bool:
    """introduced <= v < fixed, last_affected inclusive. "0" is the beginning."""
    key = parse_version(v)
    if introduced not in (None, "0") and key < parse_version(introduced):
        return False
    if fixed is not None and key >= parse_version(fixed):
        return False
    if last_affected is not None and key > parse_version(last_affected):
        return False
    return True


_CONSTRAINT = re.compile(r"^\s*(>=|<=|>|<|=)?\s*(\S+)\s*$")


def github_range_holds(v: str, rng: str) -> bool:
    """GitHub's vulnerable_version_range: comma-joined constraints, all must hold."""
    key = parse_version(v)
    for part in rng.split(","):
        m = _CONSTRAINT.match(part)
        if not m:
            raise ValueError(f"not a range: {rng!r}")
        op, bound = m.group(1) or "=", parse_version(m.group(2))
        ok = {">=": key >= bound, ">": key > bound, "<=": key <= bound,
              "<": key < bound, "=": key == bound}[op]
        if not ok:
            return False
    return True


def osv_affected_holds(v: str, affected: dict) -> bool:
    """One OSV `affected` entry: its explicit versions, then its ranges' events.

    Events read in order: each `introduced` opens an interval that the next
    `fixed` (exclusive) or `last_affected` (inclusive) closes. GIT ranges carry
    commits, not versions, and are skipped.
    """
    if v in (affected.get("versions") or []):
        return True
    for r in affected.get("ranges") or []:
        if r.get("type") == "GIT":
            continue
        start = None
        for ev in r.get("events") or []:
            if "introduced" in ev:
                start = ev["introduced"]
            elif "fixed" in ev and start is not None:
                if in_range(v, introduced=start, fixed=ev["fixed"]):
                    return True
                start = None
            elif "last_affected" in ev and start is not None:
                if in_range(v, introduced=start, last_affected=ev["last_affected"]):
                    return True
                start = None
        if start is not None and in_range(v, introduced=start):
            return True
    return False


# --- inventory ---------------------------------------------------------------

def pins() -> dict[str, str]:
    """Every `*_version` / `*_tag` of the committed defaults, value as written."""
    return {k: str(v) for k, v in ni.default_config().items()
            if PIN.search(k) and isinstance(v, (str, int, float))}


def receptors(path: pathlib.Path = RECEPTORS) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("receptors") or {}


def coverage(pin_values: dict, receptor_map: dict) -> dict[str, list[str]]:
    """Pins with no receptor, receptors with no pin, rows of no known kind."""
    malformed = [k for k, r in receptor_map.items()
                 if not isinstance(r, dict) or len([x for x in KINDS if x in r]) != 1
                 or set(r) - set(KINDS) - {"floating"}]
    return {"missing": sorted(set(pin_values) - set(receptor_map)),
            "stale": sorted(set(receptor_map) - set(pin_values)),
            "malformed": sorted(malformed)}


def _kind(r: dict) -> str:
    return next(k for k in KINDS if k in r)


def lockfile_packages(path: pathlib.Path, ecosystem: str) -> list[tuple[str, str]]:
    """(name, version) per third-party package; the organ's own crates are skipped."""
    out: set[tuple[str, str]] = set()
    if ecosystem == "crates.io":
        for p in tomllib.loads(path.read_text(encoding="utf-8")).get("package", []):
            if str(p.get("source", "")).startswith("registry+"):
                out.add((p["name"], p["version"]))
    elif ecosystem == "Packagist":
        data = json.loads(path.read_text(encoding="utf-8"))
        for p in [*data.get("packages", []), *data.get("packages-dev", [])]:
            out.add((p["name"], str(p["version"]).lstrip("v")))
    elif ecosystem == "npm":
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, p in (data.get("packages") or {}).items():
            if "node_modules/" not in key or p.get("link") or "version" not in p:
                continue
            out.add((p.get("name") or key.rsplit("node_modules/", 1)[1], p["version"]))
    else:
        raise ValueError(f"no reader for {ecosystem}")
    return sorted(out)


# --- the one fetch seam ------------------------------------------------------

def headers_for(url: str) -> dict[str, str]:
    h = {"User-Agent": "nos-advisory-status", "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        h["Authorization"] = f"Bearer {token}"
        h["Accept"] = "application/vnd.github+json"
    return h


def fetch(url: str, body: bytes | None = None):
    """GET `url` (or send `body` to it) and parse the JSON answer.

    Everything this reader learns from the network passes here, so a test
    replaces this one function. A body goes only to OSV's querybatch, a query
    that changes nothing (OSV offers no GET for it).
    """
    headers = headers_for(url)
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --- sources -----------------------------------------------------------------

def _github_advisories(repo: str, get) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, GITHUB_MAX_PAGES + 1):
        batch = get(GITHUB.format(repo=repo, page=page))
        if not isinstance(batch, list):
            raise ValueError(f"GitHub said: {str(batch)[:120]}")
        rows += batch
        if len(batch) < 100:
            return rows
    raise ValueError(f"more than {GITHUB_MAX_PAGES} pages; read stopped short")


def _match_github(version: str, advisories: list[dict]) -> tuple[list[dict], list[str]]:
    hits, unranged = [], []
    for a in advisories:
        if a.get("withdrawn_at"):
            continue
        ranges = [(v.get("vulnerable_version_range"), v.get("patched_versions"))
                  for v in a.get("vulnerabilities") or []]
        ranges = [(r, f) for r, f in ranges if r]
        if not ranges:
            unranged.append(a.get("ghsa_id"))
            continue
        for rng, patched in ranges:
            if github_range_holds(version, rng):
                hits.append({"id": a.get("ghsa_id"), "cve": a.get("cve_id"),
                             "severity": a.get("severity"), "range": rng, "fixed": patched,
                             "url": a.get("html_url")})
                break
    return hits, unranged


def _osv(queries: list[dict], get) -> list[list[str]]:
    """querybatch: the advisory ids OSV says touch each query, in order."""
    out: list[list[str]] = []
    for i in range(0, len(queries), OSV_BATCH_SIZE):
        chunk = queries[i:i + OSV_BATCH_SIZE]
        res = get(OSV_BATCH, json.dumps({"queries": chunk}).encode("utf-8"))
        results = res.get("results") if isinstance(res, dict) else None
        if not isinstance(results, list) or len(results) != len(chunk):
            raise ValueError("OSV querybatch answered a different shape")
        for r in results:
            if r.get("next_page_token"):
                raise ValueError("OSV paginated a query; read stopped short")
            out.append([v["id"] for v in r.get("vulns") or []])
    return out


def _osv_rematch(name: str, ecosystem: str | None, purl: str | None, version: str,
                 ids: list[str], details: dict, get) -> tuple[list[dict], list[str], list[str]]:
    """Re-match OSV's ids here, exactly. -> (hits, server_only, unreadable)."""
    hits, server_only, unreadable = [], [], []
    for vid in ids:
        if vid not in details:
            try:
                details[vid] = get(OSV_VULN.format(id=vid))
            except Exception as exc:  # noqa: BLE001 — the id is UNKNOWN, the rest stand
                details[vid] = exc
        d = details[vid]
        if isinstance(d, Exception):
            unreadable.append(vid)
            continue
        mine = [a for a in d.get("affected") or []
                if (purl and str(a.get("package", {}).get("purl", "")).split("@")[0] == purl)
                or (a.get("package", {}).get("name") == name
                    and (ecosystem is None or a.get("package", {}).get("ecosystem") == ecosystem))]
        if any(osv_affected_holds(version, a) for a in mine):
            cve = next((x for x in [d.get("id"), *(d.get("aliases") or [])]
                        if str(x).startswith("CVE-")), None)
            hits.append({"id": vid, "cve": cve,
                         "severity": (d.get("database_specific") or {}).get("severity"),
                         "url": f"https://osv.dev/vulnerability/{vid}"})
        else:
            server_only.append(vid)
    return hits, server_only, unreadable


def _enrich(hits: list[dict], get, kev_cache: dict, src: dict) -> None:
    for h in hits:
        cve = h.get("cve")
        if not cve:
            h.update(kev=None, epss=None, kev_reason="no CVE id; cve.now is asked by CVE id only")
            continue
        if cve not in kev_cache:
            try:
                kev_cache[cve] = get(CVE_NOW.format(id=cve))
            except Exception as exc:  # noqa: BLE001
                kev_cache[cve] = exc
        e = kev_cache[cve]
        src["asked"] += 1
        if isinstance(e, Exception) or not isinstance(e, dict):
            src["errors"].append(f"{cve}: {e}")
            h.update(kev=None, epss=None, kev_reason="UNKNOWN: cve.now unreadable")
            continue
        exp = e.get("exploitation") or {}
        h.update(kev=exp.get("kev") is not None, epss=exp.get("epssReached"), kev_reason=None)


# --- the report --------------------------------------------------------------

def collect(pin_values: dict | None = None, receptor_map: dict | None = None,
            lockfiles: dict | None = None, fetch=None) -> dict:
    get = fetch or globals()["fetch"]
    pin_values = pins() if pin_values is None else pin_values
    receptor_map = receptors() if receptor_map is None else receptor_map
    lockfiles = LOCKFILES if lockfiles is None else lockfiles
    sources = {n: {"state": "OK", "asked": 0, "errors": []} for n in ("github", "osv", "cve.now")}
    out_pins: list[dict] = []
    osv_queries: list[tuple[dict, dict]] = []  # (query, the row it answers)

    for var in sorted(pin_values):
        version = pin_values[var]
        r = receptor_map.get(var)
        row = {"var": var, "version": version, "matches": []}
        out_pins.append(row)
        if not isinstance(r, dict) or not any(k in r for k in KINDS):
            row.update(receptor={"kind": "missing"}, state="UNKNOWN",
                       reason="no receptor row in state/genome/advisory-receptors.yml")
            continue
        kind = _kind(r)
        row["receptor"] = {"kind": kind, "target": r[kind], **({"floating": r["floating"]}
                                                              if "floating" in r else {})}
        if kind == "none":
            row.update(state="none", reason=r["none"])
            continue
        if "floating" in r:
            row.update(state="UNKNOWN", reason=f"floating: {r['floating']}")
            continue
        try:
            parse_version(version)
        except ValueError:
            row.update(state="UNKNOWN", reason=f"{version!r} names no release to match")
            continue
        if kind == "tech":
            row.update(state="UNKNOWN", reason="tech: receptors are declared; no source reads them yet")
        elif kind == "github":
            sources["github"]["asked"] += 1
            try:
                advisories = _github_advisories(r["github"], get)
                hits, unranged = _match_github(version, advisories)
            except Exception as exc:  # noqa: BLE001 — this pin is UNKNOWN, the rest stand
                sources["github"]["errors"].append(f"{r['github']}: {exc}")
                row.update(state="UNKNOWN", reason=f"github {r['github']} unreadable: {exc}")
                continue
            row.update(matches=hits, published=len(advisories))
            if unranged:
                row["unranged"] = unranged
            row["state"] = "affected" if hits else ("UNKNOWN" if unranged else "clear")
            if not hits and unranged:
                row["reason"] = f"{len(unranged)} advisories carry no range to match"
        elif kind == "osv":
            osv_queries.append(({"package": {"purl": r["osv"]}, "version": version}, row))

    out_lock: list[dict] = []
    for organ, (path, eco) in sorted(lockfiles.items()):
        lf = {"organ": organ, "path": str(path), "ecosystem": eco, "matches": []}
        out_lock.append(lf)
        try:
            pkgs = lockfile_packages(pathlib.Path(path), eco)
        except Exception as exc:  # noqa: BLE001
            lf.update(state="UNKNOWN", reason=f"lockfile unreadable: {exc}")
            continue
        lf.update(packages=len(pkgs), server_only=[], unreadable=[])
        for name, ver in pkgs:
            osv_queries.append(({"package": {"name": name, "ecosystem": eco}, "version": ver},
                                {"_lock": lf, "name": name, "version": ver}))

    if osv_queries:
        sources["osv"]["asked"] = len(osv_queries)
        try:
            id_lists = _osv([q for q, _ in osv_queries], get)
        except Exception as exc:  # noqa: BLE001
            sources["osv"]["errors"].append(str(exc))
            id_lists = None
        details: dict = {}
        for i, (q, target) in enumerate(osv_queries):
            lf = target.get("_lock")
            if id_lists is None:
                holder = lf if lf is not None else target
                holder.update(state="UNKNOWN", reason=f"OSV unreadable: {sources['osv']['errors'][0]}")
                continue
            name = target["name"] if lf is not None else q["package"]["purl"]
            hits, server_only, unreadable = _osv_rematch(
                name, q["package"].get("ecosystem"), q["package"].get("purl"),
                q["version"], id_lists[i], details, get)
            if unreadable:
                sources["osv"]["errors"].append(f"{name}: records unreadable {unreadable}")
            if lf is not None:
                for h in hits:
                    lf["matches"].append({"package": name, "version": q["version"], **h})
                lf["server_only"] += server_only
                lf["unreadable"] += [f"{name}:{u}" for u in unreadable]
            else:
                target.update(matches=hits, server_only=server_only, unreadable=unreadable)
                target["state"] = ("affected" if hits else "UNKNOWN" if unreadable else "clear")
        for lf in out_lock:
            if "state" not in lf:
                lf["state"] = ("affected" if lf["matches"] else
                               "UNKNOWN" if lf["unreadable"] else "clear")

    kev_cache: dict = {}
    for holder in [*out_pins, *out_lock]:
        _enrich(holder["matches"], get, kev_cache, sources["cve.now"])

    for s in sources.values():
        if s["errors"]:
            s["state"] = "UNKNOWN"
    cve = sources["cve.now"]
    if not cve["asked"] and "UNKNOWN" in (sources["github"]["state"], sources["osv"]["state"]):
        # Nothing reached it because nothing upstream could be read: what it
        # would have been asked is unknown too, so it is not "not needed".
        cve.update(state="UNKNOWN", errors=["not asked: the sources that name CVE ids were unreadable"])
    for s in sources.values():
        if s["state"] == "OK" and not s["asked"]:
            s["state"] = "UNASKED"

    rows = [*out_pins, *out_lock]
    affected = [r for r in rows if r.get("state") == "affected"]
    unknown = [r for r in rows if r.get("state") == "UNKNOWN"]
    verdict = "AFFECTED" if affected else ("UNKNOWN" if unknown else "CLEAR")
    return {"verdict": verdict, "sources": sources, "pins": out_pins, "lockfiles": out_lock,
            "counts": {"affected": len(affected), "unknown": len(unknown),
                       "clear": sum(r.get("state") == "clear" for r in rows),
                       "none": sum(r.get("state") == "none" for r in rows)}}


def render(rep: dict) -> str:
    lines = [f"advisory-status — {rep['verdict']}  "
             f"(affected {rep['counts']['affected']}, unknown {rep['counts']['unknown']}, "
             f"read and unmatched {rep['counts']['clear']}, no receptor source {rep['counts']['none']})",
             ""]
    for name, s in rep["sources"].items():
        err = f" — {s['errors'][0]}" + (f" (+{len(s['errors']) - 1})" if len(s["errors"]) > 1 else "") \
            if s["errors"] else ""
        lines.append(f"  source {name:8} {s['state']:8} asked {s['asked']}{err}")
    lines.append("")
    for row in rep["pins"]:
        st = row["state"]
        what = row["receptor"].get("target", "")
        if st == "affected":
            lines.append(f"  AFFECTED {row['var']} {row['version']} ({what})")
            for m in row["matches"]:
                lines.append(f"      {m['id']} {m.get('severity') or '?'} range {m.get('range', '?')}"
                             f" fixed {m.get('fixed') or '?'} kev {_kev(m)}")
        elif st == "clear":
            lines.append(f"  read     {row['var']} {row['version']}: 0 of {row.get('published', '?')}"
                         f" advisories match ({what})")
        elif st == "UNKNOWN":
            lines.append(f"  UNKNOWN  {row['var']} {row['version']}: {row.get('reason', '')}")
    for lf in rep["lockfiles"]:
        if lf["state"] == "UNKNOWN":
            lines.append(f"  UNKNOWN  lockfile {lf['organ']}: {lf.get('reason', '')}")
        else:
            lines.append(f"  {'AFFECTED' if lf['matches'] else 'read    '} lockfile {lf['organ']}:"
                         f" {len(lf['matches'])} matches in {lf['packages']} packages")
            for m in lf["matches"]:
                lines.append(f"      {m['package']} {m['version']} {m['id']} kev {_kev(m)}")
    return "\n".join(lines)


def _kev(m: dict) -> str:
    return "UNKNOWN" if m.get("kev") is None else ("YES" if m["kev"] else "no")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        rep = collect(fetch=fetch)
    except Exception as exc:  # noqa: BLE001 — a reader reports, it does not crash
        rep = {"verdict": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}",
               "sources": {}, "pins": [], "lockfiles": [], "counts": {}}
        if not args.json:
            print(f"advisory-status — UNKNOWN: {rep['error']}")
            return 0
    print(json.dumps(rep, indent=2, default=str) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
