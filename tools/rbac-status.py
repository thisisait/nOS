#!/usr/bin/env python3
"""rbac-status — the permission genome as a matrix, and every enforcement point that disagrees.

Prints state/genome/permissions.yml as capability x role, then reads each
enforcement point's LITERAL in the repo (a PHP const, a TS const, a Jinja tier
expression, a YAML tier list, an agent scope, a Bone loop identity, a reserved
Wing bearer scope, an app tier) and names, with file:line, the ones
that disagree with the genome. A point whose source cannot be read or parsed is
UNKNOWN, never ok. Reads the repo only (`--root`), never the live estate; writes
nothing; exits 0 whatever it finds. Doctrine: ssot/doctrine/permissions.md.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
GENOME = "state/genome/permissions.yml"
DEFAULTS = "default.config.yml"
ENDUSER = "files/anatomy/wing/app/Security/EndUser.php"
BASE = "files/anatomy/wing/app/Presenters/BasePresenter.php"
TIER_TS = "files/anatomy/face/src/lib/security/tier.ts"
CORTEX = "files/anatomy/cortex/server/rbac.ts"
TOOLS = "files/anatomy/wing/app/AgentKit/Tools"
BONE = "files/anatomy/bone"
AGENTS = "files/anatomy/agents"


class Unknown(Exception):
    """The source is absent or its literal is not where the parser looks."""


def _read(root: pathlib.Path, rel: str) -> list[str]:
    try:
        return (root / rel).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise Unknown(f"{rel}: {e.__class__.__name__}") from None


def _strings(text: str) -> list[str]:
    return re.findall(r"""['"]([^'"]+)['"]""", text)


def _find(lines: list[str], pattern: str, rel: str, start: int = 0) -> int:
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]) and not lines[i].lstrip().startswith(("//", "#", "*")):
            return i
    raise Unknown(f"{rel}: no line matches {pattern!r}")


# ── one parser per enforcement-point family ────────────────────────────────

def _literal(lines: list[str], i: int, rel: str) -> list[str]:
    """The strings of the literal after `=` on line i: a bracket list may span lines.
    `[]` is a literal (empty); anything that yields no string otherwise is UNKNOWN."""
    text = lines[i].split("=", 1)[1].strip()
    if text.startswith("["):
        for line in lines[i + 1:]:
            if text.count("[") <= text.count("]"):
                break
            text += "\n" + line
        if text.count("[") > text.count("]"):
            raise Unknown(f"{rel}:{i + 1}: the list never closes")
        body = text[:text.rindex("]") + 1]
        if re.fullmatch(r"\[\s*\]", body):
            return []
        text = body
    got = _strings(text)
    if not got:
        raise Unknown(f"{rel}:{i + 1}: not a string literal; parser does not model it")
    return got


def php_const(root, rel, name):
    lines = _read(root, rel)
    i = _find(lines, rf"\bconst\s+{name}\s*=", rel)
    return _literal(lines, i, rel), i + 1


def php_tiermap(root, rel, name):
    """`const NAME = [1 => [...] | Class::CONST, ...];` → {tier: groups}."""
    lines = _read(root, rel)
    i = _find(lines, rf"\bconst\s+{name}\s*=", rel)
    out = {}
    for line in lines[i + 1:]:
        if line.strip().startswith("];"):
            break
        m = re.match(r"\s*(\d+)\s*=>\s*(.+)", line)
        if not m:
            continue
        ref = re.search(r"EndUser::(\w+)", m.group(2))
        out[int(m.group(1))] = php_const(root, ENDUSER, ref.group(1))[0] if ref else _strings(m.group(2))
    if not out:
        raise Unknown(f"{rel}: {name} holds no tier rows")
    return out, i + 1


def php_calls(root, rel, func, call):
    lines = _read(root, rel)
    i = _find(lines, rf"function\s+{func}\s*\(", rel)
    body = []
    for line in lines[i + 1:]:
        if re.match(r"\s*(protected|public|private)\s+function\b", line):
            break
        body.append(line)
    got = sorted(set(re.findall(rf"{call}\(\s*'([^']+)'\s*\)", "\n".join(body))))
    if not got:
        raise Unknown(f"{rel}: {func} calls no {call}()")
    return got, i + 1


def ts_const(root, rel, name):
    lines = _read(root, rel)
    i = _find(lines, rf"\bconst\s+{name}\b", rel)
    return _literal(lines, i, rel), i + 1


def ts_rankmap(root, rel, name):
    """`const NAME: Record<string, number> = { 'g': 1, ... }` → {tier: groups}."""
    lines = _read(root, rel)
    i = _find(lines, rf"\bconst\s+{name}\b", rel)
    out: dict[int, list[str]] = {}
    for line in lines[i + 1:]:
        if line.strip().startswith("}"):
            break
        m = re.match(r"""\s*['"]?([\w-]+)['"]?\s*:\s*(\d+)""", line)
        if m:
            out.setdefault(int(m.group(2)), []).append(m.group(1))
    if not out:
        raise Unknown(f"{rel}: {name} holds no rows")
    return out, i + 1


def ts_tiermap(root, rel, name):
    """`const NAME: Record<number, string[]> = { 1: ['g'], ... }`."""
    lines = _read(root, rel)
    i = _find(lines, rf"\bconst\s+{name}\b", rel)
    out = {}
    for line in lines[i + 1:]:
        if line.strip().startswith("}"):
            break
        m = re.match(r"\s*(\d+)\s*:\s*\[(.*)\]", line)
        if m:
            out[int(m.group(1))] = _strings(m.group(2))
    if not out:
        raise Unknown(f"{rel}: {name} holds no tier rows")
    return out, i + 1


def yaml_tiers(root):
    """default.config.yml `authentik_rbac_tiers` (cumulative) → {tier: cumulative groups}, line."""
    import yaml
    lines = _read(root, DEFAULTS)
    i = _find(lines, r"^authentik_rbac_tiers:", DEFAULTS)
    block = [lines[i]]
    for line in lines[i + 1:]:
        if line and not line.startswith((" ", "#")):
            break
        block.append(line)
    try:
        rows = yaml.safe_load("\n".join(block))["authentik_rbac_tiers"]
        return {int(r["tier"]): list(r["groups"]) for r in rows}, i + 1
    except Exception as e:  # noqa: BLE001 — any shape error is UNKNOWN
        raise Unknown(f"{DEFAULTS}: authentik_rbac_tiers unparseable ({e.__class__.__name__})") from None


def own_from_cumulative(cum):
    seen: set[str] = set()
    out = {}
    for t in sorted(cum):
        out[t] = [g for g in cum[t] if g not in seen]
        seen.update(cum[t])
    return out


def jinja_tier(root, rel, anchor):
    """`selectattr('tier', 'equalto', N) | first).groups ...` (or `| map(attribute='groups') | first`),
    read for what the rest of the `{{ }}` keeps of tier N's groups."""
    lines = _read(root, rel)
    i = _find(lines, anchor, rel)
    m = re.search(r"selectattr\('tier',\s*'equalto',\s*(\d+)\)", lines[i])
    row = m and re.match(r"\s*\|\s*first\s*\)\s*\.groups|\s*\|\s*map\(attribute='groups'\)\s*\|\s*first",
                         lines[i][m.end():])
    if not row:
        raise Unknown(f"{rel}:{i + 1}: no tier expression the parser models")
    how = _pick(lines[i][m.end() + row.end():].split("}}", 1)[0], rel, i + 1)
    cum, _ = yaml_tiers(root)
    groups = cum[int(m.group(1))]
    return {"all": groups, "first": groups[:1], "last": groups[-1:]}[how], i + 1


_SELECT = re.compile(r"\|\s*(first|last)\b|map\(\s*['\"](first|last)['\"]\s*\)|\[\s*(-?\d+)\s*\]")
_BENIGN = re.compile(r"\|\s*(list|to_json|unique|sort|flatten|join\([^)]*\)|default\([^)]*\))")


def _pick(tail: str, rel: str, n: int) -> str:
    """What the text after a group list keeps of it: 'all', 'first' or 'last'; else UNKNOWN."""
    found = [next(x for x in m.groups() if x) for m in _SELECT.finditer(tail)]
    if len(found) == 1 and found[0] in ("first", "0", "last", "-1"):
        return "first" if found[0] in ("first", "0") else "last"
    if not found and not re.sub(r"[\s)\]}'\"%,-]", "", _BENIGN.sub("", tail)):
        return "all"
    raise Unknown(f"{rel}:{n}: the group expression is not one the parser models")


def per_tier(root, rel, anchor, assign):
    """A line over every tier's groups, read for what it keeps of each list.
    assign: a login gets its tier's list (all = cumulative, so tier 1's groups leak down);
    else the line names the realm's set of groups (all = every group, once)."""
    lines = _read(root, rel)
    i = _find(lines, anchor, rel)
    if "groups" not in lines[i]:
        raise Unknown(f"{rel}:{i + 1}: no group expression on the line")
    how = _pick(lines[i][lines[i].rindex("groups") + len("groups"):], rel, i + 1)
    cum, _ = yaml_tiers(root)
    if how == "all":
        return (cum if assign else own_from_cumulative(cum)), i + 1
    return {t: (g[:1] if how == "first" else g[-1:]) for t, g in cum.items()}, i + 1


def blueprint_superuser(root, rel):
    lines = _read(root, rel)
    i = _find(lines, r"is_superuser:", rel)
    return _strings(lines[i].split(" in ", 1)[-1]), i + 1


def nodered_admin(root, rel):
    """`permissions: '*'` in the OIDC verify callback with no group test = every authenticated user."""
    lines = _read(root, rel)
    i = _find(lines, r"permissions:\s*['\"]\*['\"]", rel)
    if "groups" in "\n".join(lines[max(0, i - 15):i]):
        raise Unknown(f"{rel}:{i + 1}: a group test precedes the grant; parser does not model it")
    return "every authenticated user", i + 1


LOOPAUTH = "files/anatomy/bone/loopauth.py"
PROVISION = "files/anatomy/wing/bin/provision-token.php"
DGX_IDENTITY = "bootstrap/minimal-linux-dgx/identity/keap-identity.py"


def bone_loop(root):
    """loopauth.py LOOP_SCOPES + IDENTITIES → {loop:<scope>: roles}; `operator` is operator-local."""
    import ast
    src = "\n".join(_read(root, LOOPAUTH))
    try:
        found = {t.id: n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Assign, ast.AnnAssign))
                 for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                 if isinstance(t, ast.Name) and t.id in ("LOOP_SCOPES", "IDENTITIES")}

        def scopes(node):  # frozenset({"a", "b"}) only
            assert isinstance(node, ast.Call) and getattr(node.func, "id", "") == "frozenset"
            assert len(node.args) == 1 and isinstance(node.args[0], ast.Set)
            return {ast.literal_eval(e) for e in node.args[0].elts}

        out = {f"loop:{s}": [] for s in scopes(found["LOOP_SCOPES"].value)}
        ids = found["IDENTITIES"].value
        assert isinstance(ids, ast.Dict)
        for k, v in zip(ids.keys, ids.values):
            assert isinstance(v, ast.Tuple) and len(v.elts) == 2
            name = ast.literal_eval(k)
            for s in scopes(v.elts[1]):
                out.setdefault(f"loop:{s}", []).append("operator-local" if name == "operator" else name)
    except (SyntaxError, KeyError, AssertionError, ValueError):
        raise Unknown(f"{LOOPAUTH}: LOOP_SCOPES/IDENTITIES not the literal shape the parser models") from None
    return {c: sorted(r) for c, r in out.items()}, found["IDENTITIES"].lineno


def wing_reserved(root):
    """provision-token.php `in_array('<scope>', $requested, true) && $name !== '<bearer>'` → {scope: (door, line)}."""
    lines = _read(root, PROVISION)
    rx = re.compile(r"in_array\('([\w.]+)',\s*\$requested,\s*true\)\s*&&\s*\$name\s*!==\s*'([\w-]+)'")
    out = {m.group(1): (f"door:{m.group(2)}", n) for n, line in enumerate(lines, 1) for m in rx.finditer(line)}
    if not out:
        raise Unknown(f"{PROVISION}: no reserved scope found")
    return out


def app_tiers(root):
    """apps/*.yml declaring both authentik.tier and nginx.rbac_tier → [(app, tier, rbac_tier, line)]."""
    import yaml
    out = []
    for f in sorted((root / "apps").glob("*.yml")):
        rel = str(f.relative_to(root))
        lines = _read(root, rel)
        try:
            d = yaml.safe_load("\n".join(lines)) or {}
            a, b = (d.get("authentik") or {}).get("tier"), (d.get("nginx") or {}).get("rbac_tier")
        except Exception:  # noqa: BLE001
            raise Unknown(f"{rel}: unparseable") from None
        if a is not None and b is not None:
            out.append((f.stem, int(a), int(b), f"{rel}:{_find(lines, r'^authentik:', rel) + 1}"))
    if not out:
        raise Unknown("apps/: no app declares both authentik.tier and nginx.rbac_tier")
    return out


def dgx_identity(root):
    """keap-identity.py `if "<linux group>" in mine: return "<groups>"` → [(linux group, asserted, line)]."""
    lines = _read(root, DGX_IDENTITY)
    out = []
    for n, line in enumerate(lines[:-1]):
        m, r = re.search(r'if "([\w-]+)" in mine:', line), re.search(r'return "([^"]+)"', lines[n + 1])
        if m and r:
            out.append((m.group(1), sorted(r.group(1).split(",")), n + 1))
    if not out:
        raise Unknown(f"{DGX_IDENTITY}: no group mapping found")
    return out


# ── genome helpers ─────────────────────────────────────────────────────────

def load_genome(root):
    import yaml
    lines = _read(root, GENOME)
    try:
        g = yaml.safe_load("\n".join(lines))
        caps = dict(g["capabilities"])
        tiers = {int(k): list(v) for k, v in g["tiers"].items()}
    except Exception as e:  # noqa: BLE001
        raise Unknown(f"{GENOME}: unparseable ({e.__class__.__name__})") from None
    at = {}
    for n, line in enumerate(lines, 1):
        m = re.match(r"\s{2}([\w.:\-]+):", line)
        if m and m.group(1) in caps:
            at.setdefault(m.group(1), n)
    return g, caps, tiers, at


def groups_of(roles, tiers):
    out = []
    for r in roles:
        if r.startswith("tier:"):
            out += tiers.get(int(r.split(":")[1]), [])
    return sorted(set(out))


# ── the points ─────────────────────────────────────────────────────────────

GROUP_POINTS = [  # id, capability, parser, args
    ("wing-enduser", "wing.operator", php_const, (ENDUSER, "OPERATOR_GROUPS")),
    ("wing-require-superadmin", "wing.operator", php_calls, (BASE, "requireSuperAdmin", "callerHasGroup")),
    ("face-tier-ts", "face.admin", ts_const, (TIER_TS, "ADMIN_GROUPS")),
    ("face-write-groups", "table.write", ts_const, (TIER_TS, "WRITE_GROUPS")),
    ("blueprint-superuser", "idp.superuser", blueprint_superuser,
     ("files/anatomy/plugins/authentik-base/blueprints/00-admin-groups.yaml.j2",)),
    ("blueprint-superuser-role", "idp.superuser", blueprint_superuser,
     ("roles/pazny.authentik/templates/blueprints/00-admin-groups.yaml.j2",)),
    ("thalamus-tier1-env", "iris.operator_views", jinja_tier,
     ("roles/pazny.thalamus/templates/thalamus.env.j2", r"^NOS_TIER1_GROUPS=")),
    ("thalamus-tier2-env", "app.propose", jinja_tier,
     ("roles/pazny.thalamus/templates/thalamus.env.j2", r"^NOS_TIER2_GROUPS=")),
    ("thalamus-tier1-plist", "iris.operator_views", jinja_tier,
     ("roles/pazny.thalamus/templates/thalamus.plist.j2", r"'equalto', 1\)")),
    ("thalamus-tier2-plist", "app.propose", jinja_tier,
     ("roles/pazny.thalamus/templates/thalamus.plist.j2", r"'equalto', 2\)")),
    ("gitlab-admin-groups", "app.admin:gitlab", jinja_tier,
     ("roles/pazny.gitlab/templates/compose.yml.j2", r"admin_groups:")),
    ("jupyterhub-admin", "app.admin:jupyterhub", jinja_tier,
     ("roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2", r"\.admin_groups\s*=")),
    ("jupyterhub-allowed", "app.reach:jupyterhub", jinja_tier,
     ("roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2", r"\.allowed_groups\s*=")),
]

TIER_POINTS = [  # id, parser, args — each yields {tier: own groups}
    ("wing-basepresenter-tiers", php_tiermap, (BASE, "TIER_GROUPS")),
    ("face-group-rank", ts_rankmap, (TIER_TS, "GROUP_RANK")),
    ("cortex-rbac-ts", ts_tiermap, (CORTEX, "TIER_GROUPS")),
    ("receptor-identity-map", per_tier, ("roles/pazny.receptor/templates/identity-map.yml.j2", r"'groups':", True)),
    ("linux-users-unix-groups", per_tier, ("roles/pazny.linux.users/tasks/main.yml", r"_unix_tier_group:", True)),
    ("jupyterhub-unix-realm", per_tier,
     ("roles/pazny.jupyterhub/templates/jupyterhub_config.py.j2", r"^UNIX_REALM_GROUPS\s*=", False)),
    ("identity-status-unix", per_tier, ("tools/identity-status.py", r"^\s*names\s*=.*groups", False)),
]


def evaluate(root: pathlib.Path) -> dict:
    points, drift = [], []

    def point(pid, status, at=None, detail=""):
        points.append({"id": pid, "status": status, "at": at, "detail": detail})

    def drifted(pid, at, says, genome):
        drift.append({"point": pid, "at": at, "says": says, "genome": genome})
        n = sum(d["point"] == pid for d in drift)
        if n == 1:
            point(pid, "drift", at, f"says {says}, genome {genome}")
        else:
            next(p for p in points if p["id"] == pid)["detail"] = f"{n} drifts, listed below"

    try:
        g, caps, tiers, cap_at = load_genome(root)
    except Unknown as e:
        return {"matrix": None, "points": [{"id": "genome", "status": "UNKNOWN", "at": None,
                                            "detail": str(e)}], "drift": []}

    for pid, cap, fn, args in GROUP_POINTS:
        try:
            got, line = fn(root, *args)
        except Unknown as e:
            point(pid, "UNKNOWN", None, str(e))
            continue
        want = groups_of(caps.get(cap, []), tiers)
        at = f"{args[0]}:{line}"
        if sorted(set(got)) != want:
            drifted(pid, at, sorted(set(got)), want)
        else:
            point(pid, "ok", at)

    for pid, fn, args in TIER_POINTS:
        try:
            got, line = fn(root, *args)
        except Unknown as e:
            point(pid, "UNKNOWN", None, str(e))
            continue
        at = f"{args[0]}:{line}"
        bad = {t: sorted(got.get(t, [])) for t in tiers if sorted(got.get(t, [])) != sorted(tiers[t])}
        if bad:
            drifted(pid, at, bad, {t: sorted(tiers[t]) for t in bad})
        else:
            point(pid, "ok", at)

    try:
        cum, line = yaml_tiers(root)
        own = own_from_cumulative(cum)
        at = f"{DEFAULTS}:{line}"
        if {t: sorted(v) for t, v in own.items()} != {t: sorted(v) for t, v in tiers.items()}:
            drifted("authentik-rbac-tiers", at, own, tiers)
        else:
            point("authentik-rbac-tiers", "ok", at)
    except Unknown as e:
        point("authentik-rbac-tiers", "UNKNOWN", None, str(e))

    try:
        got, line = nodered_admin(root, "roles/pazny.nodered/templates/settings.js.j2")
        drifted("nodered-admin", f"roles/pazny.nodered/templates/settings.js.j2:{line}", got,
                caps.get("app.admin:nodered"))
    except Unknown as e:
        point("nodered-admin", "UNKNOWN", None, str(e))

    try:
        doors = sorted(f"door:{php_const(root, ENDUSER, n)[0][0]}" for n in ("TOKEN_NAME", "THALAMUS"))
        at = f"{ENDUSER}:{php_const(root, ENDUSER, 'TOKEN_NAME')[1]}"
        want = sorted(caps.get("identity.assert", []))
        drifted("wing-enduser-doors", at, doors, want) if doors != want else point("wing-enduser-doors", "ok", at)
    except (Unknown, IndexError) as e:
        point("wing-enduser-doors", "UNKNOWN", None, str(e))

    point("keap-internal", "UNKNOWN", None, "KEAP decides tier 1 internally; its source is not in this repo")

    try:
        got, line = bone_loop(root)
        want = {c: sorted(r) for c, r in caps.items() if c.startswith("loop:")}
        bad = {c: got.get(c, []) for c in sorted(set(got) | set(want)) if got.get(c, []) != want.get(c, [])}
        at = f"{LOOPAUTH}:{line}"
        drifted("bone-loop-identities", at, bad, {c: want.get(c, []) for c in bad}) if bad \
            else point("bone-loop-identities", "ok", at)
    except Unknown as e:
        point("bone-loop-identities", "UNKNOWN", None, str(e))

    try:
        reserved = wing_reserved(root)
        held = {c: sorted(r for r in roles if r.startswith("door:")) for c, roles in caps.items()
                if c != "identity.assert" and any(r.startswith("door:") for r in roles)}
        bad = 0
        for c in sorted(set(reserved) | set(held)):
            door, n = reserved.get(c, (None, None))
            if held.get(c, []) != ([door] if door else []):
                at = f"{PROVISION}:{n}" if n else f"{GENOME}:{cap_at.get(c, 1)}"
                drifted("wing-reserved-scopes", at, f"{c} reserved to {door}", held.get(c, []))
                bad += 1
        if not bad:
            point("wing-reserved-scopes", "ok", PROVISION)
    except Unknown as e:
        point("wing-reserved-scopes", "UNKNOWN", None, str(e))

    try:
        bad = 0
        for app, tier, rbac, at in app_tiers(root):
            want = caps.get(f"app.reach:{app}")
            says = [f"tier:{t}" for t in range(1, tier + 1)]
            if tier != rbac or (want is not None and sorted(want) != says):
                drifted("app-tiers", at, f"{app} authentik.tier {tier}, nginx.rbac_tier {rbac}", want)
                bad += 1
        if not bad:
            point("app-tiers", "ok", "apps/")
    except Unknown as e:
        point("app-tiers", "UNKNOWN", None, str(e))

    try:
        bad = 0
        for group, asserted, n in dgx_identity(root):
            tier = next((t for t, g in tiers.items() if sorted(g) == asserted), None)
            if tier is None or group not in tiers[tier]:
                drifted("dgx-keap-identity", f"{DGX_IDENTITY}:{n}", f"linux group {group} asserts {asserted}",
                        f"{group} is not a tier-{tier} group {sorted(tiers[tier])}" if tier
                        else "no tier holds that set")
                bad += 1
        if not bad:
            point("dgx-keap-identity", "ok", DGX_IDENTITY)
    except Unknown as e:
        point("dgx-keap-identity", "UNKNOWN", None, str(e))

    _scopes(root, caps, cap_at, point, drifted)
    return {"matrix": caps, "points": points, "drift": drift}


def _scopes(root, caps, cap_at, point, drifted):
    """Agent scopes: declared ⊆ genome ⊆ enforced, and the genome's agents are the declarers."""
    import yaml

    agent_caps = {c for c, r in caps.items() if (any(x.startswith("agent:") for x in r) or c.startswith("nos:"))
                  and not c.startswith("loop:")}  # loop:* is Bone loopauth, read by bone-loop-identities
    declared: dict[str, set[str]] = {}
    files = sorted((root / AGENTS).glob("*/agent.yml"))
    if not files:
        point("agent-scopes", "UNKNOWN", None, f"{AGENTS}: no agent manifests")
    else:
        n_drift = 0
        for f in files:
            rel = str(f.relative_to(root))
            name = f.parent.name
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
                a = yaml.safe_load("\n".join(lines)) or {}
            except Exception:  # noqa: BLE001
                point(f"agent-scopes:{name}", "UNKNOWN", None, f"{rel}: unparseable")
                continue
            held = list((a.get("audit") or {}).get("capability_scopes") or []) + list(a.get("capabilities") or [])
            for s in held:
                declared.setdefault(s, set()).add(f"agent:{name}")
                if f"agent:{name}" in caps.get(s, []):
                    continue
                try:
                    ln = _find(lines, rf"^\s*-\s*{re.escape(s)}\s*$", rel) + 1
                except Unknown:
                    ln = 1
                why = "no such capability (enforced nowhere)" if s not in caps else "genome does not grant it"
                drifted("agent-scopes", f"{rel}:{ln}", f"agent:{name} declares {s}", why)
                n_drift += 1
        for c in sorted(agent_caps):
            extra = sorted(set(caps[c]) - declared.get(c, set()))
            if extra:
                drifted("agent-scopes", f"{GENOME}:{cap_at.get(c, 1)}", f"{c} lists {extra}", "no manifest declares it")
                n_drift += 1
        if not n_drift:
            point("agent-scopes", "ok", AGENTS)

    def enforced(pid, rel_dir, glob, rx, want):  # Bone: require_scope("...") literals
        d = root / rel_dir
        found: dict[str, str] = {}
        for f in sorted(d.glob(glob)) if d.is_dir() else []:
            if "test" in f.name.lower():
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for s in re.findall(rx, line):
                    found.setdefault(s, f"{f.relative_to(root)}:{n}")
        if not found:
            point(pid, "UNKNOWN", None, f"{rel_dir}: no enforcement literal found")
            return
        missing = sorted(set(want) - set(found))
        for c in missing:
            drifted(pid, f"{GENOME}:{cap_at.get(c, 1)}", f"genome holds {c}", "no point enforces it")
        if not missing:
            point(pid, "ok", rel_dir)

    wing_want = [c for c in agent_caps if not c.startswith("nos:")]
    bone_want = [c for c in agent_caps if c.startswith("nos:")]
    _wing_required(root, wing_want, cap_at, point, drifted)
    enforced("bone-require-scope", BONE, "*.py", r"require_scope\(\s*\"([^\"]+)\"", bone_want)

    try:
        lines = _read(root, DEFAULTS)
        i = _find(lines, r"^authentik_agent_scopes:", DEFAULTS)
        bad = 0
        for n in range(i + 1, len(lines)):
            if lines[n] and not lines[n].startswith((" ", "#")):
                break
            m = re.match(r'\s*-\s*"([^"]+)"', lines[n])
            if m and m.group(1) not in caps:
                drifted("bone-scope-catalog", f"{DEFAULTS}:{n + 1}", f"catalog offers {m.group(1)}",
                        "no such capability (enforced nowhere)")
                bad += 1
        if not bad:
            point("bone-scope-catalog", "ok", f"{DEFAULTS}:{i + 1}")
    except Unknown as e:
        point("bone-scope-catalog", "UNKNOWN", None, str(e))


def _wing_required(root, want, cap_at, point, drifted):
    """Wing ToolRegistry: the `return [...]` of each tool's requiredScopes()."""
    d = root / TOOLS
    found = set()
    for f in sorted(d.glob("*.php")) if d.is_dir() else []:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"function requiredScopes\(\)[^{]*\{\s*return\s*\[([^\]]*)\]", src):
            found.update(_strings(m.group(1)))
    if not found:
        point("wing-required-scopes", "UNKNOWN", None, f"{TOOLS}: no requiredScopes() literal found")
        return
    missing = sorted(set(want) - found)
    for c in missing:
        drifted("wing-required-scopes", f"{GENOME}:{cap_at.get(c, 1)}", f"genome holds {c}", "no tool requires it")
    if not missing:
        point("wing-required-scopes", "ok", TOOLS)


def render(out: dict) -> str:
    rows = []
    if out["matrix"] is None:
        rows.append("matrix: UNKNOWN (genome unreadable)")
    else:
        rows.append("CAPABILITY x ROLE  (state/genome/permissions.yml — descriptive)")
        w = max(len(c) for c in out["matrix"])
        for c, roles in out["matrix"].items():
            rows.append(f"  {c:<{w}}  {', '.join(roles) or '-'}")
    rows.append("")
    rows.append("ENFORCEMENT POINTS")
    for p in out["points"]:
        rows.append(f"  {p['status']:<8} {p['id']:<26} {p['at'] or ''}  {p['detail'] if p['status'] != 'ok' else ''}".rstrip())
    rows.append("")
    rows.append(f"DRIFT ({len(out['drift'])})")
    for d in out["drift"]:
        rows.append(f"  {d['at']}  [{d['point']}] says {d['says']}; genome: {d['genome']}")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=str(REPO), help="repo checkout to read (default: this one)")
    a = ap.parse_args()
    try:
        out = evaluate(pathlib.Path(a.root))
    except Exception as e:  # noqa: BLE001 — a reader never crashes into a non-zero exit
        out = {"matrix": None, "points": [{"id": "reader", "status": "UNKNOWN", "at": None,
                                           "detail": f"{e.__class__.__name__}: {e}"}], "drift": []}
    print(json.dumps(out, indent=2, default=str) if a.json else render(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
