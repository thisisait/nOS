"""The face<->Wing joint: one uid rule, two implementations, one fixture.

WHY. face pins `uid` (uid.ts) and Wing folds the same person's name
(CanonicalUid.php) — the rule was copied by hand, so a person could be two
users (2026-09-21: `jan.novak` vs `jan-novak`). ssot/doctrine/cross-repo-contracts.md §1:
spec + fixture + symmetric gates over the SAME bytes. This runs both the TS
(node) and the PHP (php) on files/anatomy/contracts/face-wing.fixture.json.
The appendage gate checks the joint exists; this checks it holds.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO / "files/anatomy/contracts/face-wing.yml"
FIXTURE = REPO / "files/anatomy/contracts/face-wing.fixture.json"
UID_TS = REPO / "files/anatomy/face/src/lib/security/uid.ts"
UID_PHP = REPO / "files/anatomy/wing/app/Security/CanonicalUid.php"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node runs uid.ts")
needs_php = pytest.mark.skipif(not shutil.which("php"), reason="php runs CanonicalUid.php")

_TS = """
const m = await import(process.argv[1]);
const fx = JSON.parse(await (await import('node:fs/promises')).readFile(process.argv[2], 'utf8'));
console.log(JSON.stringify({
  fold: fx.fold.map((c) => m.slugifyUid(c.in)),
  claims: fx.claims.map((c) => m.canonicalUid(c.username, c.email, c.raw_uid)),
}));
"""

_PHP = r"""
require $argv[1];
$fx = json_decode(file_get_contents($argv[2]), true);
$c = App\Security\CanonicalUid::class;
echo json_encode([
  'intl' => class_exists(Normalizer::class),
  'fold' => array_map(fn($x) => $c::fold($x['in']), $fx['fold']),
  // '' is anonymous: the face never sends it, Wing refuses it (not_canonical).
  'accepts' => array_map(fn($u) => $c::isCanonical($u),
    array_filter(array_column(array_merge($fx['fold'], $fx['claims']), 'uid'), 'strlen')),
  'refuses' => array_map(fn($u) => !$c::isCanonical($u), $fx['not_canonical']),
]);
"""


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _ts(src: pathlib.Path) -> dict:
    r = subprocess.run(["node", "--no-warnings", "--experimental-strip-types", "--input-type=module",
                        "-e", _TS, str(src), str(FIXTURE)],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _php(src: pathlib.Path) -> dict:
    r = subprocess.run(["php", "-r", _PHP, str(src), str(FIXTURE)],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def _diff(cases: list[dict], got: list[str]) -> list[str]:
    return [f"{c['case']}: want {c['uid']!r}, got {g!r}" for c, g in zip(cases, got) if c["uid"] != g]


def test_the_spec_names_this_fixture_and_these_files():
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert spec["contract_version"] == _fixture()["contract_version"]
    assert REPO / spec["fixture"] == FIXTURE
    for side in ("producer", "consumer"):
        for path in spec[side]["code"]:
            assert (REPO / path).is_file(), f"{side} names a missing file: {path}"


@needs_node
def test_face_emits_the_fixture():
    fx, out = _fixture(), _ts(UID_TS)
    bad = _diff(fx["fold"], out["fold"]) + _diff(fx["claims"], out["claims"])
    assert not bad, "uid.ts drifted from the contract:\n  " + "\n  ".join(bad)


@needs_php
def test_wing_folds_and_accepts_the_fixture():
    fx, out = _fixture(), _php(UID_PHP)
    assert out["intl"], "php lacks ext-intl: Wing would fold accented names differently (spec uid.requires)"
    bad = _diff(fx["fold"], out["fold"])
    assert not bad, "CanonicalUid.php drifted from the contract:\n  " + "\n  ".join(bad)
    assert all(out["accepts"]), "Wing refuses a uid the face emits"
    refused = dict(zip(fx["not_canonical"], out["refuses"]))
    assert all(refused.values()), f"Wing accepts a non-canonical uid: {[u for u, ok in refused.items() if not ok]}"


@needs_node
@needs_php
def test_both_sides_agree_byte_for_byte():
    assert _ts(UID_TS)["fold"] == _php(UID_PHP)["fold"]


@needs_node
@needs_php
def test_a_planted_divergence_goes_red(tmp_path):
    """Drop the diacritic strip on one side; the gate must name the cases."""
    ts = tmp_path / "uid.ts"
    ts.write_text(re.sub(r"\.replace\(/\[.-.\]/g, ''\)", "", UID_TS.read_text(encoding="utf-8")),
                  encoding="utf-8")
    assert ts.read_text(encoding="utf-8") != UID_TS.read_text(encoding="utf-8"), "plant did not apply"
    assert _diff(_fixture()["fold"], _ts(ts)["fold"]), "TS plant went unseen"
    php = tmp_path / "CanonicalUid.php"
    php.write_text(UID_PHP.read_text(encoding="utf-8").replace("$s = trim($s, '-');", ""), encoding="utf-8")
    assert _diff(_fixture()["fold"], _php(php)["fold"]), "PHP plant went unseen"
    assert _ts(ts)["fold"] != _php(UID_PHP)["fold"]


# ── The thalamus contract crate: the third implementation, same bytes ───────
# agentkit-rust-organ (ruled 2026-10-10): shell and thalamus share one Rust
# contract crate, and the face<->Wing uid rule is its first consumer.
CRATE = REPO / "files/anatomy/thalamus/contract"
needs_cargo = pytest.mark.skipif(not shutil.which("cargo"), reason="cargo runs the contract crate")


def _rust(crate: pathlib.Path, target: pathlib.Path) -> dict:
    r = subprocess.run(["cargo", "run", "--quiet", "--manifest-path", str(crate / "Cargo.toml"),
                        "--example", "uid_fixture", "--", str(FIXTURE)],
                       capture_output=True, text=True, timeout=600, check=False,
                       env={**__import__("os").environ, "CARGO_TARGET_DIR": str(target)})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_cargo
def test_the_thalamus_contract_folds_and_refuses_the_fixture(tmp_path_factory):
    fx = _fixture()
    out = _rust(CRATE, tmp_path_factory.getbasetemp() / "cargo-target")
    bad = _diff(fx["fold"], out["fold"]) + _diff(fx["claims"], out["claims"])
    assert not bad, "the thalamus contract crate drifted from the contract:\n  " + "\n  ".join(bad)
    refused = dict(zip(fx["not_canonical"], out["refuses"]))
    assert all(refused.values()), f"the crate accepts a non-canonical uid: {[u for u, ok in refused.items() if not ok]}"


@needs_cargo
def test_a_planted_divergence_in_the_crate_goes_red(tmp_path, tmp_path_factory):
    """Drop the diacritic strip in the crate; the gate must name the cases."""
    import shutil as sh
    crate = tmp_path / "contract"
    sh.copytree(CRATE, crate, ignore=sh.ignore_patterns("target"))
    src = crate / "src" / "uid.rs"
    planted = src.read_text(encoding="utf-8").replace("!is_combining_mark(*c)", "true")
    assert planted != src.read_text(encoding="utf-8"), "plant did not apply"
    src.write_text(planted, encoding="utf-8")
    out = _rust(crate, tmp_path_factory.getbasetemp() / "cargo-target")
    assert _diff(_fixture()["fold"], out["fold"]), "Rust plant went unseen"


# ── A run read carries its report (iris-subagent-reports-back) ──────────────
# GET /agent-sessions/<uuid> adds `report`: the run's newest *_report event, its body
# capped at 4 KB. The REAL presenter, built as Nette's container builds it
# (EventRepository through the constructor), over in-memory SQLite.
_CTOR = ": new App\\Presenters\\Api\\AgentSessionsPresenter($sessions);"
_CACHE = "$cache = new Nette\\Caching\\Storages\\DevNullStorage;"
_REPORT = "SURVEY-HEAD " + "a" * 5000


def _with_events(presenters: str) -> str:
    """The sessions harness with an events table: a1's report, a later non-report, b1's report."""
    assert presenters.count(_CTOR) == 1 and presenters.count(_CACHE) == 1, "the borrowed harness moved"
    rows = [("conductor_report", "a1", {"report": _REPORT, "filed_by": "runner"}),
            ("agent_session_end", "a1", {"stop_reason": "outcome_satisfied"}),
            ("conductor_report", "b1", {"report": "bob's"})]
    seed = "$pdo->query('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, type TEXT, actor_action_id TEXT, result_json TEXT)');\n"
    seed += "".join(f"$pdo->query('INSERT INTO events', ['ts' => 't', 'type' => '{t}', 'actor_action_id' => '{u}', "
                    f"'result_json' => {json.dumps(json.dumps(r))}]);\n" for t, u, r in rows)
    return (presenters.replace(_CACHE, seed + _CACHE)
            .replace(_CTOR, ": new App\\Presenters\\Api\\AgentSessionsPresenter($sessions, new App\\Model\\EventRepository($db));"))


@needs_php
def test_a_run_read_carries_its_newest_report_capped(tmp_path):
    from test_face_user_owns_its_sessions import _PRESENTERS, AUTOLOAD, _agents
    from test_face_user_owns_its_sessions import _php as _wing
    if not AUTOLOAD.exists():
        pytest.skip("wing vendor/autoload.php missing (composer install)")
    got, = _wing(_with_events(_PRESENTERS), str(AUTOLOAD), str(_agents(tmp_path)), json.dumps(
        [{"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": "a1"},
          "token": "bff-secret", "uid": "alice", "groups": "nos-users"}]))
    rep = got["body"].get("report")
    assert rep is not None, got["body"]
    assert rep["type"] == "conductor_report" and isinstance(rep["event_id"], int), rep
    assert rep["body"] == _REPORT[:4096] and rep["chars"] == len(_REPORT), "the head, capped at 4 KB, and the whole length"
