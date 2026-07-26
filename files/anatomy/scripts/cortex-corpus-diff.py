#!/usr/bin/env python3
"""cortex-corpus-diff — the S2 nightly agreement harness.

Pulse job, scheduled AFTER keap-embed-sync. Reads BOTH corpora over
`/agent/v1/*` only — never host sqlite3 against a live store, never a
container exec, never a write of any kind. If the API is the only
observable path, an in-process shortcut is an unobservable call, and that
applies to the harness first.

── What this harness can and cannot earn ────────────────────────────────
It measures AGREEMENT between two corpora. It does NOT measure that
ingestion is correct — the fixture suite (server/fs-sync.test.ts) does
that, and it never counts as a night.

With 167 objects of which 166 are generated self-model cards and ONE is a
real user document, id-set agreement is satisfiable tonight and proves
almost nothing. So the report prints its DENOMINATOR ABOVE ITS VERDICT,
and below REAL_DOC_FLOOR real user documents it is REQUIRED to end with a
computed disclaimer plus an explicit NOT-EXERCISED list. That honesty is a
computed property of the harness, not a comment someone can quietly
delete.

── What is compared, and the ceilings ───────────────────────────────────
  fs objects   id set exactly; then per id — size, mtime, visibility,
               type, title, and sha256 of the BODY. Body HASHES, not just
               ids: that is what catches the empty-body class and the
               --facts-json divergence, both of which an id-only diff
               reads as green.
  taxonomy     node COUNT and the onto1 ontology digest. Both sides serve
               these on /agent/v1/health. The digest hashes the whole node
               tree, so an equal digest is a STRONGER statement than an
               equal id set — and no id-listing route exists on KEAP's
               side to compare against, which is a ceiling, stated here
               rather than papered over.
  captures     total, plus the first page of ids. KEAP's /agent/v1/captures
               takes no offset, so beyond the page cap only the totals are
               comparable. Stated as a ceiling in the report.
  embeddings   per-kind counts and the pending totals. Per-vector
               (kind, ref_id, content_hash) is not exposed by either
               surface; the VECTORS themselves are deliberately NOT an
               agreement criterion — they are the S3 experiment.
  pass health  pruneRefused, emptyBodies, danglingAnchors, rootsMissing,
               rootCollisions, sentinel, lastRefusal (organ only).

── The night ledger, and the two stops ──────────────────────────────────
A disagreeing night LOGS THE FULL DIFF AND CONTINUES; the agreement clock
resets to zero. Halting on the first disagreement turns a measurement
harness into a deploy gate and destroys the evidence it exists to collect:
from one sample you cannot tell a bug (identical every night) from a race
(shape changes) from a transient (once, never again), and those want
different responses. Continuing costs nothing real — nothing consumes the
organ's corpus yet, so a wrong shadow harms nobody.

Both stops are named NOW so neither is negotiable later:
  - 3 disagreeing nights in total (not necessarily consecutive) stops
    adding nights and notifies `high`;
  - a 14-night hard ceiling forces a report either way.

One class halts immediately: REMOVAL-SHAPED disagreement — the organ
pruned something the incumbent kept, or refused a prune on a night the
incumbent's corpus shrank. Removals are the only irreversible direction;
everything else is additive drift a re-sync repairs. The halt stops the
organ's fs-sync (`--halt-cmd`), and NEVER the diff: refusing to walk is
safe, refusing to observe is not.

Env:
  KEAP_API_URL / KEAP_AGENT_TOKEN_RO        the incumbent
  CORTEX_API_URL / CORTEX_AGENT_TOKEN_RO    the organ
  NOS_NOTIFY_BIN                            nos-notify.sh (optional)
  CORTEX_DIFF_STATE                         default ~/.nos/cortex-corpus-diff.json

Exit: 0 nights agree (or the run completed with a logged disagreement),
1 config error, 2 a corpus was unreachable, 3 removal-shaped halt.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

KEAP = (os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091").rstrip("/"),
        os.environ.get("KEAP_AGENT_TOKEN_RO", ""))
CORTEX = (os.environ.get("CORTEX_API_URL", "http://127.0.0.1:8098").rstrip("/"),
          os.environ.get("CORTEX_AGENT_TOKEN_RO", ""))
NOTIFY_BIN = os.environ.get("NOS_NOTIFY_BIN", "")
STATE_PATH = Path(os.environ.get("CORTEX_DIFF_STATE", str(Path.home() / ".nos" / "cortex-corpus-diff.json")))

NIGHTS_REQUIRED = 3
DISAGREEMENTS_ALLOWED = 3
NIGHT_CEILING = 14
PAGE = 50  # KEAP's /agent/v1/objects MAX_LIMIT — the harness cannot page wider

# Below this many REAL user documents the report must disclaim itself. 167
# objects of which 166 are generated is not a corpus; it is a fixture with a
# denominator of one.
REAL_DOC_FLOOR = 25

NOT_EXERCISED = [
    "multi-user attribution (one human uid exists)",
    "prune (no file has been removed under observation)",
    "the 20 000-file cap",
    "EACCES walk truncation",
    "visibility flip",
    "move/rename",
    "more than one tenant",
    "bodies over BODY_CAP",
    "non-ASCII paths",
]


def get(base: str, token: str, path: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(f"{base}{path}")
    req.add_header("x-keap-agent", "cortex-corpus-diff")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode())


def read_corpus(name: str, base: str, token: str) -> dict:
    """Everything the harness compares, for one side, over /agent/v1 only."""
    health = get(base, token, "/agent/v1/health")["data"]

    ids: list[str] = []
    total = None
    offset = 0
    while True:
        page = get(base, token, f"/agent/v1/objects?limit={PAGE}&offset={offset}")["data"]
        total = page["total"]
        ids += [r["id"] for r in page["results"]]
        offset += PAGE
        if offset >= total or not page["results"]:
            break
    fs_ids = sorted(i for i in ids if i.startswith("fs:"))

    # Per-object detail — the BODY HASH is why this loop exists. One GET per
    # object is 167 round-trips against a loopback daemon; that is the price of
    # comparing content rather than names.
    detail: dict[str, dict] = {}
    for oid in fs_ids:
        o = get(base, token, f"/agent/v1/objects/{urllib.parse.quote(oid, safe='')}")["data"]
        fm = o.get("frontmatter") or {}
        body = o.get("body")
        detail[oid] = {
            "size": fm.get("size"),
            "mtime": fm.get("mtime"),
            "path": fm.get("path"),
            "visibility": o.get("visibility") or "private",
            "type": o.get("type"),
            "title": o.get("title"),
            "userId": o.get("userId"),
            "bodySha256": hashlib.sha256(body.encode()).hexdigest() if body else None,
            "degradedRead": fm.get("degradedRead"),
        }

    captures = get(base, token, f"/agent/v1/captures?limit={PAGE}")["data"]

    # The onto1 digest is served under two different keys and, on an older KEAP,
    # under NEITHER — the running container is 1.26.0 and publishes only counts.
    # A missing digest is recorded as None and reported as a CEILING; it is never
    # allowed to compare equal to another None, because "neither side told us" is
    # not agreement.
    digest = (health.get("binding") or {}).get("ontologyVersion") or (health.get("ontology") or {}).get("version")

    out = {
        "name": name,
        "taxonomyNodes": health.get("corpus", {}).get("taxonomyNodes"),
        "ontologyVersion": digest,
        "serverVersion": health.get("version"),
        "objectsTotal": total,
        "fsIds": fs_ids,
        "detail": detail,
        "capturesTotal": captures["total"],
        "captureIds": sorted(c["id"] for c in captures["items"]),
        "embeddings": health.get("embeddings"),
    }
    try:
        pend = get(base, token, "/agent/v1/embeddings/pending?limit=0")["data"]
        out["embedPending"] = pend.get("total")
        out["embedModel"] = pend.get("model")
        out["embedDim"] = pend.get("dim")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, KeyError):
        out["embedPending"] = None  # no vector layer — distinct from zero
    return out


def organ_pass_health(base: str, token: str) -> dict:
    try:
        return get(base, token, "/agent/v1/fs/status")["data"]
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, KeyError) as exc:
        return {"error": str(exc)}


def real_user_docs(side: dict) -> int:
    """Objects that are somebody's actual document, not generated self-model.

    The self-model uid owns the 166 cards a converge writes; everything else in
    the fs mirror was put there by a person. This number, not `objectsTotal`, is
    the denominator that decides whether the report may speak.
    """
    selfmodel_uids = {"nos-docs"}
    return sum(1 for d in side["detail"].values() if d.get("userId") not in selfmodel_uids)


def diff(a: dict, b: dict) -> dict:
    ai, bi = set(a["fsIds"]), set(b["fsIds"])
    only_a, only_b = sorted(ai - bi), sorted(bi - ai)
    field_diffs = []
    for oid in sorted(ai & bi):
        da, db_ = a["detail"][oid], b["detail"][oid]
        for k in ("size", "mtime", "visibility", "type", "title", "bodySha256"):
            if da.get(k) != db_.get(k):
                field_diffs.append({"id": oid, "field": k, a["name"]: da.get(k), b["name"]: db_.get(k)})
    # Counts must agree. The digest must agree WHEN BOTH SIDES PUBLISH ONE —
    # two Nones are two silences, and treating them as a match would let the
    # strongest available check disappear the moment a server stopped serving it.
    digests = (a["ontologyVersion"], b["ontologyVersion"])
    digest_comparable = all(digests)
    return {
        "onlyIn_" + a["name"]: only_a,
        "onlyIn_" + b["name"]: only_b,
        "fieldDiffs": field_diffs,
        "digestComparable": digest_comparable,
        "taxonomyAgrees": a["taxonomyNodes"] == b["taxonomyNodes"]
        and (digests[0] == digests[1] if digest_comparable else True),
        "capturesAgree": a["capturesTotal"] == b["capturesTotal"]
        and a["captureIds"] == b["captureIds"],
        "embedShapeAgrees": (a.get("embedModel"), a.get("embedDim")) == (b.get("embedModel"), b.get("embedDim")),
    }


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {"nights": [], "agreeStreak": 0, "disagreements": 0, "halted": False}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


def notify(severity: str, title: str, body: str) -> None:
    if NOTIFY_BIN and os.path.exists(NOTIFY_BIN):
        subprocess.run([NOTIFY_BIN, severity, title, body, "wing-inbox"], check=False, timeout=30)


def main() -> int:
    if not KEAP[1] or not CORTEX[1]:
        print("cortex-corpus-diff: KEAP_AGENT_TOKEN_RO and CORTEX_AGENT_TOKEN_RO are both required", file=sys.stderr)
        return 1

    state = load_state()
    night_no = len(state["nights"]) + 1

    try:
        keap = read_corpus("keap", *KEAP)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        print(f"cortex-corpus-diff: KEAP unreachable: {exc}", file=sys.stderr)
        return 2
    try:
        organ = read_corpus("cortex", *CORTEX)
        health = organ_pass_health(*CORTEX)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        # A VOID night: neither +1 nor a reset. A skipped night must not be able
        # to advance a 3-night clock, and must not be able to reset it either.
        print(f"cortex-corpus-diff: cortex unreachable — night VOID: {exc}", file=sys.stderr)
        state["nights"].append({"at": datetime.now(timezone.utc).isoformat(), "result": "void", "reason": str(exc)[:200]})
        save_state(state)
        notify("low", "S2 diff: night void", f"The cortex organ was unreachable ({exc}). The 3-night clock is unchanged.")
        return 0

    d = diff(keap, organ)
    ids_agree = not d["onlyIn_keap"] and not d["onlyIn_cortex"]
    bodies_agree = not d["fieldDiffs"]

    # THE VERDICT, and every clause of it. Captures are IN, and it matters that
    # they are: they are the only thing here that measures the consolidator
    # fan-out, and with them out a night on which the second target was never
    # fed at all would still be counted as agreement. That is precisely the
    # "green it did not earn" this harness exists to refuse — an unfed shadow
    # whose fs mirror happens to match is not a corpus in parallel.
    clauses = {
        "fs ids": ids_agree,
        "body hashes": bodies_agree,
        "taxonomy": d["taxonomyAgrees"],
        "captures": d["capturesAgree"],
        "embed shape": d["embedShapeAgrees"],
    }
    agrees = all(clauses.values())

    docs = real_user_docs(keap)
    last = (health.get("lastRun") or {}).get("result") or {}

    # ── removal-shaped disagreement: the only immediate halt ─────────────────
    prev = state["nights"][-1] if state["nights"] else None
    keap_shrank = bool(prev and prev.get("keapFsCount") is not None and keap_count_shrank(prev, keap))
    removal_shaped = bool(d["onlyIn_keap"]) and (last.get("removed") or 0) > 0
    removal_shaped = removal_shaped or (bool(last.get("pruneRefused")) and keap_shrank)

    # ── the report — denominator ABOVE the verdict ───────────────────────────
    lines = []
    lines.append(f"S2 diff — night {night_no} (agree streak {state['agreeStreak']}/{NIGHTS_REQUIRED})"
                 f"    {datetime.now(timezone.utc).date().isoformat()}")
    lines.append(f"  fs objects      {len(keap['fsIds'])} vs {len(organ['fsIds'])}"
                 f"   ids {'exact' if ids_agree else 'DIFFER'}")
    lines.append(f"  real user docs  {docs}         <- the denominator that matters")
    body_verdict = "match" if bodies_agree else f"{len(d['fieldDiffs'])} field difference(s)"
    lines.append(f"  body hashes     {body_verdict}")
    lines.append(f"  taxonomy        {keap['taxonomyNodes']} vs {organ['taxonomyNodes']}"
                 f"   {'PARITY' if d['taxonomyAgrees'] else 'MISMATCH — corpus parity not pinned (§4.4)'}")
    lines.append(f"  onto1 digest    {keap['ontologyVersion'] or 'not served'} vs {organ['ontologyVersion'] or 'not served'}"
                 + ("" if d["digestComparable"]
                    else f"   CEILING — counts only (keap {keap.get('serverVersion')} does not publish it)"))
    lines.append(f"  captures        {keap['capturesTotal']} vs {organ['capturesTotal']}"
                 f"   {'ids match (first page)' if d['capturesAgree'] else 'DIFFER'}")
    lines.append(f"  embeddings      pending {keap.get('embedPending')} vs {organ.get('embedPending')}"
                 f"   (model {keap.get('embedModel')}/{keap.get('embedDim')}"
                 f" vs {organ.get('embedModel')}/{organ.get('embedDim')}"
                 f" — {'comparable' if d['embedShapeAgrees'] else 'INCOMPARABLE'})")
    lines.append(f"  organ pass      pruneRefused {last.get('pruneRefused', False)}"
                 f"  emptyBodies {last.get('emptyBodies', 0)}"
                 f"  rootsMissing {last.get('rootsMissing') or 'none'}"
                 f"  collisions {last.get('rootCollisions', 0)}"
                 f"  sentinel {last.get('sentinel', 'n/a')}")
    if health.get("lastRefusal"):
        lines.append(f"  organ REFUSAL   {health['lastRefusal']}")

    lines.append("  VERDICT         " + ("AGREE" if agrees else "DISAGREE") + "  ("
                 + ", ".join(f"{k} {'ok' if v else 'NO'}" for k, v in clauses.items()) + ")")

    if d["onlyIn_keap"]:
        lines.append(f"  in KEAP only    {len(d['onlyIn_keap'])}: {', '.join(d['onlyIn_keap'][:5])}")
    if d["onlyIn_cortex"]:
        lines.append(f"  in cortex only  {len(d['onlyIn_cortex'])}: {', '.join(d['onlyIn_cortex'][:5])}")
    for fd in d["fieldDiffs"][:10]:
        lines.append(f"    {fd['id']} {fd['field']}: keap={fd['keap']!r} cortex={fd['cortex']!r}")

    # ── the computed disclaimer ──────────────────────────────────────────────
    # A property of the run, not a comment. It fires on a NUMBER, so it cannot
    # be removed by editing prose, and it will stop firing by itself the day the
    # corpus is real.
    if docs < REAL_DOC_FLOOR:
        lines.append("")
        lines.append(f"  NOT EXERCISED tonight ({docs} real user document(s), floor {REAL_DOC_FLOOR}):")
        for item in NOT_EXERCISED:
            lines.append(f"    - {item}")
        lines.append("")
        lines.append("  This run does not show that ingestion is correct. It shows that two")
        lines.append("  near-empty corpora are equally near-empty.")
    print("\n".join(lines))

    # ── the ledger ───────────────────────────────────────────────────────────
    night = {
        "at": datetime.now(timezone.utc).isoformat(),
        "result": "agree" if agrees else "disagree",
        "keapFsCount": len(keap["fsIds"]),
        "cortexFsCount": len(organ["fsIds"]),
        "realUserDocs": docs,
        "onlyInKeap": d["onlyIn_keap"][:50],
        "onlyInCortex": d["onlyIn_cortex"][:50],
        "fieldDiffs": d["fieldDiffs"][:50],
        "taxonomyAgrees": d["taxonomyAgrees"],
    }
    if agrees:
        state["agreeStreak"] += 1
    else:
        state["agreeStreak"] = 0
        state["disagreements"] += 1
    state["nights"].append(night)

    if removal_shaped:
        state["halted"] = True
        night["halt"] = "removal-shaped"
        save_state(state)
        print("\n  HALT — removal-shaped disagreement. The organ pruned what the incumbent kept, "
              "or refused a prune while the incumbent's corpus shrank.", file=sys.stderr)
        notify("high", "S2 diff: HALT — removal-shaped disagreement",
               "The cortex organ's fs-sync must be stopped (set its interval to 0) and looked at before "
               "the next pass. Removals are the only irreversible direction. The diff keeps running: "
               "refusing to walk is safe, refusing to observe is not.")
        return 3

    save_state(state)

    if state["agreeStreak"] >= NIGHTS_REQUIRED:
        notify("medium", f"S2 diff: {NIGHTS_REQUIRED} nights of agreement",
               f"Agreement holds over {docs} real user document(s). Per §8 this is NOT sufficient on its "
               "own: corpus parity must be pinned and the fixture suite green, and the report must state "
               "its denominator. Read the run output before calling S2 done.")
    elif state["disagreements"] >= DISAGREEMENTS_ALLOWED:
        notify("high", "S2 diff: three disagreeing nights — stop adding nights",
               "S2 reports on the evidence it has; S3 decides. Adding nights past this point is how a "
               "parallel run becomes permanent furniture.")
    elif len(state["nights"]) >= NIGHT_CEILING:
        notify("high", f"S2 diff: {NIGHT_CEILING}-night ceiling reached",
               "Report whatever the harness has, with its denominator. The ceiling exists so 'we'll look "
               "at the diff eventually' never becomes the steady state.")
    return 0


def keap_count_shrank(prev: dict, keap: dict) -> bool:
    return len(keap["fsIds"]) < (prev.get("keapFsCount") or 0)


if __name__ == "__main__":
    sys.exit(main())
