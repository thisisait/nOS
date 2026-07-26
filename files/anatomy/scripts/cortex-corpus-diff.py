#!/usr/bin/env python3
"""cortex-corpus-diff — the S2 corpus agreement harness.

Pulse job, scheduled AFTER keap-embed-sync. Reads BOTH corpora over
`/agent/v1/*` only — never host sqlite3 against a live store, never a
container exec, never a write of any kind to either store. If the API is
the only observable path then an in-process shortcut is an unobservable
call, and that rule applies to the harness before it applies to anything
else.

Two corpora are built INDEPENDENTLY from one set of host sources. They
should converge. This measures whether they did.

── Why a bare red light would be worthless ──────────────────────────────
A harness that prints "DISAGREE" and stops has told you the one thing you
already suspected and none of the things you need. The whole reason to
run two builders in parallel rather than migrating one into the other is
that a DIFFERENCE IS A MEASUREMENT: each side is a check on the other, so
a disagreement should name which side is wrong and what to do about it.

So every disagreement here is ADJUDICATED, and the adjudication is not
guesswork — it appeals to a third party that neither corpus controls:

  the filesystem   For an fs-mirror object, the host tree is the referee.
                   `os.stat` on the file the row claims to describe
                   settles "the organ's reader missed it" against "KEAP
                   kept a row for a deleted file" — and, for a row both
                   sides hold with different size/mtime, settles WHICH
                   side read a stale copy, because one of them matches
                   the bytes on disk and the other does not.
  the repo         For a taxonomy node, `knowledge/canonical` at the
                   pinned ref is the referee. A node in the repo and in
                   KEAP but not the organ means the organ's store was
                   never re-materialised; the same node missing from KEAP
                   means the CONTAINER is behind the pin. Same
                   observation, opposite culprit, and only the referee
                   tells them apart.
  the feeder state `~/.nos/keap-consolidate-state.json`. A capture count
                   that differs because the fan-out has never recorded a
                   signature for a target is a job that has not run, not
                   an ingestion defect.

Where no referee can reach, the harness says `unknown` and says why. It
never picks a culprit it cannot evidence.

── What is compared, table by table ─────────────────────────────────────
  knowledge_objects   full id set both ways, plus per shared id: size,
                      mtime, visibility, type, title and sha256 of the
                      BODY. Body HASHES, not just ids — that is what
                      catches the empty-body class and the --facts-json
                      divergence, both of which an id-only diff reads as
                      green.
  taxonomy nodes      full id set both ways, via /agent/v1/graph. Until
                      that route existed on the organ this was a COUNT
                      comparison, and a count passes two DIFFERENT
                      1841-node trees as parity.
  embeddings          model, dimension, per-kind row counts, and the
                      REF SET actually embedded for every kind whose
                      sources this harness can enumerate (objects, and
                      taxonomy when both sides serve the graph). Vectors
                      themselves are deliberately NOT an agreement
                      criterion — the index asymmetry is the S3
                      experiment, not a defect.
  captures            total, plus ids as far as the page cap reaches.
  curated notes       count only; neither side lists ids. Stated ceiling.
  relations           edge + verb counts from the graph.
  pass health         pruneRefused, emptyBodies, danglingAnchors,
                      rootsMissing, rootCollisions, sentinel, lastRefusal.

Every ceiling is printed. Two missing values NEVER compare equal: "neither
side told us" is not agreement, and a check that quietly disappears when a
server stops serving it is worse than no check.

── The one call that is not a pure read ─────────────────────────────────
`GET /agent/v1/embeddings/pending` runs `pendingEmbeddings()`, which
PRUNES vectors whose source row is gone. It is the only wire path that
publishes the model, the dimension and the pending diff, so the harness
calls it — and then asserts the `pruned` it got back is 0. A non-zero
value means the harness itself mutated a store, and it is reported as
such, at `high`, under its own verdict. A tool that writes while claiming
not to is worse than one that admits it.

── The night ledger, and the two stops ──────────────────────────────────
A disagreeing night LOGS THE FULL DIFF AND CONTINUES; the agreement clock
resets to zero. Halting on the first disagreement turns a measurement
harness into a deploy gate and destroys the evidence it exists to collect:
from one sample you cannot tell a bug (identical every night) from a race
(shape changes nightly) from a transient (once, never again), and those
three want different responses. Continuing costs nothing real — nothing
consumes the organ's corpus yet, so a wrong shadow harms nobody.

Both stops are named NOW so neither is negotiable later: 3 disagreeing
nights in total stop the run and notify `high`; a 14-night ceiling forces
a report either way.

One class halts immediately: REMOVAL-SHAPED disagreement — the organ
pruned something the incumbent kept, or refused a prune on a night the
incumbent's corpus shrank. Removals are the only irreversible direction;
everything else is additive drift a re-sync repairs. The halt stops the
organ's fs-sync (`--halt-cmd`) and NEVER the diff: refusing to walk is
safe, refusing to observe is not.

── What this harness cannot earn ────────────────────────────────────────
It measures AGREEMENT. It does not measure that ingestion is CORRECT —
the fixture suite (`server/fs-sync.test.ts`) does that, and it never
counts as a night. With 167 objects of which 166 are generated self-model
cards and ONE is a real user document, id-set agreement is satisfiable
tonight and proves almost nothing. So the report prints its DENOMINATOR
ABOVE ITS VERDICT and, below REAL_DOC_FLOOR real user documents, is
required to end with a computed disclaimer and an explicit NOT-EXERCISED
list. That honesty fires on a NUMBER, so it cannot be removed by editing
prose, and it will stop firing by itself the day the corpus is real.

Env:
  KEAP_API_URL / KEAP_AGENT_TOKEN_RO        the incumbent
  CORTEX_API_URL / CORTEX_AGENT_TOKEN_RO    the organ
  NOS_NOTIFY_BIN                            nos-notify.sh (optional)
  CORTEX_DIFF_STATE                         ~/.nos/cortex-corpus-diff.json
  NOS_CONSOLIDATE_STATE                     ~/.nos/keap-consolidate-state.json

Flags:
  --json           machine-readable report on stdout, nothing else
  --no-ledger      do not record a night (ad-hoc run)
  --halt-cmd CMD   run on a removal-shaped halt (stops the organ's fs-sync)
  --canonical-dir  taxonomy referee; default: the repo tree beside this script
  --keap-url/--cortex-url/--keap-token/--cortex-token  override the env

Exit: 0 the run completed (agreeing or not), 1 config error, 2 the
incumbent was unreachable, 3 removal-shaped halt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# The ledger's own version. A night measured by an older, weaker harness must
# not count toward a clock this one owns — so a version change RETIRES the
# streak rather than inheriting it. The nights are kept for the record.
LEDGER_VERSION = 2

NIGHTS_REQUIRED = 3
DISAGREEMENTS_ALLOWED = 3
NIGHT_CEILING = 14

# KEAP's /agent/v1/objects MAX_LIMIT. The organ's is deliberately identical, so
# this is one paging loop against both sides.
PAGE = 50

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

# ── the adjudication vocabulary ──────────────────────────────────────────────
# `culprit` answers "whose defect is this?" and is the field an operator reads
# first. It is deliberately small, and `config`/`neither`/`unknown` are real
# answers rather than a shrug: most first-run disagreements are neither corpus
# being wrong, and a harness that can only blame a corpus will blame the wrong
# thing loudly.
CULPRIT_ORGAN = "organ"      # the organ's reader/store is wrong
CULPRIT_KEAP = "keap"        # the incumbent's reader/store is wrong or stale
CULPRIT_CONFIG = "config"    # both are behaving; they were pointed at different things
CULPRIT_FEEDER = "feeder"    # the fan-out job, not either store
CULPRIT_NEITHER = "neither"  # expected divergence, or not attributable yet
CULPRIT_UNKNOWN = "unknown"  # no referee could reach this case — said, not guessed


@dataclass
class Finding:
    """One adjudicated disagreement. `because` carries the EVIDENCE that picked
    the culprit; `action` is what to do next. A finding without evidence is an
    opinion, and this harness does not publish opinions."""

    table: str
    case: str
    ident: str
    culprit: str
    verdict: str
    because: str
    action: str
    detail: dict = field(default_factory=dict)


# ── uid slug (byte-exact port of server/uid.ts::slugifyUid) ──────────────────
# Needed to map an object's `userId` back onto the DIRECTORY NAME under a
# `child-dirs` root — the folder is 'Pázny', the uid is 'pazny'. Without this
# the filesystem referee cannot resolve a path, and an unresolvable referee
# turns every adjudication into `unknown`.
_COMBINING = re.compile(r"[̀-ͯ]")
_NONALNUM = re.compile(r"[^a-z0-9]+")


def slugify_uid(raw: str | None) -> str:
    s = unicodedata.normalize("NFKD", raw or "")
    s = _COMBINING.sub("", s).lower()
    s = _NONALNUM.sub("-", s).strip("-")[:64].strip("-")
    return s


# ── read-only HTTP client ────────────────────────────────────────────────────


class Unreachable(Exception):
    """A side could not be read at all — distinct from a route it does not serve."""


def get(base: str, token: str, path: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(f"{base}{path}")
    req.add_header("x-keap-agent", "cortex-corpus-diff")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode())


def get_or_none(base: str, token: str, path: str, timeout: int = 60) -> dict | None:
    """A route this side does not serve is a CEILING, not a failure. Returns
    None so the caller can state the ceiling instead of pretending agreement."""
    try:
        return get(base, token, path, timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        return None


# ── one side's corpus, as read over the wire ─────────────────────────────────


@dataclass
class Side:
    name: str
    serverVersion: str | None = None
    # per-table row counts
    taxonomyNodes: int | None = None
    curatedNotes: int | None = None
    objectsTotal: int | None = None
    capturesTotal: int | None = None
    embedTotal: int | None = None
    embedByKind: dict = field(default_factory=dict)
    relationEdges: int | None = None
    relationTypes: int | None = None
    # id sets
    objectIds: list = field(default_factory=list)
    objectMeta: dict = field(default_factory=dict)   # id -> {userId,type,title}
    objectDetail: dict = field(default_factory=dict)  # id -> digest fields
    taxonomyIds: list | None = None                   # None = route not served
    captureIds: list = field(default_factory=list)
    capturesComplete: bool = False
    # embeddings
    embedModel: str | None = None
    embedDim: int | None = None
    embedPending: int | None = None
    embedPruned: int | None = None
    pendingRefs: dict = field(default_factory=dict)   # kind -> {refId: contentHash}
    pendingComplete: bool = False
    # ontology digest (None on a server that does not publish one)
    ontologyVersion: str | None = None
    # fs pass
    fsStatus: dict = field(default_factory=dict)
    sharedUids: list = field(default_factory=list)
    userRoots: list = field(default_factory=list)

    @property
    def fsIds(self) -> list:
        return [i for i in self.objectIds if i.startswith("fs:")]

    @property
    def lastPass(self) -> dict:
        return (self.fsStatus.get("lastRun") or {}).get("result") or {}

    @property
    def lastPassAt(self) -> str | None:
        return (self.fsStatus.get("lastRun") or {}).get("at")

    @property
    def passDegraded(self) -> str | None:
        """Why this side's last pass cannot be read as a clean walk — or None.

        This gate exists so a degraded pass is never adjudicated as a reader
        bug. A truncated walk explains a missing id perfectly well, and blaming
        the derivation for it sends the operator to the wrong file."""
        if self.fsStatus.get("lastRefusal"):
            return f"the pass was REFUSED ({self.fsStatus['lastRefusal']})"
        r = self.lastPass
        if not r:
            return "no pass has run"
        if r.get("pruneRefused"):
            return "the pass refused its prune (found-set not trusted)"
        if r.get("rootsMissing"):
            return f"configured roots were absent: {r['rootsMissing']}"
        if r.get("skipped") == -1:
            return "the pass hit the file cap and truncated its found-set"
        if r.get("sentinel") not in (None, "ok", "not-configured"):
            return f"the mount sentinel read {r.get('sentinel')!r}"
        return None


def read_side(name: str, base: str, token: str, with_bodies: bool = True) -> Side:
    """Everything the harness compares, for one side, over /agent/v1 only."""
    try:
        health = get(base, token, "/agent/v1/health")["data"]
    except Exception as exc:  # noqa: BLE001 — every failure here means "cannot read"
        raise Unreachable(str(exc)) from exc

    s = Side(name=name)
    s.serverVersion = health.get("version")
    corpus = health.get("corpus") or {}
    s.taxonomyNodes = corpus.get("taxonomyNodes")
    s.curatedNotes = corpus.get("curatedNotes")
    emb = health.get("embeddings") or {}
    s.embedTotal = emb.get("total")
    s.embedByKind = emb.get("byKind") or {}
    # Served under two different keys, and on KEAP 1.26.0 under NEITHER.
    s.ontologyVersion = (health.get("binding") or {}).get("ontologyVersion") or (
        health.get("ontology") or {}
    ).get("version")

    # ── knowledge_objects: the full id set, paged ─────────────────────────────
    ids: list[str] = []
    total = 0
    offset = 0
    while True:
        page = get(base, token, f"/agent/v1/objects?limit={PAGE}&offset={offset}")["data"]
        total = page["total"]
        for r in page["results"]:
            ids.append(r["id"])
            s.objectMeta[r["id"]] = {"userId": r.get("userId"), "type": r.get("type"), "title": r.get("title")}
        offset += PAGE
        if offset >= total or not page["results"]:
            break
    s.objectsTotal = total
    s.objectIds = sorted(ids)

    # ── per-object digests. One GET per fs object is 167 loopback round-trips;
    # that is the price of comparing CONTENT rather than names, and names are
    # exactly what an empty-body bug leaves intact.
    if with_bodies:
        for oid in s.fsIds:
            o = get(base, token, f"/agent/v1/objects/{urllib.parse.quote(oid, safe='')}")["data"]
            fm = o.get("frontmatter") or {}
            body = o.get("body")
            s.objectDetail[oid] = {
                "size": fm.get("size"),
                "mtime": fm.get("mtime"),
                "path": fm.get("path"),
                "visibility": o.get("visibility") or "private",
                "type": o.get("type"),
                "title": o.get("title"),
                "userId": o.get("userId"),
                "bodySha256": hashlib.sha256(body.encode()).hexdigest() if body else None,
                "bodyLen": len(body) if body else 0,
                "degradedRead": fm.get("degradedRead"),
                "fmv": fm.get("fmv"),
            }

    # ── taxonomy node ids (+ relation counts) via the graph ───────────────────
    graph = get_or_none(base, token, "/agent/v1/graph", timeout=120)
    if graph:
        g = graph["data"]
        s.taxonomyIds = sorted(n["id"] for n in g.get("nodes", []) if n.get("kind") == "node")
        s.relationEdges = len(g.get("edges", []))
        s.relationTypes = len(g.get("types", []))

    # ── captures ──────────────────────────────────────────────────────────────
    caps = get(base, token, f"/agent/v1/captures?limit={PAGE}")["data"]
    s.capturesTotal = caps["total"]
    s.captureIds = sorted(c["id"] for c in caps["items"])
    # KEAP's route takes no offset, so the id set is exact only while the whole
    # queue fits one page. Recorded rather than assumed.
    s.capturesComplete = s.capturesTotal <= PAGE

    # ── embeddings: model, dim, and the pending (missing-or-stale) ref set ────
    pend = get_or_none(base, token, "/agent/v1/embeddings/pending?limit=500")
    if pend:
        d = pend["data"]
        s.embedModel = d.get("model")
        s.embedDim = d.get("dim")
        s.embedPending = d.get("total")
        s.embedPruned = d.get("pruned")
        s.pendingComplete = (d.get("total") or 0) <= 500
        for it in d.get("items") or []:
            s.pendingRefs.setdefault(it["kind"], {})[it["refId"]] = it.get("contentHash")

    # ── the fs pass ───────────────────────────────────────────────────────────
    st = get_or_none(base, token, "/agent/v1/fs/status")
    if st:
        s.fsStatus = st["data"]
        s.sharedUids = s.fsStatus.get("sharedUids") or []
        s.userRoots = s.fsStatus.get("userRoots") or []
    return s


# ── referee 1: the host filesystem ───────────────────────────────────────────


class HostReferee:
    """`os.stat` on the file a row claims to describe.

    This is the only impartial party in an fs disagreement. Both corpora are
    derived from this tree; neither controls it; and it answers the one question
    that separates "the reader missed a file" from "the store kept a row for a
    file that is gone".

    STRICTLY READ-ONLY, and it must stay that way: `{{ nos_data_root }}/tenants/
    <slug>/users` is real user data. Nothing here opens a file — `os.stat` only —
    so there is no path by which this can read a document's contents, let alone
    write one.

    Roots come from the ORGAN's /agent/v1/fs/status, because those are host
    paths. KEAP's `dir` is `/user-files`, a path inside a container, which no
    host process can resolve — so KEAP's own view cannot referee itself, which
    is rather the point of a referee.
    """

    def __init__(self, roots: list[dict]):
        self.roots = roots
        self.available = bool(roots)
        # uid -> [candidate absolute directory] per root, resolved once.
        self._uid_dirs: dict[str, list[str]] = {}
        for r in roots:
            spec, path = r.get("spec") or "", r.get("path") or ""
            if not path:
                continue
            if spec.startswith("literal:"):
                self._uid_dirs.setdefault(spec.split(":", 1)[1].strip(), []).append(path)
            elif spec == "child-dirs":
                try:
                    entries = sorted(os.listdir(path))
                except OSError:
                    continue
                for name in entries:
                    child = os.path.join(path, name)
                    if os.path.isdir(child):
                        # The folder name is slugified into the uid, so the uid
                        # alone cannot rebuild the path — 'Pázny' -> 'pazny'.
                        self._uid_dirs.setdefault(slugify_uid(name), []).append(child)

    def known_uids(self) -> set[str]:
        return set(self._uid_dirs)

    def stat(self, uid: str | None, rel_path: str | None) -> dict:
        """-> {'state': 'exists'|'absent'|'unresolvable', 'size':…, 'mtime':…}

        `unresolvable` is a first-class answer: no configured root can produce
        this uid at all, which is a CONFIGURATION difference between the two
        deployments and not a corpus defect. Collapsing it into 'absent' would
        blame a reader for a root it was never given."""
        if not self.available or not uid or not rel_path:
            return {"state": "unresolvable", "why": "no host roots available to this harness"}
        dirs = self._uid_dirs.get(uid)
        if not dirs:
            return {"state": "unresolvable", "why": f"no configured root derives uid {uid!r}"}
        for d in dirs:
            abs_path = os.path.join(d, rel_path)
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            return {"state": "exists", "size": st.st_size, "mtime": int(st.st_mtime), "path": abs_path}
        return {"state": "absent", "tried": [os.path.join(d, rel_path) for d in dirs]}


# ── referee 2: the pinned canonical tree in the repo ─────────────────────────


def read_canonical_ids(canonical_dir: Path | None) -> set[str] | None:
    """Node ids of the canonical taxonomy at the ref this checkout is pinned to.

    The organ materialises its store FROM this tree, and KEAP's container
    ingests the same tree at whatever tag it was built from. So the tree is the
    referee that separates "the organ's store was never re-materialised" from
    "the running container is behind the pin" — two observations that look
    identical in an id diff and have opposite fixes."""
    if not canonical_dir or not canonical_dir.is_dir():
        return None
    ids: set[str] = set()

    def walk(obj) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("id"), str):
                ids.add(obj["id"])
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for p in sorted(canonical_dir.rglob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            walk(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return ids or None


# ── referee 3: the fan-out's own state ledger ────────────────────────────────


def read_feeder_state(path: Path) -> dict:
    """-> {'version': 1|2, 'targets': {name: signature-count}}

    A v1 file has no target dimension at all, which is itself the answer to
    "why do the capture counts differ": the fan-out has never run."""
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"version": None, "targets": {}}
    if isinstance(d.get("targets"), dict):
        return {
            "version": d.get("version", 2),
            "targets": {k: sum(len(v) for v in t.values() if isinstance(v, dict)) for k, t in d["targets"].items()},
        }
    return {"version": 1, "targets": {"keap": sum(len(v) for v in d.values() if isinstance(v, dict))}}


# ── the comparison ───────────────────────────────────────────────────────────


@dataclass
class TableDiff:
    name: str
    keapRows: int | None
    organRows: int | None
    both: int | None = None
    onlyKeap: list = field(default_factory=list)
    onlyOrgan: list = field(default_factory=list)
    comparable: bool = True
    ceiling: str | None = None

    @property
    def ids_agree(self) -> bool:
        return self.comparable and not self.onlyKeap and not self.onlyOrgan

    @property
    def counts_agree(self) -> bool:
        return self.keapRows == self.organRows


def _id_table(name: str, keap_ids, organ_ids, keap_rows=None, organ_rows=None,
              ceiling: str | None = None) -> TableDiff:
    if keap_ids is None or organ_ids is None:
        return TableDiff(
            name=name,
            keapRows=keap_rows,
            organRows=organ_rows,
            comparable=False,
            ceiling=ceiling or "one side does not serve an id listing — counts only",
        )
    k, o = set(keap_ids), set(organ_ids)
    return TableDiff(
        name=name,
        keapRows=keap_rows if keap_rows is not None else len(k),
        organRows=organ_rows if organ_rows is not None else len(o),
        both=len(k & o),
        onlyKeap=sorted(k - o),
        onlyOrgan=sorted(o - k),
        ceiling=ceiling,
    )


DIGEST_FIELDS = ("size", "mtime", "visibility", "type", "title", "bodySha256")


def adjudicate_objects(keap: Side, organ: Side, fs: HostReferee) -> tuple[TableDiff, list[Finding]]:
    """The object id set, and a named culprit for every id that is not on both.

    The two asymmetries this must respect, or it will lie:
      - KEAP serves surfaces the organ does not (`/agent/v1/tables` writes
        `table-*` objects). Those rows are NOT fs-mirror rows and their absence
        from the organ is correct behaviour, not a missed read.
      - a degraded pass on either side explains a missing id perfectly well, and
        must pre-empt every reader verdict.
    """
    t = _id_table("knowledge_objects", keap.objectIds, organ.objectIds, keap.objectsTotal, organ.objectsTotal)
    out: list[Finding] = []

    def source_of(side: Side, oid: str) -> tuple[str | None, str | None]:
        d = side.objectDetail.get(oid) or {}
        return d.get("userId") or (side.objectMeta.get(oid) or {}).get("userId"), d.get("path")

    for oid in t.onlyKeap:
        if not oid.startswith("fs:"):
            meta = keap.objectMeta.get(oid) or {}
            out.append(Finding(
                "knowledge_objects", "only_in_keap", oid, CULPRIT_NEITHER, "not-a-mirror-row",
                f"the row is type {meta.get('type')!r} owned by {meta.get('userId')!r} and carries no fs: id, so it "
                "was written by a KEAP surface the organ deliberately does not serve — nothing fed it to the organ "
                "and nothing was supposed to",
                "no action; exclude from the fs-mirror comparison (it is already excluded from the fs clause)",
                {"meta": meta}))
            continue
        if organ.passDegraded:
            out.append(Finding(
                "knowledge_objects", "only_in_keap", oid, CULPRIT_NEITHER, "organ-pass-degraded",
                f"not attributable to the reader: {organ.passDegraded}. A truncated or refused pass explains a "
                "missing id on its own",
                "fix the organ's pass, then re-read this night", {}))
            continue
        uid, rel = source_of(keap, oid)
        r = fs.stat(uid, rel)
        if r["state"] == "exists":
            out.append(Finding(
                "knowledge_objects", "only_in_keap", oid, CULPRIT_ORGAN, "organ-reader-missed-it",
                f"the file EXISTS on the host ({r['path']}, {r['size']} bytes) and the organ's last pass was clean, "
                "so the organ's reader walked past a file that is really there",
                f"check the organ's root list and CORTEX_FS_SYNC_DIRS against {rel!r} for uid {uid!r}",
                {"uid": uid, "relPath": rel, "fs": r}))
        elif r["state"] == "absent":
            out.append(Finding(
                "knowledge_objects", "only_in_keap", oid, CULPRIT_KEAP, "keap-stale-not-pruned",
                f"the file does NOT exist on the host ({rel!r} under uid {uid!r}), so the organ is right to have no "
                "row; KEAP is holding one for a file that is gone",
                "check KEAP's own prune guards — a refused prune here is the guard working, a silent one is not",
                {"uid": uid, "relPath": rel, "fs": r}))
        else:
            out.append(Finding(
                "knowledge_objects", "only_in_keap", oid, CULPRIT_CONFIG, "organ-root-missing-for-uid",
                f"{r['why']} — the two deployments were pointed at different trees, so this is a configuration "
                "difference and neither reader is at fault",
                f"add a root deriving uid {uid!r} to CORTEX_FS_USER_ROOTS, or accept the divergence explicitly",
                {"uid": uid, "relPath": rel, "fs": r}))

    for oid in t.onlyOrgan:
        if not oid.startswith("fs:"):
            out.append(Finding(
                "knowledge_objects", "only_in_organ", oid, CULPRIT_ORGAN, "organ-invented-non-mirror-row",
                "the organ holds a non-fs object that KEAP does not, and the organ serves no surface that creates "
                "one — so it was not fed, it appeared",
                "read the organ's write log; nothing in the fan-out writes this shape", {}))
            continue
        if keap.passDegraded:
            out.append(Finding(
                "knowledge_objects", "only_in_organ", oid, CULPRIT_NEITHER, "keap-pass-degraded",
                f"not attributable: KEAP's last pass is not a clean walk ({keap.passDegraded})",
                "fix KEAP's pass, then re-read this night", {}))
            continue
        uid, rel = source_of(organ, oid)
        r = fs.stat(uid, rel)
        if r["state"] == "exists":
            pass_at = keap.lastPassAt
            fresh = _pass_newer_than(pass_at, r["mtime"])
            if fresh is False:
                out.append(Finding(
                    "knowledge_objects", "only_in_organ", oid, CULPRIT_KEAP, "keap-stale",
                    f"the file exists and was modified at {r['mtime']} (epoch), AFTER KEAP's last pass at {pass_at} — "
                    "KEAP has simply not walked since it appeared",
                    "no defect; the next KEAP pass closes it. If it does not, re-read as keap-reader-missed-it",
                    {"uid": uid, "relPath": rel, "fs": r, "keapLastPass": pass_at}))
            else:
                out.append(Finding(
                    "knowledge_objects", "only_in_organ", oid, CULPRIT_KEAP, "keap-reader-missed-it",
                    f"the file exists ({r['path']}) and predates KEAP's last pass at {pass_at}, so KEAP walked while "
                    "the file was there and produced no row",
                    f"check KEAP_FS_SYNC_DIRS and the container's mount for {rel!r}",
                    {"uid": uid, "relPath": rel, "fs": r, "keapLastPass": pass_at}))
        elif r["state"] == "absent":
            out.append(Finding(
                "knowledge_objects", "only_in_organ", oid, CULPRIT_ORGAN, "organ-row-without-a-file",
                f"no file exists at {rel!r} under uid {uid!r}, and the organ's last pass was clean — so the organ "
                "either derived a row for a path that never existed, or failed to prune one whose file went away",
                "read the organ's last pass counters (removed/pruneRefused) before assuming invention",
                {"uid": uid, "relPath": rel, "fs": r, "organLastPass": organ.lastPass}))
        else:
            out.append(Finding(
                "knowledge_objects", "only_in_organ", oid, CULPRIT_CONFIG, "organ-extra-root",
                f"{r['why']} — the organ is reading a tree KEAP is not; the row is correct for the organ and absent "
                "from KEAP by configuration",
                "align the root lists, or record the divergence as intended",
                {"uid": uid, "relPath": rel, "fs": r}))
    return t, out


def _pass_newer_than(pass_at: str | None, mtime: int) -> bool | None:
    """True when the pass ran after the file's mtime. None when undecidable —
    and undecidable must never be silently read as True."""
    if not pass_at:
        return None
    try:
        ts = datetime.fromisoformat(pass_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    return ts >= mtime


def adjudicate_shared_objects(keap: Side, organ: Side, fs: HostReferee) -> list[Finding]:
    """For ids BOTH sides hold: do the content digests agree, and if not, which
    side does the filesystem back?

    The referee is what makes this worth doing. "The two rows differ" is not
    actionable; "KEAP's row says 4096 bytes, the organ's says 8192, and the file
    on disk is 8192" names the stale reader in one line."""
    out: list[Finding] = []
    for oid in sorted(set(keap.objectDetail) & set(organ.objectDetail)):
        dk, do = keap.objectDetail[oid], organ.objectDetail[oid]
        differing = [f for f in DIGEST_FIELDS if dk.get(f) != do.get(f)]
        if not differing:
            continue
        uid = do.get("userId") or dk.get("userId")
        rel = do.get("path") or dk.get("path")
        r = fs.stat(uid, rel)

        if "visibility" in differing:
            out.append(Finding(
                "knowledge_objects", "field_mismatch", oid, CULPRIT_CONFIG, "shared-uids-divergence",
                f"visibility keap={dk.get('visibility')!r} organ={do.get('visibility')!r}; the value is derived "
                f"purely from the shared-uid set, and the two sides declare keap={keap.sharedUids} "
                f"organ={organ.sharedUids}",
                "set KEAP_FS_SHARED_UIDS and CORTEX_FS_SHARED_UIDS from ONE Ansible variable",
                {"keap": dk.get("visibility"), "organ": do.get("visibility")}))

        stat_fields = [f for f in ("size", "mtime") if f in differing]
        if stat_fields and r["state"] == "exists":
            k_match = all(dk.get(f) == r[f] for f in stat_fields)
            o_match = all(do.get(f) == r[f] for f in stat_fields)
            if k_match and not o_match:
                culprit, verdict, who = CULPRIT_ORGAN, "organ-stale-read", "the organ"
            elif o_match and not k_match:
                culprit, verdict, who = CULPRIT_KEAP, "keap-stale-read", "KEAP"
            else:
                culprit, verdict, who = CULPRIT_NEITHER, "both-stale", "neither side"
            out.append(Finding(
                "knowledge_objects", "field_mismatch", oid, culprit, verdict,
                f"{', '.join(stat_fields)} disagree and the file on disk says "
                f"{ {f: r[f] for f in stat_fields} } — {who} matches it "
                f"(keap={ {f: dk.get(f) for f in stat_fields} }, organ={ {f: do.get(f) for f in stat_fields} })",
                "re-run the losing side's pass; if it stays behind, its skip key is wrong, not its walk",
                {"fs": r, "keap": {f: dk.get(f) for f in stat_fields}, "organ": {f: do.get(f) for f in stat_fields}}))
        elif stat_fields:
            out.append(Finding(
                "knowledge_objects", "field_mismatch", oid, CULPRIT_UNKNOWN, "stat-mismatch-no-referee",
                f"{', '.join(stat_fields)} disagree and the host file could not be resolved ({r.get('why') or r['state']}), "
                "so no side can be named",
                "give the harness a root that resolves this uid before reading this as a defect",
                {"fs": r}))

        if "bodySha256" in differing:
            kb, ob = dk.get("bodySha256"), do.get("bodySha256")
            if bool(kb) != bool(ob):
                empty = "keap" if not kb else "organ"
                out.append(Finding(
                    "knowledge_objects", "field_mismatch", oid, CULPRIT_KEAP if empty == "keap" else CULPRIT_ORGAN,
                    "empty-body-read",
                    f"{empty} holds NO body for a file the other side read ({do.get('bodyLen')} / {dk.get('bodyLen')} "
                    "chars); the row is the right size and the content is gone — this is the class the prune guards "
                    "cannot catch, because nothing was pruned",
                    "on KEAP this is the VirtioFS empty-body hazard; on the organ (native APFS) it should be "
                    "impossible and means readBody's degraded path did not fire",
                    {"keapBodyLen": dk.get("bodyLen"), "organBodyLen": do.get("bodyLen"),
                     "degraded": {"keap": dk.get("degradedRead"), "organ": do.get("degradedRead")}}))
            elif not stat_fields:
                out.append(Finding(
                    "knowledge_objects", "field_mismatch", oid, CULPRIT_UNKNOWN, "body-derivation-divergence",
                    f"size and mtime AGREE but the body hashes do not (keap fmv={dk.get('fmv')} len={dk.get('bodyLen')}, "
                    f"organ fmv={do.get('fmv')} len={do.get('bodyLen')}) — the two sides read the same bytes and "
                    "produced different text",
                    "diff the frontmatter parser and the body cap between the ported fs-sync and upstream's; a "
                    "differing fmv is a parser-version difference, an equal one is a real code divergence",
                    {"keap": {"fmv": dk.get("fmv"), "len": dk.get("bodyLen")},
                     "organ": {"fmv": do.get("fmv"), "len": do.get("bodyLen")}}))

        for f in ("type", "title"):
            if f in differing:
                out.append(Finding(
                    "knowledge_objects", "field_mismatch", oid, CULPRIT_UNKNOWN, "card-derivation-divergence",
                    f"{f} keap={dk.get(f)!r} organ={do.get(f)!r}; both are derived from the file (frontmatter, else "
                    "extension/basename), so the same bytes produced different cards",
                    "compare parseCardFrontmatter/TYPE_BY_EXT across the two builds",
                    {"field": f, "keap": dk.get(f), "organ": do.get(f)}))
    return out


def adjudicate_taxonomy(keap: Side, organ: Side, canonical: set[str] | None) -> tuple[TableDiff, list[Finding]]:
    """Node id sets, refereed by the pinned canonical tree.

    Counts alone cannot do this job: two different 1841-node trees have equal
    counts and equal-looking parity. The referee then turns each stray id into a
    named, opposite fix — the organ's store was never re-materialised, or the
    running container is behind the pin."""
    ceiling = None
    if keap.taxonomyIds is None or organ.taxonomyIds is None:
        missing = [s.name for s in (keap, organ) if s.taxonomyIds is None]
        ceiling = f"{', '.join(missing)} does not serve /agent/v1/graph — taxonomy compared on COUNT only"
    t = _id_table("taxonomy_nodes", keap.taxonomyIds, organ.taxonomyIds,
                  keap.taxonomyNodes, organ.taxonomyNodes, ceiling)
    out: list[Finding] = []
    if not t.comparable:
        if t.counts_agree:
            out.append(Finding(
                "taxonomy_nodes", "ceiling", "-", CULPRIT_UNKNOWN, "counts-only",
                f"{ceiling}; equal counts are NOT equal trees and must not be reported as parity",
                "serve /agent/v1/graph on both sides, or compare the onto1 digest once KEAP publishes one", {}))
        return t, out

    if canonical is None:
        for oid in t.onlyKeap[:200]:
            out.append(Finding("taxonomy_nodes", "only_in_keap", oid, CULPRIT_UNKNOWN, "no-canonical-referee",
                               "the pinned canonical tree was not readable, so 'organ not materialised' and 'KEAP "
                               "ahead of the pin' cannot be told apart", "pass --canonical-dir", {}))
        for oid in t.onlyOrgan[:200]:
            out.append(Finding("taxonomy_nodes", "only_in_organ", oid, CULPRIT_UNKNOWN, "no-canonical-referee",
                               "the pinned canonical tree was not readable", "pass --canonical-dir", {}))
        return t, out

    # ── the referee's jurisdiction ───────────────────────────────────────────
    # `knowledge/canonical` is the source for the canonical taxonomy and NOTHING
    # else. The estate self-model registers its own subtree (`nos.*`) through
    # `registerExtNode` — generated, never ingested from that tree — so judging
    # those ids against it produced 91 false "fed from something this checkout is
    # not pinned to" on the first real run.
    #
    # The rule is structural rather than a hardcoded prefix, so a future
    # generated subtree does not have to be remembered: a node is in the
    # referee's jurisdiction when its ROOT segment is one the canonical tree
    # defines. `01.04.02` is judged; `nos.b2b.outline` is not, and its absence
    # from the pinned tree is a fact about the tree, not about the corpus.
    canonical_roots = {i.split(".")[0] for i in canonical}
    in_scope = lambda i: i.split(".")[0] in canonical_roots  # noqa: E731

    # ── agreement is not currency ────────────────────────────────────────────
    # Both sides can agree perfectly and both be behind the pin. The id diff
    # reads `exact` and the count line reads `1841 vs 1841`, and neither says
    # that the pinned tree has 2 393 nodes. Without this, "taxonomy exact" gets
    # read as "corpus parity pinned" — which is §4.4's whole question, answered
    # wrongly by a check that never looked at the referee when the two sides
    # happened to concur.
    both = set(keap.taxonomyIds) & set(organ.taxonomyIds)
    missing_from_both = canonical - set(keap.taxonomyIds) - set(organ.taxonomyIds)
    beyond_pin = {i for i in both - canonical if in_scope(i)}
    generated = {i for i in both if not in_scope(i)}
    if generated:
        out.append(Finding(
            "taxonomy_nodes", "parity", f"{len(generated)} node(s)", CULPRIT_NEITHER, "outside-referee-jurisdiction",
            f"both corpora hold {len(generated)} node(s) under root(s) the pinned canonical tree does not define "
            f"({', '.join(sorted({i.split('.')[0] for i in generated}))}) — generated subtrees, not ingested ones, "
            "so the tree cannot judge them either way",
            "no action; recorded so the parity numbers below are read against the right denominator",
            {"count": len(generated), "sample": sorted(generated)[:8]}))
    if missing_from_both:
        out.append(Finding(
            "taxonomy_nodes", "parity", f"{len(missing_from_both)} node(s)", CULPRIT_NEITHER, "both-behind-pin",
            f"the pinned canonical tree has {len(canonical)} nodes and NEITHER corpus has "
            f"{len(missing_from_both)} of them — the two sides agree, on a stale tree. Agreement here is not parity",
            "re-materialise the organ's store AND rebuild the KEAP container at keap_repo_ref before any recall "
            "measurement claims to be over one corpus",
            {"pinned": len(canonical), "missingFromBoth": len(missing_from_both),
             "sample": sorted(missing_from_both)[:8]}))
    if beyond_pin:
        out.append(Finding(
            "taxonomy_nodes", "parity", f"{len(beyond_pin)} node(s)", CULPRIT_NEITHER, "both-ahead-of-pin",
            f"both corpora hold {len(beyond_pin)} node(s) the pinned canonical tree does not — they were fed from "
            "something this checkout is not pinned to",
            "reconcile keap_repo_ref with what both sides actually ingested",
            {"count": len(beyond_pin), "sample": sorted(beyond_pin)[:8]}))

    # Summarised, not per-id: a parity gap is thousands of ids with two causes,
    # and 2 000 identical finding lines is a wall, not a report.
    for ids, case, in_repo_verdict, in_repo_why, out_repo_verdict, out_repo_why in (
        (t.onlyKeap, "only_in_keap",
         "organ-store-not-materialised",
         "present in the pinned canonical tree and in KEAP, absent from the organ — the organ's STORE was never "
         "re-materialised after the parity pin moved (the repo tree is fine; the db is behind it)",
         "keap-ahead-of-pin",
         "in KEAP but in NEITHER the organ nor the pinned canonical tree — the running container ingested a tree "
         "this checkout does not have"),
        (t.onlyOrgan, "only_in_organ",
         "keap-container-behind-pin",
         "present in the pinned canonical tree and in the organ, absent from KEAP — the CONTAINER is behind "
         "keap_repo_ref; the organ materialised the newer tree first",
         "organ-invented-node",
         "in the organ but in neither KEAP nor the pinned canonical tree — the organ materialises only from that "
         "tree, so this id has no source"),
    ):
        in_repo = [i for i in ids if i in canonical]
        out_repo = [i for i in ids if i not in canonical and in_scope(i)]
        no_juris = [i for i in ids if i not in canonical and not in_scope(i)]
        if no_juris:
            out.append(Finding(
                "taxonomy_nodes", case, f"{len(no_juris)} node(s)", CULPRIT_UNKNOWN, "generated-subtree-differs",
                f"{len(no_juris)} node(s) under a root the pinned tree does not define — a generated subtree, so the "
                "canonical referee cannot say which side is right; the two self-model generators disagree",
                "compare the two generators' inputs (the --facts-json divergence is the known one)",
                {"sample": no_juris[:8], "count": len(no_juris)}))
        if in_repo:
            out.append(Finding(
                "taxonomy_nodes", case, f"{len(in_repo)} node(s)",
                CULPRIT_ORGAN if in_repo_verdict.startswith("organ") else CULPRIT_KEAP,
                in_repo_verdict, in_repo_why,
                "re-materialise the organ's store (npm run store:materialise)" if in_repo_verdict.startswith("organ")
                else "rebuild/redeploy the KEAP container at keap_repo_ref",
                {"sample": in_repo[:8], "count": len(in_repo)}))
        if out_repo:
            out.append(Finding(
                "taxonomy_nodes", case, f"{len(out_repo)} node(s)",
                CULPRIT_KEAP if out_repo_verdict.startswith("keap") else CULPRIT_ORGAN,
                out_repo_verdict, out_repo_why,
                "reconcile keap_repo_ref with what is actually deployed",
                {"sample": out_repo[:8], "count": len(out_repo)}))
    return t, out


def adjudicate_embeddings(keap: Side, organ: Side, obj_table: TableDiff,
                          tax_table: TableDiff) -> tuple[list[TableDiff], list[Finding]]:
    """Same refs embedded, same model, same dimension.

    Neither surface lists embedded refs, so the ref set is DERIVED — for every
    kind whose sources this harness can enumerate:

        embedded(kind) = sources(kind) − pending(kind)

    `pending` is "missing or stale", so this is a lower bound on what is
    embedded and an exact statement of what is not CURRENT. That is the useful
    direction: a vector present but stale is as wrong for recall as one absent.

    The vectors themselves are deliberately NOT compared. The organ's ANN index
    is tuned (float8 / max_neighbors=20) and KEAP's is not; that asymmetry is
    the S3 experiment, and turning it into an agreement criterion here would
    delete the experiment."""
    tables: list[TableDiff] = []
    out: list[Finding] = []

    if keap.embedPruned or organ.embedPruned:
        for s in (keap, organ):
            if s.embedPruned:
                out.append(Finding(
                    "embeddings", "harness_side_effect", s.name, CULPRIT_NEITHER, "harness-side-effect",
                    f"reading {s.name}'s /agent/v1/embeddings/pending pruned {s.embedPruned} orphan vector(s) — that "
                    "endpoint reaps vectors whose source row is gone, so this harness WROTE to a store it claims "
                    "only to read",
                    "expected value is 0 (the nightly embed job prunes first). A standing non-zero means the embed "
                    "job is not running, and the harness is covering for it", {"pruned": s.embedPruned}))

    if (keap.embedModel, keap.embedDim) != (organ.embedModel, organ.embedDim):
        out.append(Finding(
            "embeddings", "shape_mismatch", "-", CULPRIT_CONFIG, "incomparable-embedding-space",
            f"keap={keap.embedModel}/{keap.embedDim} organ={organ.embedModel}/{organ.embedDim}; vectors from two "
            "models (or two dimensions) are not in one space, so no recall comparison downstream means anything",
            "pin KEAP_EMBED_MODEL identically on both sides before any S3 measurement",
            {"keap": [keap.embedModel, keap.embedDim], "organ": [organ.embedModel, organ.embedDim]}))

    kinds = sorted(set(keap.embedByKind) | set(organ.embedByKind))
    for kind in kinds:
        kr, orr = keap.embedByKind.get(kind, 0), organ.embedByKind.get(kind, 0)
        tables.append(TableDiff(name=f"embeddings[{kind}]", keapRows=kr, organRows=orr,
                                comparable=False, ceiling="row counts; ref set derived below where enumerable"))

    # ── the derived ref sets ──────────────────────────────────────────────────
    sources = {
        "object": (set(keap.objectIds), set(organ.objectIds), obj_table.comparable),
        "taxonomy": (set(keap.taxonomyIds or []), set(organ.taxonomyIds or []), tax_table.comparable),
    }
    for kind, (ksrc, osrc, comparable) in sources.items():
        # The count check FIRST, because it is exact and always available:
        # `byKind` is a row count and `sources` is enumerated, so a deficit is a
        # fact even when the pending page cap hides which refs are involved.
        for side, src in ((keap, ksrc), (organ, osrc)):
            rows = side.embedByKind.get(kind, 0)
            if src and rows < len(src):
                out.append(Finding(
                    "embeddings", "count_mismatch", f"{kind}@{side.name}",
                    CULPRIT_ORGAN if side.name != "keap" else CULPRIT_KEAP,
                    f"{'organ' if side.name != 'keap' else 'keap'}-embed-behind",
                    f"{side.name} holds {rows} {kind} vector(s) for {len(src)} source row(s) — {len(src) - rows} "
                    "source(s) have no vector at all",
                    f"run keap-embed-sync against {side.name}",
                    {"kind": kind, "vectors": rows, "sources": len(src)}))
            elif src and rows > len(src):
                out.append(Finding(
                    "embeddings", "count_mismatch", f"{kind}@{side.name}",
                    CULPRIT_ORGAN if side.name != "keap" else CULPRIT_KEAP, "orphan-vectors",
                    f"{side.name} holds {rows} {kind} vector(s) for only {len(src)} source row(s) — {rows - len(src)} "
                    "vector(s) outlive their source",
                    "the pending endpoint prunes these; if the count stands, the embed job is not running",
                    {"kind": kind, "vectors": rows, "sources": len(src)}))

        if not comparable:
            out.append(Finding(
                "embeddings", "ceiling", kind, CULPRIT_UNKNOWN, "ref-set-not-enumerable",
                f"the {kind} source id set is not comparable on both sides, so embedded({kind}) cannot be derived — "
                f"only the row counts (keap {keap.embedByKind.get(kind)} / organ {organ.embedByKind.get(kind)}) are "
                "available",
                "serve the listing route on both sides", {}))
            continue
        if not (keap.pendingComplete and organ.pendingComplete):
            # `sources − pending` is only the embedded set when `pending` is
            # COMPLETE. Truncated at the page cap it OVERSTATES what is embedded,
            # in a known direction, by exactly the number of rows the cap hid —
            # a store with zero vectors reported 1341 of 1841 "embedded" on the
            # first real run. A number that is wrong in a known direction is
            # worse than no number, so it is not published; the exact row counts
            # above carry the finding instead.
            tables.append(TableDiff(
                name=f"embedded[{kind}]", keapRows=keap.embedByKind.get(kind),
                organRows=organ.embedByKind.get(kind), comparable=False,
                ceiling=f"pending exceeds the {500}-item page cap on at least one side — ref set NOT derived "
                        "(sources − pending would overstate it); row counts above are exact"))
            continue
        k_emb = ksrc - set(keap.pendingRefs.get(kind, {}))
        o_emb = osrc - set(organ.pendingRefs.get(kind, {}))
        t = _id_table(f"embedded[{kind}]", sorted(k_emb), sorted(o_emb))
        tables.append(t)
        for oid in t.onlyKeap:
            in_organ_corpus = oid in osrc
            out.append(Finding(
                "embeddings", "only_in_keap", f"{kind}:{oid}",
                CULPRIT_ORGAN if in_organ_corpus else CULPRIT_NEITHER,
                "organ-embed-behind" if in_organ_corpus else "organ-corpus-lacks-source",
                ("the source row exists on BOTH sides and only KEAP has a current vector for it — the organ's embed "
                 "pass has not caught up") if in_organ_corpus else
                ("the organ has no such source row at all, so there is nothing for it to embed; this is an object/"
                 "taxonomy difference reported above, not an embedding one"),
                "run keap-embed-sync against the organ" if in_organ_corpus else "fix the corpus difference first",
                {"kind": kind}))
        for oid in t.onlyOrgan:
            in_keap_corpus = oid in ksrc
            out.append(Finding(
                "embeddings", "only_in_organ", f"{kind}:{oid}",
                CULPRIT_KEAP if in_keap_corpus else CULPRIT_NEITHER,
                "keap-embed-behind" if in_keap_corpus else "keap-corpus-lacks-source",
                ("the source row exists on both sides and only the organ has a current vector — KEAP's embed pass is "
                 "behind, or its content hash moved and has not been re-embedded") if in_keap_corpus else
                "KEAP has no such source row; nothing to embed",
                "run keap-embed-sync against KEAP" if in_keap_corpus else "fix the corpus difference first",
                {"kind": kind}))
    return tables, out


def adjudicate_captures(keap: Side, organ: Side, feeder: dict) -> tuple[TableDiff, list[Finding]]:
    """Captures are the ONLY signal here that measures the consolidator fan-out.

    With them out of the verdict, a night on which the second target was never
    fed at all reads green — an unfed shadow whose fs mirror happens to match is
    not a corpus in parallel. The feeder's own state ledger is the referee that
    separates "the job has not run" from "the job ran and the organ rejected
    items"."""
    ceiling = None if (keap.capturesComplete and organ.capturesComplete) else (
        f"/agent/v1/captures takes no offset — id set exact only up to {PAGE} rows per side")
    t = _id_table("api_taxonomy_metadata", keap.captureIds, organ.captureIds,
                  keap.capturesTotal, organ.capturesTotal, ceiling)
    out: list[Finding] = []
    if t.counts_agree and t.ids_agree:
        return t, out

    targets = feeder.get("targets") or {}
    if feeder.get("version") == 1 or "cortex" not in targets:
        out.append(Finding(
            "api_taxonomy_metadata", "count_mismatch", "-", CULPRIT_FEEDER, "fanout-never-ran",
            f"keap {keap.capturesTotal} vs organ {organ.capturesTotal}; the consolidator state ledger is "
            f"version {feeder.get('version')} with targets {sorted(targets)} — it holds NO signatures for the organ, "
            "so the fan-out has never fed it. The corpora are not disagreeing; one of them was never written to",
            "run keap-consolidate with the cortex target configured, then re-read this night",
            {"feeder": feeder}))
    else:
        out.append(Finding(
            "api_taxonomy_metadata", "count_mismatch", "-", CULPRIT_FEEDER, "fanout-partial",
            f"keap {keap.capturesTotal} vs organ {organ.capturesTotal}, and the ledger HAS run against both "
            f"({targets}); items swept for the organ were recorded but did not land",
            "read the fan-out's per-target rejection reasons — a recorded signature with no row is the data-loss "
            "shape the target dimension exists to prevent",
            {"feeder": feeder}))
    return t, out


# ── the report ───────────────────────────────────────────────────────────────


def real_user_docs(side: Side) -> int:
    """Objects that are somebody's actual document, not generated self-model.

    The shared uid owns the cards a converge writes; everything else in the
    mirror was put there by a person. This number, not `objectsTotal`, is the
    denominator that decides whether the report may speak. It reads the uid set
    off the wire rather than hardcoding it, so renaming the self-model uid
    cannot silently inflate it."""
    selfmodel = set(side.sharedUids) or {"nos-docs"}
    return sum(1 for oid, d in side.objectDetail.items()
               if oid.startswith("fs:") and (d.get("userId") not in selfmodel))


def build_report(keap: Side, organ: Side, fs: HostReferee, canonical: set[str] | None,
                 feeder: dict) -> dict:
    obj_t, obj_f = adjudicate_objects(keap, organ, fs)
    field_f = adjudicate_shared_objects(keap, organ, fs)
    tax_t, tax_f = adjudicate_taxonomy(keap, organ, canonical)
    cap_t, cap_f = adjudicate_captures(keap, organ, feeder)
    emb_tables, emb_f = adjudicate_embeddings(keap, organ, obj_t, tax_t)

    notes_t = TableDiff(name="taxonomy_metadata", keapRows=keap.curatedNotes, organRows=organ.curatedNotes,
                        comparable=False, ceiling="neither side lists curated-note ids — count only")
    rel_t = TableDiff(name="relations", keapRows=keap.relationEdges, organRows=organ.relationEdges,
                      comparable=False, ceiling="confirmed edges, count only")

    # fs-only slice of the object table — the clause the 3-night clock runs on.
    fs_t = _id_table("knowledge_objects[fs:]", keap.fsIds, organ.fsIds)

    findings = obj_f + field_f + tax_f + cap_f + emb_f
    tables = [obj_t, fs_t, tax_t, notes_t, cap_t, rel_t] + emb_tables

    # Kept OUT of `clauses` on purpose: parity is currency, not agreement, and
    # conflating them would make a stale-but-consistent pair fail the clock for
    # a reason the clock does not measure. It is printed on its own line instead,
    # directly under the taxonomy row, where "exact" would otherwise be read as
    # "pinned".
    parity = None
    if canonical is not None and keap.taxonomyIds is not None and organ.taxonomyIds is not None:
        roots = {i.split(".")[0] for i in canonical}
        parity = {
            "pinned": len(canonical),
            "keapOfPinned": len(set(keap.taxonomyIds) & canonical),
            "organOfPinned": len(set(organ.taxonomyIds) & canonical),
            "missingFromBoth": len(canonical - set(keap.taxonomyIds) - set(organ.taxonomyIds)),
            # Generated subtrees are counted separately, not netted off: they are
            # part of the corpus and outside the referee, and a single "1841 vs
            # 2393" would make that difference look like a shortfall.
            "generated": len({i for i in set(keap.taxonomyIds) | set(organ.taxonomyIds)
                              if i.split(".")[0] not in roots}),
        }

    clauses = {
        "fs ids": fs_t.ids_agree,
        "body hashes": not any(f.case == "field_mismatch" for f in findings),
        "taxonomy": tax_t.ids_agree if tax_t.comparable else False,
        "captures": cap_t.counts_agree and cap_t.ids_agree,
        "embed shape": (keap.embedModel, keap.embedDim) == (organ.embedModel, organ.embedDim),
        # `count_mismatch` is IN this clause, not only `only_in_*`. The ref-set
        # diff is skipped whenever pending exceeds the page cap — and it is
        # skipped precisely when a side is furthest behind, because that is when
        # pending is largest. A clause that reads ok because its check was
        # skipped is the same "two silences compared equal" failure the digest
        # rule refuses, and on the first real run it printed `embedded refs ok`
        # over a store holding zero vectors.
        "embedded refs": not any(
            f.table == "embeddings" and (f.case.startswith("only_in") or f.case == "count_mismatch")
            for f in findings),
    }
    docs = real_user_docs(keap) or real_user_docs(organ)

    # ── removal-shaped: the only immediate halt ──────────────────────────────
    organ_pruned_what_keap_kept = bool(
        [f for f in obj_f if f.case == "only_in_keap" and f.verdict == "organ-reader-missed-it"]
    ) and (organ.lastPass.get("removed") or 0) > 0

    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "sides": {
            "keap": {"version": keap.serverVersion, "lastPass": keap.lastPassAt, "degraded": keap.passDegraded},
            "cortex": {"version": organ.serverVersion, "lastPass": organ.lastPassAt, "degraded": organ.passDegraded},
        },
        "tables": [asdict(t) | {"idsAgree": t.ids_agree, "countsAgree": t.counts_agree} for t in tables],
        "findings": [asdict(f) for f in findings],
        "clauses": clauses,
        "corpusParity": parity,
        "agrees": all(clauses.values()),
        "realUserDocs": docs,
        "refereesAvailable": {
            "filesystem": fs.available,
            "canonicalTree": canonical is not None,
            "feederState": feeder.get("version") is not None,
        },
        "removalShaped": organ_pruned_what_keap_kept
        or bool(organ.lastPass.get("pruneRefused")),
        "organPass": organ.lastPass,
        "keapPass": keap.lastPass,
        "ontologyDigest": {"keap": keap.ontologyVersion, "cortex": organ.ontologyVersion},
    }


def render(report: dict, night_no: int, streak: int) -> str:
    L: list[str] = []
    a = report
    L.append(f"S2 corpus diff — night {night_no} (agree streak {streak}/{NIGHTS_REQUIRED})"
             f"    {a['at'][:10]}")
    L.append(f"  keap {a['sides']['keap']['version']}   cortex {a['sides']['cortex']['version']}")
    L.append("")
    # THE DENOMINATOR, above the verdict. Not decoration: it is the number that
    # decides whether any of the lines below are allowed to mean anything.
    L.append(f"  real user docs   {a['realUserDocs']}         <- the denominator that matters")
    ref = a["refereesAvailable"]
    L.append(f"  referees         filesystem {'yes' if ref['filesystem'] else 'NO'} · "
             f"canonical tree {'yes' if ref['canonicalTree'] else 'NO'} · "
             f"feeder state {'yes' if ref['feederState'] else 'NO'}")
    L.append("")
    L.append("  table                        keap   organ    both  onlyK  onlyO   ids")
    for t in a["tables"]:
        ids = "exact" if t["idsAgree"] else ("DIFFER" if t["comparable"] else "—")
        L.append(f"  {t['name']:<26} {str(t['keapRows']):>6} {str(t['organRows']):>7}"
                 f" {str(t['both'] if t['both'] is not None else '—'):>7}"
                 f" {len(t['onlyKeap']):>6} {len(t['onlyOrgan']):>6}   {ids}")
        if t["ceiling"]:
            L.append(f"      ceiling: {t['ceiling']}")
    if a.get("corpusParity"):
        p = a["corpusParity"]
        gen = f" (+{p['generated']} generated, outside the referee)" if p["generated"] else ""
        if p["missingFromBoth"]:
            L.append(f"  corpus parity    NOT PINNED — the pinned tree has {p['pinned']} nodes; keap has "
                     f"{p['keapOfPinned']}, organ has {p['organOfPinned']}{gen}, and {p['missingFromBoth']} are in "
                     "NEITHER. An 'exact' id set above is agreement on a stale tree, not parity")
        else:
            L.append(f"  corpus parity    PINNED — both sides carry all {p['pinned']} nodes of the pinned tree{gen}")
    L.append("")
    L.append(f"  onto1 digest     {a['ontologyDigest']['keap'] or 'not served'} vs "
             f"{a['ontologyDigest']['cortex'] or 'not served'}"
             + ("" if all(a["ontologyDigest"].values())
                else "   CEILING — a digest neither side publishes is not agreement"))
    op = a["organPass"]
    L.append(f"  organ pass       pruneRefused {op.get('pruneRefused', False)}  emptyBodies {op.get('emptyBodies', 0)}"
             f"  rootsMissing {op.get('rootsMissing') or 'none'}  collisions {op.get('rootCollisions', 0)}"
             f"  sentinel {op.get('sentinel', 'n/a')}")
    for side in ("keap", "cortex"):
        if a["sides"][side]["degraded"]:
            L.append(f"  {side} DEGRADED   {a['sides'][side]['degraded']}")
    L.append("")
    L.append("  VERDICT          " + ("AGREE" if a["agrees"] else "DISAGREE") + "  ("
             + ", ".join(f"{k} {'ok' if v else 'NO'}" for k, v in a["clauses"].items()) + ")")

    # ── the adjudication: every disagreement, with a named culprit ────────────
    if a["findings"]:
        L.append("")
        L.append("  ── who is wrong, and why ────────────────────────────────────────────")
        groups: dict[tuple, list] = {}
        for f in a["findings"]:
            groups.setdefault((f["table"], f["verdict"], f["culprit"]), []).append(f)
        for (table, verdict, culprit), fs_ in sorted(groups.items()):
            head = fs_[0]
            L.append(f"  [{culprit.upper():<7}] {verdict}  ×{len(fs_)}   ({table})")
            L.append(f"            {head['because']}")
            L.append(f"        do: {head['action']}")
            if len(fs_) > 1:
                L.append(f"        e.g. {', '.join(f['ident'] for f in fs_[:4])}"
                         + (" …" if len(fs_) > 4 else ""))
            else:
                L.append(f"        id: {head['ident']}")

    if a["realUserDocs"] < REAL_DOC_FLOOR:
        L.append("")
        L.append(f"  NOT EXERCISED tonight ({a['realUserDocs']} real user document(s), floor {REAL_DOC_FLOOR}):")
        for item in NOT_EXERCISED:
            L.append(f"    - {item}")
        L.append("")
        L.append("  This run does not show that ingestion is correct. It shows that two")
        L.append("  near-empty corpora are equally near-empty.")
    return "\n".join(L)


# ── ledger + notification ────────────────────────────────────────────────────


def load_state(path: Path) -> dict:
    try:
        s = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"version": LEDGER_VERSION, "nights": [], "agreeStreak": 0, "disagreements": 0, "halted": False}
    if s.get("version") != LEDGER_VERSION:
        # A night measured by a weaker harness must not count toward this one's
        # clock. Retired, not deleted — the record survives, the credit does not.
        return {
            "version": LEDGER_VERSION,
            "nights": [],
            "agreeStreak": 0,
            "disagreements": 0,
            "halted": s.get("halted", False),
            "supersededNights": s.get("nights", []),
            "supersededVersion": s.get("version"),
        }
    return s


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


def notify(bin_path: str, severity: str, title: str, body: str) -> None:
    if bin_path and os.path.exists(bin_path):
        subprocess.run([bin_path, severity, title, body, "wing-inbox"], check=False, timeout=30)


# ── entry point ──────────────────────────────────────────────────────────────


def default_canonical_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "cortex" / "knowledge" / "canonical"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="S2 corpus agreement harness (read-only)")
    p.add_argument("--json", action="store_true", help="machine-readable report only")
    p.add_argument("--no-ledger", action="store_true", help="do not record a night")
    p.add_argument("--halt-cmd", default=os.environ.get("CORTEX_DIFF_HALT_CMD", ""),
                   help="shell command run on a removal-shaped halt (stops the organ's fs-sync)")
    p.add_argument("--canonical-dir", default=None, help="taxonomy referee (pinned canonical tree)")
    p.add_argument("--keap-url", default=os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091"))
    p.add_argument("--cortex-url", default=os.environ.get("CORTEX_API_URL", "http://127.0.0.1:8098"))
    p.add_argument("--keap-token", default=os.environ.get("KEAP_AGENT_TOKEN_RO", ""))
    p.add_argument("--cortex-token", default=os.environ.get("CORTEX_AGENT_TOKEN_RO", ""))
    p.add_argument("--state", default=os.environ.get(
        "CORTEX_DIFF_STATE", str(Path.home() / ".nos" / "cortex-corpus-diff.json")))
    p.add_argument("--feeder-state", default=os.environ.get(
        "NOS_CONSOLIDATE_STATE", str(Path.home() / ".nos" / "keap-consolidate-state.json")))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    notify_bin = os.environ.get("NOS_NOTIFY_BIN", "")
    state_path = Path(args.state)

    if not args.keap_token or not args.cortex_token:
        print("cortex-corpus-diff: KEAP_AGENT_TOKEN_RO and CORTEX_AGENT_TOKEN_RO are both required", file=sys.stderr)
        return 1

    state = load_state(state_path)
    night_no = len(state["nights"]) + 1

    try:
        keap = read_side("keap", args.keap_url.rstrip("/"), args.keap_token)
    except Unreachable as exc:
        print(f"cortex-corpus-diff: KEAP unreachable: {exc}", file=sys.stderr)
        return 2
    try:
        organ = read_side("cortex", args.cortex_url.rstrip("/"), args.cortex_token)
    except Unreachable as exc:
        # A VOID night: neither +1 nor a reset. A skipped night must not be able
        # to advance a 3-night clock, and must not be able to reset it either.
        print(f"cortex-corpus-diff: cortex unreachable — night VOID: {exc}", file=sys.stderr)
        if not args.no_ledger:
            state["nights"].append({"at": datetime.now(timezone.utc).isoformat(), "result": "void",
                                    "reason": str(exc)[:200]})
            save_state(state_path, state)
        notify(notify_bin, "low", "S2 diff: night void",
               f"The cortex organ was unreachable ({exc}). The 3-night clock is unchanged.")
        return 0

    canonical_dir = Path(args.canonical_dir) if args.canonical_dir else default_canonical_dir()
    report = build_report(
        keap, organ,
        HostReferee(organ.userRoots),
        read_canonical_ids(canonical_dir),
        read_feeder_state(Path(args.feeder_state)),
    )

    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(render(report, night_no, state["agreeStreak"]))

    if args.no_ledger:
        return 3 if report["removalShaped"] else 0

    night = {
        "at": report["at"],
        "result": "agree" if report["agrees"] else "disagree",
        "clauses": report["clauses"],
        "realUserDocs": report["realUserDocs"],
        "tables": {t["name"]: {"keap": t["keapRows"], "organ": t["organRows"],
                               "onlyKeap": len(t["onlyKeap"]), "onlyOrgan": len(t["onlyOrgan"])}
                   for t in report["tables"]},
        "verdicts": sorted({f["verdict"] for f in report["findings"]}),
    }
    if report["agrees"]:
        state["agreeStreak"] += 1
    else:
        state["agreeStreak"] = 0
        state["disagreements"] += 1
    state["nights"].append(night)

    if report["removalShaped"]:
        state["halted"] = True
        night["halt"] = "removal-shaped"
        save_state(state_path, state)
        print("\n  HALT — removal-shaped disagreement. The organ pruned something the incumbent kept, "
              "or refused a prune. Removals are the only irreversible direction.", file=sys.stderr)
        if args.halt_cmd:
            subprocess.run(args.halt_cmd, shell=True, check=False, timeout=60)
        notify(notify_bin, "high", "S2 diff: HALT — removal-shaped disagreement",
               "The cortex organ's fs-sync is stopped and must be looked at before the next pass. The diff keeps "
               "running: refusing to walk is safe, refusing to observe is not.")
        return 3

    save_state(state_path, state)

    if state["agreeStreak"] >= NIGHTS_REQUIRED:
        notify(notify_bin, "medium", f"S2 diff: {NIGHTS_REQUIRED} nights of agreement",
               f"Agreement holds over {report['realUserDocs']} real user document(s). Per §8 this is NOT sufficient "
               "on its own: corpus parity must be pinned and the fixture suite green, and the report must state its "
               "denominator. Read the run output before calling S2 done.")
    elif state["disagreements"] >= DISAGREEMENTS_ALLOWED:
        notify(notify_bin, "high", "S2 diff: three disagreeing nights — stop adding nights",
               "S2 reports on the evidence it has; S3 decides. Adding nights past this point is how a parallel run "
               "becomes permanent furniture.")
    elif len(state["nights"]) >= NIGHT_CEILING:
        notify(notify_bin, "high", f"S2 diff: {NIGHT_CEILING}-night ceiling reached",
               "Report whatever the harness has, with its denominator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
