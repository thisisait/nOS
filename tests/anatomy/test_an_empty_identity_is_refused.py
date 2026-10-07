"""A missing identity is refused; it never becomes a person called "operator".

WHY (roadmap `person-disappears-at-the-api`, measured 2026-10-06). Eight browser
decision paths wrote `X-Authentik-Username ?? 'operator'` (or 'unknown', or
`getUser()->getId() ?: 'operator'`) into the ledger: Admin halt/resume,
Coexistence cancel, Migrations reject, four Upgrades verbs, Agents kill, Users
invites. Inbox:answer refused instead. Now every presenter names its person
through BasePresenter::requireActor(), which refuses (401) rather than invent one.

Said plainly so a green run is not over-read: the tier gate (requireTier /
requireSuperAdmin) already refused an empty identity before any of those lines
ran, so the defaults were latent, not live — the behavioural half below was
green before the fix too. The red half is requireActor itself and the rule
that no presenter reads the person any other way.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
PRESENTERS = WING / "app/Presenters"
ROUTER = WING / "app/Core/RouterFactory.php"
AUTOLOAD = WING / "vendor/autoload.php"

needs_php = pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing")
needs_vendor = pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor/autoload.php missing (composer install)")

#: The paths the measurement named; the derived list must hold them.
KNOWN = {("Admin", "halt"), ("Admin", "resume"), ("Coexistence", "cancel"), ("Migrations", "markRejected"),
         ("Upgrades", "queueUpgrade"), ("Upgrades", "planChoice"), ("Upgrades", "cancelPlanned"),
         ("Upgrades", "promoteToMigration"), ("Agents", "kill"), ("Inbox", "answer")}


def _code(php: str) -> str:
    php = re.sub(r"/\*.*?\*/", "", php, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", php)


def decision_actions() -> list[tuple[str, str]]:
    """Routed browser actions that change state (they call requirePostMethod)."""
    routed = set(re.findall(r"\$router->addRoute\('[^']+',\s*'(\w+):(\w+)'\)", ROUTER.read_text(encoding="utf-8")))
    out = set()
    for p, a in routed:
        src = _code((PRESENTERS / f"{p}Presenter.php").read_text(encoding="utf-8"))
        for chunk in re.split(r"(?=\n\s*(?:public|private|protected)\s+(?:static\s+)?function\s)", src):
            m = re.match(r"\s*public function action(\w+)\(", chunk)
            if m and m.group(1)[0].lower() + m.group(1)[1:] == a and "requirePostMethod()" in chunk:
                out.add((p, a))
    return sorted(out)


def test_the_derived_list_holds_the_measured_paths():
    got = set(decision_actions())
    assert KNOWN <= got, f"derivation lost: {sorted(KNOWN - got)}"


def test_no_presenter_reads_the_person_around_require_actor():
    """One reader of the person, so one place decides what an empty one means."""
    offenders = []
    for f in sorted(PRESENTERS.glob("*Presenter.php")):
        if f.name == "BasePresenter.php":
            continue
        code = _code(f.read_text(encoding="utf-8"))
        for needle in ("X-Authentik-Username", "getUser()->getId()"):
            if needle in code:
                offenders.append(f"{f.name}: {needle}")
    assert not offenders, (
        "browser presenter(s) read the forward-auth person directly; route it through "
        f"BasePresenter::requireActor(), which refuses instead of defaulting: {offenders}")


_HARNESS = r"""
$composer = require $argv[1];
$home = dirname(realpath($argv[1]), 2);
spl_autoload_register(function ($c) use ($composer, $home) {
  $own = getcwd() . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
  $f = realpath((string) $composer->findFile($c));
  if (str_starts_with($c, 'App\\') && is_file($own)) require $own;
  elseif ($f && str_starts_with($f, $home . '/app/')) require getcwd() . substr($f, strlen($home));
}, prepend: true);
putenv('NOS_WING_TRACING=0'); putenv('WING_EDGE_TOKEN='); putenv('BONE_URL=http://127.0.0.1:9');
function outcome(callable $f): array {
  try { $v = $f(); return ['code' => 'returned', 'value' => is_string($v) ? $v : null]; }
  catch (Nette\Application\BadRequestException $e) { return ['code' => $e->getHttpCode(), 'msg' => $e->getMessage()]; }
  catch (Error $e) {
    if (str_contains($e->getMessage(), 'must not be accessed before initialization')) return ['code' => 'reached'];
    return ['code' => 'error', 'msg' => $e->getMessage()];
  }
  catch (Throwable $e) { return ['code' => get_class($e), 'msg' => $e->getMessage()]; }
}
function presenter(string $name, array $headers): array {
  $cls = 'App\\Presenters\\' . $name . 'Presenter';
  $p = (new ReflectionClass($cls))->newInstanceWithoutConstructor();  // an unset dependency = no record
  $p->autoCanonicalize = false;
  $req = new Nette\Http\Request(new Nette\Http\UrlScript('http://wing/'), headers: $headers, method: 'POST');
  $p->injectPrimary($req, new Nette\Http\Response, user: new Nette\Security\User(new App\Security\ForwardAuthUserStorage($req)));
  return [$p, $cls];
}
$tier1 = ['x-authentik-username' => 'akadmin', 'x-authentik-groups' => 'nos-admins'];
$out = ['actions' => [], 'helper' => []];
foreach (json_decode($argv[2], true) as [$name, $action]) {
  $row = [];
  foreach (['none' => [], 'tier1' => $tier1] as $who => $h) {
    [$p, $cls] = presenter($name, $h);
    $params = ['action' => $action];
    foreach ((new ReflectionMethod($cls, 'action' . ucfirst($action)))->getParameters() as $param) {
      if (!$param->isOptional()) $params[$param->getName()] = 'x';
    }
    $row[$who] = outcome(fn() => $p->run(new Nette\Application\Request($name, 'POST', $params)));
  }
  $out['actions'][] = $row;
}
foreach (['none' => [], 'groups_only' => ['x-authentik-groups' => 'nos-admins'], 'tier1' => $tier1] as $who => $h) {
  [$p] = presenter('Admin', $h);
  $out['helper'][$who] = outcome(Closure::bind(fn() => $this->requireActor(), $p, $p));
}
echo json_encode($out);
"""


def _run() -> dict:
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _HARNESS, str(AUTOLOAD),
                        json.dumps(decision_actions())],
                       capture_output=True, text=True, timeout=120, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


@needs_php
@needs_vendor
def test_no_identity_no_record():
    got = _run()
    for (p, a), row in zip(decision_actions(), got["actions"]):
        assert row["none"]["code"] in (401, 403), f"{p}:{a} with no identity: {row['none']}"
        # Control: the harness can get past the gate, so the refusal above is the gate's.
        assert row["tier1"]["code"] not in (401, 403) or "CSRF" in row["tier1"].get("msg", ""), \
            f"{p}:{a} refused a Tier-1 identity: {row['tier1']}"


@needs_php
@needs_vendor
def test_require_actor_refuses_rather_than_invents():
    got = _run()
    assert got["helper"]["none"]["code"] == 401, got["helper"]
    assert got["helper"]["groups_only"]["code"] == 401, "groups without a username are not a person"
    assert got["helper"]["tier1"] == {"code": "returned", "value": "akadmin"}, got["helper"]
