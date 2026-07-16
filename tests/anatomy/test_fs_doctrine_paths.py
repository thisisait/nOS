"""Filesystem doctrine (docs/doctrine/filesystem.md) — path-var invariants.

P1 moved service data/config paths OUT of default.config.yml and INTO each role's
defaults, deriving from a single `nos_data_root`. This gate pins that:

1. `nos_data_root` + `nos_tenant_slug` are defined in default.config.yml.
2. The doctrine'd service path vars are NO LONGER in default.config.yml (option B — they
   live in role defaults so blank-reset/loader stay clean and bloat drops).
3. Every role-default `*_data_dir`/`_config_dir`/`_books_dir` that is doctrine-managed
   derives from `{{ nos_data_root }}/` with the right class prefix (platform vs tenant-shared).

Host-daemon + render-adjacent paths are explicitly EXEMPT (wing/openclaw/pi/traefik/
iiab_terminal) — they are not Docker-service data dirs.
"""
import re
import glob
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CFG = (ROOT / "default.config.yml").read_text()

# Services whose path lives outside the tree by design (host daemons / render-adjacent).
EXEMPT_VARS = {
    "wing_data_dir", "openclaw_config_dir", "pi_config_dir",
    "traefik_config_dir", "iiab_terminal_config_dir",
    "opencode_config_dir", "hermes_config_dir",  # host-tool config, like openclaw
}
# Tenant-shared content (class 2) — everything else doctrine'd is platform (class 1).
CLASS2 = {"nextcloud", "kiwix", "maps", "jellyfin", "calibreweb"}

PATH_VAR = re.compile(r'^([a-z_]+)_(data|config|books)_dir:\s*"([^"]*)"', re.M)


def test_root_vars_defined():
    assert re.search(r'^nos_data_root:\s*"', CFG, re.M), "nos_data_root missing from default.config.yml"
    assert re.search(r'^nos_tenant_slug:\s*"', CFG, re.M), "nos_tenant_slug missing from default.config.yml"


def test_config_paths_derive_from_root():
    """Path vars in default.config.yml must be GLOBAL + derive from nos_data_root.

    They are global on purpose: core-up dir-creation, blank-reset, and the plugin
    loader (template_vars={{ vars }}) all reference these BEFORE the owning role runs,
    so a role-default-only value would trip the eager-resolve trap (some plugin.yml
    refs even lack a `| default()`). They mirror the role defaults (shadow) — the
    config-surface-revision epic will DRY that. Exempt = host-daemon/render paths.
    """
    bad = []
    for m in PATH_VAR.finditer(CFG):
        var, svc, val = f"{m.group(1)}_{m.group(2)}_dir", m.group(1), m.group(3)
        if var in EXEMPT_VARS:
            continue
        if "{{ nos_data_root }}" not in val:
            bad.append(f"{var} = {val} (must derive from nos_data_root)")
            continue
        want = "tenants/{{ nos_tenant_slug }}/shared" if svc in CLASS2 else "platform/services"
        if want not in val:
            bad.append(f"{var} = {val} (expected class prefix '{want}')")
    assert not bad, "default.config.yml path vars off-doctrine:\n" + "\n".join(bad)


def test_role_default_paths_derive_from_root():
    bad = []
    for f in glob.glob(str(ROOT / "roles/pazny.*/defaults/main.yml")):
        src = pathlib.Path(f).read_text()
        for m in PATH_VAR.finditer(src):
            var, svc, val = f"{m.group(1)}_{m.group(2)}_dir", m.group(1), m.group(3)
            if var in EXEMPT_VARS:
                continue
            if "{{ nos_data_root }}" not in val:
                bad.append(f"{f}: {var} = {val} (must derive from nos_data_root)")
                continue
            want = "tenants/{{ nos_tenant_slug }}/shared" if svc in CLASS2 else "platform/services"
            if want not in val:
                bad.append(f"{f}: {var} = {val} (expected class prefix '{want}')")
    assert not bad, "role path defaults off-doctrine:\n" + "\n".join(bad)
