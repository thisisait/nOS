"""The weakness reader: what it must surface, and what it must never swallow.

Two requirements have teeth here and each gets its own class:

  * the git working tree is a FIRST-CLASS source — a file written by a
    scheduled job and left uncommitted is a weakness, named with its writer;
  * a source whose freshness is SELF-REPORTED is marked as such, and any
    severity derived from such a value says so.

The third theme is the one the estate paid for in v0.10-beta: ABSENCE IS NEVER
SUCCESS. A source that cannot be read must produce a weakness and drop
`complete`, never an empty list that reads as health.
"""

from __future__ import annotations

import json

from .fakes import JUDGE_TOKEN, PROPOSE_TOKEN, make_queue, make_scan_state

QUEUE_REL = "docs/llm/security/remediation-queue.json"
SCAN_REL = "docs/llm/security/scan-state.json"


def _ids(payload):
    return [w["weakness_id"] for w in payload["weaknesses"]]


def _by_id(payload, wid):
    for w in payload["weaknesses"]:
        if w["weakness_id"] == wid:
            return w
    raise AssertionError(f"{wid} not in {_ids(payload)}")


def _source(payload, name):
    for s in payload["sources"]:
        if s["name"] == name:
            return s
    raise AssertionError(f"source {name} missing from {[s['name'] for s in payload['sources']]}")


# ── Requirement 1: the git working tree ─────────────────────────────────────


class TestGitWorkingTreeIsFirstClass:
    def test_clean_tree_reports_no_git_weakness(self, repo, weaknesses):
        payload = weaknesses.read_weaknesses()
        assert [w for w in payload["weaknesses"] if w["source"] == "git-worktree"] == [], (
            "a committed tree must not manufacture git weaknesses"
        )
        assert _source(payload, "git-worktree")["status"] == "ok"

    def test_uncommitted_scheduled_job_output_surfaces_high_and_names_the_writer(
        self, repo, weaknesses
    ):
        """THE requirement: the nightly scan wrote the queue, nothing committed
        it, and nothing tells the operator. This is that alarm."""
        (repo / QUEUE_REL).write_text(
            json.dumps(make_queue(pending=[("CRITICAL", "gitea")], resolved=1))
        )

        w = _by_id(weaknesses.read_weaknesses(), f"git:uncommitted:{QUEUE_REL}")

        assert w["severity"] == "high"
        assert w["evidence"]["machine_written"] is True
        assert "security scan" in w["evidence"]["writer"], (
            "the weakness must name WHO wrote the file — 'a dirty file' is a "
            "lint finding, 'a scheduled job's output never landed' is the defect"
        )
        assert w["evidence"]["porcelain_xy"].strip() == "M"
        assert "not committed" in w["title"]

    def test_untracked_scheduled_job_output_is_the_same_failure(self, repo, weaknesses):
        """git-add never happened is not milder than git-commit never happened."""
        (repo / "state").mkdir(exist_ok=True)
        (repo / "state" / "devlog-bundle.jsonl").write_text("{}\n")

        w = _by_id(weaknesses.read_weaknesses(), "git:uncommitted:state/devlog-bundle.jsonl")
        assert w["severity"] == "high"
        assert w["evidence"]["porcelain_xy"] == "??"
        assert w["evidence"]["writer"] == "tools/devlog-compile.py"

    def test_operator_edits_rank_below_machine_writes(self, repo, weaknesses):
        (repo / QUEUE_REL).write_text(json.dumps(make_queue(pending=[("LOW", "x")])))
        (repo / "docs" / "hidden_fees" / "01-alpha.md").write_text("# edited by hand\n")
        (repo / "scratch.txt").write_text("untracked\n")

        payload = weaknesses.read_weaknesses()
        assert _by_id(payload, f"git:uncommitted:{QUEUE_REL}")["severity"] == "high"
        assert _by_id(payload, "git:uncommitted-tracked")["severity"] == "medium"
        assert _by_id(payload, "git:untracked")["severity"] == "low"

    def test_file_backed_weaknesses_carry_the_tracked_state_of_their_file(
        self, repo, weaknesses
    ):
        """A weakness read out of an UNCOMMITTED queue must not be mistakable
        for one read out of the committed queue."""
        (repo / QUEUE_REL).write_text(json.dumps(make_queue(pending=[("HIGH", "gitea")])))

        rem = _by_id(weaknesses.read_weaknesses(), "rem:REM-001")
        assert rem["observed"]["file_git_state"] == "modified-uncommitted"

    def test_renamed_paths_do_not_desync_the_porcelain_parser(self, repo, weaknesses):
        """`-z` rename entries carry two NUL-separated paths; consuming only one
        shifts every later entry by one and mislabels files."""
        parsed = weaknesses._parse_porcelain_z(
            "R  new/path.txt\0old/path.txt\0 M docs/other.md\0?? scratch.txt\0"
        )
        assert parsed == [
            ("R ", "new/path.txt"),
            (" M", "docs/other.md"),
            ("??", "scratch.txt"),
        ]

    def test_git_freshness_is_observed_never_self_reported(self, repo, weaknesses):
        f = _source(weaknesses.read_weaknesses(), "git-worktree")["freshness"]
        assert f["basis"] == "observed"
        assert f["self_reported"] is False


# ── Requirement 2: self-reported freshness ──────────────────────────────────


class TestSelfReportedFreshnessIsMarked:
    def test_scan_state_freshness_is_marked_self_reported_and_names_its_author(
        self, repo, weaknesses
    ):
        f = _source(weaknesses.read_weaknesses(), "scan-state")["freshness"]
        assert f["basis"] == "self_reported"
        assert f["self_reported"] is True
        assert f["written_by"], "a self-report with no named author is an anonymous claim"
        assert "scan" in f["written_by"].lower()

    def test_staleness_severity_declares_it_came_from_a_self_report(self, repo, weaknesses):
        """The scar: the drift watcher was fed the value that silences it."""
        (repo / SCAN_REL).write_text(
            json.dumps(make_scan_state(last_full_scan="2026-01-01T00:00:00Z"))
        )

        w = _by_id(weaknesses.read_weaknesses(), "scan:stale-full-scan")
        assert w["derived_from_self_report"] is True
        assert "author" in w["observed"]["warning"]
        assert w["observed"]["age_days"] > 14

    def test_a_self_report_contradicted_by_the_append_only_log_is_its_own_weakness(
        self, repo, state, weaknesses
    ):
        """The scan claims today; the append-only event log's last finished
        batch is months old. The reader resolves this in NEITHER direction."""
        (state / "events" / "scan.jsonl").write_text(
            json.dumps({"ts": "2026-01-01T00:00:00Z", "type": "scan.batch_done"}) + "\n"
        )
        (repo / SCAN_REL).write_text(
            json.dumps(make_scan_state(last_full_scan="2026-08-02T02:14:02Z"))
        )

        payload = weaknesses.read_weaknesses()
        w = _by_id(payload, "freshness:scan-state:not-corroborated")
        assert w["severity"] == "high", (
            "scan-state's freshness is LOAD-BEARING — the nightly drift watcher "
            "reads it, so an uncorroborated value is the alarm feeding itself"
        )
        assert w["derived_from_self_report"] is True
        assert w["evidence"]["corroborator_value"] == "2026-01-01T00:00:00+00:00"
        assert _source(payload, "scan-state")["freshness"]["corroborated"] is False

    def test_the_same_check_covers_every_self_reporting_source(
        self, repo, state, weaknesses
    ):
        """The second sighting of this defect was `generated_at` in
        remediation-queue.json — measured byte-identical across a change that
        ADDED items. A per-source patch would not have caught it."""
        (state / "events" / "scan.jsonl").write_text(
            json.dumps({"ts": "2026-08-02T02:14:02Z", "type": "scan.batch_done"}) + "\n"
        )
        (repo / QUEUE_REL).write_text(
            json.dumps(
                make_queue(pending=[("HIGH", "gitea")], generated_at="2026-01-01T00:00:00Z")
            )
        )

        w = _by_id(weaknesses.read_weaknesses(), "freshness:remediation-queue:not-corroborated")
        assert w["severity"] == "medium", "not load-bearing: nothing derives a severity from it"
        assert w["derived_from_self_report"] is True

    def test_the_load_bearing_set_is_declared_not_inferred(self, weaknesses):
        assert weaknesses.SOURCE_FRESHNESS_LOAD_BEARING == {"scan-state"}
        assert weaknesses.SOURCE_FRESHNESS_LOAD_BEARING <= set(weaknesses.SOURCE_ORDER)

    def test_a_corroborated_self_report_says_so(self, repo, state, weaknesses):
        (state / "events" / "scan.jsonl").write_text(
            json.dumps({"ts": "2026-08-02T02:14:02Z", "type": "scan.batch_done"}) + "\n"
        )
        (repo / SCAN_REL).write_text(
            json.dumps(make_scan_state(last_full_scan="2026-08-02T02:14:02Z"))
        )

        payload = weaknesses.read_weaknesses()
        assert _source(payload, "scan-state")["freshness"]["corroborated"] is True
        assert "freshness:scan-state:not-corroborated" not in _ids(payload)

    def test_every_self_reporting_source_is_listed_at_the_top_level(self, repo, weaknesses):
        payload = weaknesses.read_weaknesses()
        assert set(payload["self_reported_sources"]) == {
            "remediation-queue", "scan-state", "hidden-fees", "corpus-diff",
        }, "a consumer must be able to see the self-reporting set without walking sources"

    def test_both_iso_spellings_parse(self, weaknesses):
        """Two writers, two spellings. A consumer that accepted only the `Z`
        form made the nightly drift watcher produce no verdict at all."""
        z = weaknesses.parse_iso("2026-08-02T02:14:02Z")
        offset = weaknesses.parse_iso("2026-08-02T04:14:02+02:00")
        assert z is not None and offset is not None
        assert z == offset, "the same instant in two spellings must compare equal"
        assert weaknesses.parse_iso("not-a-date") is None
        assert weaknesses.parse_iso(None) is None

    def test_freshness_refuses_an_anonymous_self_report(self, weaknesses):
        """Enforced in the type, not by reviewer discipline."""
        import pytest

        with pytest.raises(ValueError, match="written_by"):
            weaknesses.Freshness(basis="self_reported", value="2026-01-01T00:00:00Z")


# ── Absence is never success ────────────────────────────────────────────────


class TestAbsenceIsNeverSuccess:
    def test_a_missing_required_source_produces_a_weakness_and_drops_complete(
        self, repo, weaknesses
    ):
        (repo / SCAN_REL).unlink()

        payload = weaknesses.read_weaknesses()
        assert payload["complete"] is False
        assert payload["degraded_sources"] == ["scan-state"]
        w = _by_id(payload, "source:scan-state:unavailable")
        assert w["severity"] == "medium"
        assert "incomplete" in w["title"]

    def test_a_malformed_source_outranks_a_missing_one(self, repo, weaknesses):
        (repo / QUEUE_REL).write_text("{ this is not json")

        w = _by_id(weaknesses.read_weaknesses(), "source:remediation-queue:malformed")
        assert w["severity"] == "high", (
            "a file that exists and does not parse is a defect wherever it lives; "
            "an absent optional file may just be an organ nobody installed"
        )

    def test_an_optional_host_source_absent_is_info_but_still_visible(
        self, repo, state, weaknesses
    ):
        (state / "cortex-corpus-diff.json").unlink()

        payload = weaknesses.read_weaknesses()
        w = _by_id(payload, "source:corpus-diff:unavailable")
        assert w["severity"] == "info"
        assert payload["complete"] is False, (
            "an optional source that did not report still means the list is partial"
        )

    def test_an_empty_fee_table_is_format_drift_not_thirteen_closed_fees(
        self, repo, weaknesses
    ):
        (repo / "docs" / "hidden_fees" / "README.md").write_text("# Hidden fees\n\nno table\n")

        w = _by_id(weaknesses.read_weaknesses(), "source:hidden-fees:malformed")
        assert "zero rows" in w["evidence"]["detail"]

    def test_a_source_that_raises_does_not_blank_the_list(
        self, repo, weaknesses, monkeypatch
    ):
        def boom(_dirty):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(weaknesses, "_source_scan_state", boom)
        payload = weaknesses.read_weaknesses()

        assert "source:scan-state:malformed" in _ids(payload)
        assert "kaboom" in _by_id(payload, "source:scan-state:malformed")["evidence"]["detail"]
        assert any(w["source"] == "remediation-queue" for w in payload["weaknesses"]), (
            "one exploding source must not take the other four with it"
        )

    def test_an_empty_corpus_ledger_is_not_an_agreeing_one(self, repo, state, weaknesses):
        (state / "cortex-corpus-diff.json").write_text(
            json.dumps({"version": 2, "nights": [], "agreeStreak": 0})
        )

        w = _by_id(weaknesses.read_weaknesses(), "corpus:no-nights-recorded")
        assert w["severity"] == "medium"


# ── The sources themselves ──────────────────────────────────────────────────


class TestRemediationQueue:
    def test_severity_is_gated_on_pending_status(self, repo, weaknesses):
        """37 CRITICAL items exist in the live file and ZERO are pending.
        Reading severity without the status gate reports a solved estate as
        catastrophic — and then nobody reads the list at all."""
        (repo / QUEUE_REL).write_text(
            json.dumps(make_queue(pending=[("HIGH", "gitea")], resolved=5))
        )

        payload = weaknesses.read_weaknesses()
        rem_ids = [w for w in payload["weaknesses"] if w["source"] == "remediation-queue"]
        assert [w["weakness_id"] for w in rem_ids] == ["rem:REM-001"]
        assert payload["counts"]["critical"] == 0

    def test_counts_are_derived_from_items_and_the_summary_is_audited(
        self, repo, weaknesses
    ):
        """Measured at HEAD: summary claimed 121/19 while items[] gave 128/12 —
        wrong by 7 in BOTH directions. Never read the summary; DO report that
        it disagrees."""
        (repo / QUEUE_REL).write_text(
            json.dumps(
                make_queue(
                    pending=[("HIGH", "gitea")],
                    resolved=2,
                    summary_by_status={"pending": 19, "resolved": 121},
                )
            )
        )

        w = _by_id(weaknesses.read_weaknesses(), "rem:summary-disagrees-with-items")
        assert w["evidence"]["recomputed_by_status"] == {"pending": 1, "resolved": 2}
        assert w["evidence"]["deltas"] == {"pending": 18, "resolved": 119}

    def test_an_agreeing_summary_is_silent(self, repo, weaknesses):
        (repo / QUEUE_REL).write_text(
            json.dumps(
                make_queue(
                    pending=[("HIGH", "gitea")],
                    resolved=2,
                    summary_by_status={"pending": 1, "resolved": 2},
                )
            )
        )
        assert "rem:summary-disagrees-with-items" not in _ids(weaknesses.read_weaknesses())


class TestHiddenFees:
    def test_closed_rows_are_excluded_and_open_ones_carry_their_file(
        self, repo, weaknesses
    ):
        payload = weaknesses.read_weaknesses()
        fee_ids = [w["weakness_id"] for w in payload["weaknesses"] if w["source"] == "hidden-fees"]
        assert "fee:03" not in fee_ids, "'**closed 2026-07-26**' is closed"
        assert {"fee:01", "fee:02", "fee:09"} <= set(fee_ids)
        assert _by_id(payload, "fee:01")["evidence"]["file"] == "docs/hidden_fees/01-alpha.md"
        assert "override" in _by_id(payload, "fee:01")["evidence"]["the_fee"]

    def test_a_fee_being_paid_now_outranks_a_conditional_one(self, repo, weaknesses):
        payload = weaknesses.read_weaknesses()
        assert _by_id(payload, "fee:09")["severity"] == "high"   # "being paid now"
        assert _by_id(payload, "fee:01")["severity"] == "medium" # conditional
        assert _by_id(payload, "fee:02")["severity"] == "low"    # partly closed

    def test_a_file_status_that_contradicts_the_index_is_reported(self, repo, weaknesses):
        """Only 3 of 13 files carry a `**Status:**` line, so the index is the
        authority — but where both exist and disagree, nothing else notices."""
        p = repo / "docs" / "hidden_fees" / "01-alpha.md"
        p.write_text(p.read_text() + "\n**Status:** closed 2026-08-01\n")

        w = _by_id(weaknesses.read_weaknesses(), "fee:01:status-disagrees")
        assert w["evidence"]["index_status"] == "open"
        assert w["evidence"]["file_status"] == "closed 2026-08-01"


class TestCorpusDiff:
    def test_a_disagreeing_night_names_its_failing_clauses(self, repo, state, weaknesses):
        (state / "cortex-corpus-diff.json").write_text(
            json.dumps({
                "version": 2,
                "agreeStreak": 0,
                "halted": False,
                "nights": [{
                    "at": "2026-08-02T05:33:24+00:00",
                    "result": "disagree",
                    "clauses": {"fs ids": True, "taxonomy": False, "captures": False},
                }],
            })
        )

        w = _by_id(weaknesses.read_weaknesses(), "corpus:last-night-disagrees")
        assert w["severity"] == "high"
        assert w["evidence"]["failing_clauses"] == ["captures", "taxonomy"]

    def test_halted_is_critical(self, repo, state, weaknesses):
        (state / "cortex-corpus-diff.json").write_text(
            json.dumps({"version": 2, "halted": True, "nights": [
                {"at": "2026-08-02T05:33:24+00:00", "result": "agree", "clauses": {}}
            ]})
        )
        assert _by_id(weaknesses.read_weaknesses(), "corpus:halted")["severity"] == "critical"


# ── Shape: hashing, ranking, filters ────────────────────────────────────────


class TestEvidenceHashing:
    def test_evidence_sha_is_stable_across_reads_of_an_unchanged_estate(
        self, repo, weaknesses
    ):
        a = {w["weakness_id"]: w["evidence_sha"] for w in weaknesses.read_weaknesses()["weaknesses"]}
        b = {w["weakness_id"]: w["evidence_sha"] for w in weaknesses.read_weaknesses()["weaknesses"]}
        assert a == b and a, "an unstable evidence hash lifts every dedup block for free"

    def test_the_passage_of_time_does_not_change_evidence_sha(self, repo, weaknesses):
        """`observed` holds ages and skews; `evidence` holds what the source
        SAYS. If age_days were hashed, every block would lift once a day."""
        (repo / SCAN_REL).write_text(
            json.dumps(make_scan_state(last_full_scan="2026-01-01T00:00:00Z"))
        )
        w = _by_id(weaknesses.read_weaknesses(), "scan:stale-full-scan")

        assert "age_days" in w["observed"] and "age_days" not in w["evidence"]
        recomputed = weaknesses.Weakness(
            weakness_id=w["weakness_id"], source=w["source"], severity=w["severity"],
            title=w["title"], evidence=w["evidence"],
            observed={"age_days": 99999, "totally": "different"},
        )
        assert recomputed.evidence_sha == w["evidence_sha"]

    def test_a_changed_source_fact_changes_the_hash(self, repo, weaknesses):
        (repo / QUEUE_REL).write_text(json.dumps(make_queue(pending=[("HIGH", "gitea")])))
        before = _by_id(weaknesses.read_weaknesses(), "rem:REM-001")["evidence_sha"]

        doc = make_queue(pending=[("HIGH", "gitea")])
        doc["items"][0]["fix_version"] = "2.0.0"
        (repo / QUEUE_REL).write_text(json.dumps(doc))

        after = _by_id(weaknesses.read_weaknesses(), "rem:REM-001")["evidence_sha"]
        assert before != after, "contract §4: a block lifts when the evidence moves"


class TestRankingAndFilters:
    def test_ranking_is_source_order_then_severity_then_id(self, repo, weaknesses):
        (repo / QUEUE_REL).write_text(
            json.dumps(make_queue(pending=[("LOW", "a"), ("CRITICAL", "b")]))
        )
        payload = weaknesses.read_weaknesses()

        order = {n: i for i, n in enumerate(weaknesses.SOURCE_ORDER)}
        keys = [
            (order[w["source"]], list(weaknesses.SEVERITIES).index(w["severity"]), w["weakness_id"])
            for w in payload["weaknesses"]
        ]
        assert keys == sorted(keys)

    def test_git_worktree_leads_the_declared_source_order(self, weaknesses):
        assert weaknesses.SOURCE_ORDER[0] == "git-worktree", (
            "requirement 1: it is the only finding here with no other reporter"
        )

    def test_ranking_is_deterministic(self, repo, weaknesses):
        assert _ids(weaknesses.read_weaknesses()) == _ids(weaknesses.read_weaknesses())

    def test_min_severity_filters_without_changing_the_total(self, repo, weaknesses):
        payload = weaknesses.read_weaknesses(min_severity="high")
        assert payload["weaknesses"], "fixture has at least one high"
        assert all(w["severity"] in ("critical", "high") for w in payload["weaknesses"])

    def test_top_truncates_the_list_but_counts_stay_honest(self, repo, weaknesses):
        full = weaknesses.read_weaknesses()
        capped = weaknesses.read_weaknesses(top=1)
        assert capped["returned"] == 1
        assert capped["counts"]["total"] == full["counts"]["total"], (
            "a truncated view must not report a smaller estate"
        )


# ── The route ───────────────────────────────────────────────────────────────


class TestRoute:
    def test_either_identity_may_read(self, client):
        for token in (PROPOSE_TOKEN, JUDGE_TOKEN):
            r = client.get(
                "/api/v1/loop/weaknesses", headers={"Authorization": f"Bearer {token}"}
            )
            assert r.status_code == 200, r.text
            assert "weaknesses" in r.json()

    def test_filters_are_the_only_input(self, client):
        """Nothing a caller sends can set a severity, a title or an evidence
        field. The route accepts no body at all."""
        r = client.request(
            "GET",
            "/api/v1/loop/weaknesses",
            headers={"Authorization": f"Bearer {PROPOSE_TOKEN}"},
            json={"weaknesses": [{"weakness_id": "forged", "severity": "info"}]},
        )
        assert r.status_code == 200
        assert "forged" not in [w["weakness_id"] for w in r.json()["weaknesses"]]

    def test_unknown_source_is_refused_not_silently_empty(self, client):
        r = client.get(
            "/api/v1/loop/weaknesses?source=nope",
            headers={"Authorization": f"Bearer {PROPOSE_TOKEN}"},
        )
        assert r.status_code == 400

    def test_unknown_severity_is_refused_not_coerced_to_info(self, client):
        r = client.get(
            "/api/v1/loop/weaknesses?min_severity=urgent",
            headers={"Authorization": f"Bearer {PROPOSE_TOKEN}"},
        )
        assert r.status_code == 400, (
            "coercing an unknown floor to 'info' would silently widen the filter"
        )
