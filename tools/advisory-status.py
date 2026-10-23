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
             cve.now  /feed?tech=<slug>&format=json for `tech:` pins, each entry
                      fetched by id and matched on its affected[] product
                      ranges; /api/v1/entries/<CVE> for KEV and EPSS

MATCHING is exact: introduced <= v < fixed, last_affected inclusive; a
prerelease sorts before its release; an image variant ("16.15-alpine",
"-ce.0") and a digest ("@sha256:...") are not part of the version. A GitHub
advisory lists one range per release line; a range whose patch is on another
line does not count when the version's own line has a patch (release_line()).

WHAT IT DOES NOT DO. It writes nothing and exits 0 whatever it finds. Each
source is UNKNOWN on its own: an unreachable source makes its pins UNKNOWN,
never clean, and the report never says "no findings" — a pin is `clear` only
when its source was read, and the line says how many advisories were read.
One advisory that cannot be read is UNKNOWN on its own; a cve.now feed that is
empty for a slug leaves its pin UNKNOWN. The report says how many network
calls the run made.

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
import urllib.error
import urllib.parse
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import _advisory_cache  # noqa: E402
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
CVE_NOW_FEED = "https://cve.now/feed?tech={slug}&format=json"
TIMEOUT = 20
GITHUB_MAX_PAGES = 30
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


_OP = r"(?:>=|<=|=<|=>|>|<|=)"
_TOKEN = re.compile(rf"({_OP})?(.+?)({_OP})?")
#: An operator written AFTER its version reads from the bound's side:
#: "1.2=<" is 1.2 =< v, a lower bound.
_POSTFIX = {"=<": ">=", "<=": ">=", "<": ">", "=>": "<=", ">=": "<=", ">": "<", "=": "="}
_LOWER, _UPPER = (">=", ">"), ("<=", "<")


def range_groups(rng: str) -> list[list[tuple[str, tuple]]]:
    """A vulnerable_version_range as an OR of AND-groups of (op, version key).

    Forms seen live (2026-10-23): "<= 1.13.1", ">= 1.0, < 1.2.3",
    "v1.11.2=< <=v1.12.2", ">=9.2.0 <9.2.10 >=9.3.0 <9.3.4" (space-joined
    pairs: a lower bound after an upper starts a new range), "1.0.0 - 1.1.1"
    (inclusive), "\u2264 2026.5.2". Anything else raises ValueError.
    """
    s = str(rng or "").replace("\u2264", "<=").replace("\u2265", ">=")
    groups: list[list[tuple[str, tuple]]] = []
    for alt in re.split(r"\|\||;", s):
        hyphen = re.fullmatch(r"\s*(\S+)\s+-\s+(\S+)\s*", alt)
        if hyphen:
            groups.append([(">=", parse_version(hyphen.group(1))),
                           ("<=", parse_version(hyphen.group(2)))])
            continue
        cur: list[tuple[str, tuple]] = []
        for tok in re.split(r"[,\s]+", re.sub(rf"(^|[\s,])({_OP})\s+", r"\1\2", alt).strip()):
            if not tok:
                continue
            pre, ver, post = _TOKEN.fullmatch(tok).groups()
            if pre and post:
                raise ValueError(f"not a range: {rng!r}")
            op = {"=<": "<=", "=>": ">="}.get(pre, pre) if pre else _POSTFIX.get(post, "=")
            bound = parse_version(ver)
            if cur and (op in (*_LOWER, "=") and any(o in (*_UPPER, "=") for o, _ in cur)):
                groups.append(cur)
                cur = []
            cur.append((op, bound))
        if cur:
            groups.append(cur)
    if not groups:
        raise ValueError(f"not a range: {rng!r}")
    return groups


def _holds(key: tuple, group: list[tuple[str, tuple]]) -> bool:
    return all({">=": key >= b, ">": key > b, "<=": key <= b, "<": key < b, "=": key == b}[op]
               for op, b in group)


def github_range_holds(v: str, rng: str) -> bool:
    """True when `v` sits in any range of `rng` (see range_groups)."""
    key = parse_version(v)
    return any(_holds(key, g) for g in range_groups(rng))


def release_line(key: tuple) -> tuple:
    """The release line a version belongs to: its major, or major.minor for a
    calendar version (2026.5.x) and for 0.x, where the minor is the line."""
    nums = key[0]
    return nums[:2] if nums[0] >= 1000 or nums[0] == 0 else nums[:1]


def _fmt_range(introduced=None, fixed=None, last_affected=None) -> str:
    parts = [f">= {introduced}"] if introduced not in (None, "0") else []
    parts += [f"< {fixed}"] if fixed is not None else []
    parts += [f"<= {last_affected}"] if last_affected is not None else []
    return ", ".join(parts) or "all versions"


def osv_affected_holds(v: str, affected: dict) -> bool:
    return osv_affected_match(v, affected) is not None


def osv_affected_match(v: str, affected: dict) -> dict | None:
    """One OSV `affected` entry: its explicit versions, then its ranges' events.

    Events read in order: each `introduced` opens an interval that the next
    `fixed` (exclusive) or `last_affected` (inclusive) closes. GIT ranges carry
    commits, not versions, and are skipped. Returns the interval that matched.
    """
    if v in (affected.get("versions") or []):
        return {"range": f"= {v} (listed)", "fixed": None}
    for r in affected.get("ranges") or []:
        if r.get("type") == "GIT":
            continue
        start = None
        for ev in r.get("events") or []:
            if "introduced" in ev:
                start = ev["introduced"]
            elif "fixed" in ev and start is not None:
                if in_range(v, introduced=start, fixed=ev["fixed"]):
                    return {"range": _fmt_range(start, fixed=ev["fixed"]), "fixed": ev["fixed"]}
                start = None
            elif "last_affected" in ev and start is not None:
                if in_range(v, introduced=start, last_affected=ev["last_affected"]):
                    return {"range": _fmt_range(start, last_affected=ev["last_affected"]), "fixed": None}
                start = None
        if start is not None and in_range(v, introduced=start):
            return {"range": _fmt_range(start), "fixed": None}
    return None


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
                 or set(r) - set(KINDS) - {"floating", "product"}]
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


#: The ETag cache, only when the operator passes --cache-dir (no default).
#: Its writes live in tools/_advisory_cache.py; see that file for why.
CACHE: _advisory_cache.Cache | None = None
CACHE_STATS = {"not_modified": 0}


def use_cache(path) -> None:
    """Point the cache at `path` (None turns it off). ValueError inside the repo."""
    global CACHE
    CACHE = None if path is None else _advisory_cache.Cache(path)
    CACHE_STATS["not_modified"] = 0


def fetch(url: str, body: bytes | None = None):
    """GET `url` (or send `body` to it) and parse the JSON answer.

    Everything this reader learns from the network passes here, so a test
    replaces this one function. A body goes only to OSV's querybatch, a query
    that changes nothing (OSV offers no GET for it).
    """
    headers = headers_for(url)
    cached = CACHE.get(url) if CACHE is not None and body is None else None
    if cached:
        headers["If-None-Match"] = cached["etag"]
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            etag = resp.headers.get("ETag")
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and cached:
            CACHE_STATS["not_modified"] += 1
            return cached["body"]
        raise
    if CACHE is not None and body is None and etag:
        try:
            CACHE.put(url, etag, data)
        except OSError:
            pass  # a cache that cannot be written only costs the next run a call
    return data


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
    """-> (hits, unreadable ids). One advisory that cannot be read is UNKNOWN
    on its own; the rest of the repo is still matched.

    GitHub lists one vulnerabilities[] entry per release line (authentik:
    "<= 2026.8.1 -> 2026.8.2 ; <= 2026.5.6 -> 2026.5.7"). A range whose patch
    sits on ANOTHER line does not count against `version` when its own line
    has a patch of its own: 2026.5.7 is not inside "<= 2026.8.1". A line with
    no patch of its own (an older line) stays affected.
    """
    key, hits, unreadable = parse_version(version), [], []
    own = release_line(key)
    for a in advisories:
        if a.get("withdrawn_at"):
            continue
        vulns = [v for v in a.get("vulnerabilities") or [] if v.get("vulnerable_version_range")]
        try:
            if not vulns:
                raise ValueError("no range")
            rows = []
            for v in vulns:
                patched = [parse_version(p) for p in re.split(r"[,\s]+", str(v.get("patched_versions") or ""))
                           if p.strip()]
                rows.append((v, any(_holds(key, g) for g in range_groups(v["vulnerable_version_range"])),
                             patched))
        except ValueError:
            unreadable.append(a.get("ghsa_id"))
            continue
        own_patched = any(release_line(p) == own for _, _, ps in rows for p in ps)
        for v, holds, patched in rows:
            if not holds:
                continue
            if own_patched and patched and all(release_line(p) != own for p in patched):
                continue  # this range is another line's; ours has its own patch
            pkg = v.get("package") or {}
            # A repo advisory can cover several packages: the hit names the
            # one whose range matched, so a cross-package match is visible.
            hits.append({"id": a.get("ghsa_id"), "cve": a.get("cve_id"),
                         "severity": a.get("severity"), "range": v["vulnerable_version_range"],
                         "fixed": v.get("patched_versions") or None, "package": pkg.get("name"),
                         "ecosystem": pkg.get("ecosystem"), "url": a.get("html_url")})
            break
    return hits, unreadable


def _match_tech(version: str, product: str | None, entries: list[dict]) -> tuple[list[dict], list[str]]:
    """cve.now entries -> (hits, unreadable ids), by affected[] vendor/product
    ranges. `product` (from the receptor) narrows affected[] to that product;
    an entry with no affected row for it is not about this pin. A bound of
    "*" or one that names no release makes that entry UNKNOWN."""
    hits, unreadable = [], []
    for e in entries:
        rows = [a for a in e.get("affected") or []
                if not product or str(a.get("product", "")).casefold() == product.casefold()]
        if not rows:
            continue
        found = None
        try:
            for a in rows:
                if version in (a.get("versions") or []):
                    found = {"range": f"= {version} (listed)", "fixed": None}
                for r in a.get("ranges") or []:
                    ev = {k: r.get(k) for k in ("introduced", "fixed", "last_affected") if r.get(k)}
                    if not ev:
                        raise ValueError("empty range")
                    if in_range(version, **ev) and found is None:
                        found = {"range": _fmt_range(ev.get("introduced"), ev.get("fixed"),
                                                     ev.get("last_affected")), "fixed": ev.get("fixed")}
        except ValueError:
            unreadable.append(e.get("id"))
            continue
        if found:
            exp = e.get("exploitation") or {}
            eid = str(e.get("id"))
            hits.append({"id": eid, "cve": eid if eid.startswith("CVE-") else None,
                         "severity": (e.get("severity") or {}).get("cvss"), **found,
                         "kev": exp.get("kev") is not None, "epss": exp.get("epssReached"),
                         "kev_reason": None, "url": f"https://cve.now/{eid}"})
    return hits, unreadable


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
        if not mine:
            unreadable.append(vid)  # OSV named it, but no entry here is tied to our package
            continue
        try:
            held = next((m for m in (osv_affected_match(version, a) for a in mine) if m), None)
        except ValueError:
            unreadable.append(vid)  # a version here or in the record names no release
            continue
        if held:
            cve = next((x for x in [d.get("id"), *(d.get("aliases") or [])]
                        if str(x).startswith("CVE-")), None)
            hits.append({"id": vid, "cve": cve, **held,
                         "severity": (d.get("database_specific") or {}).get("severity"),
                         "url": f"https://osv.dev/vulnerability/{vid}"})
        else:
            server_only.append(vid)
    return hits, server_only, unreadable


def _enrich(hits: list[dict], get, kev_cache: dict, src: dict) -> None:
    for h in hits:
        if "kev" in h:
            continue  # the source already said (cve.now tech entries)
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
    raw = fetch or globals()["fetch"]
    calls = [0]

    def get(url, body=None):
        calls[0] += 1
        return raw(url) if body is None else raw(url, body)

    pin_values = pins() if pin_values is None else pin_values
    receptor_map = receptors() if receptor_map is None else receptor_map
    lockfiles = LOCKFILES if lockfiles is None else lockfiles
    sources = {n: {"state": "OK", "asked": 0, "errors": []} for n in ("github", "osv", "cve.now")}
    out_pins: list[dict] = []
    osv_queries: list[tuple[dict, dict]] = []  # (query, the row it answers)
    kev_cache: dict = {}  # cve.now entries by id: tech matching and KEV/EPSS share them

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
            slug = r["tech"]
            try:
                feed = get(CVE_NOW_FEED.format(slug=urllib.parse.quote(str(slug))))
                items = feed.get("items") if isinstance(feed, dict) else None
                if not isinstance(items, list):
                    raise ValueError("feed answered a different shape")
            except Exception as exc:  # noqa: BLE001
                sources["cve.now"]["errors"].append(f"feed tech={slug}: {exc}")
                row.update(state="UNKNOWN", reason=f"cve.now feed tech={slug} unreadable: {exc}")
                continue
            if not items:
                row.update(state="UNKNOWN", reason=f"cve.now feed is empty for tech={slug}")
                continue
            entries, unreadable = [], []
            for it in items:
                eid = str(it.get("id"))
                if eid not in kev_cache:
                    try:
                        kev_cache[eid] = get(CVE_NOW.format(id=eid))
                    except Exception as exc:  # noqa: BLE001
                        kev_cache[eid] = exc
                sources["cve.now"]["asked"] += 1
                e = kev_cache[eid]
                if isinstance(e, dict):
                    entries.append(e)
                else:
                    unreadable.append(eid)
                    sources["cve.now"]["errors"].append(f"{eid}: {e}")
            hits, bad = _match_tech(version, r.get("product"), entries)
            unreadable += bad
            row.update(matches=hits, published=len(items), unreadable=unreadable)
            row["state"] = "affected" if hits else ("UNKNOWN" if unreadable else "clear")
            if not hits and unreadable:
                row["reason"] = f"{len(unreadable)} advisories unreadable"
        elif kind == "github":
            sources["github"]["asked"] += 1
            try:
                advisories = _github_advisories(r["github"], get)
                hits, unreadable = _match_github(version, advisories)
            except Exception as exc:  # noqa: BLE001 — this pin is UNKNOWN, the rest stand
                sources["github"]["errors"].append(f"{r['github']}: {exc}")
                row.update(state="UNKNOWN", reason=f"github {r['github']} unreadable: {exc}")
                continue
            row.update(matches=hits, published=len(advisories), unreadable=unreadable)
            row["state"] = "affected" if hits else ("UNKNOWN" if unreadable else "clear")
            if not hits and unreadable:
                row["reason"] = f"{len(unreadable)} advisories unreadable"
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
    return {"verdict": verdict, "calls": calls[0], "sources": sources, "pins": out_pins, "lockfiles": out_lock,
            "counts": {"affected": len(affected), "unknown": len(unknown),
                       "clear": sum(r.get("state") == "clear" for r in rows),
                       "none": sum(r.get("state") == "none" for r in rows)}}


def render(rep: dict) -> str:
    lines = [f"advisory-status — {rep['verdict']}  "
             f"(affected {rep['counts']['affected']}, unknown {rep['counts']['unknown']}, "
             f"read and unmatched {rep['counts']['clear']}, no receptor source {rep['counts']['none']})",
             f"  {rep.get('calls', '?')} network call(s){rep.get('cache_note', '')}", ""]
    for name, s in rep["sources"].items():
        err = f" — {s['errors'][0]}" + (f" (+{len(s['errors']) - 1})" if len(s["errors"]) > 1 else "") \
            if s["errors"] else ""
        lines.append(f"  source {name:8} {s['state']:8} asked {s['asked']}{err}")
    lines.append("")
    for row in rep["pins"]:
        st = row["state"]
        what = row["receptor"].get("target", "")
        if st == "affected":
            bad = len(row.get("unreadable") or [])
            lines.append(f"  AFFECTED {row['var']} {row['version']} ({what})"
                         + (f"; {bad} advisories unreadable" if bad else ""))
            for m in row["matches"]:
                lines.append(f"      {_match_line(m)}")
        elif st == "clear":
            seen = (f"0 of {row['published']} advisories match" if "published" in row
                    else "0 OSV ids re-matched")
            lines.append(f"  read     {row['var']} {row['version']}: {seen} ({what})"
                         + _server_only(row))
        elif st == "UNKNOWN":
            lines.append(f"  UNKNOWN  {row['var']} {row['version']}: {row.get('reason', '')}")
    for lf in rep["lockfiles"]:
        if lf["state"] == "UNKNOWN":
            lines.append(f"  UNKNOWN  lockfile {lf['organ']}: {lf.get('reason', '')}")
        else:
            lines.append(f"  {'AFFECTED' if lf['matches'] else 'read    '} lockfile {lf['organ']}:"
                         f" {len(lf['matches'])} matches in {lf['packages']} packages" + _server_only(lf))
            for m in lf["matches"]:
                lines.append(f"      {m['package']} {m['version']} {_match_line(m)}")
    return "\n".join(lines)


def _match_line(m: dict) -> str:
    return (f"{m['id']} {m.get('severity') or '?'} range {m.get('range') or '?'}"
            f" fixed {m.get('fixed') or 'none published'} kev {_kev(m)}")


def _server_only(row: dict) -> str:
    n = len(row.get("server_only") or [])
    return f"; {n} OSV id(s) not re-matched (server_only)" if n else ""


def _kev(m: dict) -> str:
    return "UNKNOWN" if m.get("kev") is None else ("YES" if m["kev"] else "no")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cache-dir", help="keep ETags here between runs (outside the repo; no default)")
    args = ap.parse_args(argv)
    cache_note = ""
    try:
        use_cache(args.cache_dir)
    except ValueError as exc:
        use_cache(None)
        cache_note = f"; cache {exc}"
    try:
        rep = collect(fetch=fetch)
        if CACHE is not None:
            cache_note = f"; {CACHE_STATS['not_modified']} answered 304 from cache"
        rep["cache_note"] = cache_note
    except Exception as exc:  # noqa: BLE001 — a reader reports, it does not crash
        rep = {"verdict": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}", "cache_note": cache_note,
               "sources": {}, "pins": [], "lockfiles": [], "counts": {}}
        if not args.json:
            print(f"advisory-status — UNKNOWN: {rep['error']}")
            return 0
    print(json.dumps(rep, indent=2, default=str) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
