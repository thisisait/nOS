#!/usr/bin/env python3
"""The manifest row is the only place a service's spellings meet.

A service is spelled four ways — `install_calibreweb`, manifest id
`calibre_web`, fragment `calibre-web.yml`, container `iiab-calibre-web-1` —
and every consumer that GUESSED a hop got a hop wrong: the compose prune's
separator-insensitive match cannot reach `calibre-web` from `calibreweb`, nor
`tileserver` from `offline_maps` by any rule at all. Ask the row instead.

Importable, not a CLI: `sys.path.insert(0, "<repo>/tools")`.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "state" / "manifest.yml"

#: In ansible precedence order, LOWEST first. A role default is a real
#: declaration and a reader that skips it answers "declared in no layer" about
#: a variable that is declared — `keap_repo_ref` lives only in role defaults.
CONFIG_LAYERS = ("roles/*/defaults/main.yml", "config.d/*.yml", "default.config.yml", "config.yml")


def default_layers() -> list[Path]:
    """The committed defaults in load order: config.d/*.yml (lexical), then the
    remainder. main.yml vars_files lists the same files (gate:
    test_config_d_is_one_layer_set). Every variable lives in exactly one."""
    return [*sorted((REPO / "config.d").glob("*.yml")), REPO / "default.config.yml"]
#: The synthetic test identities (alice/bob/carol/dave): declared ONLY in the
#: profile, switched by one flag. main.yml adopts the same roster the same way.
SYNTHETIC_PROFILE = REPO / "profiles" / "test-users.yml"
SYNTHETIC_FLAG = "nos_test_users_enabled"


def layer_paths() -> list[Path]:
    """The layers that exist, LOWEST precedence first. One list, every reader."""
    return [p for p in (*sorted((REPO / "roles").glob("*/defaults/main.yml")),
                        *default_layers(), REPO / "config.yml")
            if p.exists()]


def default_config_text() -> str:
    """The defaults as ONE text: regex it or safe_load it. Each file's leading
    `---` is dropped so the join is one YAML document, not a stream."""
    return "\n".join(re.sub(r"\A---[ \t]*\n", "", p.read_text(encoding="utf-8"))
                     for p in default_layers())


def default_config() -> dict:
    """The defaults as ONE mapping (no override layer), unrendered."""
    out: dict = {}
    for p in default_layers():
        out.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return out


@lru_cache(None)
def local_tld_suffixes() -> tuple[str, ...]:
    """The suffixes tenant_domain_is_local counts as local, read from its own expression."""
    m = re.search(r"endswith\(\(([^)]*)\)\)", default_config()["tenant_domain_is_local"])
    return tuple(s.strip(" '\"") for s in m.group(1).split(","))


def is_local_domain(name: str) -> bool:
    """tenant_domain_is_local for any host name (mkcert, not a public CA)."""
    return name == "localhost" or name.endswith(local_tld_suffixes())


def resolve_flag(flag: str, paths: list[Path] | None = None) -> list[tuple[str, str]]:
    """Every layer that declares it, in precedence order. The LAST one wins."""
    pattern = re.compile(rf"^{re.escape(flag)}:\s*(\S+)", re.MULTILINE)
    seen: list[tuple[str, str]] = []
    for path in layer_paths() if paths is None else paths:
        m = pattern.search(path.read_text(encoding="utf-8"))
        if m:
            seen.append((str(path.relative_to(REPO)), m.group(1).strip().strip('"\'')))
    return seen


def resolve_list(name: str, paths: list[Path] | None = None) -> list:
    """A top-level list var through the layers; the LAST layer that declares it
    wins, an empty list included. `paths` is for tests; default layer_paths()."""
    value: list = []
    for p in layer_paths() if paths is None else paths:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict) and isinstance(doc.get(name), list):
            value = doc[name]
    return value


def profile_layers(profile: Path) -> list[Path]:
    """The committed layers with `profile` on top (as `-e @profile`), no config.yml."""
    return [p for p in layer_paths() if p != REPO / "config.yml"] + [profile]


def install_flags(paths: list[Path] | None = None) -> dict[str, bool]:
    """Every top-level install_* resolved like resolve_flag. A Jinja value is omitted, not guessed."""
    paths = layer_paths() if paths is None else paths
    names = {m for p in paths
             for m in re.findall(r"^(install_\w+):", p.read_text(encoding="utf-8"), re.MULTILINE)}
    bools = {"true": True, "yes": True, "false": False, "no": False}
    out = {f: bools.get(resolve_flag(f, paths)[-1][1].lower()) for f in sorted(names)}
    return {f: v for f, v in out.items() if v is not None}


def synthetic_identities(merged: dict | None = None) -> list[dict]:
    """The synthetic roster, kind: synthetic always: the config's own list when
    it declares one (config.yml / -e), else profiles/test-users.yml."""
    own = (merged or {}).get("nos_synthetic_identities") or []
    roster = own or (yaml.safe_load(SYNTHETIC_PROFILE.read_text(encoding="utf-8")) or {}).get(
        "nos_synthetic_identities") or []
    return [{**i, "kind": "synthetic"} for i in roster if isinstance(i, dict)]


def services() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]


def _on(value) -> bool:
    return str(value).lower() in ("true", "yes", "1")


def installed(flags: dict, rows: list[dict] | None = None) -> list[dict]:
    """The manifest rows THIS host runs: install_flag resolved on in `flags`.
    The one derivation — services-status, and the registry via filter nos_installed."""
    return [r for r in (services() if rows is None else rows) if _on(flags.get(r.get("install_flag")))]


def installed_names(names, flags: dict, rows: list[dict] | None = None) -> list[str]:
    """The names (scan-state keys) this host runs. A name matches a row by a spelling the
    row records — id, fragment, image basename, install_<name> — else its own install_<name>
    flag. A name nothing records (freepbx) is not installed."""
    rows = services() if rows is None else rows
    on = {r["id"] for r in installed(flags, rows)}

    def row(n):
        return next((r for r in rows if n in (r["id"], fragment_stem(r), str(r.get("image", "")).rsplit("/", 1)[-1])
                     or r.get("install_flag") == f"install_{n}"), None)
    return [n for n in names if (r := row(n)) and r["id"] in on or not r and _on(flags.get(f"install_{n}"))]


def scan_batch(state, batch: int, flags: dict | None = None) -> list[str]:
    """scan-runner.sh's batch: the oldest-checked notebook components this host installed."""
    comps = json.loads(Path(state).read_text(encoding="utf-8")).get("components") or {}
    names = installed_names(comps, install_flags() if flags is None else flags)
    return sorted(names, key=lambda n: (comps[n] or {}).get("last_checked") or "1970-01-01T00:00:00Z")[:batch]


def plugin_installed(name: str, plugins: dict[str, dict], flags: dict) -> bool:
    """A plugin is live when its requires.feature_flag is on and every requires.plugin
    peer is live. The Pulse catalog filters its jobs by this."""
    req = (plugins.get(name) or {}).get("requires") or {}
    peers = req.get("plugin") or []
    return (name in plugins and (not req.get("feature_flag") or _on(flags.get(req["feature_flag"])))
            and all(plugin_installed(p, plugins, flags) for p in ([peers] if isinstance(peers, str) else peers)))


def by_flag(flag: str) -> dict | None:
    """install_<x> -> the row, or None. The hop no consumer may guess."""
    return next((s for s in services() if s.get("install_flag") == flag), None)


def fragment_stem(row: dict) -> str | None:
    """<stacks_dir>/<stack>/overrides/<stem>.yml. None = owns no fragment."""
    if "fragment" in row:
        return row["fragment"]
    return row["id"] if row.get("stack") else None


def fragment_path(row: dict) -> str | None:
    stem = fragment_stem(row)
    return f"{row['stack']}/overrides/{stem}.yml" if stem else None


if __name__ == "__main__":  # self-check: the three hops no guess can make
    for flag, stem in (("install_calibreweb", "calibre-web"),
                       ("install_openwebui", "open-webui"),
                       ("install_offline_maps", "tileserver")):
        row = by_flag(flag)
        assert row and fragment_stem(row) == stem, (flag, row)
    assert fragment_stem({"id": "x", "stack": "apps", "fragment": None}) is None
    assert fragment_stem(by_flag("install_gitea")) == "gitea"
    assert {i["kind"] for i in synthetic_identities()} == {"synthetic"}
    assert "macos_dock_autohide" in default_config() and "global_password_prefix" in default_config()
    assert yaml.safe_load(default_config_text())["global_password_prefix"]
    print("ok")
