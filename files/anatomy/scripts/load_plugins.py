"""Plugin loader — discovers, validates, DAG-resolves, and runs lifecycle hooks.

A6 implementation per files/anatomy/docs/plugin-loader-spec.md.

Usage from CLI (operator dev path):
    python3 -m anatomy.scripts.load_plugins discover --root files/anatomy/plugins
    python3 -m anatomy.scripts.load_plugins validate <manifest.yml>
    python3 -m anatomy.scripts.load_plugins hook pre_render --manifests-glob ...

Usage from Ansible (production path): wrapped by
    files/anatomy/library/nos_plugin_loader.py
which exposes a custom module so the playbook gets structured changed/failed
events rather than a raw shell wrapper.

Design notes:
- All hooks are idempotent. Re-running pre_compose for a plugin that's already
  rendered a fragment is a no-op (template re-render that produces the same
  bytes is harmless).
- Plugin failures in hook 1/4 abort; failures in hook 2/3 mark the plugin as
  ``degraded`` but let other plugins proceed (critical-ordering invariant
  per spec doc).
- Empty plugin set is the COMMON case during PoC bootstrap. Loader must
  return cleanly with zero work done — that's the test for "wired correctly
  but no plugins yet."
"""

from __future__ import annotations

import dataclasses
import enum
import glob as _glob
import json
import os
import pathlib
import sys
import typing as t

import yaml


# ── Schema validation (lightweight — we don't ship jsonschema as a hard dep) ──

class ValidationError(Exception):
    """Raised when a plugin manifest fails schema or structural validation."""


def _load_schema(repo_root: pathlib.Path) -> dict:
    p = repo_root / "state" / "schema" / "plugin.schema.json"
    return json.loads(p.read_text())


def validate_manifest(manifest: dict, schema: dict | None = None) -> list[str]:
    """Return a list of validation errors (empty = valid).

    We use jsonschema if available (preferred — full Draft 2020-12 support);
    otherwise fall back to a minimal hand-rolled checker that covers the
    required-fields / enum / pattern subset the loader actually relies on.
    """
    try:
        import jsonschema  # type: ignore
        if schema is None:
            return ["schema not loaded"]
        v = jsonschema.Draft202012Validator(schema)
        return [
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in v.iter_errors(manifest)
        ]
    except ImportError:
        return _validate_manifest_fallback(manifest)


def _validate_manifest_fallback(m: dict) -> list[str]:
    """Hand-rolled minimal validator — used when jsonschema isn't installed.

    Covers: required top-level fields, type/enum constraints, and the
    fields the loader actually consumes. Adequate for CI but operators
    who want strict draft-2020 validation should pip install jsonschema
    in their venv.
    """
    errs: list[str] = []
    for k in ("name", "version", "type", "gdpr"):
        if k not in m:
            errs.append(f"missing required top-level: {k!r}")
    if "name" in m and not isinstance(m["name"], str):
        errs.append("name must be a string")
    if "type" in m:
        if not isinstance(m["type"], list) or not m["type"]:
            errs.append("type must be a non-empty list")
        else:
            allowed = {"skill", "service", "composition",
                       "scheduled-job", "ui-extension", "notifier"}
            for entry in m["type"]:
                if entry not in allowed:
                    errs.append(f"type entry {entry!r} not in {sorted(allowed)}")
    g = m.get("gdpr") or {}
    if g:
        for k in ("data_categories", "data_subjects", "legal_basis",
                  "retention_days", "processors"):
            if k not in g:
                errs.append(f"gdpr.{k} required")
        if "legal_basis" in g and g["legal_basis"] not in (
                "consent", "contract", "legal_obligation", "vital_interests",
                "public_task", "legitimate_interests"):
            errs.append(f"gdpr.legal_basis {g['legal_basis']!r} not Article 6(1)")
    return errs


# ── Plugin model ──────────────────────────────────────────────────────────────

class PluginBehavior(str, enum.Enum):
    SKILL = "skill"
    SERVICE = "service"
    COMPOSITION = "composition"


@dataclasses.dataclass
class Plugin:
    """Loaded + validated plugin (manifest + path + computed inputs)."""

    name: str
    path: pathlib.Path                        # plugin dir (where plugin.yml sits)
    manifest: dict
    behavior: PluginBehavior                  # primary behavioral class
    requires: dict                            # alias for manifest['requires'] | {}
    aggregates: list[dict]                    # alias for manifest['aggregates'] | []
    inputs: dict[str, t.Any] = dataclasses.field(default_factory=dict)
    status: str = "loaded"                    # loaded | degraded | failed | skipped

    @classmethod
    def from_manifest_file(cls, manifest_path: pathlib.Path) -> "Plugin":
        with open(manifest_path) as fh:
            m = yaml.safe_load(fh) or {}
        if not isinstance(m, dict):
            raise ValidationError(f"{manifest_path}: top-level must be a mapping")
        types = m.get("type") or []
        if "service" in types:
            behavior = PluginBehavior.SERVICE
        elif "composition" in types:
            behavior = PluginBehavior.COMPOSITION
        else:
            behavior = PluginBehavior.SKILL
        return cls(
            name=m.get("name", ""),
            path=manifest_path.parent,
            manifest=m,
            behavior=behavior,
            requires=m.get("requires") or {},
            aggregates=m.get("aggregates") or [],
        )


# ── Discovery ────────────────────────────────────────────────────────────────

def discover(plugins_root: pathlib.Path) -> list[Plugin]:
    """Find every plugins_root/<name>/plugin.yml. Returns Plugin objects.

    Raises ValidationError if any manifest is structurally bogus (not a
    mapping, etc.) — but does NOT run schema validation here (that's a
    separate explicit step for clearer error attribution).
    """
    out: list[Plugin] = []
    if not plugins_root.is_dir():
        return out
    for entry in sorted(plugins_root.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / "plugin.yml"
        if not manifest.is_file():
            continue
        out.append(Plugin.from_manifest_file(manifest))
    return out


# ── DAG resolution ────────────────────────────────────────────────────────────

def topological_order(plugins: list[Plugin]) -> list[Plugin]:
    """Return plugins in topological order per ``requires.plugin`` edges.

    Implicit edges (added automatically):
      * every plugin with an ``authentik:`` block → ``authentik-base``
        (when authentik-base is present in the loaded set)
      * every plugin with ``observability.scrape:`` → ``prometheus-base``
        (post-Q1; today the edge is recorded but no-op since prometheus-base
        isn't loaded yet)

    Cycles raise ValidationError with the offending plugin names.
    """
    by_name = {p.name: p for p in plugins}
    edges: dict[str, set[str]] = {p.name: set() for p in plugins}

    for p in plugins:
        for dep in p.requires.get("plugin") or []:
            if dep in by_name:
                edges[p.name].add(dep)
        # implicit edge: authentik consumers wait for authentik-base
        if "authentik" in p.manifest and "authentik-base" in by_name \
                and p.name != "authentik-base":
            edges[p.name].add("authentik-base")
        # implicit edge: scrape declarers wait for prometheus-base
        obs = p.manifest.get("observability") or {}
        if obs.get("scrape") and "prometheus-base" in by_name \
                and p.name != "prometheus-base":
            edges[p.name].add("prometheus-base")

    ordered: list[Plugin] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str, stack: list[str]) -> None:
        if name in seen:
            return
        if name in visiting:
            raise ValidationError(
                f"plugin DAG cycle: {' → '.join(stack + [name])}")
        visiting.add(name)
        for dep in sorted(edges.get(name, set())):
            visit(dep, stack + [name])
        visiting.discard(name)
        seen.add(name)
        ordered.append(by_name[name])

    for p in plugins:
        visit(p.name, [])
    return ordered


# ── Aggregator pattern (V4 SR-1) ─────────────────────────────────────────────

def run_aggregators(plugins: list[Plugin],
                    agent_profiles: list[dict] | None = None) -> None:
    """For every source plugin's `aggregates` block, harvest matching blocks
    from consumer plugins (and optionally agent profiles) into the source
    plugin's `inputs[output_var]`.

    Mutates ``plugins`` in place (sets each source plugin's `.inputs`).
    """
    agent_profiles = agent_profiles or []
    for source in plugins:
        for spec in source.aggregates:
            from_kind = spec.get("from")
            block_path = spec.get("block_path")
            output_var = spec.get("output_var")
            if not (from_kind and block_path and output_var):
                continue
            harvested: list[dict] = []
            if from_kind == "consumer_block":
                for p in plugins:
                    if p.name == source.name:
                        continue
                    block = p.manifest.get(block_path)
                    if isinstance(block, dict):
                        harvested.append(block)
            elif from_kind == "agent_profile":
                for ap in agent_profiles:
                    block = ap.get(block_path)
                    if isinstance(block, dict):
                        harvested.append(block)
            source.inputs[output_var] = harvested


# ── Lifecycle hooks (PoC: skeleton — actual side-effects are no-ops when
#     plugin set is empty, which is the common case until A7+) ──────────────

class HookResult(t.TypedDict):
    plugin: str
    status: str               # ok | degraded | skipped | failed
    note: str


def run_hook(name: str, plugins: list[Plugin]) -> list[HookResult]:
    """Execute the named lifecycle hook in topological order (or reverse for
    post_blank). Each plugin's actions are run by ``_run_actions``.
    """
    if name not in {"pre_render", "pre_compose", "post_compose", "post_blank"}:
        raise ValueError(f"unknown hook: {name!r}")
    ordered = topological_order(plugins)
    if name == "post_blank":
        ordered = list(reversed(ordered))
    results: list[HookResult] = []
    for p in ordered:
        if p.status in ("skipped", "failed"):
            results.append({"plugin": p.name, "status": p.status,
                            "note": "skipped due to prior status"})
            continue
        actions = (p.manifest.get("lifecycle") or {}).get(name) or []
        try:
            note = _run_actions(p, name, actions)
            results.append({"plugin": p.name, "status": "ok", "note": note})
        except Exception as e:                        # noqa: BLE001
            # hooks 1/4 abort entire loader; hooks 2/3 mark plugin degraded
            if name in ("pre_render", "post_blank"):
                p.status = "failed"
                results.append({"plugin": p.name, "status": "failed",
                                "note": str(e)})
                raise
            p.status = "degraded"
            results.append({"plugin": p.name, "status": "degraded",
                            "note": str(e)})
    return results


def _run_actions(plugin: Plugin, hook: str, actions: list) -> str:
    """Execute the action list for one plugin/hook.

    Each action is a dict of ``{action_key: param}`` — the loader interprets
    well-known keys. Unknown keys are recorded and ignored (forward-compat).
    """
    summary: list[str] = []
    for raw in actions:
        if not isinstance(raw, dict) or len(raw) != 1:
            summary.append(f"skipped malformed action: {raw!r}")
            continue
        action, param = next(iter(raw.items()))
        if action == "ensure_dir":
            pathlib.Path(os.path.expandvars(str(param))).mkdir(
                parents=True, exist_ok=True)
            summary.append(f"ensure_dir:{param}")
        elif action == "remove_dir":
            p = pathlib.Path(os.path.expandvars(str(param)))
            if p.is_dir():
                # Use shutil.rmtree (recursive). Plugin is responsible for
                # owning the path — loader doesn't double-check.
                import shutil
                shutil.rmtree(p, ignore_errors=True)
            summary.append(f"remove_dir:{param}")
        elif action in ("render", "render_compose_extension",
                        "copy_dashboards", "wait_health"):
            # Implementation deferred: these are the next-commit work
            # (when first real plugin lands). For PoC we record the intent
            # so the operator sees what would happen.
            summary.append(f"{action}:deferred")
        else:
            summary.append(f"unknown:{action}")
    return ", ".join(summary) if summary else "no-op"


# ── CLI entry point ──────────────────────────────────────────────────────────

def _main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("usage: load_plugins.py {discover|validate|hook} ...",
              file=sys.stderr)
        return 2
    cmd, *rest = argv
    if cmd == "discover":
        # python3 -m anatomy.scripts.load_plugins discover --root <path>
        root = pathlib.Path(_arg(rest, "--root", default="files/anatomy/plugins"))
        plugins = discover(root)
        for p in plugins:
            print(f"{p.name}\t{p.behavior.value}\t{p.path}")
        return 0
    if cmd == "validate":
        # python3 -m anatomy.scripts.load_plugins validate <manifest.yml>
        if not rest:
            print("validate: need a manifest path", file=sys.stderr)
            return 2
        manifest_path = pathlib.Path(rest[0])
        repo_root = _find_repo_root(manifest_path)
        schema = _load_schema(repo_root) if repo_root else None
        with open(manifest_path) as fh:
            manifest = yaml.safe_load(fh) or {}
        errs = validate_manifest(manifest, schema)
        for e in errs:
            print(f"ERROR {e}", file=sys.stderr)
        return 0 if not errs else 1
    if cmd == "hook":
        # python3 -m anatomy.scripts.load_plugins hook <name> --root <path>
        if not rest:
            print("hook: need a hook name", file=sys.stderr)
            return 2
        hook = rest[0]
        root = pathlib.Path(_arg(rest[1:], "--root",
                                  default="files/anatomy/plugins"))
        plugins = discover(root)
        run_aggregators(plugins)
        results = run_hook(hook, plugins)
        for r in results:
            print(f"{r['plugin']}\t{r['status']}\t{r['note']}")
        return 0
    print(f"unknown command: {cmd!r}", file=sys.stderr)
    return 2


def _arg(args: list[str], flag: str, default: str = "") -> str:
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    p = start.resolve()
    for candidate in (p, *p.parents):
        if (candidate / "ansible.cfg").is_file():
            return candidate
    return None


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
