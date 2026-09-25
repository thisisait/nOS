#!/usr/bin/env python3
"""Can this sandbox PULL every image the profile would run? Ask before converging.

A cloud agent sandbox reaches some registries and not others (a Claude cloud
session, default policy: Docker Hub yes; ghcr.io blob storage, quay.io, lscr.io
no). Without this, the answer arrives forty minutes into a converge as a compose
error naming one image; with it, it arrives in seconds naming every one.

    tools/cloud/registry-reach.py --profile profiles/cloud-e2e.yml
    tools/cloud/registry-reach.py --profile P -e install_gitea=true
    tools/cloud/registry-reach.py --all        # every service, enabled or not
    tools/cloud/registry-reach.py --pull       # actually pull (warms the cache)

Which services: state/manifest.yml `install_flag` (plus apps/*.yml when
apps_runner_enabled, minus apps_skip), resolved against
default.config.yml < config.yml < --profile < -e (the playbook's precedence for
these files). Which image: the role's own templates/compose*.j2 `image:` lines,
rendered against role defaults + those vars — the template, not the manifest's
`image:` field, is what compose pulls.

Probe: a HEAD on the manifest (registry API + anonymous token; Docker Hub
images try the daemon's registry-mirrors first) AND a CONNECT to the registry's
blob host, because the two are different hosts and a policy can allow one and
refuse the other (ghcr.io answers; pkg-containers.githubusercontent.com is 403 —
measured 2026-09-25). `--pull` replaces both with the truth.

Exit 0 iff every ENABLED service's images are reachable. A template this cannot
render is UNRESOLVED — printed, and not counted as reachable.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "state" / "manifest.yml"

# registry -> the host its layer blobs are served from, when that differs.
BLOB_HOSTS = {
    "ghcr.io": "pkg-containers.githubusercontent.com",
    "lscr.io": "pkg-containers.githubusercontent.com",   # lscr redirects to ghcr
    "quay.io": "cdn01.quay.io",
    "docker.io": "production.cloudflare.docker.com",
    "gcr.io": "storage.googleapis.com",
}
# Images the playbook BUILDS (nos/face, nos/keap, nos/superset, nos-bone) — no
# registry holds them. Their build contexts may still fetch from the network;
# that surfaces in the converge, not here.
LOCAL_NAMESPACES = {"nos", "nos-bone"}
IMAGE_RE = re.compile(r"^\s*image:\s*(.+?)\s*$", re.MULTILINE)


def load(path: Path) -> dict:
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def parse_extra(extra: list[str]) -> dict:
    out: dict = {}
    for e in extra:
        if e.startswith("@"):
            out.update(load(REPO / e[1:]))
        elif e.startswith("{"):
            out.update(yaml.safe_load(e))
        else:
            for tok in e.split():
                k, _, v = tok.partition("=")
                out[k] = yaml.safe_load(v) if v else v
    return out


class Resolver:
    """Render Jinja strings against a var dict, recursively, leniently."""

    def __init__(self, vars_: dict):
        self.vars = vars_
        self.env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
        self.env.filters.setdefault("bool", lambda v: str(v).lower() in ("1", "true", "yes", "on"))
        self.env.filters.setdefault("regex_replace", lambda v, *a, **k: v)

    def value(self, key: str, depth: int = 0):
        return self.render(self.vars.get(key), depth)

    def render(self, v, depth: int = 0):
        if not isinstance(v, str) or "{{" not in v or depth > 8:
            return v
        ctx = _Lazy(self, depth + 1)
        try:
            tpl = self.env.from_string(v)
            # shared=True: resolve names against ctx itself (lazily, recursively)
            # instead of a dict() copy of it, which would be empty.
            out = "".join(tpl.root_render_func(tpl.new_context(ctx, shared=True)))
        except Exception:  # noqa: BLE001 — unrenderable = unresolved, said below
            return None
        if out in ("True", "False"):
            return out == "True"
        return out


class _Lazy(dict):
    def __init__(self, r: Resolver, depth: int):
        super().__init__()
        self.r, self.depth = r, depth

    def __contains__(self, k):
        return k in self.r.vars

    def __getitem__(self, k):
        if k not in self.r.vars:
            raise KeyError(k)
        return self.r.value(k, self.depth)

    def get(self, k, d=None):
        return self[k] if k in self else d


def truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def registry_of(image: str) -> str:
    first = image.split("/", 1)[0]
    if "/" in image and ("." in first or ":" in first or first == "localhost"):
        return first
    return "docker.io"


def connect_ok(host: str) -> bool:
    try:
        urllib.request.urlopen(f"https://{host}/", timeout=10)
        return True
    except urllib.error.HTTPError:
        return True          # the host answered; the policy let us through
    except Exception:  # noqa: BLE001 — refused CONNECT, DNS, timeout
        return False


ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def split_ref(image: str) -> tuple[str, str, str]:
    reg = registry_of(image)
    rest = image[len(reg) + 1:] if image.startswith(reg + "/") else image
    if "@" in rest:                        # name:tag@sha256:… — the digest is what pulls
        name, _, ref = rest.partition("@")
        name = name.rsplit(":", 1)[0] if ":" in name.split("/")[-1] else name
        if reg == "docker.io" and "/" not in name:
            name = f"library/{name}"
        return reg, name, ref
    name, _, tag = rest.rpartition(":") if ":" in rest.split("/")[-1] else (rest, "", "latest")
    if reg == "docker.io" and "/" not in name:
        name = f"library/{name}"
    return reg, name, tag or "latest"


def _head(url: str, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="HEAD", headers={"Accept": ACCEPT})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


def _token(challenge: str, repo: str) -> str | None:
    m = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    if "realm" not in m:
        return None
    q = f"{m['realm']}?service={m.get('service', '')}&scope=repository:{repo}:pull"
    try:
        with urllib.request.urlopen(q, timeout=20) as r:
            body = yaml.safe_load(r.read().decode())
        return body.get("token") or body.get("access_token")
    except Exception:  # noqa: BLE001
        return None


def docker_mirrors() -> list[str]:
    p = subprocess.run(["docker", "info", "--format", "{{json .RegistryConfig.Mirrors}}"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        return [m.rstrip("/") for m in (yaml.safe_load(p.stdout) or [])]
    except Exception:  # noqa: BLE001
        return []


RATE: dict[str, str] = {}


def probe(image: str, pull: bool, mirrors: list[str]) -> tuple[bool, str]:
    """HEAD the manifest — a HEAD does not spend Docker Hub's anonymous pull
    budget (a GET, which `docker manifest inspect` issues, does; the sandbox's
    egress IP is shared, and the budget was measured at 24/100 on 2026-09-25)."""
    if pull:
        p = subprocess.run(["docker", "pull", "-q", image], capture_output=True, text=True,
                           timeout=1800, stdin=subprocess.DEVNULL)
        return (p.returncode == 0,
                "pulled" if p.returncode == 0 else (p.stderr.strip().splitlines() or ["?"])[-1][:140])
    if image.split("/", 1)[0] in LOCAL_NAMESPACES:
        present = subprocess.run(["docker", "image", "inspect", image], capture_output=True,
                                 stdin=subprocess.DEVNULL).returncode == 0
        return True, "LOCAL build (" + ("present" if present else "built by the converge") + ")"
    reg, repo, tag = split_ref(image)
    if reg == "docker.io":
        for m in mirrors:
            code, _ = _head(f"{m}/v2/{repo}/manifests/{tag}")
            if code == 200:
                return True, f"via mirror {m.split('//')[-1]}"
    host = "registry-1.docker.io" if reg == "docker.io" else reg
    url = f"https://{host}/v2/{repo}/manifests/{tag}"
    try:
        code, hdrs = _head(url)
        if code == 401:
            code, hdrs = _head(url, _token(hdrs.get("www-authenticate", ""), repo))
    except Exception as e:  # noqa: BLE001 — refused CONNECT, DNS, timeout
        return False, f"registry unreachable ({type(e).__name__})"
    if "ratelimit-remaining" in hdrs:
        RATE[reg] = hdrs["ratelimit-remaining"]
    if code != 200:
        return False, f"manifest HTTP {code}"
    blob = BLOB_HOSTS.get(reg)
    if blob and not connect_ok(blob):
        return False, f"manifest ok, blob host {blob} refused"
    return True, "manifest ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default=None)
    ap.add_argument("-e", dest="extra", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pull", action="store_true")
    a, rest = ap.parse_known_args()
    # e2e.sh forwards the converge's ansible args verbatim; keep the -e ones.
    it = iter(rest)
    for tok in it:
        if tok == "-e":
            a.extra.append(next(it, ""))
        elif tok.startswith("-e"):
            a.extra.append(tok[2:])

    vars_ = load(REPO / "default.config.yml")
    vars_.update(load(REPO / "default.credentials.yml"))
    vars_.update(load(REPO / "config.yml"))
    if a.profile:
        vars_.update(load(REPO / a.profile))
    vars_.update(parse_extra(a.extra))
    top = Resolver(vars_)

    rows = yaml.safe_load(MANIFEST.read_text())["services"]
    wanted: dict[str, list[str]] = {}   # image -> [service ids]
    unresolved: list[str] = []
    enabled_ids = []
    for row in rows:
        flag = row.get("install_flag")
        role = REPO / "roles" / f"pazny.{row['id']}"
        if not flag or not role.is_dir():
            continue
        if not a.all and not truthy(top.value(flag)):
            continue
        enabled_ids.append(row["id"])
        local = load(role / "defaults" / "main.yml")
        local.update(vars_)                       # vars_files outrank role defaults
        r = Resolver(local)
        for tpl in sorted((role / "templates").glob("compose*.j2")):
            for expr in IMAGE_RE.findall(tpl.read_text()):
                expr = expr.strip().strip('"\'')
                if expr.split("/", 1)[0] in LOCAL_NAMESPACES:
                    wanted.setdefault(expr.split(":", 1)[0], []).append(row["id"])
                    continue
                img = r.render(expr)
                if not img or "{{" in str(img) or img.endswith(":") or " " in img:
                    unresolved.append(f"{row['id']}: {expr}")
                    continue
                wanted.setdefault(img, []).append(row["id"])

    # Base stack files carry images of their own (infra: the docker socket
    # proxy) — pulled whenever that stack comes up at all.
    for base in sorted((REPO / "templates" / "stacks").glob("*/docker-compose.yml.j2")):
        for expr in IMAGE_RE.findall(base.read_text()):
            img = top.render(expr.strip().strip("\"'"))
            if img and "{{" not in str(img):
                wanted.setdefault(img, []).append(f"stack:{base.parent.name}")

    # Tier-2 manifest apps (apps_runner): literal images, gated by the runner
    # switch and apps_skip — the same discovery the role does.
    if a.all or truthy(top.value("apps_runner_enabled")):
        skip = set(top.vars.get("apps_skip") or []) if not a.all else set()
        for m in sorted((REPO / "apps").glob("*.yml")):
            if m.name.startswith("_") or m.stem in skip:
                continue
            enabled_ids.append(f"app:{m.stem}")
            for expr in IMAGE_RE.findall(m.read_text()):
                img = expr.strip().strip("\"'")
                if img.startswith("docker.io/"):
                    img = img[len("docker.io/"):]
                wanted.setdefault(img, []).append(f"app:{m.stem}")

    print(f"enabled services with an image: {len(enabled_ids)} — {', '.join(sorted(enabled_ids))}")
    bad = 0
    mirrors = docker_mirrors()
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(probe, img, a.pull, mirrors): img for img in sorted(wanted)}
        results = {futs[f]: f.result() for f in concurrent.futures.as_completed(futs)}
    for img in sorted(results):
        ok, why = results[img]
        bad += 0 if ok else 1
        print(f"  {'OK     ' if ok else 'BLOCKED'} {img:70} {why}  [{', '.join(sorted(set(wanted[img])))}]")
    for u in unresolved:
        print(f"  UNRESOLVED {u}")
    by_reg: dict[str, list[bool]] = {}
    for img, (ok, _) in results.items():
        by_reg.setdefault(registry_of(img), []).append(ok)
    for reg, left in RATE.items():
        print(f"{reg} anonymous pull budget left: {left}")
    print("registries: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(by_reg.items())))
    print(f"{len(results) - bad}/{len(results)} images reachable"
          + (f", {len(unresolved)} unresolved" if unresolved else ""))
    return 1 if (bad or unresolved) else 0


if __name__ == "__main__":
    sys.exit(main())
