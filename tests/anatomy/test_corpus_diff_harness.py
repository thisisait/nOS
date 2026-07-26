"""The S2 corpus diff harness — the gate is on the ADJUDICATION, not the red light.

`files/anatomy/scripts/cortex-corpus-diff.py` compares two corpora built
independently from one source. Anyone can write the part that says they differ.
The part worth gating is the part that says WHICH SIDE IS WRONG, because that is
the only reason to run two builders in parallel instead of migrating one into
the other — each corpus is a check on the other, and a difference is a
measurement rather than an alarm.

Every case below stages a disagreement whose correct culprit is known by
construction and asserts the harness reaches it — including the several cases
where the correct answer is "neither corpus is wrong":

  - a row KEAP has because it serves a surface the organ does not;
  - a row missing on a side whose last pass was refused or truncated (a
    degraded pass explains it on its own, and blaming the reader sends the
    operator to the wrong file);
  - a visibility difference that is one env var, not one bug;
  - a capture count that differs because the fan-out has never run.

A harness that can only blame a corpus will blame the wrong thing loudly, so
those four are gated as hard as the real defects.

Offline and hermetic: synthetic corpora, a `tmp_path` file tree as the
filesystem referee, a synthetic canonical tree as the taxonomy referee. It never
reaches the live KEAP container, the cortex organ, or the real user tree — and
it never writes anything outside `tmp_path`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files" / "anatomy" / "scripts" / "cortex-corpus-diff.py"


def _load():
    spec = importlib.util.spec_from_file_location("cortex_corpus_diff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cortex_corpus_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


D = _load()


# ── fixture builders ─────────────────────────────────────────────────────────


def mk_side(name, *, objects=None, details=None, taxonomy_ids=None, taxonomy_count=None,
            captures=None, by_kind=None, pending=None, model="nomic-embed-text", dim=768,
            pruned=0, shared_uids=("nos-docs",), roots=(), last_pass=None, last_pass_at=None,
            last_refusal=None, digest=None, version="test"):
    s = D.Side(name=name)
    s.serverVersion = version
    s.objectIds = sorted(objects or [])
    s.objectsTotal = len(s.objectIds)
    s.objectMeta = {o: {"userId": (details or {}).get(o, {}).get("userId"),
                        "type": (details or {}).get(o, {}).get("type"),
                        "title": (details or {}).get(o, {}).get("title")} for o in s.objectIds}
    s.objectDetail = dict(details or {})
    s.taxonomyIds = sorted(taxonomy_ids) if taxonomy_ids is not None else None
    s.taxonomyNodes = taxonomy_count if taxonomy_count is not None else (
        len(taxonomy_ids) if taxonomy_ids is not None else None)
    s.captureIds = sorted(captures or [])
    s.capturesTotal = len(s.captureIds)
    s.capturesComplete = True
    s.embedByKind = dict(by_kind or {})
    s.embedTotal = sum(s.embedByKind.values())
    s.embedModel, s.embedDim, s.embedPruned = model, dim, pruned
    s.pendingRefs = {k: dict(v) for k, v in (pending or {}).items()}
    s.embedPending = sum(len(v) for v in s.pendingRefs.values())
    s.pendingComplete = True
    s.ontologyVersion = digest
    s.sharedUids = list(shared_uids)
    s.userRoots = list(roots)
    s.fsStatus = {
        "sharedUids": list(shared_uids),
        "userRoots": list(roots),
        "lastRefusal": last_refusal,
        "lastRun": {"at": last_pass_at or "2026-07-27T00:00:00.000Z",
                    "result": last_pass if last_pass is not None else
                    {"scanned": len(s.objectIds), "upserted": 0, "removed": 0, "unchanged": len(s.objectIds),
                     "skipped": 0, "pruneRefused": False, "emptyBodies": 0, "sentinel": "ok"}},
    }
    return s


def detail(*, uid="akadmin", path="documents/a.md", size=10, mtime=1000, visibility="private",
           type_="page", title="a.md", body="hello", fmv=1, degraded=None):
    import hashlib
    return {
        "size": size, "mtime": mtime, "path": path, "visibility": visibility, "type": type_,
        "title": title, "userId": uid, "fmv": fmv, "degradedRead": degraded,
        "bodySha256": hashlib.sha256(body.encode()).hexdigest() if body else None,
        "bodyLen": len(body) if body else 0,
    }


def host_tree(tmp_path, files, uid_dir="akadmin"):
    """A `child-dirs` root with one uid directory. Returns the roots list."""
    root = tmp_path / "users"
    for rel, content in files.items():
        p = root / uid_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    root.mkdir(parents=True, exist_ok=True)
    return [{"path": str(root), "spec": "child-dirs", "exists": True}]


def report(keap, organ, roots=(), canonical=None, feeder=None):
    return D.build_report(
        keap, organ, D.HostReferee(list(roots)), canonical,
        feeder if feeder is not None else {"version": 2, "targets": {"keap": 1, "cortex": 1}},
    )


def verdicts(rep, table=None):
    return {f["verdict"] for f in rep["findings"] if table is None or f["table"] == table}


def culprit_of(rep, verdict):
    return {f["culprit"] for f in rep["findings"] if f["verdict"] == verdict}


# ── 0. the uid slug, because the whole filesystem referee rides on it ────────


def test_slugify_uid_matches_the_typescript_contract():
    # A folder named 'Pázny' owns a uid of 'pazny'. If this port drifts, the
    # referee cannot resolve a single path and EVERY adjudication degrades to
    # `unknown` — silently, because an unresolvable referee is a valid answer.
    assert D.slugify_uid("Pázny") == "pazny"
    assert D.slugify_uid("a.b_c@d") == "a-b-c-d"
    assert D.slugify_uid("--x--") == "x"
    assert D.slugify_uid(None) == ""


# ── 1. agreement ─────────────────────────────────────────────────────────────


def test_identical_corpora_agree_with_no_findings(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    det = {"fs:akadmin:aaa": detail()}
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details=det, taxonomy_ids=["01"],
                captures=["dp-1"], by_kind={"object": 1, "taxonomy": 1}, roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"], details=det, taxonomy_ids=["01"],
                captures=["dp-1"], by_kind={"object": 1, "taxonomy": 1}, roots=roots)
    rep = report(k, o, roots, canonical={"01"})
    assert rep["agrees"] is True
    assert rep["findings"] == []


# ── 2. an id only in KEAP ────────────────────────────────────────────────────


def test_only_in_keap_and_the_file_exists_blames_the_organs_reader(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details={"fs:akadmin:aaa": detail()}, roots=roots)
    o = mk_side("cortex", objects=[], details={}, roots=roots)
    rep = report(k, o, roots)
    assert "organ-reader-missed-it" in verdicts(rep)
    assert culprit_of(rep, "organ-reader-missed-it") == {D.CULPRIT_ORGAN}
    # The evidence, not just the verdict: the referee's own numbers must appear,
    # or "the organ missed it" is an assertion rather than a finding.
    f = next(f for f in rep["findings"] if f["verdict"] == "organ-reader-missed-it")
    assert f["detail"]["fs"]["state"] == "exists"
    assert str(tmp_path) in f["because"]


def test_only_in_keap_and_the_file_is_gone_blames_keaps_prune(tmp_path):
    roots = host_tree(tmp_path, {})  # the uid dir exists, the file does not
    (tmp_path / "users" / "akadmin").mkdir(parents=True, exist_ok=True)
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details={"fs:akadmin:aaa": detail()}, roots=roots)
    o = mk_side("cortex", objects=[], details={}, roots=roots)
    rep = report(k, o, roots)
    assert "keap-stale-not-pruned" in verdicts(rep)
    assert culprit_of(rep, "keap-stale-not-pruned") == {D.CULPRIT_KEAP}


def test_only_in_keap_with_an_unroutable_uid_is_config_not_a_defect(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"}, uid_dir="akadmin")
    k = mk_side("keap", objects=["fs:otheruser:aaa"],
                details={"fs:otheruser:aaa": detail(uid="otheruser")}, roots=roots)
    o = mk_side("cortex", objects=[], details={}, roots=roots)
    rep = report(k, o, roots)
    assert "organ-root-missing-for-uid" in verdicts(rep)
    # NOT the organ's reader: it was never given a root that could produce this
    # uid. A reader cannot miss a tree it was not pointed at.
    assert culprit_of(rep, "organ-root-missing-for-uid") == {D.CULPRIT_CONFIG}


def test_a_degraded_organ_pass_preempts_every_reader_verdict(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details={"fs:akadmin:aaa": detail()}, roots=roots)
    o = mk_side("cortex", objects=[], details={}, roots=roots,
                last_pass={"scanned": 0, "removed": 0, "pruneRefused": True, "sentinel": "ok"})
    rep = report(k, o, roots)
    # The file IS on disk, so the naive answer is "the organ missed it". It did
    # not: its pass refused the prune, which explains a missing id by itself.
    assert "organ-pass-degraded" in verdicts(rep)
    assert "organ-reader-missed-it" not in verdicts(rep)
    assert culprit_of(rep, "organ-pass-degraded") == {D.CULPRIT_NEITHER}


def test_a_non_fs_row_only_in_keap_is_not_an_ingestion_defect(tmp_path):
    # The nOS face DataTables land as `table-*` objects through a KEAP surface
    # the organ deliberately does not serve. If these read as "the organ's
    # reader missed three files", every real finding drowns beside them.
    roots = host_tree(tmp_path, {})
    k = mk_side("keap", objects=["table-face-controls"],
                details={}, roots=roots)
    k.objectMeta["table-face-controls"] = {"userId": "nos-agent", "type": "table", "title": "controls"}
    o = mk_side("cortex", objects=[], roots=roots)
    rep = report(k, o, roots)
    assert "not-a-mirror-row" in verdicts(rep)
    assert culprit_of(rep, "not-a-mirror-row") == {D.CULPRIT_NEITHER}
    # …and the fs clause, which the 3-night clock runs on, stays clean.
    assert rep["clauses"]["fs ids"] is True


# ── 3. an id only in the organ ───────────────────────────────────────────────


def test_only_in_organ_with_a_file_older_than_keaps_pass_blames_keaps_reader(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    p = tmp_path / "users" / "akadmin" / "documents" / "a.md"
    os.utime(p, (1_000_000, 1_000_000))  # long before KEAP's last pass
    k = mk_side("keap", objects=[], roots=roots, last_pass_at="2026-07-27T00:00:00.000Z")
    o = mk_side("cortex", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(mtime=1_000_000)}, roots=roots)
    rep = report(k, o, roots)
    assert "keap-reader-missed-it" in verdicts(rep)
    assert culprit_of(rep, "keap-reader-missed-it") == {D.CULPRIT_KEAP}


def test_only_in_organ_with_a_file_newer_than_keaps_pass_is_mere_staleness(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    p = tmp_path / "users" / "akadmin" / "documents" / "a.md"
    os.utime(p, (2_000_000_000, 2_000_000_000))  # after KEAP last walked
    k = mk_side("keap", objects=[], roots=roots, last_pass_at="2026-07-27T00:00:00.000Z")
    o = mk_side("cortex", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(mtime=2_000_000_000)}, roots=roots)
    rep = report(k, o, roots)
    # Still KEAP's side of the ledger — but "has not walked yet" and "walked and
    # missed it" are different bugs with different fixes, and the referee's
    # mtime is the only thing that separates them.
    assert "keap-stale" in verdicts(rep)
    assert "keap-reader-missed-it" not in verdicts(rep)


def test_only_in_organ_with_no_file_at_all_is_the_organs_row_to_explain(tmp_path):
    roots = host_tree(tmp_path, {})
    (tmp_path / "users" / "akadmin").mkdir(parents=True, exist_ok=True)
    k = mk_side("keap", objects=[], roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"], details={"fs:akadmin:aaa": detail()}, roots=roots)
    rep = report(k, o, roots)
    assert "organ-row-without-a-file" in verdicts(rep)
    assert culprit_of(rep, "organ-row-without-a-file") == {D.CULPRIT_ORGAN}


# ── 4. shared ids: the content digests ───────────────────────────────────────


@pytest.mark.parametrize("disk_size,expect", [(10, "organ-stale-read"), (99, "keap-stale-read")])
def test_the_filesystem_names_the_stale_reader(tmp_path, disk_size, expect):
    roots = host_tree(tmp_path, {"documents/a.md": "x" * disk_size})
    st = os.stat(tmp_path / "users" / "akadmin" / "documents" / "a.md")
    k = mk_side("keap", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(size=10, mtime=int(st.st_mtime))}, roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(size=99, mtime=int(st.st_mtime))}, roots=roots)
    rep = report(k, o, roots)
    # "The two rows differ" is not actionable. "The file on disk is N bytes and
    # only one side says so" names the loser in one line.
    assert expect in verdicts(rep)


def test_an_empty_body_beside_a_full_one_names_the_empty_side(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    k = mk_side("keap", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(body=None)}, roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(body="hello")}, roots=roots)
    rep = report(k, o, roots)
    # The size is right and the content is gone — the one failure class the
    # prune guards cannot catch, because nothing was pruned.
    assert "empty-body-read" in verdicts(rep)
    assert culprit_of(rep, "empty-body-read") == {D.CULPRIT_KEAP}


def test_equal_stats_and_different_bodies_is_a_derivation_divergence(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    k = mk_side("keap", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(body="hello")}, roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(body="hello world")}, roots=roots)
    rep = report(k, o, roots)
    # Same bytes on disk, different text in the row: a parser difference, not a
    # reader one. Refusing to name a culprit here is the correct answer.
    assert "body-derivation-divergence" in verdicts(rep)
    assert culprit_of(rep, "body-derivation-divergence") == {D.CULPRIT_UNKNOWN}


def test_a_visibility_difference_is_one_env_var_not_one_bug(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    k = mk_side("keap", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(visibility="shared")},
                shared_uids=("nos-docs", "akadmin"), roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"],
                details={"fs:akadmin:aaa": detail(visibility="private")},
                shared_uids=("nos-docs",), roots=roots)
    rep = report(k, o, roots)
    assert "shared-uids-divergence" in verdicts(rep)
    assert culprit_of(rep, "shared-uids-divergence") == {D.CULPRIT_CONFIG}
    f = next(f for f in rep["findings"] if f["verdict"] == "shared-uids-divergence")
    # The proof is on the wire: both sides publish their shared-uid set.
    assert "akadmin" in f["because"]


# ── 5. taxonomy: the repo is the referee ─────────────────────────────────────


def test_a_node_in_the_pin_and_in_keap_means_the_organ_never_rematerialised():
    k = mk_side("keap", taxonomy_ids=["01", "02"])
    o = mk_side("cortex", taxonomy_ids=["01"])
    rep = report(k, o, canonical={"01", "02"})
    assert "organ-store-not-materialised" in verdicts(rep)
    assert culprit_of(rep, "organ-store-not-materialised") == {D.CULPRIT_ORGAN}


def test_a_node_in_the_pin_and_in_the_organ_means_the_container_is_behind():
    k = mk_side("keap", taxonomy_ids=["01"])
    o = mk_side("cortex", taxonomy_ids=["01", "02"])
    rep = report(k, o, canonical={"01", "02"})
    # Identical observation shape to the previous case, opposite culprit and
    # opposite fix. Only the referee tells them apart.
    assert "keap-container-behind-pin" in verdicts(rep)
    assert culprit_of(rep, "keap-container-behind-pin") == {D.CULPRIT_KEAP}


def test_a_node_in_neither_the_pin_nor_the_organ_means_keap_is_ahead_of_it():
    # In-scope: root '01' IS a root the pinned tree defines, so the referee has
    # jurisdiction and the absence is a statement about the pin.
    k = mk_side("keap", taxonomy_ids=["01", "01.99"])
    o = mk_side("cortex", taxonomy_ids=["01"])
    rep = report(k, o, canonical={"01"})
    assert "keap-ahead-of-pin" in verdicts(rep)


def test_equal_node_counts_without_id_sets_are_never_reported_as_parity():
    # 1841 vs 1841 with different trees is the exact green this harness must not
    # be able to earn — and it is what a count-only comparison hands you.
    k = mk_side("keap", taxonomy_ids=None, taxonomy_count=1841)
    o = mk_side("cortex", taxonomy_ids=None, taxonomy_count=1841)
    rep = report(k, o, canonical={"01"})
    assert rep["clauses"]["taxonomy"] is False
    assert "counts-only" in verdicts(rep)
    tax = next(t for t in rep["tables"] if t["name"] == "taxonomy_nodes")
    assert tax["comparable"] is False and tax["ceiling"]


# ── 6. captures: the fan-out's own ledger is the referee ─────────────────────


def test_agreement_on_a_stale_tree_is_not_reported_as_parity():
    # Both sides can hold the SAME 1841 nodes while the pin holds 2393. The id
    # diff reads `exact`, the counts match, and nothing in either corpus knows
    # about the referee — so without this the strongest-looking line in the
    # report answers §4.4's question wrongly.
    k = mk_side("keap", taxonomy_ids=["01", "02"], by_kind={"taxonomy": 2})
    o = mk_side("cortex", taxonomy_ids=["01", "02"], by_kind={"taxonomy": 2})
    rep = report(k, o, canonical={"01", "02", "03", "04"})
    assert rep["clauses"]["taxonomy"] is True          # they DO agree…
    assert "both-behind-pin" in verdicts(rep)          # …on a tree that is short
    assert rep["corpusParity"]["missingFromBoth"] == 2
    text = D.render(rep, 1, 0)
    assert "corpus parity    NOT PINNED" in text
    # …and the clock is not failed for it: parity is currency, not agreement.
    assert rep["agrees"] is True


def test_a_generated_subtree_is_outside_the_referees_jurisdiction():
    # The estate self-model registers `nos.*` through registerExtNode — it is
    # generated, never ingested from knowledge/canonical. Judging it against
    # that tree produced 91 false "fed from something this checkout is not
    # pinned to" on the first real run. The rule is structural (an unknown ROOT
    # segment), so the next generated subtree needs no remembering.
    k = mk_side("keap", taxonomy_ids=["01", "nos", "nos.b2b"])
    o = mk_side("cortex", taxonomy_ids=["01", "nos", "nos.b2b"])
    rep = report(k, o, canonical={"01"})
    assert "both-ahead-of-pin" not in verdicts(rep)
    assert "outside-referee-jurisdiction" in verdicts(rep)
    assert rep["corpusParity"]["generated"] == 2
    assert "+2 generated" in D.render(rep, 1, 0)


def test_a_generated_node_on_one_side_only_is_not_blamed_on_the_pin():
    k = mk_side("keap", taxonomy_ids=["01", "nos.b2b"])
    o = mk_side("cortex", taxonomy_ids=["01"])
    rep = report(k, o, canonical={"01"})
    # A real disagreement — but the canonical tree cannot arbitrate it, and
    # saying `keap-ahead-of-pin` would send the operator to reconcile a pin that
    # has nothing to do with it.
    assert "generated-subtree-differs" in verdicts(rep)
    assert culprit_of(rep, "generated-subtree-differs") == {D.CULPRIT_UNKNOWN}
    assert "keap-ahead-of-pin" not in verdicts(rep)


def test_an_in_scope_node_absent_from_the_pin_is_still_blamed_on_the_pin():
    k = mk_side("keap", taxonomy_ids=["01", "01.99"])
    o = mk_side("cortex", taxonomy_ids=["01"])
    rep = report(k, o, canonical={"01"})
    assert "keap-ahead-of-pin" in verdicts(rep)


def test_full_parity_says_so_rather_than_saying_nothing():
    k = mk_side("keap", taxonomy_ids=["01", "02"])
    o = mk_side("cortex", taxonomy_ids=["01", "02"])
    rep = report(k, o, canonical={"01", "02"})
    assert "both-behind-pin" not in verdicts(rep)
    assert "corpus parity    PINNED" in D.render(rep, 1, 0)


def test_a_capture_gap_with_a_v1_ledger_is_a_job_that_never_ran():
    k = mk_side("keap", captures=[f"dp-{i}" for i in range(20)])
    o = mk_side("cortex", captures=["dp-0"])
    rep = report(k, o, feeder={"version": 1, "targets": {"keap": 20}})
    assert "fanout-never-ran" in verdicts(rep)
    assert culprit_of(rep, "fanout-never-ran") == {D.CULPRIT_FEEDER}
    # The corpora are not disagreeing — one of them was never written to.
    assert rep["clauses"]["captures"] is False


def test_captures_are_inside_the_verdict():
    # With captures out of the verdict, a night on which the shadow was never
    # fed reads AGREE and advances a 3-night clock. That is the green this
    # harness exists to refuse.
    k = mk_side("keap", captures=["dp-0", "dp-1"])
    o = mk_side("cortex", captures=["dp-0"])
    rep = report(k, o)
    assert rep["agrees"] is False
    assert rep["clauses"]["captures"] is False


def test_a_capture_gap_with_a_v2_ledger_is_a_partial_fanout():
    k = mk_side("keap", captures=["dp-0", "dp-1"])
    o = mk_side("cortex", captures=["dp-0"])
    rep = report(k, o, feeder={"version": 2, "targets": {"keap": 2, "cortex": 2}})
    # The ledger says both were swept. A recorded signature with no row is the
    # data-loss shape the target dimension exists to prevent.
    assert "fanout-partial" in verdicts(rep)


# ── 7. embeddings: same refs, same model, same dimension ─────────────────────


def test_a_different_model_or_dimension_is_an_incomparable_space():
    k = mk_side("keap", model="nomic-embed-text", dim=768)
    o = mk_side("cortex", model="mxbai-embed-large", dim=1024)
    rep = report(k, o)
    assert "incomparable-embedding-space" in verdicts(rep)
    assert rep["clauses"]["embed shape"] is False


def test_a_shared_source_embedded_on_one_side_only_names_the_lagging_pass(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    det = {"fs:akadmin:aaa": detail()}
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details=det, by_kind={"object": 1}, roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"], details=det, by_kind={"object": 0},
                pending={"object": {"fs:akadmin:aaa": "h1"}}, roots=roots)
    rep = report(k, o, roots)
    assert "organ-embed-behind" in verdicts(rep)
    assert culprit_of(rep, "organ-embed-behind") == {D.CULPRIT_ORGAN}
    assert rep["clauses"]["embedded refs"] is False


def test_a_missing_source_is_not_reported_as_a_missing_vector(tmp_path):
    # An object only KEAP has is already reported as an object difference.
    # Reporting it a second time as an embedding difference doubles the noise
    # and points at the wrong job.
    roots = host_tree(tmp_path, {})
    (tmp_path / "users" / "akadmin").mkdir(parents=True, exist_ok=True)
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details={"fs:akadmin:aaa": detail()},
                by_kind={"object": 1}, roots=roots)
    o = mk_side("cortex", objects=[], by_kind={"object": 0}, roots=roots)
    rep = report(k, o, roots)
    assert "organ-corpus-lacks-source" in verdicts(rep)
    assert culprit_of(rep, "organ-corpus-lacks-source") == {D.CULPRIT_NEITHER}


def test_a_truncated_pending_page_never_publishes_a_derived_number(tmp_path):
    # `sources − pending` is the embedded set ONLY when pending is complete.
    # Truncated at the page cap it overstates embedding by exactly what the cap
    # hid: the first real run reported 1341 of 1841 taxonomy refs "embedded"
    # against a store holding ZERO vectors. A number wrong in a known direction
    # is worse than no number.
    ids = [f"{i:04d}" for i in range(600)]
    k = mk_side("keap", taxonomy_ids=ids, by_kind={"taxonomy": 600})
    o = mk_side("cortex", taxonomy_ids=ids, by_kind={"taxonomy": 0},
                pending={"taxonomy": {i: "h" for i in ids}})
    o.pendingComplete = False
    rep = report(k, o, canonical=set(ids))
    t = next(t for t in rep["tables"] if t["name"] == "embedded[taxonomy]")
    assert t["comparable"] is False and "NOT derived" in t["ceiling"]
    assert t["organRows"] == 0 and t["keapRows"] == 600
    # The exact row-count check still names the culprit and the real deficit.
    f = next(f for f in rep["findings"] if f["verdict"] == "organ-embed-behind")
    assert f["detail"] == {"kind": "taxonomy", "vectors": 0, "sources": 600}
    # …and the clause does NOT read ok just because the ref-set diff was the
    # thing that got skipped. Pending is largest exactly when a side is furthest
    # behind, so "skipped" and "fine" would coincide at the worst moment.
    assert rep["clauses"]["embedded refs"] is False


def test_orphan_vectors_are_named_on_the_side_that_holds_them():
    k = mk_side("keap", objects=["fs:a:1"], by_kind={"object": 5})
    o = mk_side("cortex", objects=["fs:a:1"], by_kind={"object": 1})
    rep = report(k, o)
    assert "orphan-vectors" in verdicts(rep)
    assert culprit_of(rep, "orphan-vectors") == {D.CULPRIT_KEAP}


def test_the_harness_admits_when_reading_pending_pruned_a_store():
    # GET /agent/v1/embeddings/pending runs pendingEmbeddings(), which reaps
    # orphan vectors. A tool that writes while claiming not to is worse than one
    # that admits it.
    k = mk_side("keap", pruned=3)
    o = mk_side("cortex")
    rep = report(k, o)
    assert "harness-side-effect" in verdicts(rep)


# ── 8. the denominator, and what it forbids ──────────────────────────────────


def test_the_disclaimer_fires_on_a_number_not_on_a_comment(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    det = {"fs:akadmin:aaa": detail()}
    k = mk_side("keap", objects=["fs:akadmin:aaa"], details=det, taxonomy_ids=["01"],
                by_kind={"object": 1, "taxonomy": 1}, roots=roots)
    o = mk_side("cortex", objects=["fs:akadmin:aaa"], details=det, taxonomy_ids=["01"],
                by_kind={"object": 1, "taxonomy": 1}, roots=roots)
    rep = report(k, o, roots, canonical={"01"})
    assert rep["agrees"] is True
    assert rep["realUserDocs"] == 1
    text = D.render(rep, 1, 0)
    assert "This run does not show that ingestion is correct" in text
    for item in D.NOT_EXERCISED:
        assert item in text
    # The denominator is printed ABOVE the verdict, so nobody reads AGREE first.
    assert text.index("real user docs") < text.index("VERDICT")


def test_self_model_cards_do_not_count_as_real_user_documents(tmp_path):
    roots = host_tree(tmp_path, {})
    det = {f"fs:nos-docs:{i}": detail(uid="nos-docs", path=f"nOS/x{i}.md") for i in range(30)}
    s = mk_side("keap", objects=list(det), details=det, roots=roots)
    # 30 objects, 0 documents: the floor must not be cleared by the estate
    # describing itself.
    assert D.real_user_docs(s) == 0


def test_two_unpublished_ontology_digests_never_compare_equal():
    k = mk_side("keap", digest=None)
    o = mk_side("cortex", digest=None)
    text = D.render(report(k, o), 1, 0)
    assert "CEILING" in text and "not served" in text


# ── 9. the ledger ────────────────────────────────────────────────────────────


def test_a_ledger_from_an_older_harness_does_not_carry_its_streak(tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({"version": 1, "nights": [{"result": "agree"}] * 2,
                             "agreeStreak": 2, "disagreements": 0}))
    s = D.load_state(p)
    # Nights measured by a weaker harness are kept for the record and stripped
    # of their credit — otherwise a clause added today inherits agreement that
    # was never tested for it.
    assert s["agreeStreak"] == 0 and s["nights"] == []
    assert len(s["supersededNights"]) == 2 and s["supersededVersion"] == 1


def test_a_current_ledger_is_carried_forward(tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({"version": D.LEDGER_VERSION, "nights": [{"result": "agree"}],
                             "agreeStreak": 1, "disagreements": 0}))
    assert D.load_state(p)["agreeStreak"] == 1


# ── 10. end to end, over the wire ────────────────────────────────────────────


class _Corpus(BaseHTTPRequestHandler):
    """A minimal /agent/v1 daemon, so the wire reader is gated too, not only the
    adjudicator it feeds."""

    def log_message(self, *_a):
        pass

    def do_GET(self):  # noqa: N802
        c = self.server.corpus
        path = self.path.split("?")[0]
        if self.headers.get("authorization") != f"Bearer {c['token']}":
            return self._json(401, {"success": False, "error": "invalid token"})
        if path == "/agent/v1/health":
            return self._json(200, {"success": True, "data": {
                "version": c["version"],
                "corpus": {"taxonomyNodes": len(c["nodes"]), "curatedNotes": 0, "objects": len(c["objects"])},
                "embeddings": {"total": len(c["objects"]), "byKind": {"object": len(c["objects"])},
                               "model": "nomic-embed-text"}}})
        if path == "/agent/v1/objects":
            return self._json(200, {"success": True, "data": {
                "total": len(c["objects"]),
                "results": [{"id": k, "type": v["type"], "title": v["title"], "userId": v["userId"]}
                            for k, v in c["objects"].items()]}})
        if path.startswith("/agent/v1/objects/"):
            oid = __import__("urllib.parse", fromlist=["unquote"]).unquote(path.rsplit("/", 1)[1])
            o = c["objects"].get(oid)
            if not o:
                return self._json(404, {"success": False, "error": "unknown object"})
            return self._json(200, {"success": True, "data": {
                "id": oid, "type": o["type"], "title": o["title"], "userId": o["userId"],
                "visibility": o["visibility"], "body": o["body"],
                "frontmatter": {"source": "fs", "path": o["path"], "size": o["size"],
                                "mtime": o["mtime"], "fmv": 1}}})
        if path == "/agent/v1/graph":
            return self._json(200, {"success": True, "data": {
                "nodes": [{"id": n, "kind": "node", "name": n} for n in c["nodes"]],
                "edges": [], "types": [], "meta": {}}})
        if path == "/agent/v1/captures":
            return self._json(200, {"success": True, "data": {"total": 0, "items": []}})
        if path == "/agent/v1/embeddings/pending":
            return self._json(200, {"success": True, "data": {
                "model": "nomic-embed-text", "dim": 768, "total": 0, "pruned": 0, "items": []}})
        if path == "/agent/v1/fs/status":
            return self._json(200, {"success": True, "data": {
                "sharedUids": ["nos-docs"], "userRoots": c["roots"], "lastRefusal": None,
                "lastRun": {"at": "2026-07-27T00:00:00.000Z",
                            "result": {"scanned": len(c["objects"]), "removed": 0, "pruneRefused": False,
                                       "emptyBodies": 0, "sentinel": "ok"}}}})
        return self._json(404, {"success": False, "error": "no such route"})

    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _serve(corpus):
    http = HTTPServer(("127.0.0.1", 0), _Corpus)
    http.corpus = corpus
    threading.Thread(target=http.serve_forever, daemon=True).start()
    return http, f"http://127.0.0.1:{http.server_address[1]}"


def test_end_to_end_over_the_wire_reads_both_sides_and_adjudicates(tmp_path):
    roots = host_tree(tmp_path, {"documents/a.md": "hello"})
    st = os.stat(tmp_path / "users" / "akadmin" / "documents" / "a.md")
    obj = {"type": "page", "title": "a.md", "userId": "akadmin", "visibility": "private",
           "body": "hello", "path": "documents/a.md", "size": st.st_size, "mtime": int(st.st_mtime)}
    keap_http, keap_url = _serve({"token": "k", "version": "1.26.0", "nodes": ["01"],
                                  "objects": {"fs:akadmin:aaa": obj}, "roots": []})
    organ_http, organ_url = _serve({"token": "c", "version": "test", "nodes": ["01"],
                                    "objects": {}, "roots": roots})
    try:
        out = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", "--no-ledger",
             "--keap-url", keap_url, "--cortex-url", organ_url,
             "--keap-token", "k", "--cortex-token", "c",
             "--canonical-dir", str(tmp_path / "nope")],
            capture_output=True, text=True, timeout=120, check=False)
        assert out.returncode == 0, out.stderr
        rep = json.loads(out.stdout)
    finally:
        keap_http.shutdown()
        organ_http.shutdown()
    assert rep["agrees"] is False
    assert "organ-reader-missed-it" in {f["verdict"] for f in rep["findings"]}
    # The referee reached the tree over a real run, not only in-process.
    assert rep["refereesAvailable"]["filesystem"] is True
    assert rep["refereesAvailable"]["canonicalTree"] is False


def test_a_missing_canonical_referee_is_stated_rather_than_guessed_around():
    k = mk_side("keap", taxonomy_ids=["01", "02"])
    o = mk_side("cortex", taxonomy_ids=["01"])
    rep = report(k, o, canonical=None)
    assert "no-canonical-referee" in verdicts(rep)
    assert culprit_of(rep, "no-canonical-referee") == {D.CULPRIT_UNKNOWN}
