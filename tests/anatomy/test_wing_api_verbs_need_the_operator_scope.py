"""An operator decision over the Wing API needs a scope no agent token holds.

WHY (roadmap `wing-api-has-no-tier`, measured 2026-10-06). Upgrade apply,
migration rollback, coexistence cutover, patch apply and the inbox answer took
ANY `wing.write` bearer; librarian, surveyor and cortex-executor hold one, and
the operator bearer travels into agent runs (pulse-run-agent.sh). Tier 1 lived
only in the browser presenters. Now each such action is listed in its
presenter's `$operatorActions`, and BaseApiPresenter::requireOperator() asks for
`wing.operator` (explicit-only; NULL grants nothing) plus Tier 1 from a face-bff
person.

What runs: the verb list is DERIVED from RouterFactory + the Api presenters;
every routed write action must be either an operator verb or named below with a
reason, so a new write cannot arrive unclassified. Then the REAL presenters run
through Nette's Presenter::run over a scratch wing.db (bin/init-db.php). The
presenters are built without their constructors: an effect the gate lets through
dies on an uninitialised dependency ("reached"), so nothing leaves the process.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
API = WING / "app/Presenters/Api"
ROUTER = WING / "app/Core/RouterFactory.php"
POST_YML = REPO / "roles/pazny.wing/tasks/post.yml"
AGENTS = REPO / "files/anatomy/agents"
AUTOLOAD = WING / "vendor/autoload.php"

needs_php = pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
needs_vendor = pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")

#: The verbs the 2026-10-06 measurement named. The derived list must hold them.
KNOWN = {("Upgrades", "apply"), ("Upgrades", "applyDetached"), ("Upgrades", "queue"),
         ("Upgrades", "planChoice"), ("Migrations", "apply"), ("Migrations", "rollback"),
         ("Coexistence", "promote"), ("Coexistence", "cutover"), ("Coexistence", "cleanup"),
         ("Pulse", "runNow"), ("Admin", "halt"), ("Admin", "resume")}

#: Every other routed write, and why it is not an operator decision.
NOT_DECISIONS = {
    ("Advisories", "default"): "scan pipeline ingests an advisory record",
    ("Agents", "sessions"): "opens an agent session; the BFF path narrows to metadata.end_user below Tier 1",
    ("Components", "default"): "component inventory record",
    ("CortexExecutor", "execute"): "gated by its own three cortex axes (CortexBindingGate)",
    ("DeployTrigger", "default"): "HMAC-only from CI with branch+tag allowlists; no bearer reaches it",
    ("Events", "default"): "POST is the HMAC ingestion path; agents report through it",
    ("Gdpr", "processing"): "Article 30 register record",
    ("Gdpr", "dsar"): "DSAR register record",
    ("Gdpr", "breaches"): "breach register record (filing, not deciding)",
    ("Gitleaks", "default"): "scanner files findings",
    ("Gitleaks", "resolve"): "triage record, attributed to the bearer (follow-up: candidate operator verb)",
    ("Hub", "systems"): "hub card registration from the converge",
    ("Inbox", "questions"): "an agent ASKS; asking is not deciding",
    ("Inbox", "cancel"): "the asking agent withdraws its own question",
    ("Migrations", "authored"): "migration-author records a DRAFT; the forge MR is the gate",
    ("Migrations", "preview"): "dry-run through Bone; changes nothing",
    ("Patches", "default"): "patch catalog record",
    ("Patches", "plan"): "dry-run through Bone; changes nothing",
    ("Pentest", "targets"): "pentest record",
    ("Pentest", "areasTested"): "pentest record",
    ("Pentest", "areasPlanned"): "pentest record",
    ("Pentest", "findings"): "pentest record",
    ("Pentest", "findingUpdate"): "pentest record",
    ("Pentest", "patches"): "pentest record (legacy nested patches)",
    ("Pulse", "jobs"): "already pulse.write (minted for ansible-provisioned alone)",
    ("Pulse", "runs"): "the Pulse daemon records a run",
    ("Pulse", "runFinish"): "the Pulse daemon records a run",
    ("Remediation", "default"): "remediation queue record",
    ("Remediation", "bulkStatus"): "remediation queue record",
    ("Scan", "cycle"): "scan pipeline record",
    ("Scan", "component"): "scan pipeline record",
    ("Scan", "config"): "scan pipeline record",
    ("Scan", "rotation"): "scan pipeline record",
    ("Scan", "probeComplete"): "scan pipeline record",
    ("State", "sync"): "mirrors Bone's state into Wing's read tables",
    ("Upgrades", "plan"): "dry-run through Bone; changes nothing",
}


def _code(php: str) -> str:
    php = re.sub(r"/\*.*?\*/", "", php, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", php)


def _routes() -> list[tuple[str, str, str]]:
    return re.findall(r"\$api->addRoute\('([^']+)',\s*'(\w+):(\w+)'\)", ROUTER.read_text(encoding="utf-8"))


def _list_prop(src: str, prop: str) -> list[str]:
    m = re.search(r"protected\s+array\s+\$" + prop + r"\s*=\s*\[([^\]]*)\]", src)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


def _presenter(name: str) -> str:
    return _code((API / f"{name}Presenter.php").read_text(encoding="utf-8"))


def _routed() -> set[tuple[str, str]]:
    return {(p, a) for _, p, a in _routes()}


def _writes() -> set[tuple[str, str]]:
    out = set()
    for p, a in _routed():
        src = _presenter(p)
        for chunk in re.split(r"(?=\n\s*(?:public|private|protected)\s+(?:static\s+)?function\s)", src):
            m = re.match(r"\s*public function action(\w+)\(", chunk)
            if m and m.group(1)[0].lower() + m.group(1)[1:] == a and re.search(
                    r"'(?:POST|PUT|DELETE|PATCH)'|\['GET',\s*'HEAD'\]", chunk):
                out.add((p, a))
    return out


def operator_verbs() -> set[tuple[str, str]]:
    """(presenter, action) pairs a route reaches and a presenter declares operator-only."""
    return {(p, a) for p, a in _routed() if a in _list_prop(_presenter(p), "operatorActions")}


def test_the_derived_list_is_real_and_holds_the_measured_verbs():
    verbs = operator_verbs()
    assert verbs, "no routed action is declared in $operatorActions — the property was renamed or emptied"
    assert KNOWN <= verbs, f"measured decision verbs left out: {sorted(KNOWN - verbs)}"


def test_every_routed_write_is_classified():
    writes, ops = _writes(), operator_verbs()
    assert len(writes) > 30, f"only {len(writes)} write actions derived — the detector went blind"
    unclassified = writes - ops - set(NOT_DECISIONS)
    assert not unclassified, (
        f"write action(s) neither operator-only nor named in NOT_DECISIONS: {sorted(unclassified)}. "
        "Decide: does it write an operator decision? Then add it to the presenter's $operatorActions.")
    assert not (ops & set(NOT_DECISIONS)), "a verb is both operator-only and excused"
    stale = set(NOT_DECISIONS) - writes
    assert not stale, f"NOT_DECISIONS names actions that are no longer routed writes: {sorted(stale)}"


def test_no_operator_verb_is_public():
    for p, a in operator_verbs():
        assert a not in _list_prop(_presenter(p), "publicActions"), f"{p}:{a} skips token auth entirely"


# ── who holds the scope ─────────────────────────────────────────────────────

def _mints() -> dict[str, set[str]]:
    src = POST_YML.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"--name=([a-z0-9-]+)\n(?:(?!--name=).*\n)*?.*--scopes=([^\n]+)", src):
        name, raw = m.group(1), m.group(2)
        if "capability_scopes" in raw:
            doc = yaml.safe_load((AGENTS / name / "agent.yml").read_text(encoding="utf-8"))
            out[name] = {s for s in doc["audit"]["capability_scopes"] if s.startswith("wing.")}
        else:
            out[name] = set(raw.strip().split(","))
    return out


def test_no_agent_token_is_minted_with_the_operator_scope():
    mints = _mints()
    assert {"ansible-provisioned", "librarian", "surveyor", "cortex-executor", "face-bff"} <= set(mints), mints
    holders = sorted(n for n, s in mints.items() if "wing.operator" in s)
    assert holders == ["face-bff"], (
        f"wing.operator minted for {holders}. ansible-provisioned travels into agent runs "
        "(pulse-run-agent.sh, McpWingTool fallback) and the converge calls no operator verb.")
    for yml in AGENTS.glob("*/agent.yml"):
        scopes = (yaml.safe_load(yml.read_text(encoding="utf-8")).get("audit") or {}).get("capability_scopes") or []
        assert "wing.operator" not in scopes, f"{yml.parent.name} declares wing.operator; a derived mint would carry it"


def _tool_kam() -> dict[str, list[str]]:
    spec = importlib.util.spec_from_file_location("agent_capability", REPO / "tools/agent-capability.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.TOOL_KAM


def _route_of(path: str) -> tuple[str, str] | None:
    path = path.split("?")[0].rstrip(".,;:)`'\"/")
    for pattern, p, a in _routes():  # Nette is first-match-wins
        rx = re.escape(pattern).replace(r"\[/", "(?:/").replace(r"\]", ")?")
        rx = re.sub(r"\\<[^>]+\\>|<[^>]+>", "[^/]+", rx)
        if re.fullmatch("/?" + rx, path):
            return p, a
    return None


def test_what_agents_write_needs_no_operator_scope():
    """Measured from each writing agent's own manifest + prompts, not assumed."""
    writers = [k for k, v in _tool_kam().items() if "wing" in v]
    assert writers, "TOOL_KAM no longer names a Wing write tool"
    ops, calls = operator_verbs(), {}
    for yml in sorted(AGENTS.glob("*/agent.yml")):
        doc = yaml.safe_load(yml.read_text(encoding="utf-8"))
        tools = {t.get("id") for t in doc.get("tools") or [] if isinstance(t, dict)}
        if not tools & set(writers) and "wing.write" not in (doc.get("audit") or {}).get("capability_scopes", []):
            continue
        text = "\n".join(f.read_text(encoding="utf-8") for f in yml.parent.glob("*") if f.suffix in (".yml", ".md"))
        for path in re.findall(r"\b(?:POST|PUT|DELETE|PATCH)\s+(/api/v1/\S+)", text):
            calls.setdefault(yml.parent.name, set()).add(_route_of(path))
    assert calls, "no writing agent declares a write call — the measurement went blind"
    # An unrouted path (inspektor's POST /pentest/findings, 2026-10-07) 404s; it cannot be a verb here.
    for agent, routes in calls.items():
        assert not routes & ops, f"{agent} needs operator verb(s) {sorted(routes & ops)}"


@needs_php
def test_provision_token_refuses_the_scope_to_any_other_name(tmp_path):
    subprocess.run(["php", str(WING / "bin/init-db.php"), f"--data-dir={tmp_path}"],
                   capture_output=True, check=True, timeout=60)
    db = tmp_path / "wing.db"

    def mint(name: str) -> int:
        return subprocess.run(["php", str(WING / "bin/provision-token.php"), f"--db={db}", "--token=t-" + name,
                               f"--name={name}", "--scopes=wing.operator,wing.write"],
                              capture_output=True, timeout=60).returncode
    assert mint("librarian") == 1 and mint("ansible-provisioned") == 1
    assert mint("face-bff") == 0


# ── the presenters, run ─────────────────────────────────────────────────────

_HARNESS = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
putenv('WING_PHP_BIN=/usr/bin/true'); putenv('BONE_URL=http://127.0.0.1:9');
$pdo = new Nette\Database\Connection('sqlite:' . $argv[2]);
foreach (['write' => ['librarian', 'wing.read,wing.write'], 'legacy' => ['scout', null],
          'op' => ['converge', 'wing.operator,wing.write'],
          'bffw' => ['face-bff', 'wing.write'], 'bffo' => ['face-bff', 'wing.operator,wing.write']] as $t => [$n, $s]) {
  $pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', $t), 'name' => $n, 'scopes' => $s, 'active' => 1]);
}
$cache = new Nette\Caching\Storages\DevNullStorage;
$structure = new Nette\Database\Structure($pdo, $cache);
$db = new Nette\Database\Explorer($pdo, $structure, new Nette\Database\Conventions\DiscoveredConventions($structure), $cache);
$events = new App\Model\EventRepository($db);
$questions = new App\Model\AgentQuestionRepository($db, $events, new App\Model\NotificationRepository($db));
$box = (new ReflectionClass(App\Model\BoneClient::class))->newInstanceWithoutConstructor();
$real = [App\Model\EventRepository::class => $events, App\Model\AgentQuestionRepository::class => $questions,
         App\Model\CoexistenceRepository::class => new App\Model\CoexistenceRepository($db, $box)];
$q = $questions->ask(agentName: 'librarian', prompt: 'may I?');
$out = ['results' => []];
foreach (json_decode($argv[3], true) as $c) {
  $cls = 'App\\Presenters\\Api\\' . $c['presenter'] . 'Presenter';
  $rc = new ReflectionClass($cls);
  $p = $rc->newInstanceWithoutConstructor();   // a dependency left unset is an effect that cannot happen
  foreach ($rc->getConstructor()?->getParameters() ?? [] as $param) {
    $t = (string) $param->getType();
    if (isset($real[$t])) (new ReflectionProperty($cls, $param->getName()))->setValue($p, $real[$t]);
  }
  $p->tokenRepo = new App\Model\TokenRepository($db);
  $p->autoCanonicalize = false;
  $params = ['action' => $c['action']];
  foreach ($rc->getMethod('action' . ucfirst($c['action']))->getParameters() as $param) {
    if ($param->isOptional() && !isset($c['params'][$param->getName()])) continue;
    $params[$param->getName()] = str_replace('{q}', $q['uuid'], $c['params'][$param->getName()] ?? 'x');
  }
  $body = json_encode(str_replace('{reply_token}', $q['reply_token'], $c['body'] ?? []));
  $headers = array_filter(['authorization' => 'Bearer ' . $c['token'],
    'x-nos-user-uid' => $c['uid'] ?? null, 'x-nos-user-groups' => $c['groups'] ?? null]);
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/api'), headers: $headers,
    method: 'POST', rawBodyCallback: fn() => $body);
  $res = new Nette\Http\Response;
  $p->injectPrimary($req, $res);
  try {
    $r = $p->run(new Nette\Application\Request('Api:' . $c['presenter'], 'POST', $params));
    $out['results'][] = ['code' => $res->getCode(), 'error' => $r instanceof Nette\Application\Responses\JsonResponse ? ($r->getPayload()['error'] ?? null) : null];
  } catch (Error $e) {
    if (!str_contains($e->getMessage(), 'must not be accessed before initialization')) throw $e;
    $out['results'][] = ['code' => 'reached', 'error' => null];
  }
}
$out['planned_by'] = $pdo->fetchField('SELECT planned_by FROM coexistence_planned WHERE tag = ?', 'bff');
$out['planned_by_op'] = $pdo->fetchField('SELECT planned_by FROM coexistence_planned WHERE tag = ?', 'op');
$out['answered_by'] = $pdo->fetchField('SELECT answered_by FROM agent_questions WHERE uuid = ?', $q['uuid']);
echo json_encode($out);
"""

WHO = {
    "agent": {"token": "write"},
    "legacy_null_scope": {"token": "legacy"},
    "operator_token": {"token": "op"},
    "bff_user": {"token": "bffo", "uid": "alice", "groups": "nos-users"},
    "bff_admin": {"token": "bffo", "uid": "alice", "groups": "nos-admins"},
    "bff_admin_old_mint": {"token": "bffw", "uid": "alice", "groups": "nos-admins"},
}


def _run(tmp_path, cases: list[dict]) -> dict:
    subprocess.run(["php", str(WING / "bin/init-db.php"), f"--data-dir={tmp_path}"],
                   capture_output=True, check=True, timeout=60)
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _HARNESS, str(AUTOLOAD),
                        str(tmp_path / "wing.db"), json.dumps(cases)],
                       capture_output=True, text=True, timeout=120, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


@needs_php
@needs_vendor
def test_each_operator_verb_refuses_everyone_but_the_operator(tmp_path):
    verbs = sorted(operator_verbs() | KNOWN)  # KNOWN too: an emptied declaration cannot pass vacuously
    cases = [{"presenter": p, "action": a, **who} for p, a in verbs for who in WHO.values()]
    results = _run(tmp_path, cases)["results"]
    for i, (p, a) in enumerate(verbs):
        row = dict(zip(WHO, results[i * len(WHO):(i + 1) * len(WHO)]))
        for denied in ("agent", "legacy_null_scope", "bff_user", "bff_admin_old_mint"):
            assert row[denied]["code"] == 403, f"{p}:{a} as {denied}: {row[denied]}"
            assert "operator decision" in (row[denied]["error"] or ""), f"{p}:{a} as {denied}: {row[denied]}"
        for allowed in ("operator_token", "bff_admin"):
            assert row[allowed]["code"] not in (401, 403), f"{p}:{a} as {allowed} was refused: {row[allowed]}"


@needs_php
@needs_vendor
def test_the_record_names_the_person_not_the_token(tmp_path):
    def queue(tag, **who):
        return {"presenter": "Coexistence", "action": "queue", "params": {"service": "grafana"},
                "body": {"tag": tag}, **who}
    got = _run(tmp_path, [
        queue("bff", **WHO["bff_admin"]),
        queue("op", **WHO["operator_token"]),
        {"presenter": "Inbox", "action": "answer", "params": {"uuid": "{q}"},
         "body": {"reply_token": "{reply_token}", "answer": "yes", "answered_by": "pazny"}, **WHO["bff_admin"]},
        {"presenter": "Inbox", "action": "questions", "body": {}, **WHO["agent"]},  # agents still ask
    ])
    assert got["planned_by"] == "user:alice", got
    assert got["planned_by_op"] == "converge", got
    assert got["results"][2]["code"] == 200, got
    assert got["answered_by"] == "user:alice", "the body named someone else; the BFF person decided"
    assert got["results"][3]["code"] == 400, f"an agent asking must reach the action: {got['results'][3]}"
