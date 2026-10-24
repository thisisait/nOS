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
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

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


def operator_file(name: str, repo: Path | None = None) -> Path:
    """A gitignored operator file (config.yml, credentials.yml) as the converge
    reads it: the estate clone's (NOS_ESTATE_DIR, default ~/.nos/estate, since
    2026-10-23), else the main checkout's (a worktree has none), else this one's.
    Reads files only, never runs git (a reader may precede a forge check)."""
    repo = REPO if repo is None else repo
    est = Path(os.environ.get("NOS_ESTATE_DIR") or Path.home() / ".nos" / "estate")
    if (est / ".git").exists() and (est / name).is_file():
        return est / name
    main = None
    try:  # a worktree's .git is "gitdir: <main>/.git/worktrees/<wt>"
        dotgit = repo / ".git"
        if dotgit.is_file():
            gitdir = Path(dotgit.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            main = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve().parent / name
    except (OSError, IndexError):
        main = None
    return main if main and main.is_file() else repo / name


def layer_paths() -> list[Path]:
    """The layers that exist, LOWEST precedence first. One list, every reader."""
    return [p for p in (*sorted((REPO / "roles").glob("*/defaults/main.yml")),
                        *default_layers(), operator_file("config.yml"))
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


def is_local_host(name: str, paths: list[Path] | None = None) -> bool:
    """Whether a host's TLS chain is mkcert: the tenant and its subdomains follow the resolved
    tenant_domain_is_local (an operator may call a public TLD local), any other name its TLD."""
    def last(flag: str) -> str:
        return (resolve_flag(flag, paths) or [("", "")])[-1][1]
    tenant, flag = last("tenant_domain"), last("tenant_domain_is_local").lower()
    if tenant and "{{" not in tenant and flag in ("true", "false") and (name == tenant or name.endswith("." + tenant)):
        return flag == "true"
    return is_local_domain(name)


def resolve_flag(flag: str, paths: list[Path] | None = None) -> list[tuple[str, str]]:
    """Every layer that declares it, in precedence order. The LAST one wins."""
    pattern = re.compile(rf"^{re.escape(flag)}:\s*(\S+)", re.MULTILINE)
    seen: list[tuple[str, str]] = []
    for path in layer_paths() if paths is None else paths:
        m = pattern.search(path.read_text(encoding="utf-8"))
        if m:
            label = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else path.name
            seen.append((label, m.group(1).strip().strip('"\'')))
    return seen


def resolved(names, paths: list[Path] | None = None) -> dict:
    """Each var through the layers as YAML reads it (the last wins), a Jinja value rendered against
    the same layers (llm_on_host -> ollama_enabled). One that needs a filter or a fact reads ""."""
    from jinja2 import meta
    from jinja2.nativetypes import NativeEnvironment
    merged: dict = {}
    for p in layer_paths() if paths is None else paths:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        merged.update(doc if isinstance(doc, dict) else {})
    env = NativeEnvironment()

    def value(name, seen=()):
        v = merged.get(name, "")
        if not (isinstance(v, str) and "{{" in v) or name in seen:
            return v
        try:
            deps = meta.find_undeclared_variables(env.parse(v))
            return env.from_string(v).render({d: value(d, (*seen, name)) for d in deps if d in merged})
        except Exception:  # noqa: BLE001 — an unrenderable default is unknown, not a crash
            return ""
    return {n: value(n) for n in names}


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
    return [p for p in layer_paths() if p.name != "config.yml"] + [profile]


def forced_installs() -> dict[str, list[str]]:
    """Provider flag -> the flags that force it on at run time: state/manifest.yml
    forced_by, the one list main.yml and tasks/removal-set.yml also read."""
    return {r["install_flag"]: list(r["forced_by"]) for r in services() if r.get("forced_by")}


def install_flags(paths: list[Path] | None = None) -> dict[str, bool]:
    """Every install_*, *_on_host switch and manifest install_flag (redis_docker) resolved like resolve_flag, then
    the manifest's forced_by applied. A Jinja install_* is omitted, not guessed."""
    paths = layer_paths() if paths is None else paths
    names = {m for p in paths
             for m in re.findall(r"^(install_\w+|\w+_on_host):", p.read_text(encoding="utf-8"), re.MULTILINE)}
    names |= {r["install_flag"] for r in services() if r.get("install_flag")}
    bools = {"true": True, "yes": True, "false": False, "no": False}
    out = {f: bools.get(seen[-1][1].lower()) for f in sorted(names) if (seen := resolve_flag(f, paths))}
    # A *_on_host switch derives from layer vars only (vlm_on_host <- ollama_vision_model): render it.
    jinja = [f for f, v in out.items() if v is None and f.endswith("_on_host")]
    out |= {f: v for f, v in (resolved(jinja, paths) if jinja else {}).items() if isinstance(v, bool)}
    out = {f: v for f, v in out.items() if v is not None}
    for flag, triggers in forced_installs().items():
        if any(out.get(t) for t in triggers):
            out[flag] = True
    return out


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


# ── what RAN: ~/.nos/state.yml, rewritten by every converge ──────────────────
#: The layers answer "what is declared"; they cannot see a run's -e (a profile),
#: so a host converged with `-e @profiles/core.yml` read as running apps it never
#: deployed (2026-10-22). state.yml records what the playbook resolved, -e included.
STATE_ENV = "NOS_STATE_FILE"
UNKNOWN = "UNKNOWN"


def state_file() -> Path:
    """~/.nos/state.yml, or $NOS_STATE_FILE. Resolved per call: tests move HOME."""
    return Path(os.environ.get(STATE_ENV) or Path.home() / ".nos" / "state.yml").expanduser()


class Ran(NamedTuple):
    """What the last converge resolved. source: "state.yml" (read), "layers" (no
    file: a fresh host, CI, a fork — the layers decide) or UNKNOWN (unreadable)."""
    source: str
    state: dict
    path: Path
    why: str = ""

    def provenance(self) -> str:
        if self.source == "state.yml":
            run = self.state.get("last_run") or {}
            return f"state.yml ({self.path}; run {run.get('run_id', '?')} at {run.get('at', '?')})"
        if self.source == "layers":
            return f"layers (no {self.path}: no converge recorded)"
        return f"UNKNOWN ({self.path} unreadable: {self.why})"

    def apps(self) -> dict | None:
        """The apps runner record, or None when this state.yml predates it."""
        rec = self.state.get("apps")
        return rec if isinstance(rec, dict) and "runner_enabled" in rec else None

    def flag(self, flag: str) -> list[tuple[str, bool | None]]:
        """(subject, value the run resolved) for a flag state.yml records: a
        service's install_flag -> services.<id>.enabled; apps_runner_enabled ->
        apps.runner_enabled. [] when the flag is not one state.yml records."""
        if flag == "apps_runner_enabled":
            rec = self.apps()
            return [("apps", None if rec is None else rec.get("runner_enabled"))]
        recorded = self.state.get("services") or {}
        return [(r["id"], (recorded.get(r["id"]) or {}).get("enabled"))
                for r in services() if r.get("install_flag") == flag]


def ran(path: Path | None = None) -> Ran:
    """Read state.yml once. Never raises: a missing file is "layers", one that
    cannot be read or is not a mapping is UNKNOWN — never silently everything on."""
    path = state_file() if path is None else Path(path)
    if not path.exists():
        return Ran("layers", {}, path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return Ran(UNKNOWN, {}, path, type(exc).__name__)
    if not isinstance(doc, dict):
        return Ran(UNKNOWN, {}, path, f"top level is {type(doc).__name__}, not a mapping")
    return Ran("state.yml", doc, path)


def installed_apps(vars_: dict) -> list[str]:
    """The manifest apps (apps/<id>.yml) this host runs: apps_runner_enabled on,
    minus apps_skip. pazny.apps_runner deploys the same set. A reader that wants
    what RAN passes vars that carry the run's record (nos-smoke load_vars applies
    state.yml's apps block), not the bare layers."""
    if not _on(vars_.get("apps_runner_enabled")):
        return []
    skip = set(vars_.get("apps_skip") or [])
    return [p.stem for p in sorted((REPO / "apps").glob("*.yml"))
            if not p.name.startswith("_") and p.stem not in skip]


def installed_names(names, flags: dict, rows: list[dict] | None = None) -> list[str]:
    """The names (scan-state keys) this host runs. A name matches a row by id, fragment or
    install_<name>, else its own install_<name> flag, else an image basename (postgres).
    A name nothing records (freepbx) is not installed."""
    rows = services() if rows is None else rows
    on = {r["id"] for r in installed(flags, rows)}

    def row(n):  # an own install_<n> flag outranks an image basename ('nginx' is not apex)
        return (next((r for r in rows if n in (r["id"], fragment_stem(r))
                      or r.get("install_flag") == f"install_{n}"), None)
                or (None if f"install_{n}" in flags else
                    next((r for r in rows if str(r.get("image", "")).rsplit("/", 1)[-1] == n), None)))
    return [n for n in names if (r := row(n)) and r["id"] in on or not r and _on(flags.get(f"install_{n}"))]


# backup.sh status name -> its toggle; the toggle's own Jinja names the install flag.
_BACKUP_TOGGLES = {"mariadb": "backup_databases_mariadb", "postgres": "backup_databases_postgresql",
                   "authentik-blueprints": "backup_authentik_blueprints",
                   "wing-db": "backup_wing_db", "keap-db": "backup_keap_db"}


def backup_sources_installed(names, flags: dict, cfg: dict | None = None) -> list[str]:
    """The backup-status names this host backs up: one whose install flag `flags` holds
    OFF is dropped. backup_dirs_to_dump carries `flag:`; an unmapped or unknown flag is kept."""
    cfg = default_config() if cfg is None else cfg
    by = {n: m.group(0) for n, v in _BACKUP_TOGGLES.items() if (m := re.search(r"install_\w+", str(cfg.get(v))))}
    by |= {f"dir-{d['name']}": d["flag"] for d in cfg.get("backup_dirs_to_dump") or [] if d.get("flag")}
    return [n for n in names if by.get(n) not in flags or _on(flags[by[n]])]


def copy1_installed(flags: dict, cfg: dict | None = None) -> bool:
    """backup_copy1_enabled for `flags`: every install flag its own Jinja names is on."""
    cfg = default_config() if cfg is None else cfg
    return all(_on(flags.get(f)) for f in re.findall(r"install_\w+", str(cfg.get("backup_copy1_enabled"))))


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
