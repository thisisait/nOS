#!/usr/bin/env python3
"""nOS profile builder — a static page, rendered at release, that writes a
config.yml (and, if asked, a one-line credentials.yml) before the first `nos` run.

    tools/profile-builder-build.py --out _site/profile-builder   # pages.yml
    tools/profile-builder-build.py --out ~/nos-profile-builder && open ~/nos-profile-builder/index.html
    tools/profile-builder-build.py --out DIR --image-lock <cache>/images/images.lock.json [--config config.yml]

The page is one self-contained file (no server, no network): it works from file://.

Everything the page knows comes from the artifacts, at build time:
  default.config.yml   every install_* flag and its default; every field's default;
                       authentik_rbac_tiers (the access levels); nos_identities
                       (the always-on and test accounts)
  state/manifest.yml   each flag's service category → its plain group (GROUPS)
  plugins/*/plugin.yml each service's hub_card title + description (plain words)
  profiles/*.yml       the `axis:` header, an optional `plain:` line, flags, knobs
  roles/*/templates    each service's images and mem_limit, rendered the way
                       tools/cloud/registry-reach.py renders them (its code)
  --image-lock         tools/nos-image-cache.py's lock: per-image bytes, and
                       which services an OFFLINE build can run at all
  --config             the operator's config.yml: image overrides (euro-office for
                       onlyoffice) resolve before the lock is consulted
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
PLUGINS = REPO / "files/anatomy/plugins"
MANIFEST = REPO / "state/manifest.yml"
TPL = REPO / "tools/profile-builder/index.html.tpl"

_spec = importlib.util.spec_from_file_location("registry_reach", REPO / "tools/cloud/registry-reach.py")
reach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reach)

FLAG = re.compile(r"^(install_[a-z0-9_]+):\s*(.+?)\s*(?:#\s*(.*))?$")
AXES = ["service-set", "use-case", "policy", "environment", "constraint"]
AXIS_QUESTIONS = {
    "service-set": "Which set of services do you want to start from?",
    "use-case": "What will this machine be used for?",
    "policy": "Do you need stricter security rules?",
    "environment": "Where will nOS run?",
    "constraint": "Is there anything this hardware cannot do well?",
}
# Plain group per manifest category. Keyed by the CLOSED enum in
# state/schema/manifest.schema.json — the gate fails when the enum grows a value
# this table does not place, so the grouping cannot drift silently.
GROUPS = [
    ("Sign-in, passwords & backup", ["identity", "iam", "vault", "security"]),
    ("Files, documents & knowledge", ["storage", "collaboration", "wiki", "productivity", "knowledge"]),
    ("Websites & home screen", ["web", "cms", "desktop", "rss"]),
    ("Media, books & maps", ["media", "iiab", "gis"]),
    ("Mail, messages & phone", ["mail", "messaging", "notifications", "pbx"]),
    ("Business: customers, helpdesk & money", ["crm", "helpdesk", "finance", "app"]),
    ("Automation & smart home", ["automation", "homeautomation"]),
    ("AI & assistants", ["ai", "agent"]),
    ("Charts, data & monitoring", ["data", "observability", "monitoring"]),
    ("Developer tools", ["devops"]),
    ("Under the hood: databases & network", ["infra", "database", "cache", "proxy", "vpn", "api"]),
]
HOST_GROUP = "This computer itself: tools & system settings"   # a flag with no manifest row

# The steps, in the order a person decides them. Every key is a variable
# default.config.yml declares (the gate checks); `hint` is the plain-language
# line under the field; `check` names a rule in the page's problems(). A
# `secret` field is never written to config.yml.
STEPS = [
    {"id": "machine", "title": "This computer", "blurb": "Where nOS keeps its data, and which clock it uses.", "fields": [
        {"key": "nos_timezone", "label": "Time zone", "type": "timezone", "check": "timezone",
         "hint": "Every service shows times in this zone. Start typing your city, e.g. Europe/London."},
        {"key": "nos_data_root", "label": "Data folder", "type": "text", "check": "abs_path",
         "placeholder": "/Users/<you>/nos  (the default)",
         "hint": "One folder holds every service's data. Leave empty for the default in your home folder, or write a full path on an external SSD, e.g. /Volumes/SSD1TB/nos."},
        {"key": "configure_external_storage", "label": "Also move Docker, AI models and caches to an external disk", "type": "bool",
         "hint": "Docker's disk image, AI models and package caches are the big things. Turn this on if you have an external SSD."},
        {"key": "external_storage_root", "label": "External disk", "type": "text", "check": "abs_path", "when": "configure_external_storage",
         "hint": "Where that disk is mounted, e.g. /Volumes/SSD1TB. Only used when the switch above is on."},
        {"key": "artifact_cache_seed", "label": "Keep a local copy of every app download", "type": "bool",
         "hint": "Lets a rebuild skip downloading again (about 70 GB for everything). Kept next to the data folder; a removal never deletes it."},
        {"key": "stack_up_parallel", "label": "Start services all at once", "type": "bool",
         "hint": "Faster on a strong machine. Turn off on a small one, or when you turn on many services."},
    ]},
    {"id": "domain", "title": "Web address", "blurb": "The address every service answers on, and who can reach it from outside.", "fields": [
        {"key": "tenant_domain", "label": "Domain", "type": "text", "check": "domain",
         "hint": "Every service gets its own name under it, e.g. files.dev.local. A name ending in .local, .lan or .test stays on this machine. A real domain you own gets proper certificates through Cloudflare."},
        {"key": "install_tailscale", "label": "Reach it from anywhere with Tailscale", "type": "bool",
         "hint": "A private network between your own devices. You sign in once in the browser after the first run."},
        {"key": "tailscale_hostname", "label": "Tailscale name of this machine", "type": "text", "placeholder": "mac-studio.tailnet-abc.ts.net",
         "hint": "Optional. Shown on the home page as the remote address."},
        {"key": "services_lan_access", "label": "Let other devices on your home or office network connect", "type": "bool",
         "hint": "Off keeps every service on this machine only. On opens them to your local network and VPN."},
    ]},
    {"id": "owner", "title": "Organisation & security", "blurb": "Who owns this installation, and how strict sign-in is.", "fields": [
        {"key": "instance_name", "label": "Name of this installation", "type": "text", "check": "slug",
         "hint": "Lowercase letters, digits and dashes. Appears in backups and notifications."},
        {"key": "instance_org", "label": "Organisation", "type": "text",
         "hint": "Your company or team. Recorded as the data controller in the GDPR record."},
        {"key": "default_admin_email", "label": "System e-mail", "type": "text", "check": "email", "placeholder": "admin@<your domain>",
         "hint": "Receives notifications and certificate notices; the e-mail of the built-in akadmin account."},
        {"key": "enforce_mfa", "label": "Require a second factor to sign in", "type": "bool",
         "hint": "An authenticator app or passkey for everyone. Recommended when the domain is public."},
        {"key": "global_password_prefix", "label": "Master password", "type": "password", "secret": True, "check": "prefix",
         "hint": "nOS builds the services' passwords from it. At least 12 letters or digits; keep it safe. It goes into a separate credentials.yml, never into config.yml."},
    ]},
    {"id": "services", "title": "Services", "fields": []},
    {"id": "backup", "title": "Backup & mail", "blurb": "Where the nightly copy goes, and whether the machine sends real e-mail.", "fields": [
        {"key": "install_backup", "label": "Nightly backup of every service", "type": "bool",
         "hint": "Databases, files and settings, every night at 03:00, into the built-in storage on this machine."},
        {"key": "install_backrest", "label": "Second copy on another disk or server", "type": "bool",
         "hint": "Recommended. Needs a place below; lets you browse and restore single files."},
        {"key": "restic_repo", "label": "Where the second copy goes", "type": "text", "check": "repo", "when": "install_backrest",
         "placeholder": "/Volumes/Backup/restic  or  s3:https://nas.lan:9000/nos-restic",
         "hint": "A folder on another disk, or a storage bucket (your own NAS or off-site). Bucket keys go into credentials.yml."},
        {"key": "backup_encryption_enabled", "label": "Encrypt the backups", "type": "bool",
         "hint": "Scrambled with a key before anything is written. Keep the master password safe: it unlocks them."},
    ]},
    {"id": "accounts", "title": "People", "blurb": "Who can sign in. Every account below is created on the first run, with its own account in every app.", "fields": [
        {"key": "nos_primary_admin", "label": "Your username", "type": "text", "check": "username", "placeholder": "your login name on this machine",
         "hint": "Your own administrator account. Leave empty to use your login name on this machine."},
        {"key": "nos_operator_email", "label": "Your e-mail", "type": "text", "check": "email",
         "hint": "Must differ from the system e-mail: apps that match people by e-mail would otherwise mix up you and akadmin."},
        {"key": "nos_test_users_enabled", "label": "Add four test accounts for trying out access levels", "type": "bool",
         "hint": "For testing only — their passwords are generated and not meant for real people."},
    ]},
    {"id": "review", "title": "Download", "fields": []},
]
MAIL = {"key": "mail", "label": "E-mail from this machine", "options": [
    {"id": "none", "label": "None — services cannot send mail", "flags": {"install_mailpit": False, "install_smtp_stalwart": False}},
    {"id": "mailpit", "label": "Test inbox — every mail stays in a local inbox, nothing is really sent", "flags": {"install_mailpit": True, "install_smtp_stalwart": False}},
    {"id": "stalwart", "label": "Real mail server on your domain — needs a public domain, DNS records and port 25",
     "flags": {"install_mailpit": False, "install_smtp_stalwart": True}},
]}
# Mirrors main.yml "[Security] Refuse a weak password prefix" (the gate reads both).
PREFIX_RULE = {"min": 12, "refused": ["changeme", ""]}

# Where nothing is measurable, ONE table of assumptions, shown as such in the
# page: GB of service data per manifest category after a year of normal use.
DATA_GB_ASSUMED = {"database": 2, "media": 20, "ai": 10, "knowledge": 5, "storage": 10, "collaboration": 10,
                   "gis": 5, "devops": 5, "cms": 1, "app": 1, "_default": 1}
HOST_NOTE = "runs on the host, no container limit — not counted"


def _raw() -> dict:
    return yaml.safe_load(CONFIG.read_text()) or {}


def _hub_cards() -> dict:
    """install flag → hub_card, from each plugin's requires.feature_flag."""
    out = {}
    for p in sorted(PLUGINS.glob("*/plugin.yml")):
        d = yaml.safe_load(p.read_text()) or {}
        card = d.get("hub_card") or (d.get("ui-extension") or {}).get("hub_card")
        flag = (d.get("requires") or {}).get("feature_flag")
        if card and flag:
            out.setdefault(flag, card)
    return out


def _plain(label: str) -> tuple[str, str]:
    """`Nextcloud – self-hosted cloud [requires: …]` → ("Nextcloud", "self-hosted cloud")."""
    text = re.sub(r"\[[^\]]*\]", "", label).strip()
    parts = re.split(r"\s[–—-]\s", text, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", text)


def flags() -> list[dict]:
    rows = yaml.safe_load(MANIFEST.read_text())["services"]
    cat = {}
    for r in rows:
        if r.get("install_flag"):
            cat.setdefault(r["install_flag"], r["category"])
    group_of = {c: g for g, cs in GROUPS for c in cs}
    cards = _hub_cards()
    out = []
    for ln in CONFIG.read_text().splitlines():
        m = FLAG.match(ln)
        if not m:
            continue
        key, raw, label = m.groups()
        raw = raw.strip().strip('"')
        default, auto = (None, True) if "{{" in raw else (raw.lower() == "true", False)
        title, plain = _plain((label or "").strip())
        card = cards.get(key) or {}
        out.append({"key": key, "default": default, "auto": auto, "label": (label or "").strip(),
                    "title": card.get("title") or title or key.removeprefix("install_").replace("_", " "),
                    "plain": card.get("description") or plain,
                    "group": group_of.get(cat.get(key), HOST_GROUP)})
    order = [g for g, _ in GROUPS] + [HOST_GROUP]
    return sorted(out, key=lambda f: order.index(f["group"]))     # stable: config order inside a group


def profiles() -> list[dict]:
    out = []
    for p in sorted(PROFILES.glob("*.yml")):
        text = p.read_text()
        m = re.search(r"^# axis: ([a-z-]+)", text, re.M)
        if not m:
            continue
        data = yaml.safe_load(text) or {}
        plain = re.search(r"^# plain: (.+)$", text, re.M)
        # A profile whose every key one step asks (test-users = the People step's
        # switch) is answered there, not offered as an axis choice: one source.
        owner = [s["id"] for s in STEPS if data and set(data) <= {f["key"] for f in s["fields"]}]
        out.append({"id": p.stem, "axis": m.group(1), "plain": plain.group(1).strip() if plain else "",
                    "step": owner[0] if owner else None,
                    "flags": {k: bool(v) for k, v in data.items() if k.startswith("install_") and isinstance(v, bool)},
                    "knobs": {k: v for k, v in data.items() if not k.startswith("install_")}})
    return out


def defaults(profs: list[dict]) -> dict:
    """Every field's and every profile knob's default. A Jinja default
    (`{{ … }}`) is the playbook's to decide: null, the page writes what is set."""
    raw = _raw()
    keys = [f["key"] for s in STEPS for f in s["fields"]] + [k for p in profs for k in p["knobs"]]
    return {k: (None if isinstance(raw.get(k), str) and "{{" in raw[k] else raw.get(k, "")) for k in keys}


def accounts() -> dict:
    """The access levels and the declared accounts, as default.config.yml says."""
    raw = _raw()
    r = reach.Resolver(raw)
    names = [str(r.render(i["name"]) or "") for i in raw["nos_identities"]]
    return {
        "tiers": [{"tier": t["tier"], "label": t["name"].removeprefix("tier-"), "description": t["description"]}
                  for t in raw["authentik_rbac_tiers"]],
        "test_users": [{"name": i["name"], "tier": i["tier"]} for i in raw["nos_identities"]
                       if i.get("enabled_by") == "nos_test_users_enabled"],
        "reserved": sorted(n for n in names if n),
    }


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


def services(lock: dict | None, override: dict | None = None) -> dict:
    """Per install_* flag (and apps_runner_enabled): images, declared memory,
    the data-size assumption and, given a lock, whether an offline build has
    every image. Multi-container roles sum; a flag no role renders is a host
    daemon and says so. `override` (the operator's config.yml) outranks the
    defaults, so an image swap is looked up as the image it swaps in."""
    vars_ = reach.load(CONFIG)
    vars_.update(reach.load(REPO / "default.credentials.yml"))
    vars_.update(override or {})
    out: dict = {}
    for row in reach.discover(vars_, all_=True):
        if not row["flag"]:
            continue
        s = out.setdefault(row["flag"], {"ids": [], "images": [], "mem_bytes": 0, "data_gb": 0, "missing": []})
        s["ids"].append(row["id"])
        s["images"] += [i for i in row["images"] if i not in s["images"]]
        s["mem_bytes"] += sum(mem_bytes(m) for m in row["mem_limits"])
        s["data_gb"] += DATA_GB_ASSUMED.get(row["category"], DATA_GB_ASSUMED["_default"])
    for s in out.values():
        s["host"] = not s["images"]
        s["mem_note"] = HOST_NOTE if s["host"] else "declared container limit"
        if lock is not None:
            s["image_sizes"] = {}
            for img in s["images"]:
                if img.split("/", 1)[0] in reach.LOCAL_NAMESPACES:
                    continue                      # built by the converge, not pulled
                e = lock_entry(img, lock)
                if e:
                    s["image_sizes"][img] = e["bytes"]
                else:
                    s["missing"].append(img)
            s["image_bytes"] = sum(s["image_sizes"].values())
        s["offline_ok"] = not s["missing"]
    return out


def build(lock_path: Path | None = None, config_path: Path | None = None) -> dict:
    lock = json.loads(Path(lock_path).read_text())["images"] if lock_path else None
    override = reach.load(Path(config_path)) if config_path else None
    svcs, fl, profs = services(lock, override), flags(), profiles()
    raw = _raw()
    # A service gated by a plain knob (redis_docker, apps_runner_enabled) counts
    # when that knob resolves true: default → profile knobs → fields.
    knob_defaults = {k: bool(raw.get(k)) for k in svcs if k not in {f["key"] for f in fl}}
    flag_default = {f["key"]: f["default"] for f in fl}
    mail = {**MAIL, "default": next((o["id"] for o in MAIL["options"]
                                     if all(flag_default.get(k) == v for k, v in o["flags"].items())), None)}
    return {"axes": AXES, "axis_questions": AXIS_QUESTIONS, "steps": STEPS, "defaults": defaults(profs),
            "knob_defaults": knob_defaults, "mail": mail, "flags": fl, "groups": [g for g, _ in GROUPS] + [HOST_GROUP],
            "profiles": profs, "services": svcs, "accounts": accounts(), "prefix_rule": PREFIX_RULE,
            "offline": lock is not None, "assumptions": DATA_GB_ASSUMED,
            "local_suffixes": [".local", ".lan", ".test", ".localhost"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--image-lock", default=None, help="images.lock.json of a nos-image-cache; marks an OFFLINE build")
    ap.add_argument("--config", default=None, help="an operator config.yml whose image overrides the offline list honours")
    ap.add_argument("--json", action="store_true", help="print the data, build nothing")
    a = ap.parse_args()
    data = build(a.image_lock, a.config)
    if a.json:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return 0
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    html = TPL.read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (out / "index.html").write_text(html)
    offline = sum(1 for s in data["services"].values() if not s["offline_ok"])
    print(f"{out / 'index.html'}: {len(data['flags'])} flags, {len(data['profiles'])} profiles"
          + (f", offline build: {offline} services without an image" if data["offline"] else "")
          + f"\nopen it: open '{out / 'index.html'}'   (file:// works; nothing is fetched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
