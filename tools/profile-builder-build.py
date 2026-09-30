#!/usr/bin/env python3
"""nOS profile builder — a static page, rendered at release, that writes a
config.yml before the first `nos` run.

    tools/profile-builder-build.py --out _site/profile-builder   # pages.yml
    tools/profile-builder-build.py --out /tmp/pb && open /tmp/pb/index.html
    tools/profile-builder-build.py --out DIR --image-lock <cache>/images/images.lock.json

Everything the page knows comes from the artifacts, at build time:
  default.config.yml   every install_* flag, its default, its inline label and
                       the section it sits in; the defaults of every field
  profiles/*.yml       the `axis:` header (use-case | policy | service-set |
                       environment | constraint), its install_* flags and its
                       other knobs
  roles/*/templates    each service's images and mem_limit, rendered the way
                       tools/cloud/registry-reach.py renders them (its code)
  --image-lock         tools/nos-image-cache.py's lock: per-image bytes, and
                       which services an OFFLINE build can run at all
The page itself (tools/profile-builder/index.html.tpl) is plain HTML + JS with
no dependencies; the build only substitutes __DATA__.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "default.config.yml"
PROFILES = REPO / "profiles"
TPL = REPO / "tools/profile-builder/index.html.tpl"

_spec = importlib.util.spec_from_file_location("registry_reach", REPO / "tools/cloud/registry-reach.py")
reach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reach)

FLAG = re.compile(r"^(install_[a-z0-9_]+):\s*(.+?)\s*(?:#\s*(.*))?$")
SECTION = re.compile(r"^# ─+ ?(.+?) ?─*$")
AXES = ["service-set", "use-case", "policy", "environment", "constraint"]

# The steps, in the order a person decides them. Every key is a variable
# default.config.yml declares (the gate checks); `hint` is the plain-language
# line under the field. A `secret` field is shown but never written.
STEPS = [
    {"id": "machine", "title": "Machine & storage", "blurb": "Where nOS keeps its data, and whether it keeps a copy of the apps it downloads.", "fields": [
        {"key": "nos_data_root", "label": "Data folder", "type": "text", "placeholder": "~/nos",
         "hint": "One folder holds every service's data. Point it at an external SSD (e.g. /Volumes/SSD1TB/nos) to keep the internal disk free."},
        {"key": "configure_external_storage", "label": "Also move Docker, AI models and caches to an external disk", "type": "bool",
         "hint": "Docker's disk image, AI models and package caches are the big things. Turn this on if you have an external SSD."},
        {"key": "external_storage_root", "label": "External disk", "type": "text",
         "hint": "The mount point of that disk. Only used when the switch above is on."},
        {"key": "artifact_cache_seed", "label": "Keep a local copy of every app image", "type": "bool",
         "hint": "Lets a rebuild skip re-downloading (~70 GB for everything). Stored next to the data folder, never deleted by a removal."},
        {"key": "stack_up_parallel", "label": "Start services all at once", "type": "bool",
         "hint": "Faster on a strong machine. Turn off on a small one, or when turning on many services at once."},
    ]},
    {"id": "domain", "title": "Domain & access", "blurb": "The address every service answers on, and who can reach it from outside.", "fields": [
        {"key": "tenant_domain", "label": "Domain", "type": "text",
         "hint": "Every service gets its own name under it, e.g. files.dev.local. A name ending in .local/.lan/.test stays on this machine (self-signed certificate, no internet needed). A real domain you own gets Let's Encrypt certificates through Cloudflare DNS."},
        {"key": "install_tailscale", "label": "Reach it from anywhere with Tailscale", "type": "bool",
         "hint": "A private VPN between your devices. You log in once in the browser after the first run."},
        {"key": "tailscale_hostname", "label": "Tailscale name of this machine", "type": "text", "placeholder": "mac-studio.tailnet-abc.ts.net",
         "hint": "Optional. Shown on the home page as the remote address."},
        {"key": "services_lan_access", "label": "Let other devices on the local network connect by port", "type": "bool",
         "hint": "Off keeps every service on this machine only. On opens them to your LAN and VPN."},
    ]},
    {"id": "people", "title": "People", "blurb": "Who owns this installation. Everyone else is invited from the Users page after the first run.", "fields": [
        {"key": "instance_name", "label": "Name of this installation", "type": "text",
         "hint": "Lowercase, no spaces. Appears in backups and notifications."},
        {"key": "instance_org", "label": "Organisation", "type": "text",
         "hint": "Your company or team. Goes into the GDPR record of processing as the controller."},
        {"key": "default_admin_email", "label": "Admin e-mail", "type": "text", "placeholder": "admin@<your domain>",
         "hint": "Receives notifications and certificate notices; the fallback admin address in every service."},
        {"key": "nos_primary_admin", "label": "Admin username", "type": "text", "placeholder": "your login on this machine",
         "hint": "The account that owns the git forge and CI. Defaults to your login name on this machine."},
        {"key": "enforce_mfa", "label": "Require a second factor to sign in", "type": "bool",
         "hint": "Authenticator app or passkey for everyone. Recommended when the domain is public."},
        {"key": "global_password_prefix", "label": "Password prefix", "type": "password", "secret": True,
         "hint": "Every generated password starts with it. Choose once, keep it secret — it goes into credentials.yml, never into this file."},
    ]},
    {"id": "services", "title": "Services", "fields": []},
    {"id": "backup", "title": "Backup & mail", "blurb": "Where the nightly copy goes, and whether the machine sends real e-mail.", "fields": [
        {"key": "install_backup", "label": "Nightly backup of every service", "type": "bool",
         "hint": "Databases, files and settings, every night at 03:00, into the built-in object store on this machine."},
        {"key": "install_backrest", "label": "Second copy on another disk or bucket (restic)", "type": "bool",
         "hint": "Recommended. Needs a target below; gives browse-and-restore per file."},
        {"key": "restic_repo", "label": "Where the second copy goes", "type": "text", "placeholder": "/Volumes/Backup/restic  or  s3:https://nas.lan:9000/nos-restic",
         "hint": "A folder on another disk, or an S3 bucket (local NAS or off-site). S3 keys go into credentials.yml."},
        {"key": "backup_encryption_enabled", "label": "Encrypt the backups", "type": "bool",
         "hint": "AES-256 before anything is written. Keep the key with the password prefix."},
    ]},
    {"id": "review", "title": "Review & download", "fields": []},
]
MAIL = {"key": "mail", "label": "E-mail from this machine", "options": [
    {"id": "none", "label": "None — services cannot send mail", "flags": {"install_mailpit": False, "install_smtp_stalwart": False}},
    {"id": "mailpit", "label": "Capture only — every mail lands in a local inbox, nothing leaves the box", "flags": {"install_mailpit": True, "install_smtp_stalwart": False}},
    {"id": "stalwart", "label": "Real mail server on your domain — needs a public domain, DNS records and port 25",
     "flags": {"install_mailpit": False, "install_smtp_stalwart": True}},
]}

# Where nothing is measurable, ONE table of assumptions, shown as such in the
# page: GB of service data per manifest category after a year of normal use.
DATA_GB_ASSUMED = {"database": 2, "media": 20, "ai": 10, "knowledge": 5, "storage": 10, "collaboration": 10,
                   "gis": 5, "devops": 5, "cms": 1, "app": 1, "_default": 1}
HOST_NOTE = "runs on the host, no container limit — not counted"


def flags() -> list[dict]:
    out, section = [], "General"
    for ln in CONFIG.read_text().splitlines():
        m = SECTION.match(ln.strip())
        if m:
            section = m.group(1).strip()
            continue
        m = FLAG.match(ln)
        if not m:
            continue
        key, raw, label = m.groups()
        raw = raw.strip().strip('"')
        if "{{" in raw:
            default, auto = None, True
        else:
            default, auto = raw.lower() == "true", False
        out.append({"key": key, "default": default, "auto": auto,
                    "label": (label or "").strip(), "section": section})
    return out


def defaults() -> dict:
    """Every field's default. A Jinja default (`{{ … }}`) is the playbook's
    to decide, so the page shows its placeholder and writes nothing."""
    raw = yaml.safe_load(CONFIG.read_text()) or {}
    out = {}
    for step in STEPS:
        for f in step["fields"]:
            v = raw.get(f["key"], "")
            out[f["key"]] = None if isinstance(v, str) and "{{" in v else v
    return out


def profiles() -> list[dict]:
    out = []
    for p in sorted(PROFILES.glob("*.yml")):
        text = p.read_text()
        m = re.search(r"^# axis: ([a-z-]+)", text, re.M)
        if not m:
            continue
        data = yaml.safe_load(text) or {}
        purpose = re.search(r"^# Purpose: (.+)$", text, re.M)
        out.append({"id": p.stem, "axis": m.group(1),
                    "purpose": (purpose.group(1) if purpose else "").strip(),
                    "flags": {k: bool(v) for k, v in data.items() if k.startswith("install_") and isinstance(v, bool)},
                    "knobs": {k: v for k, v in data.items() if not k.startswith("install_")}})
    return out


def mem_bytes(limit: str) -> int:
    m = re.fullmatch(r"(\d+)([kmg]?)b?", limit.strip().lower())
    return int(m.group(1)) << {"": 0, "k": 10, "m": 20, "g": 30}[m.group(2)] if m else 0


def lock_entry(image: str, lock: dict) -> dict | None:
    """The lock keys images as docker lists them: `repo:tag`, no docker.io/ or
    library/, and a digest-pinned compose ref by its repo digest."""
    ref = image.removeprefix("docker.io/").removeprefix("library/")
    if ref in lock:
        return lock[ref]
    if "@" in ref:
        digest = ref.split("@", 1)[1]
        for k, e in lock.items():
            if k.endswith("@" + digest) or any(d.endswith("@" + digest) for d in e.get("digests", [])):
                return e
    return None


def services(lock: dict | None) -> dict:
    """Per install_* flag (and apps_runner_enabled): images, declared memory,
    the data-size assumption and, given a lock, whether an offline build has
    every image. Multi-container roles sum; a flag no role renders is a host
    daemon and says so."""
    vars_ = reach.load(CONFIG)
    vars_.update(reach.load(REPO / "default.credentials.yml"))
    out: dict = {}
    for row in reach.discover(vars_, all_=True):
        if not row["flag"]:
            continue
        s = out.setdefault(row["flag"], {"ids": [], "images": [], "mem_bytes": 0, "data_gb": 0, "missing": []})
        s["ids"].append(row["id"])
        s["images"] += row["images"]
        s["mem_bytes"] += sum(mem_bytes(m) for m in row["mem_limits"])
        s["data_gb"] += DATA_GB_ASSUMED.get(row["category"], DATA_GB_ASSUMED["_default"])
    for s in out.values():
        s["host"] = not s["images"]
        s["mem_note"] = HOST_NOTE if s["host"] else "declared container limit"
        if lock is not None:
            sizes = []
            for img in s["images"]:
                if img.split("/", 1)[0] in reach.LOCAL_NAMESPACES:
                    continue                      # built by the converge, not pulled
                e = lock_entry(img, lock)
                (sizes.append(e["bytes"]) if e else s["missing"].append(img))
            s["image_bytes"] = sum(sizes)
        s["offline_ok"] = not s["missing"]
    return out


def build(lock_path: Path | None = None) -> dict:
    lock = json.loads(Path(lock_path).read_text())["images"] if lock_path else None
    svcs, fl = services(lock), flags()
    raw = yaml.safe_load(CONFIG.read_text()) or {}
    # A service gated by a plain knob (redis_docker, apps_runner_enabled) counts
    # when that knob resolves true: default → profile knobs → fields.
    knob_defaults = {k: bool(raw.get(k)) for k in svcs if k not in {f["key"] for f in fl}}
    return {"axes": AXES, "steps": STEPS, "defaults": defaults(), "knob_defaults": knob_defaults, "mail": MAIL,
            "flags": fl, "profiles": profiles(), "services": svcs,
            "offline": lock is not None, "assumptions": DATA_GB_ASSUMED,
            "local_suffixes": [".local", ".lan", ".test", ".localhost"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--image-lock", default=None, help="images.lock.json of a nos-image-cache; marks an OFFLINE build")
    ap.add_argument("--json", action="store_true", help="print the data, build nothing")
    a = ap.parse_args()
    data = build(a.image_lock)
    if a.json:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    html = TPL.read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (out / "index.html").write_text(html)
    offline = sum(1 for s in data["services"].values() if not s["offline_ok"])
    print(f"{out / 'index.html'}: {len(data['flags'])} flags, {len(data['profiles'])} profiles"
          + (f", offline build: {offline} services without an image" if data["offline"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
