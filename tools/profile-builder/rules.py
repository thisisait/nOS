"""Profile-builder contradiction rules, DERIVED from what the estate declares, and
the offline sweep that proves the page cannot write a config they refuse.
  auto     main.yml's Auto-enable blocks — the playbook turns the provider on itself.
  refused  every fail/assert the page can reach (main.yml, preflights, role mains).
  silent   depends_on `unenforced:` edges, `authentik:` blocks, blueprint accounts,
           profile knobs only one service reads — the service would come up unwired.
    tools/profile-builder-build.py --sweep     # exit 1 on any contradiction let through
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

import jinja2
import jinja2.meta
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
import load_plugins as lp  # noqa: E402

PLUGINS = REPO / "files/anatomy/plugins"
ROLES = REPO / "roles"
TPL = REPO / "tools/profile-builder/index.html.tpl"
REFUSAL_FILES = ["main.yml", "tasks/run-mode.yml", *sorted(str(p.relative_to(REPO)) for p in (REPO / "tasks").glob("preflight*.yml"))]
FAIL_KEYS = ("ansible.builtin.fail", "fail", "ansible.builtin.assert", "assert")
_ENV = lp._jinja_env()
# Ansible's tests, so a task expression parses; registered-result tests only
# occur in tasks this module skips as runtime, so their truth is never read.
_ENV.tests.update(match=lambda v, p: re.match(p, str(v)) is not None, search=lambda v, p: re.search(p, str(v)) is not None,
                  contains=lambda v, x: x in v, **{k: (lambda v: False) for k in ("skipped", "failed", "changed", "succeeded", "success")})
_ENV.filters["regex_search"] = lambda v, p, ignorecase=False: (m.group(0) if (m := re.search(p, str(v), re.I if ignorecase else 0)) else None)
_Y = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _y(p: Path):
    return yaml.load(p.read_text(encoding="utf-8"), Loader=_Y)


@lru_cache(None)
def _cfg() -> dict:
    return {**(_y(REPO / "default.credentials.yml") or {}), **(_y(REPO / "default.config.yml") or {})}


@lru_cache(None)
def _plugins() -> dict:
    return {p.parent.name: (_y(p) or {}) for p in sorted(PLUGINS.glob("*/plugin.yml"))}


def _walk(tasks):
    for t in tasks or []:
        if isinstance(t, dict):
            yield t
            for k in ("block", "rescue", "always"):
                yield from _walk(t.get(k))


@lru_cache(None)
def _task_files() -> list:
    return list(_task_files_walk())


def _task_files_walk():
    for p in [REPO / "main.yml", *sorted((REPO / "tasks").rglob("*.yml"))]:
        doc = _y(p)
        for play in (doc if isinstance(doc, list) else []):
            if isinstance(play, dict) and any(k in play for k in ("pre_tasks", "tasks")):
                for sec in ("pre_tasks", "tasks", "post_tasks"):
                    yield p, list(_walk(play.get(sec)))
            elif isinstance(play, dict):
                yield p, list(_walk([play]))


def _when(t) -> list[str]:
    w = t.get("when")
    return [str(x) for x in (w if isinstance(w, list) else [w] if w is not None else [])]


@lru_cache(None)
def flag_of_service() -> dict:
    """manifest service id → the variable that turns it on. A manifest flag no
    config declares (install_redis) falls back to the role's plugin flag."""
    cfg, out = _cfg(), {}
    by_role = {(d.get("requires") or {}).get("role"): (d.get("requires") or {}).get("feature_flag")
               for n, d in _plugins().items() if n.endswith("-base")}
    for r in _y(REPO / "state/manifest.yml")["services"]:
        f = r.get("install_flag")
        out[r["id"]] = f if f in cfg else by_role.get(f"pazny.{r['id']}") or f
    return out


@lru_cache(None)
def flag_of_role() -> dict:
    """role → the flag that runs it: the include/import gate in the playbook when
    it is one flag, else the role's plugin flag (backup-base declares
    configure_backup while main.yml imports pazny.backup under install_backup)."""
    out = {}
    for n, d in _plugins().items():
        req = d.get("requires") or {}
        if req.get("role") and req.get("feature_flag") and (n.endswith("-base") or req["role"] not in out):
            out[req["role"]] = req["feature_flag"]
    for r in ROLES.glob("pazny.*"):
        gate = [literal(w) for w in _include_gate(r.name)]
        if len(gate) == 1 and gate[0] and gate[0][1] and gate[0][0] in _cfg():
            out[r.name] = gate[0][0]
        elif r.name not in out and "install_" + r.name.removeprefix("pazny.") in _cfg():
            out[r.name] = "install_" + r.name.removeprefix("pazny.")
    return out


# ── auto ────────────────────────────────────────────────────────────────────
def auto_rules() -> list[dict]:
    out = []
    for _, tasks in _task_files():
        for t in tasks:
            sf = t.get("ansible.builtin.set_fact") or {}
            if str(t.get("name", "")).startswith("Auto-enable") and len(sf) == 1 and list(sf.values()) == [True]:
                up = next(iter(sf))
                for c in re.findall(r"\(([a-z_0-9]+)\s*\|", " ".join(_when(t))):
                    out.append({"cls": "auto", "consumer": {"flag": c}, "upstream": [up], "source": f"main.yml: {t['name']}"})
    return out


def auto_tasks() -> list[tuple[str, str]]:
    """(fact, when) as main.yml writes them — the oracle evaluates these."""
    return [(next(iter(t["ansible.builtin.set_fact"])), " ".join(_when(t)))
            for _, ts in _task_files() for t in ts
            if str(t.get("name", "")).startswith("Auto-enable") and len(t.get("ansible.builtin.set_fact") or {}) == 1]


# ── silent ──────────────────────────────────────────────────────────────────
@lru_cache(None)
def _text_index() -> dict:
    """owner → concatenated text, for every role and plugin (and the playbook body)."""
    idx = {}
    for root, key in ((ROLES, lambda p: "role:" + p.relative_to(ROLES).parts[0]),
                      (PLUGINS, lambda p: "plugin:" + p.relative_to(PLUGINS).parts[0])):
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in (".yml", ".yaml", ".j2", ".py", ".sh", ".json", ".php", ".conf", ".ini", ".env", ""):
                try:
                    idx.setdefault(key(p), []).append(p.read_text(encoding="utf-8"))
                except (UnicodeDecodeError, OSError):
                    pass
    body = [REPO / "main.yml", *(REPO / "tasks").rglob("*.yml"), *(REPO / "templates").rglob("*")]
    idx["playbook"] = [p.read_text(encoding="utf-8", errors="ignore") for p in body if p.is_file()]
    return {k: "\n".join(v) for k, v in idx.items()}


def _consumers_of(var: str, idx: dict) -> list[str] | None:
    """The flags of every role/plugin that reads `var`; None when the playbook
    body reads it too (it acts whatever is installed) or an owner has no flag."""
    pat = re.compile(rf"\b{re.escape(var)}\b")
    owners = [k for k, txt in idx.items() if var in txt and pat.search(txt)]
    if not owners or "playbook" in owners:
        return None
    flags = []
    for o in owners:
        kind, name = o.split(":", 1)
        f = flag_of_role().get(name) if kind == "role" else (_plugins()[name].get("requires") or {}).get("feature_flag")
        if not f:
            return None
        flags.append(f)
    return sorted(set(flags))


def silent_rules(profile_knobs: list[tuple[str, str]]) -> list[dict]:
    auto = {(r["consumer"]["flag"], r["upstream"][0]) for r in auto_rules()}
    svc = flag_of_service()
    out, seen = [], set()

    def add(consumer, up, source, text=""):
        key = (json.dumps(consumer, sort_keys=True), up)
        if up and key not in seen and consumer.get("flag") != up:
            seen.add(key)
            out.append({"cls": "auto" if (consumer.get("flag"), up) in auto else "silent", "consumer": consumer,
                        "upstream": [up] if isinstance(up, str) else list(up), "source": source, "text": text})

    for name, d in _plugins().items():
        req = d.get("requires") or {}
        flag = req.get("feature_flag")
        if not flag:
            continue
        for dep in d.get("depends_on") or []:
            if dep.get("unenforced") and not dep.get("optional"):   # optional: degrades, never required
                add({"flag": flag}, svc.get(dep["upstream"].removeprefix("service:")),
                    f"{name}/plugin.yml depends_on {dep['upstream']}", dep["unenforced"])
        if req.get("peer_service") in svc:
            add({"flag": flag}, svc[req["peer_service"]], f"{name}/plugin.yml requires.peer_service")
        if isinstance(d.get("authentik"), dict):
            add({"flag": flag}, "install_authentik", f"{name}/plugin.yml authentik: (mode {d['authentik'].get('mode', '?')})")
    # The accounts authentik-base's blueprint creates: the extra people, and every
    # nos_identities entry switched on by a variable (the test users).
    ak = _plugins()["authentik-base"]
    ak_flag = ak["requires"]["feature_flag"]
    idx = _text_index()
    if "nos_extra_identities" in idx["plugin:authentik-base"]:
        add({"people": True}, ak_flag, "authentik-base blueprint renders nos_extra_identities")
    if "nos_identities" in idx["plugin:authentik-base"]:
        for v in sorted({i["enabled_by"] for i in _cfg()["nos_identities"] if i.get("enabled_by")}):
            add({"field": v}, ak_flag, f"authentik-base blueprint renders nos_identities (enabled_by: {v})")
    for prof, k in profile_knobs:
        flags = _consumers_of(k, idx)
        if flags:
            add({"knob": k, "profile": prof}, tuple(flags), f"{k} is read only by " + ", ".join(flags))
    return out


# ── refused ─────────────────────────────────────────────────────────────────
_NEG = re.compile(r"^\s*not\s*\((.*)\)\s*$", re.S)
_BOOL = re.compile(r"^\(?\s*([a-z_][a-z0-9_]*)\s*(?:\|\s*default\([^()]*\)\s*)?(?:\|\s*bool\s*)?\)?\s*$")
_LEN = re.compile(r"^\(?\s*([a-z_][a-z0-9_]*)\s*(?:\|\s*default\([^()]*\)\s*)?\|\s*length\s*\)?\s*(==\s*0|>\s*0)\s*$")
GATED_FACT = "_nos_gated_without_authentik_refusable"


def literal(expr: str) -> tuple[str, bool] | None:
    """`[not] (var | default(x) | bool)` or `(var | default('') | length) ==0/>0` → (var, wanted truth)."""
    m = _NEG.match(expr)
    if m and (inner := literal(m.group(1))):
        return inner[0], not inner[1]
    if m := _LEN.match(expr):
        return m.group(1), m.group(2).startswith(">")
    if m := _BOOL.match(expr):
        return m.group(1), True
    return None


def _names(expr: str) -> set[str]:
    return jinja2.meta.find_undeclared_variables(_ENV.parse("{{ " + expr + " }}"))


def _truth(expr: str, ctx: dict) -> bool:
    return bool(_compiled(expr)(**ctx))


@lru_cache(None)
def _compiled(expr: str):
    return _ENV.compile_expression(expr.strip())


@lru_cache(None)
def derived_vars() -> dict:
    """Vars default.config computes from tenant_domain alone → 'local'/'public'."""
    out = {}
    for k, v in _cfg().items():
        if isinstance(v, str) and "{{" in v and "tenant_domain" in v and k != "tenant_domain":
            got = [_render_default(k, d) for d in ("dev.local", "example.eu")]
            if got == [True, False]:
                out[k] = "local"
            elif got == [False, True]:
                out[k] = "public"
    return out


@lru_cache(None)
def _render_default(key: str, domain: str):
    r = _resolver({"tenant_domain": domain})
    return r.value(key)


def _resolver(over: dict):
    import importlib.util
    spec = importlib.util.spec_from_file_location("registry_reach", REPO / "tools/cloud/registry-reach.py")
    reach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reach)
    return reach.Resolver({**_cfg(), **over})


def local_suffixes() -> list[str]:
    m = re.search(r"endswith\(\(([^)]*)\)\)", _cfg()["tenant_domain_is_local"])
    return [s.strip(" '\"") for s in m.group(1).split(",")] if m else []


@lru_cache(None)
def gated_flags() -> dict:
    """flag → router ids main.yml's preflight would refuse without Authentik:
    services.yml.j2 rendered with every flag on, read back (main.yml does the same)."""
    man = _y(REPO / "state/manifest.yml")
    tv = _y(REPO / "roles/pazny.traefik/vars/main.yml")
    v = {**_cfg(), **{s["install_flag"]: True for s in man["services"] if s.get("install_flag")}, **tv, "nos_manifest": man}
    r = _resolver(v)
    ctx = {k: (r.value(k) if isinstance(x, str) else x) for k, x in v.items()}
    ctx["lookup"] = lambda kind, name, default=None, **_: r.value(name) if name in v else default
    routers = yaml.safe_load(_ENV.from_string((REPO / "roles/pazny.traefik/templates/dynamic/services.yml.j2").read_text()).render(**ctx))["http"]["routers"]
    exempt = set(re.findall(r"difference\(\[([^\]]*)\]\)", (REPO / "main.yml").read_text())[0].replace("'", "").replace('"', "").split(", "))
    by_router = {s["id"].replace("_", "-"): flag_of_service()[s["id"]] for s in man["services"]}
    out: dict = {}
    for rid, x in routers.items():
        if "authentik@file" in ((x or {}).get("middlewares") or []) and rid not in exempt:
            out.setdefault(by_router[rid], []).append(rid)
    return out


@lru_cache(None)
def proxy_apps() -> list[str]:
    """Tier-2 apps main.yml's preflight counts (its own file filter): auth defaults to proxy."""
    out = []
    for f in sorted([*(REPO / "apps").glob("*.yml"), *(REPO / "apps").glob("*.yaml")]):
        if not f.name.startswith(("_", ".")) and ".draft." not in f.name:
            if ((_y(f) or {}).get("nginx") or {}).get("auth", "proxy") == "proxy":
                out.append(f.stem)
    return out


@lru_cache(None)
def _include_gate(role: str) -> list[str]:
    for _, ts in _task_files():
        for t in ts:
            inc = next((t[k] for k in ("ansible.builtin.include_role", "include_role", "ansible.builtin.import_role", "import_role") if k in t), {})
            if isinstance(inc, dict) and inc.get("name") == role and not inc.get("tasks_from"):
                return _when(t)
    return []


def _refusal_tasks():
    """(source, role or None, task) for every fail/assert in the refusal files and role mains."""
    for f in REFUSAL_FILES:
        doc = _y(REPO / f) or []
        tasks = [x for p in doc for s in ("pre_tasks", "tasks", "post_tasks") for x in (p.get(s) or [])] if f == "main.yml" else doc
        for t in _walk(tasks):
            yield f, None, t
    for main in sorted(ROLES.glob("pazny.*/tasks/main.yml")):
        for t in _walk(_y(main)):
            yield str(main.relative_to(REPO)), main.parent.parent.name, t


def refusals(page_vars: set[str], checked_fields: set[str]) -> dict:
    """Every fail/assert the page can reach. Returns {rules, oracle, skipped, derived}."""
    cfg, derived = _cfg(), derived_vars()
    consts = {k: v for k, v in cfg.items() if not (isinstance(v, str) and "{{" in v)}
    rules, oracle, skipped = [], [], []
    for src, role, t in _refusal_tasks():
        key = next((k for k in FAIL_KEYS if k in t), None)
        if not key:
            continue
        name = f"{src}: {t.get('name', '?')}"
        when = (_include_gate(role) if role else []) + _when(t)
        raw = (t[key] or {}).get("that") if "assert" in key else None
        that = [str(x) for x in (raw if isinstance(raw, list) else [raw] if raw else [])]
        names = set().union(set(), *[_names(e) for e in when + that])
        page = {n for n in names if n in page_vars or n in derived}
        runtime = {n for n in names - page - {GATED_FACT}
                   if (n not in cfg and not n.startswith(("nos_skip_", "allow_", "ansible_os")))
                   or (n in cfg and n not in consts)}
        if not page or runtime:
            skipped.append({"source": name, "why": "not reachable from the page" if not page else f"needs runtime facts {sorted(runtime)}"})
            continue
        if not all(_truth(e, consts) is not False for e in when if not (_names(e) & (page | {GATED_FACT, "ansible_os_family"}))):
            skipped.append({"source": name, "why": "an escape hatch the page never writes keeps it closed"})
            continue
        oracle.append({"source": name, "when": when, "that": that})
        if page <= checked_fields:
            skipped.append({"source": name, "why": "the page validates that field itself (problems())", "judged": True})
            continue
        if that:
            raise SystemExit(f"{name}: an assert the page can reach and cannot carry — extend rules.py")
        lits, any_ = [], []
        for e in when:
            if GATED_FACT in e:
                any_ = sorted(gated_flags()) + (["apps_runner_enabled"] if proxy_apps() else [])
            elif not (_names(e) & page):
                continue                          # a constant (checked open above) or a host fact
            elif (lit := literal(e)) is None:
                raise SystemExit(f"{name}: `{e}` is not a literal rules.py can carry to the page — extend it")
            elif list(lit) not in lits:
                lits.append(list(lit))
        labels = {"apps_runner_enabled": "the apps " + ", ".join(proxy_apps())} if any_ else {}
        why = re.sub(r"^\[[^\]]*\]\s*", "", str(t.get("name", "")))
        twin = next((r for r in rules if sorted(map(tuple, r["all"])) == sorted(map(tuple, lits)) and r["any"] == any_), None)
        if twin:                                  # main.yml and pazny.traefik refuse the same pair: one message
            twin["source"] += f" + {name}"
            continue
        rules.append({"cls": "refused", "all": lits, "any": any_, "labels": labels, "why": why, "source": name})
    return {"rules": rules, "oracle": oracle, "skipped": skipped, "derived": derived}


# ── the oracle: what the playbook would do with a written config ─────────────
class Oracle:
    """Judges a config.yml the page wrote against the real expressions in main.yml
    and the roles (Jinja-evaluated), then against the silent rules."""

    def __init__(self, data: dict):
        self.data, self.cfg = data, _cfg()
        self.refused = data["rules_oracle"]
        self.auto = auto_tasks()
        self.silent = [r for r in data["rules"] if r["cls"] == "silent"]
        self.gated, self.apps = gated_flags(), proxy_apps()
        exprs = [e for r in self.refused for e in r["when"] + r["that"]] + [w for _, w in self.auto]
        used = set().union(*map(_names, exprs)) | {u for r in self.silent for u in r["upstream"]} \
            | {r["consumer"][k] for r in self.silent for k in ("flag", "field") if k in r["consumer"]}
        self.consts = {k: v for k, v in self.cfg.items() if k in used and not (isinstance(v, str) and "{{" in v)}

    def __call__(self, cfg: dict, creds: dict) -> list[str]:
        ctx = {**self.consts, **cfg, **creds, "ansible_os_family": "Darwin"}
        for k, kind in self.data["derived"].items():
            local = _render_default("tenant_domain_is_local", ctx.get("tenant_domain") or "dev.local")
            if k not in cfg:
                ctx[k] = local if kind == "local" else not local
        on = lambda f: bool(ctx.get(f))  # noqa: E731
        ctx[GATED_FACT] = sorted(r for f, rs in self.gated.items() if on(f) for r in rs) + \
            ([f"app:{a}" for a in self.apps] if ctx.get("apps_runner_enabled", True) else [])
        bad = []
        for r in self.refused:
            if all(_truth(e, ctx) for e in r["when"]) and not (r["that"] and all(_truth(e, ctx) for e in r["that"])):
                bad.append("refused: " + r["source"])
        for fact, when in self.auto:                       # main.yml runs these before the stacks
            if _truth(when, ctx):
                ctx[fact] = True
        knobs_set = {k for k in cfg if not k.startswith("install_")}
        for r in self.silent:
            c = r["consumer"]
            active = (on(c["flag"]) if "flag" in c else bool(cfg.get("nos_extra_identities")) if "people" in c
                      else on(c["field"]) if "field" in c else c["knob"] in knobs_set and bool(cfg[c["knob"]]))
            if active and not any(on(u) for u in r["upstream"]):
                bad.append(f"silent: {r['source']} — {' / '.join(r['upstream'])} off")
        return bad


# ── the sweep ───────────────────────────────────────────────────────────────
SWEEP_JS = r"""
const P = "FAKEsweep12345678", tok = "cf-sweep-token";
const offered = a => [undefined, ...DATA.profiles.filter(p => p.axis === a && !p.step).map(p => p.id)];
const combos = DATA.axes.reduce((acc, a) => acc.flatMap(c => offered(a).map(id => ({...c, [a]: id}))), [{}]);
const person = [{name: "jana", email: "jana@example.test", tier: 3}];
const out = {states: 0, blocked: 0, configs: {}, blocks: {}, notes: {}};
function run(s) {
  out.states++;
  const pr = problems(DATA, s);
  if (pr.length) { out.blocked++; for (const p of pr) out.blocks[p.msg.replace(/"[^"]*"/g, "…")] = (out.blocks[p.msg.replace(/"[^"]*"/g, "…")] || 0) + 1; return; }
  const st = settle(DATA, s);
  for (const n of st.notes) { const k = `${n.key} <- ${n.by} (${n.cls})`; out.notes[k] = (out.notes[k] || 0) + 1; }
  const y = renderConfig(DATA, s, st.on), c = renderCredentials(DATA, s.fields.global_password_prefix, s.fields);
  const k = y + "\u0000" + c;
  if (!(k in out.configs)) out.configs[k] = JSON.stringify(s);
}
for (const picks of (SUBSET.picks || combos)) for (const mail of [null, ...DATA.mail.options.map(o => o.id)])
  for (const test of [false, true]) for (const people of [[], person]) for (const dom of SUBSET.domains || [null, "example.eu"]) {
    const fields = {global_password_prefix: P, nos_test_users_enabled: test, restic_repo: "/Volumes/Backup/restic"};
    if (dom) Object.assign(fields, {tenant_domain: dom, acme_cloudflare_api_token: tok});
    const base = {fields, picks, mail, manual: {}, people};
    run(base);
    if (dom) run({...base, fields: {...fields, acme_cloudflare_api_token: ""}});
    if (SUBSET.toggles === false || dom) continue;      // toggles from the default domain; the public one is judged per combination
    const on0 = settle(DATA, base).on;
    for (const f of DATA.flags) if (!f.auto && !blocked(DATA, f.key)) run({...base, manual: {[f.key]: !on0[f.key]}});
  }
console.log(JSON.stringify(out));
"""


def logic_js() -> str:
    return re.search(r'<script id="logic">(.*?)</script>', TPL.read_text(), re.S).group(1)


def sweep(data: dict, subset: dict | None = None, logic: str | None = None, page_data: dict | None = None) -> dict:
    """Every profile combination × mail × test users × one extra person × domain,
    and from each, every install_* flag toggled once; each config the page would
    let you download is judged by Oracle. Returns counts and every let-through."""
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required: the sweep runs the page's own JS")
    t0 = time.monotonic()
    js = (logic or logic_js()) + f"\nconst DATA={json.dumps(page_data or data)};\nconst SUBSET={json.dumps(subset or {})};\n" + SWEEP_JS
    run = subprocess.run([node, "-"], input=js, capture_output=True, text=True)
    if run.returncode:
        raise SystemExit(f"the page's JS failed under node:\n{run.stderr[-2000:]}")
    res = json.loads(run.stdout)
    t_node = time.monotonic() - t0
    judge, leaks = Oracle(data), {}
    for key, state in res["configs"].items():
        y, c = key.split("\u0000")
        for why in judge(yaml.load(y, Loader=_Y) or {}, yaml.load(c, Loader=_Y) or {}):
            leaks.setdefault(why, state)
    return {"states": res["states"], "blocked": res["blocked"], "configs": len(res["configs"]),
            "blocks": res["blocks"], "notes": res["notes"], "leaks": leaks,
            "seconds": {"node": round(t_node, 2), "total": round(time.monotonic() - t0, 2)}}


def main(data: dict) -> int:
    r = sweep(data)
    cls = {c: sum(1 for x in data["rules"] if x["cls"] == c) for c in ("auto", "silent", "refused")}
    print(f"rules: {cls}  (+{len(data['rules_skipped'])} refusals the page cannot reach or already checks)")
    print(f"sweep: {r['states']} states, {r['blocked']} blocked, {r['configs']} distinct configs judged, {r['seconds']}")
    for why, s in r["leaks"].items():
        print(f"LET THROUGH: {why}\n  state: {s}")
    return 1 if r["leaks"] else 0


if __name__ == "__main__":
    print("run through tools/profile-builder-build.py --sweep", file=sys.stderr)
    raise SystemExit(2)
