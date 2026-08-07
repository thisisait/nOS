"""Does the estate's CODE perform a service→service dependency? — the probe.

Plan: docs/idea/13-relations.md §R1/§R2
Doctrine: docs/doctrine/layers.md §4.1 — repair before declare.

WHY THIS IS A MODULE AND NOT A HELPER INSIDE ONE TEST FILE. It is the single
mechanism behind "repair before declare" for every non-database edge, so it is
read by BOTH the edge gate (test_service_dependency_edges.py) and the layer
gate (test_service_layer_is_derived.py), and it carries its own fixtures — a
probe whose failure modes are untested is prose with parentheses.

WHAT IT REPLACED, AND WHAT EACH REPLACEMENT COST. The first version asked
`provider not in line` on the consumer's compose template. Three adversarial
reviews measured it certifying and missing real things, all reproduced before
the rewrite (quoted in the R2 report):

  * `performs('gitlab','postgresql') -> True` on
    `postgresql['shared_buffers'] = '256MB'` — GitLab Omnibus configuring its
    OWN bundled Postgres, not the estate's service.
  * `performs('onlyoffice','postgresql') -> True` on the `/var/lib/postgresql`
    volume of OnlyOffice's baked internal cluster.
  * `performs('grafana','redis') -> True` partly on compose.yml.j2:93, a line
    inside a multi-line `{# … #}` Jinja comment.
  * `performs('mcp_gateway','postgresql') -> (False, [])` — reported to the
    operator as "(no mention at all)" — while mcpo-config.json.j2:20 renders a
    full DSN and post.yml:12-31 runs `psql` inside the estate's own container.
    One path was read; the dependency lived in two others.
  * `{% else %}`/`{% elif %}` never popped the guard stack, so moving a live
    line into an else-branch flipped a true edge to False and the equality gate
    announced "a live dependency has silently stopped rendering" — a false RED
    phrased as an outage, on a template that renders correctly.

So the probe now asks the question the old docstring only claimed: does the
provider appear in a HOST POSITION, on a line the render can reach?

  evidence positions   `@host:`, `//host:`, `KEY: host` / `KEY=host`,
                       `{{ host_var }}`, `docker compose exec -T <container>`
  provider aliases     the compose service name AND the manifest's own
                       `domain_var` / `port_var` — Woodpecker reaches Gitea by
                       `{{ gitea_domain }}`, never by the compose hostname, and
                       a probe that only knows hostnames calls that edge false
  reachability         a full Jinja control-flow walk: nested if/elif/else,
                       inline one-line ifs evaluated at the MENTION's offset,
                       `or`-guards dead only when every disjunct rests on an
                       unknown name, `{# … #}` comments blanked
  search set           every template in the role plus tasks/{main,post}.yml

CEILING, NAMED RATHER THAN HIDDEN. In a tasks file the probe models no `when:`
guard — a task gated on a phantom flag reads as reachable. The phantom-flag
class lives in compose templates (that is where `install_redis` hides), and
those are walked in full. A tasks-file `when:` gate would need the Ansible
block structure, which is a different tool.

Offline: no docker, no network.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "state" / "manifest.yml"

#: Jinja/Ansible names that are not config variables and must not be mistaken
#: for undefined ones when reading an `{% if %}` guard.
GUARD_BUILTINS = {
    "ansible_facts", "ansible_os_family", "ansible_distribution", "ansible_system",
    "true", "false", "none", "not", "and", "or", "in", "is", "if", "else",
    "defined", "default", "bool", "string", "lower", "upper", "int", "length",
    "trim", "item", "vars", "env", "home", "machine", "map", "list", "select",
    "selectattr", "join", "startswith", "endswith", "version", "loop", "range",
    "undefined", "equalto", "regex_search", "d",
}

#: Jinja tags whose BODY is control flow, not content. Their text is blanked
#: before the host-position scan. `set`/`do` are NOT here: mcpo-config.json.j2
#: builds its PostgreSQL DSN inside a `{% set %}`, and blanking that tag is how
#: the first probe reported "(no mention at all)" about a live DSN.
_CONTROL_TAGS = {
    "if", "elif", "else", "endif", "for", "endfor", "macro", "endmacro",
    "block", "endblock", "with", "endwith", "filter", "endfilter",
    "call", "endcall", "raw", "endraw", "import", "from", "extends", "include",
}
_BLOCK_OPENERS = {"for", "macro", "block", "with", "filter", "call", "raw"}

_TAG = re.compile(r"\{%-?\s*(\w+)([^%]*?)-?%\}")
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_FULL_LINE_YAML_COMMENT = re.compile(r"^[ \t]*#[^\n]*$", re.M)


def _blank(text: str) -> str:
    """Same length, same newlines, no content — offsets and line numbers survive."""
    return re.sub(r"[^\n]", " ", text)


# ── the config layer: which identifiers a guard may name and still render ──


@functools.lru_cache(maxsize=1)
def config_layer_keys() -> frozenset[str]:
    """Every identifier a `{% if %}` may name and still be defined at render.

    WIDENED after a review measured the first version reading only
    default.config.yml + default.credentials.yml + roles/*/defaults/main.yml:
    a variable defined in roles/*/vars, group_vars, a profile, tests/config.yml
    or a `set_fact` was indistinguishable from one that exists nowhere, and the
    probe calls an unknown guard DEAD. Narrow here means false REDs on correct
    templates, which is the expensive direction.
    """
    keys: set[str] = set()
    sources = [
        REPO / "default.config.yml",
        REPO / "default.credentials.yml",
        REPO / "tests" / "config.yml",
    ]
    sources += sorted(REPO.glob("roles/*/defaults/main.yml"))
    sources += sorted(REPO.glob("roles/*/vars/*.yml"))
    sources += sorted(REPO.glob("group_vars/*.yml"))
    sources += sorted(REPO.glob("profiles/*.yml"))
    for path in sources:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([a-z_][a-z0-9_]*):", line)
            if m:
                keys.add(m.group(1))
    # set_fact keys — main.yml's three auto-enable blocks define `install_mariadb`,
    # `install_postgresql` and `redis_docker` at runtime, and a template guard
    # naming one of those is live.
    for path in [REPO / "main.yml", *sorted(REPO.glob("tasks/**/*.yml"))]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"set_fact:\s*\n((?:\s+[a-z_][a-z0-9_]*:.*\n)+)", text):
            for line in m.group(1).splitlines():
                k = re.match(r"\s+([a-z_][a-z0-9_]*):", line)
                if k:
                    keys.add(k.group(1))
    return frozenset(keys)


def guard_dead(expr: str, keys: set[str]) -> set[str]:
    """The identifiers that make this guard render to nothing — empty if live.

    An `or` is dead only when EVERY disjunct rests on an unknown name:
    `{% if phantom or real_flag %}` still renders. An `and` with any unknown
    operand IS dead, because an undefined name is falsy.
    """
    disjuncts = re.split(r"\bor\b", expr)
    unknown = []
    for d in disjuncts:
        idents = {i for i in re.findall(r"[a-z_][a-z0-9_]*", d)
                  if i not in keys and i not in GUARD_BUILTINS}
        unknown.append(idents)
    if unknown and all(u for u in unknown):
        return set().union(*unknown)
    return set()


# ── the reachability walk ─────────────────────────────────────────────────


def reachable_text(text: str, keys: set[str]) -> tuple[str, list[frozenset[str]]]:
    """Flatten a Jinja template to (searchable text, per-character dead-set).

    Character offsets and line numbers are preserved, so a mention found in the
    flattened text can be reported at its real line AND evaluated against the
    guard that lexically encloses IT — which is what makes an inline
    `{% if %}…{% endif %}` (roles/pazny.nextcloud/templates/compose.yml.j2:24)
    behave the same as the block form instead of reading as unguarded.
    """
    text = _JINJA_COMMENT.sub(lambda m: _blank(m.group(0)), text)
    text = _FULL_LINE_YAML_COMMENT.sub(lambda m: _blank(m.group(0)), text)

    stack: list[dict] = []
    flat: list[str] = []
    dead: list[frozenset[str]] = []

    def cur() -> frozenset[str]:
        acc: set[str] = set()
        for frame in stack:
            acc |= frame["dead"]
        return frozenset(acc)

    def push(segment: str) -> None:
        flat.append(segment)
        dead.extend([cur()] * len(segment))

    pos = 0
    for m in _TAG.finditer(text):
        push(text[pos:m.start()])
        kw, expr = m.group(1), m.group(2)
        if kw == "if":
            stack.append({"t": "if", "dead": guard_dead(expr, keys)})
        elif kw == "elif" and stack and stack[-1]["t"] == "if":
            stack[-1]["dead"] = guard_dead(expr, keys)
        elif kw == "else" and stack and stack[-1]["t"] == "if":
            # The else-branch of a guard whose condition names an undefined
            # variable is the branch that DOES render.
            stack[-1]["dead"] = set()
        elif kw in _BLOCK_OPENERS:
            stack.append({"t": kw, "dead": set()})
        elif kw.startswith("end") and stack:
            stack.pop()
        body = m.group(0) if kw not in _CONTROL_TAGS else _blank(m.group(0))
        push(body)
        pos = m.end()
    push(text[pos:])
    return "".join(flat), dead


def host_position_re(token: str) -> re.Pattern:
    """Where a HOST may legally appear. Everything else is a grep match.

    `@host:` / `//host:` are URL authorities; `KEY: host` / `KEY=host` an
    assignment; `{{ host_var }}` the manifest's own domain/port variable; and
    `exec -T <container>` the estate reaching into a running provider.

    A trailing `/` or `.` disqualifies the match: `image: grafana/loki` and
    `image: grafana/tempo` are IMAGE NAMESPACES, and the first draft of this
    pattern reported them as `loki → grafana` and `tempo → grafana` — two
    dependencies that do not exist, in the direction opposite to the real one.

    So does a key from `_NOT_A_HOST_KEY`: `{'db': 'paperclip'}` in
    roles/pazny.postgresql/tasks/post.yml:234 is a DATABASE NAME inside the
    provider's own CREATE-DATABASE loop, and the first draft read it as
    `postgresql → paperclip` — a provider depending on its consumer.
    """
    t = re.escape(token)
    prefix = r"(?:@|//|\{\{\s*|[:=][ \t]*[\"']?[ \t]*|exec[ \t]+-T[ \t]+)"
    return re.compile(prefix + t + r"(?![A-Za-z0-9_/.-])")


#: Key names whose VALUE is a label, never a host. Checked as a suffix of the
#: key immediately left of the `:`/`=`, case-insensitively.
_NOT_A_HOST_KEY = ("db", "database", "name", "image", "user", "username",
                   "password", "secret", "token")

_KEY_BEFORE = re.compile(r"([A-Za-z0-9_]+)[\"']?[ \t]*[:=][ \t]*[\"']?[ \t]*$")


def is_host_context(flat: str, start: int) -> bool:
    """False when the matched prefix was `KEY: ` and KEY names a label field."""
    m = _KEY_BEFORE.search(flat[max(0, start - 64):start])
    if not m:
        return True
    key = m.group(1).lower()
    return not any(key == w or key.endswith("_" + w) for w in _NOT_A_HOST_KEY)


@functools.lru_cache(maxsize=None)
def _flatten(path: Path) -> tuple[str, tuple[frozenset[str], ...]] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    flat, dead = reachable_text(raw, config_layer_keys())
    return flat, tuple(dead)


@functools.lru_cache(maxsize=1)
def provider_aliases() -> dict[str, frozenset[str]]:
    """service id → every spelling the code may legally reach it by."""
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    out: dict[str, frozenset[str]] = {}
    for svc in doc.get("services") or []:
        if not (isinstance(svc, dict) and svc.get("id")):
            continue
        sid = str(svc["id"])
        aliases = {sid, sid.replace("_", "-")}
        for key in ("domain_var", "port_var"):
            if svc.get(key):
                aliases.add(str(svc[key]))
        out[sid] = frozenset(aliases)
    return out


@functools.lru_cache(maxsize=None)
def consumer_sources(consumer: str) -> tuple[Path, ...]:
    role = REPO / f"roles/pazny.{consumer}"
    paths = sorted(p for p in role.glob("templates/*") if p.is_file())
    for rel in ("tasks/main.yml", "tasks/post.yml"):
        if (role / rel).exists():
            paths.append(role / rel)
    return tuple(paths)


@functools.lru_cache(maxsize=None)
def _performs(consumer: str, provider: str) -> tuple[bool, tuple[str, ...]]:
    """Does `roles/pazny.<consumer>` reach `service:<provider>` at render time?

    Returns (reachable, diagnostics) — diagnostics always name the file:line
    they rest on, both for a hit and for a line refused as unreachable, because
    an empty list reported as "(no mention at all)" is the one answer that
    cannot be argued with and was wrong.
    """
    aliases = provider_aliases().get(provider, frozenset({provider}))
    patterns = [(a, host_position_re(a)) for a in sorted(aliases)]
    sources = consumer_sources(consumer)
    if not sources:
        return False, (f"no role at roles/pazny.{consumer}/",)
    reachable = False
    notes: list[str] = []
    for path in sources:
        flattened = _flatten(path)
        if flattened is None:
            continue
        flat, dead = flattened
        for alias, rx in patterns:
            for m in rx.finditer(flat):
                at = m.end() - len(alias)
                if not is_host_context(flat, at):
                    continue
                lineno = flat.count("\n", 0, at) + 1
                blocked = sorted(dead[at]) if at < len(dead) else []
                rel = path.relative_to(REPO)
                if blocked:
                    notes.append(f"{rel}:{lineno} names {alias!r} but is unreachable — "
                                 f"guarded by {blocked}, which the config layer never "
                                 f"defines")
                else:
                    reachable = True
                    notes.append(f"{rel}:{lineno} reaches {alias!r}")
    return reachable, tuple(notes)


def performs(consumer: str, provider: str) -> tuple[bool, list[str]]:
    ok, notes = _performs(consumer, provider)
    return ok, list(notes)


@functools.lru_cache(maxsize=1)
def sweep() -> frozenset[tuple[str, str]]:
    """EVERY (consumer, provider) the code performs, over all manifest services.

    The completeness side of the gate used to iterate a hand seed — main.yml's
    three auto-enable blocks — so a dependency those blocks had never heard of
    was outside the derivation entirely, and `mcp_gateway → postgresql` sat
    undiscoverable behind a full DSN and a live `psql` exec. A sweep cannot
    have that blind spot: it starts from the service registry, not from one
    place the estate happens to have written the fact down.
    """
    ids = sorted(provider_aliases())
    return frozenset((c, p) for c in ids for p in ids
                     if c != p and _performs(c, p)[0])
