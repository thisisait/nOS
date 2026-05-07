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

def _deep_render(value, ctx: dict):
    """Recursively render Jinja2 strings in nested dict/list values.

    Anatomy D1.2 (2026-05-05): when run_aggregators harvests a peer
    plugin's block (e.g. authentik:), strings like
    ``"{{ install_outline | default(false) }}"`` would otherwise sit
    in the source plugin's ``inputs[var]`` as literal Jinja text — the
    consuming blueprint template wouldn't re-render them. Pre-rendering
    here lets the blueprint treat ``c.enabled`` as a real boolean-ish
    string, ``c.redirect_uris[0]`` as a real URL, etc.
    """
    if isinstance(value, str):
        try:
            return _render_string(value, ctx)
        except Exception:
            # Leave un-renderable strings (missing var refs etc.) in place
            # — blueprint's Jinja filter chain handles defaults / coercions.
            return value
    if isinstance(value, dict):
        return {k: _deep_render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_render(v, ctx) for v in value]
    return value


def run_aggregators(plugins: list[Plugin],
                    agent_profiles: list[dict] | None = None,
                    app_manifests: list[dict] | None = None,
                    template_vars: dict | None = None) -> None:
    """For every source plugin's `aggregates` block, harvest matching blocks
    from consumer plugins (and optionally agent profiles / Tier-2 app
    manifests) into the source plugin's `inputs[output_var]`.

    Mutates ``plugins`` in place (sets each source plugin's `.inputs`).

    Sources:
      - ``consumer_block`` (D1.2)  — peer plugin manifests
      - ``agent_profile`` (D1.2)   — agents/<name>.yml
      - ``app_manifest`` (X.3, 2026-05-08) — Tier-2 apps/<name>.yml.
        Tier-2 apps that declare an `authentik:` block land in the
        Authentik blueprint render alongside Tier-1 plugins, closing
        the SSO outpost gap (was: documenso/qdrant/roundcube/twofauth
        had Traefik routers but Authentik forward-auth returned 404
        because the proxy outpost had no registered provider).

    D1.2 extensions:
      - ``template_vars``: when provided, recursively pre-renders Jinja
        strings inside harvested blocks, AND skips peer plugins whose
        ``requires.feature_flag`` is set-to-False in template_vars
        (disabled services don't pollute aggregated output).
    """
    agent_profiles = agent_profiles or []
    app_manifests = app_manifests or []
    tvars = template_vars or {}
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
                    # Feature-flag gate (D1.2): when running with
                    # template_vars, skip peers whose feature_flag is off.
                    flag = (p.requires or {}).get("feature_flag")
                    if tvars and flag and flag in tvars and not tvars.get(flag):
                        continue
                    block = p.manifest.get(block_path)
                    if isinstance(block, dict):
                        if tvars:
                            block = _deep_render(block, tvars)
                        # Carry the slug forward even if the manifest's
                        # block omits one (defensive — current schema
                        # requires it for authentik:).
                        block.setdefault("slug", p.name.replace("-base", ""))
                        block.setdefault("plugin_name", p.name)
                        harvested.append(block)
            elif from_kind == "agent_profile":
                for ap in agent_profiles:
                    block = ap.get(block_path)
                    if isinstance(block, dict):
                        if tvars:
                            block = _deep_render(block, tvars)
                        harvested.append(block)
            elif from_kind == "app_manifest":
                # Tier-2 source. App manifests have shape:
                #   meta:        { name, version, ... }
                #   gdpr:        { ... }
                #   compose:     { services: { ... } }
                #   authentik:   { mode, slug, name, ... }   ← harvested
                # The slug defaults to meta.name; tier=2 hint added so
                # the blueprint renderer can split bookkeeping if it
                # ever needs to (today both tiers fan into one list).
                for app in app_manifests:
                    block = app.get(block_path)
                    if isinstance(block, dict):
                        if tvars:
                            block = _deep_render(block, tvars)
                        meta = app.get("meta") or {}
                        block.setdefault("slug", meta.get("name"))
                        block.setdefault("plugin_name",
                                         f"app:{meta.get('name')}")
                        block.setdefault("tier", 2)
                        harvested.append(block)
            # Multiple aggregates specs that share the same output_var
            # MERGE (Tier-1 plugin clients + Tier-2 app clients land in
            # one list). Single-spec output_var assignment keeps its
            # historical shape (assignment, not list-of-one).
            existing = source.inputs.get(output_var)
            if isinstance(existing, list):
                source.inputs[output_var] = existing + harvested
            else:
                source.inputs[output_var] = harvested


# ── Lifecycle hooks (PoC: skeleton — actual side-effects are no-ops when
#     plugin set is empty, which is the common case until A7+) ──────────────

class HookResult(t.TypedDict):
    plugin: str
    status: str               # ok | degraded | skipped | failed
    note: str


def _plugin_stack(p: "Plugin") -> str | None:
    """Return the Docker compose stack a plugin belongs to, or None.

    Priority:
    1. compose_extension.target_stack  — explicit stack for compose-override plugins
    2. observability.loki.labels.stack — universal metadata label on every plugin
    """
    ce = p.manifest.get("compose_extension") or {}
    if ce.get("target_stack"):
        return ce["target_stack"]
    labels = ((p.manifest.get("observability") or {}).get("loki") or {}).get("labels") or {}
    return labels.get("stack")


def run_hook(name: str, plugins: list[Plugin],
             template_vars: dict | None = None,
             stack_filter: list[str] | None = None) -> list[HookResult]:
    """Execute the named lifecycle hook in topological order (or reverse for
    post_blank). Each plugin's actions are run by ``_run_actions``.

    ``template_vars`` (optional) is the Jinja2 rendering context — the
    Ansible module wrapper passes the playbook's `vars` dict so action
    params containing ``{{ … }}`` (target paths, URLs, etc.) and plugin
    Jinja templates render with the operator's full var scope.

    ``stack_filter`` (optional) limits execution to plugins whose stack
    matches one of the listed names. Plugins with no resolvable stack are
    always included. Pass ``None`` (default) to run all plugins.
    """
    if name not in {"pre_render", "pre_compose", "post_compose", "post_blank"}:
        raise ValueError(f"unknown hook: {name!r}")

    # Anatomy P0.9 (2026-05-04): fail-loudly preflight on the host Python
    # interpreter's missing-deps surface. The blank that surfaced this
    # silently degraded all 5 render-doing plugins (authentik-base /
    # grafana-base / loki-base / prometheus-base / tempo-base) with
    # `No module named 'jinja2'`, then Docker compose mounted the missing
    # config files as DIRECTORIES (bind-mount race), then tempo / loki /
    # prometheus crashed at startup. Operator only saw `failed=1` for an
    # unrelated wing post-task and had to dig 30 minutes into docker logs
    # to find the root cause. Failing hard here means the next operator
    # gets `Module nos_plugin_loader failed: jinja2 is required` upfront.
    try:
        import jinja2 as _check_jinja2  # noqa: F401
    except ImportError as e:
        msg = (
            "jinja2 is required by the plugin loader but missing from the "
            "Ansible host's Python interpreter "
            f"({sys.executable}). Install with:\n"
            "  python3 -m pip install --break-system-packages jinja2 "
            "pyyaml jsonschema\n"
            f"(original error: {e})"
        )
        raise RuntimeError(msg) from e

    ordered = topological_order(plugins)
    if name == "post_blank":
        ordered = list(reversed(ordered))
    results: list[HookResult] = []
    tvars = template_vars or {}
    for p in ordered:
        if p.status in ("skipped", "failed"):
            results.append({"plugin": p.name, "status": p.status,
                            "note": "skipped due to prior status"})
            continue
        # Anatomy P1 (2026-05-05). Feature-flag gating closes a structural
        # bug surfaced in blank #5: plugins like gitlab-base, hedgedoc-base,
        # bookstack-base rendered their compose-extensions even when the
        # operator had `install_<svc>: false`. The role-side compose.yml.j2
        # is correctly gated (no override file written), but the plugin
        # loader rendered an extension on top of a non-existent service →
        # `service "X" has neither an image nor a build context specified:
        # invalid compose project` → entire stack failed to come up.
        # Resolution: if the manifest declares `requires.feature_flag: foo`
        # AND `template_vars['foo']` is falsy, skip every action on this
        # plugin for this hook. A flag that's *unset* in template_vars
        # defaults to enabled (matches Ansible's `default(true)` filter
        # convention used in tasks/stacks/core-up.yml).
        flag = (p.requires or {}).get("feature_flag")
        if flag and flag in tvars and not tvars.get(flag):
            results.append({"plugin": p.name, "status": "skipped",
                            "note": f"feature_flag {flag}=false"})
            continue
        if stack_filter is not None:
            pstack = _plugin_stack(p)
            if pstack is not None and pstack not in stack_filter:
                results.append({"plugin": p.name, "status": "skipped",
                                "note": f"stack_filter: {pstack!r} not in {stack_filter}"})
                continue
        actions = (p.manifest.get("lifecycle") or {}).get(name) or []
        try:
            note = _run_actions(p, name, actions, template_vars or {})
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


def _resolve_path(manifest: dict, dot_path: str) -> dict | list | str | None:
    """Walk a dotted path into the manifest. ``provisioning.datasources``
    becomes ``manifest['provisioning']['datasources']``. Returns None when
    any segment is absent.
    """
    cur: t.Any = manifest
    for segment in dot_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(segment)
        if cur is None:
            return None
    return cur


def _jinja_env():
    """Return a lazy-imported jinja2 Environment configured to match
    Ansible's defaults closely enough for plugin manifests.

    Ansible-parity filter shim (Anatomy P0.6, 2026-05-04): plugin
    templates frequently call Ansible-specific filters (``to_json``,
    ``regex_replace``, ``mandatory``, ``b64encode``, …). When the
    loader fires hooks via the Ansible module wrapper these run inside
    the Ansible process — but Jinja2 itself doesn't carry those
    filters, so plain Environment() rendering fails on them. Without
    this shim, every consumer plugin that uses Ansible-style filters
    silently degrades the source plugin's render hook (the role-side
    template task still works because Ansible's own Templater has
    them, hiding the problem). We register the most common ones here
    so plugin-side render produces byte-identical output to role-side
    render — the load-bearing contract for the Phase 2 cutover when
    role-side renders go away.
    """
    import jinja2
    env = jinja2.Environment(
        keep_trailing_newline=True,
        # `'{{ var }}'` in a YAML scalar is the lingua franca; preserve.
        autoescape=False,
        # Strict undefined would be safer but breaks defaults like
        # ``{{ var | default('x') }}`` when var is undefined upstream;
        # use ChainableUndefined so chained filters keep working.
        undefined=jinja2.ChainableUndefined,
    )
    _register_ansible_filters(env)
    return env


def _register_ansible_filters(env) -> None:
    """Register Ansible-equivalent Jinja filters on ``env``.

    Coverage matches the filters actually used by current nOS
    templates (rendered via ``grep -rEoh '\\| ?[a-z_]+' templates`` on
    files/anatomy/plugins + roles/pazny.*/templates as of 2026-05-04).
    Add more here as new plugin templates surface them.
    """
    import base64 as _b64
    import json as _json
    import re as _re

    import yaml as _yaml

    def _to_json(v, indent=None, sort_keys=False):
        return _json.dumps(v, indent=indent, sort_keys=sort_keys, default=str)

    def _to_nice_json(v, indent=4, sort_keys=True):
        return _json.dumps(v, indent=indent, sort_keys=sort_keys, default=str)

    def _from_json(s):
        return _json.loads(s) if isinstance(s, (str, bytes)) else s

    def _to_yaml(v, indent=2, default_flow_style=False):
        return _yaml.safe_dump(v, indent=indent,
                               default_flow_style=default_flow_style,
                               sort_keys=False)

    def _to_nice_yaml(v):
        return _yaml.safe_dump(v, indent=2, default_flow_style=False,
                               sort_keys=False)

    def _from_yaml(s):
        return _yaml.safe_load(s) if isinstance(s, (str, bytes)) else s

    def _regex_replace(value, pattern, replace=""):
        return _re.sub(pattern, replace, str(value))

    def _regex_search(value, pattern):
        m = _re.search(pattern, str(value))
        return m.group(0) if m else None

    def _regex_findall(value, pattern):
        return _re.findall(pattern, str(value))

    def _mandatory(value, msg=None):
        # In Ansible: raise AnsibleFilterError if undefined. We translate
        # Jinja2's ChainableUndefined into a ValueError so the loader can
        # surface it via plugin status=degraded with the operator-supplied
        # message.
        import jinja2 as _j2
        if isinstance(value, _j2.Undefined):
            raise ValueError(msg or "mandatory filter: variable is undefined")
        return value

    def _b64encode(s, encoding="utf-8"):
        if isinstance(s, str):
            s = s.encode(encoding)
        return _b64.b64encode(s).decode("ascii")

    def _b64decode(s, encoding="utf-8"):
        return _b64.b64decode(s).decode(encoding)

    def _quote(s):
        # Minimal shell-quote (Ansible's quote filter is shlex-based).
        s = str(s)
        return "'" + s.replace("'", "'\"'\"'") + "'"

    def _bool_filter(value):
        # Ansible's `bool` filter: truthy strings → True. Yes/no/true/false/1/0.
        if isinstance(value, bool):
            return value
        if value in (None, "", 0):
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        s = str(value).strip().lower()
        return s in ("true", "yes", "y", "1", "on")

    def _hash_filter(value, algo="sha1"):
        import hashlib
        h = hashlib.new(algo)
        h.update(str(value).encode("utf-8"))
        return h.hexdigest()

    def _basename(path):
        import os as _os
        return _os.path.basename(str(path))

    def _dirname(path):
        import os as _os
        return _os.path.dirname(str(path))

    def _splitext(path):
        import os as _os
        return _os.path.splitext(str(path))

    def _combine(*dicts, recursive=False):
        # Ansible's combine. Shallow merge by default.
        out: dict = {}
        for d in dicts:
            if not isinstance(d, dict):
                continue
            if recursive:
                for k, v in d.items():
                    if (k in out and isinstance(out[k], dict)
                            and isinstance(v, dict)):
                        out[k] = _combine(out[k], v, recursive=True)
                    else:
                        out[k] = v
            else:
                out.update(d)
        return out

    def _flatten_filter(seq, levels=None):
        # Ansible's flatten: drop one level of nesting (or all if levels=None).
        out = []
        def _walk(items, depth):
            for it in items:
                if isinstance(it, list) and (levels is None or depth < levels):
                    _walk(it, depth + 1)
                else:
                    out.append(it)
        _walk(list(seq), 0)
        return out

    env.filters.update({
        # Serialization
        "to_json":       _to_json,
        "to_nice_json":  _to_nice_json,
        "from_json":     _from_json,
        "to_yaml":       _to_yaml,
        "to_nice_yaml":  _to_nice_yaml,
        "from_yaml":     _from_yaml,
        # Regex
        "regex_replace": _regex_replace,
        "regex_search":  _regex_search,
        "regex_findall": _regex_findall,
        # Type guards
        "mandatory":     _mandatory,
        "bool":          _bool_filter,
        # Encoding
        "b64encode":     _b64encode,
        "b64decode":     _b64decode,
        "quote":         _quote,
        "hash":          _hash_filter,
        # Path
        "basename":      _basename,
        "dirname":       _dirname,
        "splitext":      _splitext,
        # Collection
        "combine":       _combine,
        "flatten":       _flatten_filter,
    })


def _render_string(s: str, ctx: dict) -> str:
    """Render a Jinja2 template string against the context."""
    if "{{" not in s and "{%" not in s:
        return s  # cheap fast-path
    return _jinja_env().from_string(s).render(**ctx)


def _render_file(src: pathlib.Path, dest: pathlib.Path, ctx: dict) -> bool:
    """Render src (Jinja2 template) → dest. Returns True if dest changed."""
    src_text = src.read_text()
    rendered = _jinja_env().from_string(src_text).render(**ctx)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.read_text() == rendered:
        return False
    dest.write_text(rendered)
    return True


def _wait_health(url: str, timeout: int = 60, interval: float = 2.0,
                 expect_status: int = 200,
                 accept_any_status: bool = False) -> bool:
    """HTTP GET ``url`` until ``expect_status`` or timeout. Stdlib only.

    ``accept_any_status=True`` treats any 2xx/3xx/4xx response as healthy —
    used for forward-auth-gated services that return 401/302 when hit directly
    (bypassing Traefik/Authentik). urllib follows 3xx redirects automatically;
    4xx raises HTTPError which is caught explicitly when this flag is set.
    """
    import time
    import urllib.error
    import urllib.request
    deadline = time.monotonic() + timeout
    last_err = ""
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
                if accept_any_status or resp.status == expect_status:
                    return True
                last_err = f"http {resp.status}"
        except urllib.error.HTTPError as e:
            if accept_any_status and e.code < 500:
                return True
            last_err = f"http {e.code}"
        except Exception as e:                                    # noqa: BLE001
            last_err = str(e)
        time.sleep(interval)
    raise RuntimeError(f"wait_health timeout after {timeout}s @ {url}: {last_err}")


def _run_actions(plugin: Plugin, hook: str, actions: list,
                 template_vars: dict) -> str:
    """Execute the action list for one plugin/hook.

    Each action is a dict of ``{action_key: param}`` — the loader interprets
    well-known keys. Unknown keys are recorded and ignored (forward-compat).
    Jinja2 rendering uses ``template_vars`` as context (passed from the
    Ansible module wrapper, typically operator's ``vars``).

    The ctx passed to every action is an augmented copy of ``template_vars``
    with two additional keys exposed by the loader:

    - ``inputs``           — this plugin's aggregated harvest (set by
                              ``run_aggregators`` for source plugins).
                              Empty dict for non-source plugins.
    - ``plugin_manifest``  — the plugin's own manifest dict, so templates
                              can reference static metadata without an
                              extra round-trip through the operator vars.

    Both names are reserved — operator vars with the same names get
    shadowed inside action ctx (collision is intentional: aggregator
    plugins MUST see their harvest under a stable key).
    """
    ctx = dict(template_vars)
    # Anatomy P0.3 (2026-05-04): expose inputs + plugin metadata so
    # source plugins (authentik-base) can render templates that iterate
    # over the harvested ``inputs.clients`` list.
    ctx["inputs"] = dict(plugin.inputs)
    ctx["plugin_manifest"] = plugin.manifest
    summary: list[str] = []
    for raw in actions:
        if not isinstance(raw, dict) or len(raw) != 1:
            summary.append(f"skipped malformed action: {raw!r}")
            continue
        action, param = next(iter(raw.items()))
        try:
            note = _dispatch_action(plugin, action, param, ctx)
            summary.append(note)
        except Exception as e:                                    # noqa: BLE001
            summary.append(f"{action}:ERROR:{e}")
            raise
    return ", ".join(summary) if summary else "no-op"


def _dispatch_action(plugin: Plugin, action: str, param,
                     ctx: dict) -> str:
    """Single-action dispatcher. Returns a one-line summary fragment."""
    if action == "ensure_dir":
        path = pathlib.Path(_render_string(str(param), ctx))
        path.mkdir(parents=True, exist_ok=True)
        return f"ensure_dir:{path}"

    if action == "remove_dir":
        import shutil
        path = pathlib.Path(_render_string(str(param), ctx))
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        return f"remove_dir:{path}"

    if action == "remove_file":
        # File-level cleanup (post_blank). Use this when a plugin's render
        # output is a single file inside a directory owned by a peer plugin
        # (e.g. composition plugins drop a file into the grafana-base
        # provisioning dir — the peer's remove_dir would race the
        # composition plugin's wipe). Idempotent: missing file is success.
        path = pathlib.Path(_render_string(str(param), ctx))
        if path.is_file():
            path.unlink()
        return f"remove_file:{path}"

    if action == "render":
        # `param` is a dotted path into the manifest (e.g.
        # "provisioning.datasources") that resolves to {template, target}.
        spec = _resolve_path(plugin.manifest, str(param))
        if not isinstance(spec, dict) or "template" not in spec or "target" not in spec:
            return f"render:{param}:skipped(spec missing template/target)"
        src = plugin.path / _render_string(spec["template"], ctx)
        dest = pathlib.Path(_render_string(spec["target"], ctx))
        if not src.is_file():
            return f"render:{param}:skipped(no src @ {src})"
        changed = _render_file(src, dest, ctx)
        return f"render:{param}:{'changed' if changed else 'unchanged'} -> {dest}"

    if action == "render_compose_extension":
        # `param` resolves to compose_extension block: {template, target_stack}.
        spec = _resolve_path(plugin.manifest, str(param))
        if not isinstance(spec, dict):
            return f"render_compose_extension:{param}:skipped(spec missing)"
        tmpl_rel = spec.get("template")
        target_stack = spec.get("target_stack")
        if not tmpl_rel or not target_stack:
            return f"render_compose_extension:{param}:skipped(missing template/target_stack)"
        src = plugin.path / _render_string(tmpl_rel, ctx)
        # Target: {{ stacks_dir }}/<stack>/overrides/<plugin-name>.yml
        stacks_dir = ctx.get("stacks_dir") or os.path.expanduser("~/stacks")
        dest = pathlib.Path(stacks_dir) / target_stack / "overrides" / f"{plugin.name}.yml"
        if not src.is_file():
            return f"render_compose_extension:{param}:skipped(no src @ {src})"
        changed = _render_file(src, dest, ctx)
        return f"render_compose_extension:{param}:{'changed' if changed else 'unchanged'} -> {dest}"

    if action == "copy_dir":
        # P0.6 (2026-05-04): copies a directory verbatim — NO Jinja
        # rendering. Use this for files that contain `{{ … }}` syntax
        # belonging to a NON-Ansible templating system (e.g. Prometheus
        # alert annotations use `{{ $labels.x }}`, Grafana variables
        # use `${var}` etc.). render_dir would try to evaluate those
        # as Jinja2 expressions and fail. param: dotted path resolving
        # to {source_dir, target_dir}.
        import shutil
        spec = _resolve_path(plugin.manifest, str(param))
        if not isinstance(spec, dict):
            return f"copy_dir:{param}:skipped(spec missing)"
        src_dir = plugin.path / _render_string(spec.get("source_dir", ""), ctx)
        dst_dir = pathlib.Path(_render_string(spec.get("target_dir", ""), ctx))
        if not src_dir.is_dir():
            return f"copy_dir:{param}:skipped(no src dir @ {src_dir})"
        dst_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        skipped = 0
        for sf in sorted(src_dir.iterdir()):
            if not sf.is_file():
                continue
            df = dst_dir / sf.name
            # Idempotency: skip when content unchanged.
            if df.is_file() and df.read_bytes() == sf.read_bytes():
                skipped += 1
                continue
            shutil.copy2(sf, df)
            copied += 1
        return f"copy_dir:{param}:{copied} copied / {skipped} unchanged -> {dst_dir}"

    if action == "render_dir":
        # `param` resolves to {source_dir, target_dir}. Renders every file
        # in source_dir into target_dir, stripping any trailing `.j2`
        # from the basename so config files land at their canonical
        # extension. Idempotent: skip write when content unchanged.
        spec = _resolve_path(plugin.manifest, str(param))
        if not isinstance(spec, dict):
            return f"render_dir:{param}:skipped(spec missing)"
        src_dir = plugin.path / _render_string(spec.get("source_dir", ""), ctx)
        dst_dir = pathlib.Path(_render_string(spec.get("target_dir", ""), ctx))
        if not src_dir.is_dir():
            return f"render_dir:{param}:skipped(no src dir @ {src_dir})"
        dst_dir.mkdir(parents=True, exist_ok=True)
        rendered = 0
        skipped = 0
        for sf in sorted(src_dir.iterdir()):
            if not sf.is_file():
                continue
            out_name = sf.name[:-3] if sf.name.endswith(".j2") else sf.name
            df = dst_dir / out_name
            if _render_file(sf, df, ctx):
                rendered += 1
            else:
                skipped += 1
        return f"render_dir:{param}:{rendered} rendered / {skipped} unchanged -> {dst_dir}"

    if action == "copy_dashboards":
        # `param` resolves to {source_dir, target_dir, files}.
        import shutil
        spec = _resolve_path(plugin.manifest, str(param))
        if not isinstance(spec, dict):
            return f"copy_dashboards:{param}:skipped(spec missing)"
        src_dir = plugin.path / _render_string(spec.get("source_dir", ""), ctx)
        dst_dir = pathlib.Path(_render_string(spec.get("target_dir", ""), ctx))
        files = spec.get("files") or []
        if not src_dir.is_dir() or not files:
            return f"copy_dashboards:{param}:skipped(src dir or files missing)"
        dst_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for fname in files:
            sf = src_dir / fname
            if sf.is_file():
                df = dst_dir / fname
                # Idempotency: skip if same content
                if df.is_file() and df.read_bytes() == sf.read_bytes():
                    continue
                shutil.copy2(sf, df)
                copied += 1
        return f"copy_dashboards:{param}:{copied}/{len(files)} updated -> {dst_dir}"

    if action == "wait_health":
        # Accept both string-shorthand and dict-form params:
        #   wait_health: "http://127.0.0.1:6333/healthz"          # default 60s
        #   wait_health: { url: "...", timeout: 30, interval: 2 } # tunable
        #   wait_health: { url: "...", accept_any_2xx_3xx_4xx: true }  # liveness only
        if isinstance(param, dict):
            url = _render_string(str(param.get("url", "")), ctx)
            timeout = int(param.get("timeout", 60))
            interval = float(param.get("interval", 2.0))
            expect_status = int(param.get("expect_status", 200))
            accept_any = bool(param.get("accept_any_2xx_3xx_4xx", False))
        else:
            url = _render_string(str(param), ctx)
            timeout, interval, expect_status, accept_any = 60, 2.0, 200, False
        ok = _wait_health(url, timeout=timeout, interval=interval,
                          expect_status=expect_status,
                          accept_any_status=accept_any)
        return f"wait_health:{url}:ok"

    if action == "conditional_remove_dir":
        # Vaultwarden uses this — skip when condition is false.
        if not isinstance(param, dict):
            return "conditional_remove_dir:skipped(malformed)"
        path = pathlib.Path(_render_string(str(param.get("path", "")), ctx))
        when = _render_string(str(param.get("when", "false")), ctx).strip().lower()
        if when in ("true", "1", "yes"):
            import shutil
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            return f"conditional_remove_dir:{path}:removed"
        return f"conditional_remove_dir:{path}:preserved(when={when})"

    return f"unknown:{action}"


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
    if cmd == "smoke":
        # P0.7 (2026-05-04): pre-blank validation. Discover all plugins,
        # validate each manifest against the schema, run aggregators,
        # fire pre_compose against a tmp stacks_dir. Report status table
        # + exit non-zero if any plugin is in `failed` state. Operator
        # runs this before `ansible-playbook -e blank=true` to catch
        # plugin issues that would otherwise surface as silent
        # degradation during the real blank.
        #
        # Usage:
        #   python3 -m module_utils.load_plugins smoke [--root <path>]
        import shutil
        import tempfile
        root = pathlib.Path(_arg(rest, "--root",
                                  default="files/anatomy/plugins"))
        if not root.is_dir():
            print(f"plugins root not found: {root}", file=sys.stderr)
            return 1
        plugins = discover(root)
        repo_root = _find_repo_root(root)
        schema = _load_schema(repo_root) if repo_root else None
        # Validate manifests up-front.
        validation_errors: list[tuple[str, list[str]]] = []
        for p in plugins:
            errs = validate_manifest(p.manifest, schema)
            if errs:
                validation_errors.append((p.name, errs))
        # Run aggregators (in-memory, no fs).
        run_aggregators(plugins)
        # Fire pre_compose against a tmp stacks_dir. Use realistic
        # operator-y vars to surface filter / template issues like
        # the to_json + $labels issues uncovered by P0.6.
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="anatomy-smoke-"))
        # Mock the slice of ansible_facts that plugin templates actually
        # touch. Plugins like grafana-base reference
        # ``ansible_facts['env']['HOME']`` for host-side mount targets;
        # without this mock those targets fall through to ``/`` and
        # the render attempts to write under root → "Read-only file
        # system" degradation in standalone smoke. Real Ansible blank
        # fills ansible_facts via the setup module.
        mock_home = str(tmp / "fake-home")
        pathlib.Path(mock_home).mkdir(parents=True, exist_ok=True)
        template_vars = {
            "stacks_dir": str(tmp),
            "ansible_facts": {
                "env": {"HOME": mock_home, "USER": "smoke"},
                "user_dir": mock_home,
            },
            "tenant_domain": "smoke.local",
            "authentik_domain": "auth.smoke.local",
            "authentik_default_groups": [{"name": "nos-admins"}],
            "authentik_bootstrap_password": "smoke-pw",
            "authentik_bootstrap_email": "admin@smoke.local",
            "default_admin_email": "admin@smoke.local",
            "authentik_oidc_apps": [],
            "authentik_rbac_tiers": [],
            "authentik_app_tiers": {},
            "authentik_agent_clients": [],
            "authentik_agent_scopes": {},
            "global_password_prefix": "smoke",
            "nos_tester_username": "nos-tester",
            "nos_tester_password": "smoke-pw",
            "nos_tester_email": "tester@smoke.local",
            "apps_subdomain": "apps",
        }
        try:
            results = run_hook("pre_compose", plugins,
                               template_vars=template_vars)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        # Report.
        print(f"=== {len(plugins)} plugin(s) discovered ===")
        for p in plugins:
            print(f"  {p.name:25s} {p.behavior.value}")
        if validation_errors:
            print()
            print("=== Schema validation errors ===")
            for name, errs in validation_errors:
                print(f"  {name}:")
                for e in errs[:3]:
                    print(f"    - {e}")
                if len(errs) > 3:
                    print(f"    ... ({len(errs) - 3} more)")
        else:
            print()
            print("Schema validation: OK")
        print()
        print("=== pre_compose hook smoke (tmp stacks_dir) ===")
        ok = degraded = failed = 0
        for r in results:
            status = r["status"]
            if status == "ok":
                ok += 1
            elif status == "degraded":
                degraded += 1
            elif status == "failed":
                failed += 1
            print(f"  {r['plugin']:25s} {status:10s} {r['note'][:80]}")
        print()
        print(f"Summary: {ok} ok, {degraded} degraded, "
              f"{failed} failed, {len(validation_errors)} schema errors")
        # Exit non-zero ONLY on `failed` plugins (real runtime crashes
        # that would also break the blank). Schema errors + degraded
        # state are reported but non-blocking — known-draft plugins
        # (portainer/qdrant/vaultwarden/woodpecker) carry preexisting
        # drift that Phase 1 cleans up; degraded state often comes
        # from missing ansible_facts in this standalone smoke (real
        # blank fills them via setup module).
        if failed > 0:
            return 1
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
