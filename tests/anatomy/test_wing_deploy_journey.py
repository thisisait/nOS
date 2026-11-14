"""One journey through Wing's role render & deploy: pazny.wing tasks, the FrankenPHP
pin, the daemon load, the Pulse catalog it registers, its contracts and code hygiene.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_a_dry_run_gathers_its_own_evidence, test_the_pulse_tag_registers_jobs,
  test_wing_frankenphp_version_pin, test_frankenphp_pin_governs_every_platform,
  test_wing_daemon_load_hardening, test_pulse_catalog_renders_every_token,
  test_wing_ingests_the_registry_this_run_wrote, test_the_wing_contract_is_current,
  test_wing_comments_cite_existing_gates, test_php_no_deprecated_curl_close,
  test_the_backend_register_compat_read.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import jinja2
import pytest
import yaml

from test_a_declared_tag_can_be_reached import _analyse

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

ROLE = REPO / "roles/pazny.wing/tasks"
WING_TASKS = ROLE / "main.yml"
WING_DIR = REPO / "files/anatomy/wing"
AUTOLOAD = REPO / "files/anatomy/wing/vendor/autoload.php"


def _flat(tasks) -> list[dict]:
    """Every task dict in a task list, recursing into block/rescue/always."""
    out = []
    for t in tasks or []:
        if isinstance(t, dict):
            out += [t] + _flat(t.get("block")) + _flat(t.get("rescue")) + _flat(t.get("always"))
    return out


# ── test_a_dry_run_gathers_its_own_evidence ─────────────────────────────────
# 2026-08-29 `--tags wing --check`: command/uri run nothing under --check, the
# empty register read as 0, and the frankenphp-version and daemon-bind refusals
# fired on a healthy host. A read gets `check_mode: false` (hidden_fees/36).

#: Modules that perform NO work under `--check` and hand back an empty result.
BLIND_IN_CHECK = {"command", "shell", "raw", "script", "uri",
                  "ansible.builtin.command", "ansible.builtin.shell",
                  "ansible.builtin.raw", "ansible.builtin.script",
                  "ansible.builtin.uri"}
DECIDERS = {"fail", "assert", "ansible.builtin.fail", "ansible.builtin.assert"}


def _dry_tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _dry_tasks(item)
    elif isinstance(node, dict):
        if any(k in node for k in ("name", "block", "when", "register")):
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _dry_tasks(node[key])


def test_no_wing_refusal_reads_a_result_a_dry_run_never_produced() -> None:
    offences = []
    for path in sorted(ROLE.rglob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not doc:
            continue
        tasks = list(_dry_tasks(doc))
        blind = {t["register"]: t.get("name", "?") for t in tasks
                 if (set(t) & BLIND_IN_CHECK) and "register" in t
                 and t.get("check_mode") is not False}
        for task in tasks:
            decider = set(task) & DECIDERS
            if not decider:
                continue
            # The DECISION only, never the `msg:` (it renders its own default).
            condition = str(task.get("when", ""))
            body = task[decider.pop()]
            if isinstance(body, dict) and "that" in body:      # assert
                condition += str(body["that"])
            for register, source in blind.items():
                if register in condition:
                    offences.append(
                        f"{path.relative_to(REPO)}: {task.get('name', '?')!r} "
                        f"decides on ${register}, filled by {source!r} which "
                        "runs nothing under --check")
    assert not offences, (
        "a dry run of this role would refuse on evidence it never gathered:\n  "
        + "\n  ".join(offences)
        + "\nAdd `check_mode: false` to the reading task — it is a read, and "
          "the alternative is a --check that invents failures.")


def test_the_two_measured_probes_still_opt_out() -> None:
    """Named individually so a reflow of the scan above cannot quietly drop the
    two cases that were actually observed failing."""
    body = (ROLE / "main.yml").read_text(encoding="utf-8")
    for marker in ("did not report the pinned", "did not bind 127.0.0.1"):
        assert marker in body, f"the {marker!r} refusal is gone — re-scope this gate"
    assert body.count("check_mode: false") >= 2, (
        "pazny.wing has fewer than two check-mode opt-outs; the frankenphp "
        "version read and the daemon health probe both need one")


# ── test_the_pulse_tag_registers_jobs ───────────────────────────────────────
# 2026-10-27: `nos --tags pulse` deployed changed job scripts but Wing kept the
# old pulse_jobs rows until `--tags wing` — the upsert sat behind an include
# tagged only wing,security. Walks the real include chain.

POST = "roles/pazny.wing/tasks/post.yml"
REGISTRATION = ("Wait for Wing API health", "Discover Pulse job catalog", "Parse Pulse job catalog",
                "Drop Pulse jobs of retired agents", "Drop Pulse jobs of services not installed",
                "Register discovered Pulse jobs")


def test_the_pulse_tag_selects_the_job_registration():
    alive = {name for where, name, tag in _analyse().alive if where == POST and tag == "pulse"}
    missing = [n for n in REGISTRATION if not any(n in a for a in alive)]
    assert not missing, f"--tags pulse never reaches {missing} in {POST}"


# ── test_wing_frankenphp_version_pin ────────────────────────────────────────
# darwin27-frankenphp-binary-compatibility (2026-06): an unpinned FrankenPHP
# drifts silently and a half-built binary leaves launchd to segfault. Pins
# frankenphp_version as a bare semver literal AND the role's --version refusal.

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _config() -> dict:
    return ni.default_config() or {}


def test_frankenphp_version_pinned_as_semver_literal():
    cfg = _config()
    assert "frankenphp_version" in cfg, (
        "frankenphp_version missing from default.config.yml — the FrankenPHP "
        "binary version must be pinned (tested on arm64_sequoia).")
    val = cfg["frankenphp_version"]
    assert isinstance(val, str) and _SEMVER.match(val), (
        f"frankenphp_version must be a MAJOR.MINOR.PATCH string literal, "
        f"got {val!r}")


def test_frankenphp_version_is_stock_jinja_safe():
    # No Jinja in the raw value: the plugin loader's {{ vars }} eager-resolve trap.
    raw = ni.default_config_text()
    m = re.search(r"^frankenphp_version:\s*(.+?)\s*$", raw, re.M)
    assert m, "frankenphp_version line not found in default.config.yml"
    literal = m.group(1)
    assert "{{" not in literal and "|" not in literal, (
        f"frankenphp_version must be a bare literal, not a Jinja expr: {literal!r}")


def test_wing_role_validates_frankenphp_version():
    tasks = WING_TASKS.read_text()
    assert "--version" in tasks, (
        "pazny.wing must read `frankenphp --version` as a post-install preflight.")
    assert "frankenphp_version" in tasks, (
        "pazny.wing version preflight must reference frankenphp_version to gate "
        "the landed binary against the pinned version.")
    assert re.search(r"ansible\.builtin\.fail", tasks), (
        "pazny.wing must `fail` on a frankenphp version mismatch.")


# ── test_frankenphp_pin_governs_every_platform ──────────────────────────────
# thisisait/nOS#48: macOS installed the Homebrew tap's latest (no version
# selector), so every upstream release broke every FRESH macOS install at the
# version refusal. One pinned, checksummed fetch, RENDERED per platform here.

# (ansible_os_family, ansible_architecture, the release asset it must fetch)
PLATFORMS = [
    ("Darwin", "arm64", "frankenphp-mac-arm64"),
    ("Darwin", "x86_64", "frankenphp-mac-x86_64"),
    ("Debian", "aarch64", "frankenphp-linux-aarch64"),
    ("Debian", "x86_64", "frankenphp-linux-x86_64"),
]


def _pin_tasks():
    return _flat(yaml.safe_load(WING_TASKS.read_text(encoding="utf-8")))


def _frankenphp_fetches():
    return [
        t for t in _pin_tasks()
        if "frankenphp" in str((t.get("ansible.builtin.get_url") or t.get("get_url") or {}).get("url", ""))
    ]


def _render(expr: str, **ctx) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(expr).render(**ctx)


def test_no_homebrew_task_installs_a_frankenphp_formula():
    offenders = []
    for t in _pin_tasks():
        mod = t.get("community.general.homebrew") or t.get("homebrew")
        if not isinstance(mod, dict):
            continue
        names = mod.get("name")
        names = names if isinstance(names, list) else [names]
        if any(str(n).split("/")[-1] == "frankenphp" for n in names):
            offenders.append(t.get("name"))
    assert not offenders, (
        f"{offenders}: a Homebrew frankenphp formula has no version selector — "
        "it lands the tap's latest, not frankenphp_version (#48)"
    )


def test_one_fetch_serves_every_platform():
    fetches = _frankenphp_fetches()
    assert len(fetches) == 1, f"expected ONE frankenphp release fetch, found {len(fetches)}"
    when = fetches[0].get("when")
    assert "Darwin" not in str(when or ""), (
        f"the frankenphp fetch is gated on the OS ({when!r}); macOS must take "
        "the same pinned path as Linux"
    )


@pytest.mark.parametrize("family,arch,asset", PLATFORMS)
def test_fetch_renders_the_pinned_asset_with_a_checksum(family, arch, asset):
    cfg = yaml.safe_load(ni.default_config_text())
    mod = _frankenphp_fetches()[0].get("ansible.builtin.get_url") or _frankenphp_fetches()[0]["get_url"]
    ctx = {
        "ansible_os_family": family,
        "ansible_architecture": arch,
        "frankenphp_version": cfg["frankenphp_version"],
        "frankenphp_checksums": cfg.get("frankenphp_checksums", {}),
    }
    task = _frankenphp_fetches()[0]
    for key, expr in (task.get("vars") or {}).items():  # task vars, in order
        ctx[key] = _render(str(expr), **ctx).strip()
    url = _render(mod["url"], **ctx)
    assert url == (
        # our attested mirror, not upstream (operator ruling 2026-11-14, tools/frankenphp-repin.py --mirror)
        f"https://github.com/thisisait/nOS/releases/download/"
        f"mirror-frankenphp-v{cfg['frankenphp_version']}/{asset}"
    ), url
    checksum = _render(mod["checksum"], **ctx)
    assert checksum.startswith("sha256:") and len(checksum) == len("sha256:") + 64, (
        f"{family}/{arch}: no recorded sha256 for {asset} (got {checksum!r})"
    )


# ── test_wing_daemon_load_hardening ─────────────────────────────────────────
# A17 (2026-05-20): bootstrap task and "Restart wing" handler both swallowed
# errors via `failed_when: false`; wing.pazny.eu was 502 on a green run
# (2026-05-18). Both now probe, diagnose and exit non-zero. A18: always-sweep.

def test_wing_role_bootstrap_carries_health_probe():
    src = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
    assert "Wait for daemon to bind" in src
    assert "ansible.builtin.uri" in src
    probe_block_start = src.find("Wait for daemon to bind")
    probe_block_end = src.find("\n- name:", probe_block_start + 1)
    probe = src[probe_block_start:probe_block_end]
    m = re.search(r"retries:\s*(\d+)", probe)
    assert m and int(m.group(1)) >= 10, "probe must retry ≥ 10 times"


def test_wing_role_fails_loud_on_dead_daemon():
    src = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
    assert "Fail-loud if daemon never came up" in src
    assert "ansible.builtin.fail" in src
    assert "Diagnose dead daemon" in src
    assert "launchctl print" in src


def test_main_yml_restart_wing_handler_probes_after_bootstrap():
    src = (REPO / "main.yml").read_text()
    start = src.find("- name: Restart wing")
    assert start > 0
    end = src.find("\n    - name:", start + 10)
    handler = src[start:end]
    assert "curl -sS" in handler
    assert "code=$(curl" in handler or "code=$( curl" in handler or 'code=$(curl' in handler
    assert "for i in $(seq 1 20)" in handler
    assert "exit 1" in handler
    assert "launchctl print" in handler
    assert "launchd.err.log" in handler


def test_main_yml_preflight_loads_all_anatomy_daemons():
    """A18 (2026-05-23): a partial-tag run skips the wing role, so an unloaded
    launchd job stayed down forever. The always-tagged pre-task bootstraps every
    unloaded {wing,bone,pulse} plist, Darwin only, no-op without a plist."""
    src = (REPO / "main.yml").read_text()
    start = src.find("Ensure anatomy daemons (Wing/Bone/Pulse) loaded")
    assert start > 0, "anatomy-daemon sweep pre-task missing from main.yml"
    end = src.find("\n  environment:", start + 10)
    task = src[start:end]
    assert "tags: ['always']" in task, \
        "anatomy-daemon sweep must carry tags:['always'] so partial-tag runs still execute it"
    assert "{{ wing_launchd_label" in task and "{{ bone_launchd_label" in task and "{{ pulse_launchd_label" in task, \
        "sweep must iterate all three anatomy daemons (wing/bone/pulse)"
    assert "ansible_os_family == 'Darwin'" in task, \
        "sweep must be gated on Darwin (no Linux launchd)"
    assert "launchctl print" in task and "launchctl bootstrap" in task, \
        "sweep must use the check-then-bootstrap pattern"
    assert "no-plist" in task or "! -f" in task, \
        "sweep must skip gracefully when plist file doesn't exist yet"
    # 2026-05-23 crash: the post-loop aggregate does not exist mid-loop.
    assert "_anatomy_daemons_sweep.results" not in task, \
        "changed_when must use per-iteration `stdout`, not the post-loop aggregate"
    assert "'ok:bootstrapped:' in (stdout" in task, \
        "changed_when must inspect per-iteration stdout"


def test_main_yml_restart_wing_handler_dropped_silent_failure_flag():
    """The handler MUST NOT carry `failed_when: false` (comments may mention it)."""
    src = (REPO / "main.yml").read_text()
    start = src.find("- name: Restart wing")
    end = src.find("\n    - name:", start + 10)
    handler = src[start:end]
    for line in handler.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.match(r"^failed_when\s*:\s*false\s*$", stripped), (
            "Restart wing handler still has `failed_when: false` — A17 "
            "surfaces dead daemons via non-zero exit; this flag would "
            "hide that signal"
        )


# ── test_pulse_catalog_renders_every_token ──────────────────────────────────
# 2026-08-01: `{{ backup_verify_command }}` (a var that never existed) passed the
# catalog's literal str.replace verbatim; Wing 400'd mid-converge after 80
# changes. The allowlist gate had been taught the answer. Runs the real script.

CATALOG = REPO / "files" / "anatomy" / "scripts" / "discover-pulse-catalog.py"
POST_YML = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"

TOKEN = re.compile(r"\{\{.*?\}\}")


def _catalog() -> list[dict]:
    """The catalog exactly as post.yml produces it; only NOS_PLAYBOOK_DIR set, so
    an unmapped token keeps its braces while a mapped-but-empty one renders ''."""
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO)}
    out = subprocess.run(
        ["python3", str(CATALOG)], capture_output=True, text=True, env=env, check=True
    ).stdout
    return json.loads(out)


def _unrendered(value) -> list[str]:
    if isinstance(value, str):
        return TOKEN.findall(value)
    if isinstance(value, list):
        return [t for v in value for t in _unrendered(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _unrendered(v)]
    return []


def test_the_catalog_is_not_empty():
    """Guard the guard — an empty catalog passes every assertion below."""
    assert len(_catalog()) > 5, "catalog produced almost nothing; discovery is broken"


def test_no_job_carries_an_unrendered_token():
    offenders = []
    for item in _catalog():
        job = item.get("job", {})
        for field in ("command", "args", "env", "schedule", "runner"):
            for tok in _unrendered(job.get(field)):
                offenders.append(f"{item.get('plugin_name')}:{job.get('name')} {field} -> {tok}")
    assert not offenders, (
        "these reach Wing verbatim and are rejected with a bare 400 mid-converge. "
        "The catalog does a literal str.replace, so an unknown token is silently "
        "passed through — add it to discover-pulse-catalog.py `_build_substitutions` "
        "AND feed its NOS_* env var from roles/pazny.wing/tasks/post.yml:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


def test_every_mapped_token_is_actually_fed_by_the_playbook():
    """A mapped token whose env var nobody sets renders '' — Wing 400s just the
    same, with no clue which token was to blame."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_pulse_catalog", CATALOG)
    mod = importlib.util.module_from_spec(spec)
    os.environ.setdefault("NOS_PLAYBOOK_DIR", str(REPO))
    spec.loader.exec_module(mod)

    src = CATALOG.read_text()
    post = POST_YML.read_text()
    wanted = set(re.findall(r'_env\("(NOS_[A-Z0-9_]+)"\)', src))
    missing = sorted(v for v in wanted if f"{v}:" not in post)
    assert not missing, (
        "the catalog substitutes these, but pazny.wing/tasks/post.yml never "
        "sets them — they render to '' and the failure gives no name:\n  "
        + "\n  ".join(missing)
    )


# ── test_wing_ingests_the_registry_this_run_wrote ───────────────────────────
# 2026-11-02, Linux host re-tenanted box.dev.local -> mini.local: Wing ingested
# service-registry.json four minutes BEFORE this run rendered it; every url kept
# the old tenant and six answering services read down.

INGEST = "bin/ingest-registry.php"
RENDER = "service-registry.json.j2"


def _task_lists() -> dict[str, list[dict]]:
    out = {}
    for root in ("roles", "tasks"):
        for p in (REPO / root).rglob("*.yml"):
            if "/tasks/" in f"/{p.relative_to(REPO)}" or root == "tasks":
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(doc, list):
                    out[str(p.relative_to(REPO))] = _flat(doc)
    return out


def _body(t: dict) -> str:
    return json.dumps({k: v for k, v in t.items() if k not in ("name", "block", "rescue", "always")})


def test_every_ingest_follows_a_render() -> None:
    lists = _task_lists()
    ingesting = {f: ts for f, ts in lists.items() if any(INGEST in _body(t) for t in ts)}
    bad = []
    for f, ts in ingesting.items():
        rendered = False
        for t in ts:
            rendered = rendered or RENDER in _body(t)
            if INGEST in _body(t) and not rendered:
                bad.append(f)
    assert not bad, f"{bad} run {INGEST} before rendering the registry: they ingest the last run's file"
    assert "tasks/service-registry.yml" in ingesting, "the registry render no longer hands Wing its result"


# ── test_the_wing_contract_is_current ───────────────────────────────────────
# 2026-10-25: two branches hand-edited wing.openapi.yml; local lanes green, dev
# CI red twice on "Contracts drift check". Same scripts as CI, checked where the
# edit is made. Fix a red in the exporter or presenter docblock, never the YAML.

CONTRACTS = REPO / "files/anatomy/contracts"
EXPORTS = [("export-openapi.php", "wing.openapi.yml"), ("export-schema.php", "wing.db-schema.sql")]


@pytest.mark.skipif(not shutil.which("php"), reason="php runs Wing's exporters")
@pytest.mark.parametrize("script,artifact", EXPORTS)
def test_the_committed_artifact_is_what_the_exporter_prints(tmp_path, script, artifact):
    out = tmp_path / artifact
    r = subprocess.run(["php", str(WING_DIR / "bin" / script), f"--output={out}"],
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.read_text(encoding="utf-8") == (CONTRACTS / artifact).read_text(encoding="utf-8"), (
        f"{artifact} drifted from bin/{script}: regenerate with "
        f"`php files/anatomy/wing/bin/{script} --output=files/anatomy/contracts/{artifact}` "
        "and teach the exporter or the presenter docblock what the hand edit wanted")


# ── test_wing_comments_cite_existing_gates ──────────────────────────────────
# RBAC audit 2026-10-21: BasePresenter::requireSuperAdmin cited
# `test_security_admin_gate_unchanged`, which never existed. A reader who trusts
# the comment trusts a gate nobody runs.

WING_APP = REPO / "files/anatomy/wing/app"
_COMMENT = re.compile(r"^\s*(?:\*|//|/\*|#)")
_CITE = re.compile(r"\btest_[a-z0-9_]+(?:\.py)?")
# Dead citations in files this gate's row does not own; once fixed, the entry fails.
_KNOWN_DEAD: set[tuple[str, str]] = set()


def _known() -> set[str]:
    names: set[str] = set()
    for py in list((REPO / "tests").rglob("test_*.py")) + list((REPO / "files").rglob("test_*.py")):
        names.add(py.stem)
        names.update(re.findall(r"^\s*def (test_\w+)", py.read_text(encoding="utf-8", errors="replace"), re.M))
    return names


def _dead() -> set[tuple[str, str, int]]:
    known = _known()
    out = set()
    for php in sorted(WING_APP.rglob("*.php")):
        for no, line in enumerate(php.read_text(encoding="utf-8").splitlines(), 1):
            if _COMMENT.match(line):
                for cite in _CITE.findall(line):
                    if cite.removesuffix(".py") not in known:
                        out.add((str(php.relative_to(REPO)), cite, no))
    return out


def test_every_cited_gate_exists() -> None:
    dead = sorted(d for d in _dead() if d[:2] not in _KNOWN_DEAD)
    assert not dead, "Wing comments cite gates that do not exist:\n" + "\n".join(f"{p}:{n}: {c}" for p, c, n in dead)


def test_known_dead_entries_are_still_dead() -> None:
    still = {d[:2] for d in _dead()}
    fixed = _KNOWN_DEAD - still
    assert not fixed, f"fixed — delete from _KNOWN_DEAD: {sorted(fixed)}"


# ── test_php_no_deprecated_curl_close ───────────────────────────────────────
# PHP 8.5 deprecates curl_close(); FrankenPHP surfaces E_DEPRECATED as a 500.
# 2026-05-17 sweep of 9 files, then 2026-05-18 AuthentikClient.php +
# dispatch-notifications.php slipped through and broke /users on the first run.

WING_PHP_ROOTS = [
    REPO / "files/anatomy/wing/app",
    REPO / "files/anatomy/wing/bin",
]


def test_no_curl_close_calls_in_wing_php():
    offenders: list[tuple[str, int, str]] = []
    for root in WING_PHP_ROOTS:
        if not root.is_dir():
            continue
        for php in root.rglob("*.php"):
            if "/vendor/" in str(php):
                continue
            for line_no, line in enumerate(php.read_text().splitlines(), 1):
                if "curl_close(" not in line:
                    continue
                stripped = line.lstrip()
                if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("#"):
                    continue
                if re.match(r"^\s*\*", line):
                    continue
                offenders.append((
                    str(php.relative_to(REPO)),
                    line_no,
                    line.strip(),
                ))
    assert not offenders, (
        "curl_close() calls remain in Wing PHP (PHP 8.5 deprecated → "
        f"FrankenPHP 500). Remove and replace with `unset($ch);` or let "
        f"$ch fall out of scope:\n"
        + "\n".join(f"  {f}:{ln}  {code}" for f, ln, code in offenders)
    )


# ── test_the_backend_register_compat_read ───────────────────────────────────
# repo-body-plan I-11 (2026-10-07): the register moved to state/habitat/; a
# missing file reads as an EMPTY register, not an error. Drop the old-path case
# when the compat read goes, after every host's `--tags wing` converge.

PROBE = (
    "require $argv[1]; echo json_encode(array_keys("
    "App\\AgentKit\\LLMClient\\BindingResolver::readRegistry()));"
)


def _rows(root: pathlib.Path) -> list[str]:
    php = shutil.which("php")
    out = subprocess.run([php, "-r", PROBE, str(AUTOLOAD)], capture_output=True, text=True,
                         timeout=60, env={"NOS_REPO_ROOT": str(root), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-500:]
    return json.loads(out.stdout)


@pytest.fixture
def register_text():
    if shutil.which("php") is None or not AUTOLOAD.is_file():
        pytest.skip("php or wing vendor/autoload.php missing — composer install in files/anatomy/wing")
    return (REPO / "state/habitat/llm-backends.yml").read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", ["state/habitat/llm-backends.yml", "state/llm-backends.yml"])
def test_the_register_is_found(tmp_path, register_text, rel):
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(register_text)
    assert "anthropic" in _rows(tmp_path)


def test_no_register_is_empty_not_a_crash(tmp_path, register_text):
    assert _rows(tmp_path) == []
