"""Anatomy gate — the cortex organ's role/plugin/manifest contract (P-4b).

The organ's daemon code has its own vitest + Playwright suites (CI `cortex`
job); what THIS shim pins is the Ansible wiring around it — the part nothing
else executes until a converge:

  1. the role's shipped files exist (a deleted template is a crash at converge);
  2. the plist embeds the fail-closed token pair and only loopback semantics;
  3. the credentials follow the {{ global_password_prefix }}_pw_* pattern;
  4. the manifest row is loopback-only: cortex MUST stay in traefik_skip_ids —
     removing it silently derives a public route for a daemon whose auth model
     assumes there is none (design §5);
  5. main.yml imports the role gated on install_cortex with the cortex tag;
  6. the plugin manifest validates against the loader schema and deliberately
     carries NO authentik block and NO pulse jobs (C2 scope);
  7. the vendored package-lock.json stays lockfileVersion 3 (npm 10 compatible)
     — npm 11 writes locks npm 10 rejects, which has broken KEAP CI three times.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.cortex"
ORGAN = REPO / "files" / "anatomy" / "cortex"
PLUGIN = REPO / "files" / "anatomy" / "plugins" / "cortex-base" / "plugin.yml"


def test_role_files_present():
    for p in [
        ROLE / "defaults" / "main.yml",
        ROLE / "tasks" / "main.yml",
        ROLE / "templates" / "cortex.plist.j2",
        ROLE / "handlers" / "main.yml",
        ROLE / "meta" / "main.yml",
        ORGAN / "package.json",
        ORGAN / "package-lock.json",
        ORGAN / "server" / "index.ts",
        ORGAN / "knowledge" / "onto1-conformance.mjs",
    ]:
        assert p.exists(), f"cortex contract file missing: {p.relative_to(REPO)}"


def test_plist_embeds_both_tokens_and_no_bind_override():
    plist = (ROLE / "templates" / "cortex.plist.j2").read_text()
    # Fail-closed rule: both tokens provisioned, or the surface 503s. The plist
    # must template BOTH; an operator with only one configured is a defect the
    # daemon reports, not one the template hides.
    assert "CORTEX_TOKEN_RO" in plist and "cortex_ro_token" in plist
    assert "CORTEX_TOKEN_RW" in plist and "cortex_rw_token" in plist
    # The daemon defaults to 127.0.0.1; the role must not template a bind host
    # override — a public bind is an explicit code decision, never a var.
    # (Key-form check: the template may MENTION these names in comments.)
    assert "<key>CORTEX_BIND_HOST</key>" not in plist
    # Materialisation is a converge act (role task), never a boot act.
    assert "<key>CORTEX_MATERIALISE_ON_BOOT</key>" not in plist


def test_plist_rendered_mode_0600():
    tasks = (ROLE / "tasks" / "main.yml").read_text()
    render = re.search(r"cortex\.plist\.j2.*?mode: '(\d+)'", tasks, re.S)
    assert render, "plist render task (with mode:) not found in tasks/main.yml"
    assert render.group(1) == "0600", "plist embeds bearer tokens — must be 0600"


def test_credentials_follow_prefix_pattern():
    creds = (REPO / "default.credentials.yml").read_text()
    assert 'cortex_ro_token: "{{ global_password_prefix }}_pw_cortex_ro"' in creds
    assert 'cortex_rw_token: "{{ global_password_prefix }}_pw_cortex_rw"' in creds


def test_manifest_row_is_loopback_only():
    manifest = yaml.safe_load((REPO / "state" / "manifest.yml").read_text())
    rows = [s for s in manifest["services"] if s.get("id") == "cortex"]
    assert len(rows) == 1, "exactly one cortex row in state/manifest.yml"
    row = rows[0]
    assert row["install_flag"] == "install_cortex"
    assert row["launchd_label"] == "eu.thisisait.nos.cortex"
    assert row["port_var"] == "cortex_port"

    traefik_vars = yaml.safe_load(
        (REPO / "roles" / "pazny.traefik" / "vars" / "main.yml").read_text()
    )
    assert "cortex" in traefik_vars.get("traefik_skip_ids", []), (
        "cortex left traefik_skip_ids — that silently derives a public route "
        "for a loopback-auth daemon (design §5: pure loopback default)"
    )


def test_main_yml_imports_role_gated_and_tagged():
    main = (REPO / "main.yml").read_text()
    block = re.search(
        r"name: pazny\.cortex\n(.*?)tags: \[([^\]]*)\]", main, re.S
    )
    assert block, "pazny.cortex import not found in main.yml"
    assert "install_cortex" in block.group(1), "import must be gated on install_cortex"
    assert "'cortex'" in block.group(2), "--tags cortex must reach the role"


def test_plugin_validates_and_stays_loopback_pure():
    sys.path.insert(0, str(REPO / "files" / "anatomy"))
    from module_utils import load_plugins  # noqa: PLC0415

    schema = json.loads((REPO / "state" / "schema" / "plugin.schema.json").read_text())
    manifest = yaml.safe_load(PLUGIN.read_text())
    assert load_plugins.validate_manifest(manifest, schema) == []
    assert manifest["_NOS_PLUGIN"] == "cortex-base"
    assert manifest["requires"]["feature_flag"] == "install_cortex"
    # Deliberate absence — presence is scope creep, not progress: no route ⇒ no
    # authentik provider (§5).
    assert "authentik" not in manifest, "cortex-base must not register an Authentik provider"

    # The pulse half of this gate used to read "no pulse job before C2 (no embed
    # surface exists)". That premise was spent by S2
    # (docs/plans/cortex-corpus-parallel.md): the daemon now serves
    # /agent/v1/embeddings{,/pending} and /ingest/v1/capture. Rather than delete
    # the assertion, it is narrowed to what still has to be true — because the
    # thing worth preventing was never "a job", it was a job on this plugin
    # QUIETLY BECOMING A WRITER.
    #
    # The two FEEDERS stay on keap-base and fan out (one job, N targets,
    # incumbent first). cortex-base owns exactly one job: the agreement harness,
    # which reads both corpora over /agent/v1 and writes to neither.
    jobs = (manifest.get("pulse") or {}).get("jobs") or []
    assert sorted(j["name"] for j in jobs) == ["cortex-corpus-diff", "cortex-fs-sync"], (
        "cortex-base owns exactly two pulse jobs — the organ's OWN mirror pass and the "
        "read-only agreement harness. The consolidator and embed feeders belong on "
        "keap-base as FAN-OUT jobs: duplicating them here would sweep the sources twice "
        "and give the shadow its own schedule to drift on."
    )
    by_name = {j["name"]: j for j in jobs}
    diff_env = by_name["cortex-corpus-diff"].get("env") or {}
    # RO tokens only. A harness holding a write token is one edit away from
    # being a repair tool, and a measurement that can fix what it measures
    # stops being a measurement.
    assert not [k for k in diff_env if k.endswith(("_RW", "_CAPTURE"))], (
        f"the diff harness must hold read-only tokens only, got {sorted(diff_env)}"
    )


def test_something_actually_triggers_the_organs_mirror_pass():
    """The pass has to be CAUSED by something. It was not.

    `cortex_fs_sync_interval_s: 0` disables the in-daemon timer on purpose (the
    pass is a decision, and §5.3's halt needs something haltable) — and nothing
    made the decision: no interval, no job POSTing /agent/v1/fs/sync, and a role
    that restarts the daemon only when the plist template changes. The organ's
    ONLY pass was its boot pass, so its mirror froze at the last build-changing
    converge while KEAP re-walked every 300 s. Every file created since then read
    as `only_in_keap` over a CLEAN (just old) pass, the harness blamed the
    organ's reader nightly, and the 3-night agreement clock could never advance.

    Three things must therefore hold together, and a comment asserting any of
    them is not one of the three."""
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    manifest = yaml.safe_load(PLUGIN.read_text())
    jobs = {j["name"]: j for j in (manifest.get("pulse") or {}).get("jobs") or []}
    tasks = (ROLE / "tasks" / "main.yml").read_text()

    # 1. the nightly job exists, runs the trigger, and holds a token that can
    #    actually cause a pass (a pass WRITES; an ro token would 401 forever).
    assert "cortex-fs-sync" in jobs, (
        "with cortex_fs_sync_interval_s at 0 and no Pulse job, the organ's only pass "
        "is its boot pass — the mirror freezes at the last converge that changed the build"
    )
    job = jobs["cortex-fs-sync"]
    assert job["command"].endswith("files/anatomy/scripts/cortex-fs-sync.py")
    assert (REPO / "files" / "anatomy" / "scripts" / "cortex-fs-sync.py").exists()
    assert "CORTEX_AGENT_TOKEN_RW" in (job.get("env") or {}), (
        "a mirror pass writes the corpus; an ro token makes this job a nightly 401"
    )

    # 2. it lands BEFORE the harness reads both corpora, or the diff measures a
    #    pass that has not happened yet.
    def minute_of(spec: str) -> int:
        m, h = spec.split()[0], spec.split()[1]
        return int(h) * 60 + int(m)

    assert minute_of(job["schedule"]) < minute_of(jobs["cortex-corpus-diff"]["schedule"]), (
        "the mirror pass must run before the agreement harness reads it"
    )

    # 3. the converge kicks a pass too — a converge that publishes new self-model
    #    cards must not leave the organ without them until 04:30.
    assert "/agent/v1/fs/sync" in tasks, (
        "the role must kick one pass at converge, the way pazny.keap does at the end "
        "of selfmodel.yml — otherwise the organ's corpus is only ever as fresh as its "
        "last daemon restart"
    )

    # The default stays 0 (an interval is a coincidence, a job is a decision, and
    # §5.3's halt has to have something to halt) — pinned so flipping it becomes a
    # deliberate act that has to revisit the halt path.
    assert defaults["cortex_fs_sync_interval_s"] == 0


def test_keap_cutover_is_a_second_decision():
    """The KEAP P-5 flip is gated on its OWN flag, defaulting off.

    Standing the organ up and repointing a live product's reasoning at it are two
    decisions. Collapsing them into `install_cortex` would mean the organ cannot
    be converged and observed without simultaneously taking KEAP's typechecker
    out of the path — and the rollback for that is a KEAP release, not a var.

    Also pins the pairing: KEAP 500s (naming the missing variable) if it gets the
    URL without the token, so rendering one without the other is a broken deploy
    that only shows up at the first validate call.
    """
    keap_defaults = yaml.safe_load((REPO / "roles" / "pazny.keap" / "defaults" / "main.yml").read_text())
    assert keap_defaults["keap_cortex_cutover"] is False, (
        "keap_cortex_cutover must default OFF — a converge that stands up the "
        "organ must not also silently repoint KEAP's reasoning at it"
    )

    compose = (REPO / "roles" / "pazny.keap" / "templates" / "compose.yml.j2").read_text()
    guard = re.search(r"\{%\s*if\s*\(install_cortex[^%]*keap_cortex_cutover[^%]*%\}(.*?)\{%\s*endif\s*%\}", compose, re.S)
    assert guard, "the CORTEX_BACKEND_URL block must be gated on install_cortex AND keap_cortex_cutover"
    assert "CORTEX_BACKEND_URL" in guard.group(1)
    assert "CORTEX_TOKEN_RO" in guard.group(1), (
        "CORTEX_BACKEND_URL without CORTEX_TOKEN_RO is a half-configured cutover: "
        "KEAP 500s at the first validate call"
    )


def test_lockfile_is_npm10_compatible():
    lock = json.loads((ORGAN / "package-lock.json").read_text())
    assert lock.get("lockfileVersion") == 3, (
        "package-lock.json must stay lockfileVersion 3 — npm 11 emits locks "
        "npm 10 rejects (validate with `npx npm@10 ci --dry-run` before bumping)"
    )


def test_volume_uuid_is_best_effort_and_cannot_abort_the_play():
    """A field documented "never asserted on" must not be able to fail a converge.

    Regression: the S2 mount sentinel read the data root's volume UUID with
    `regex_search(...) | first | default('', true)`. `regex_search` yields None
    (and `regex_findall` yields []) when nothing matches, and `first` RAISES on
    those — so the trailing `default` never runs, the filter has already thrown.
    The converge died at "Extract the volume UUID" with 'NoneType' object is not
    iterable, on a best-effort field nothing reads.

    Two things are pinned:
      1. the empty-sequence guard (`+ ['']`) is present, so `first` always has
         something to take;
      2. diskutil is asked about a MOUNT POINT resolved via absolute /bin/df —
         `diskutil info` exits 1 on a subdirectory (nos_data_root normally IS
         one), and a bare `df` resolves to Homebrew's `duf` on some hosts, which
         has no -P.
    """
    txt = (ROLE / "tasks" / "main.yml").read_text()
    assert "_cortex_volume_uuid" in txt, "the volume-UUID fact vanished — update this gate"

    block = txt.split("_cortex_volume_uuid", 1)[1].split("\n- name:", 1)[0]
    assert "+ ['']" in block, (
        "the empty-sequence guard is gone: regex_findall yields [] and `first` "
        "raises on it, so a best-effort field can abort the play again"
    )
    assert "| first" in block, "gate assumes the `first` idiom; the extraction changed shape"

    assert "/bin/df" in txt, (
        "diskutil must be pointed at the mount point resolved by ABSOLUTE /bin/df "
        "(a bare `df` can resolve to duf, and diskutil exits 1 on a subdirectory)"
    )
    assert "-plist {{ nos_data_root }}" not in txt, (
        "diskutil is being handed nos_data_root itself again — it exits 1 on a "
        "subdirectory, so the UUID could never be read; pass the resolved mount point"
    )
