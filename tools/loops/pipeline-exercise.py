#!/usr/bin/env python3
"""pipeline-exercise — drive the WHOLE invoice pipeline with varied documents.

files/anatomy/loops/pipeline-exercise.loop.yml is the manifest; this runs it.

WHAT IT IS FOR (operator, 2026-09-23): simulate a clerk's daily post over many
document kinds and carrying conditions — a crumpled photo, a 150-dpi scan, a
stained page — and record what the pipeline did with each. It does NOT judge.
Every verdict here comes from a CODE ORACLE (`invoice_fixture.parse_image_txt`,
the text each image was RENDERED from), never from a model: a model grading its
own extraction would make the whole measurement decorative.

ONE CYCLE = render a degraded document -> sweep it into the verify queue ->
approve or reject it against the truth -> absorb -> assert what the estate now
holds -> tear that cycle's rows out again. Each step is the estate's own door
(gen-invoice-images, invoice-vision-intake, invoice-verify,
digest-import-vision, digest-teardown), never a reimplementation — a loop that
exercised its own copy of the pipeline would be measuring itself.

THE ASSERTIONS ARE THE POINT. Extraction accuracy is what vision-bench already
measures; what this adds is everything AFTER the model: does the queue row
carry the source, does approve reach absorb, is the booked slug the DERIVED
identity, does the document stand exactly once, does its entry balance. The
2026-09-23 duplicate was invisible to every balance check and would have been
caught here on cycle one.

WHAT IT TOUCHES. Each cycle removes exactly the rows it created; a document
that was ALREADY booked (every fixture invoice is, from the consulting-firm
seed) is upserted rather than duplicated, and left standing. The visible
consequence: that row's provenance reads `source: vision` until the next
converge re-seeds the fixture. Identity and balance are unaffected, and the
alternative — exercising documents the books have never seen — needs fixtures
that do not exist yet (zaloha, paragon; dobropis and PDP have no image render).

PLANNERS. `--planner matrix` (default) picks the thinnest (document,
degradation) cell — deterministic, no model, runs unattended. `--planner agent`
hands that choice to the Sonnet-tier agent named by --agent, which sees the
coverage matrix and the last cycles' outcomes and answers with ONE validated
JSON object; it never sees a verdict, because choosing what to try next and
judging the result are different jobs.

BUDGET. One document through the VLM took ~2 min on this host (2026-09-23), so
--cycles 4 is about an hour and 20+ cycles is a WEEK of nights, not one run.
The coverage matrix persists across runs, which is what makes "at least 20
cycles" a coverage target rather than an impossible single job.

Usage:
  tools/loops/pipeline-exercise.py --cycles 2
  tools/loops/pipeline-exercise.py --cycles 1 --doc beta-002 --degrade crumple
  tools/loops/pipeline-exercise.py --cycles 4 --planner agent --agent pipeline-clerk

Exit: 0 every cycle held · 3 a cycle's assertions failed (a finding, declared
in the manifest's findings_exit_codes) · 2 could not run at all.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from invoice_fixture import parse_image_txt  # noqa: E402
import digest_absorb  # noqa: E402
import nos_digest  # noqa: E402

FIXTURE = REPO / "state" / "fixtures" / "consulting-firm"
STATE = REPO / "state" / "pipeline-exercise"
PY = sys.executable


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load("gen_invoice_images", REPO / "tools" / "gen-invoice-images.py")
BENCH = _load("vision_bench", REPO / "tools" / "loops" / "vision-bench.py")

#: Every document the fixture can render, and every way it can be carried.
DOCS = sorted(p.name[: -len(".image.txt")] for p in FIXTURE.glob("*.image.txt"))
DEGRADATIONS = [p for p in GEN.DEGRADE_PROFILES if p != "combo"]


# ── coverage: what has been tried, across runs ───────────────────────────────

def load_coverage() -> dict:
    p = STATE / "coverage.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_coverage(cov: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "coverage.json").write_text(json.dumps(cov, indent=2, sort_keys=True),
                                         encoding="utf-8")


def thinnest_cell(cov: dict) -> tuple[str, str]:
    """The least-tried (document, degradation), ties broken by name so a run is
    reproducible. This is the whole matrix planner: no model needed to notice
    that a cell has been visited fewer times than another."""
    return min(((d, g) for d in DOCS for g in DEGRADATIONS),
               key=lambda c: (cov.get(f"{c[0]}|{c[1]}", 0), c[0], c[1]))


# ── one cycle ────────────────────────────────────────────────────────────────

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, **kw)


def plan_cycle(planner: str, cov: dict, n: int, history: list[dict],
               agent: str, forced: tuple[str | None, str | None]) -> dict:
    doc, degrade = forced
    if doc and degrade:
        return {"doc": doc, "degrade": degrade, "seed": n, "reason": "operator-named"}
    if planner == "matrix":
        d, g = thinnest_cell(cov)
        return {"doc": doc or d, "degrade": degrade or g, "seed": n,
                "reason": f"thinnest cell ({cov.get(f'{d}|{g}', 0)} prior visit(s))"}
    # agent planner: ONE json object, validated before anything runs. A planner
    # that silently fell back to the matrix would report coverage the model
    # never chose, so an unusable answer is a refusal, not a default.
    prompt = json.dumps({
        "documents": DOCS, "degradations": DEGRADATIONS,
        "coverage": cov, "recent": history[-5:],
    })
    out = _run([str(REPO / "tools" / "run-agent.sh"), f"--agent={agent}",
                f"--prompt={prompt}", "--trigger=pulse"])
    try:
        obj = json.loads(out.stdout[out.stdout.index("{"):out.stdout.rindex("}") + 1])
        pick = obj.get("result") or obj
        if pick["doc"] not in DOCS or pick["degrade"] not in DEGRADATIONS:
            raise ValueError(f"agent named an unknown cell: {pick}")
        return {"doc": pick["doc"], "degrade": pick["degrade"],
                "seed": int(pick.get("seed", n)), "reason": str(pick.get("reason", ""))[:200]}
    except (ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"REFUSING: the agent planner did not answer usably ({exc})\n"
                         f"  stderr tail: {out.stderr[-300:]}")


def render(doc: str, degrade: str, seed: int, into: pathlib.Path) -> pathlib.Path:
    """The degraded page, carrying the SAME data the clean render carries."""
    into.mkdir(parents=True, exist_ok=True)
    r = _run([PY, str(REPO / "tools" / "gen-invoice-images.py"),
              "--only", doc, "--degrade", degrade, "--seed", str(seed),
              "--suffix", "--out", str(into)])
    if r.returncode != 0:
        raise RuntimeError(f"render failed: {r.stderr[-300:]}")
    made = sorted(into.glob("*.jpg"))
    if not made:
        raise RuntimeError(f"render wrote nothing for {doc}/{degrade}")
    return made[-1]


def truth_for(doc: str) -> dict:
    return parse_image_txt((FIXTURE / f"{doc}.image.txt").read_text(encoding="utf-8"))


def book_owner_of(truth: dict) -> tuple[str | None, str | None]:
    """Whose book this document belongs to, as (party slug, IČO), read from the
    fixture's own party spine — the loop never invents a client.

    BOTH halves matter and they are not interchangeable: the importer is told
    the owner by IČO and stamps the party it resolves to. Passing the seller's
    IČO for a RECEIVED invoice names the wrong side, and the row would come
    back unbooked with the importer politely explaining why."""
    seed = yaml.safe_load((REPO / "state" / "fixtures" / "consulting-firm.seed.yml")
                          .read_text(encoding="utf-8"))
    by_ico = {str(t["value"]): t["party"] for t in seed.get("party-tax-identity", [])
              if t.get("scheme") == "ICO"}
    for side in ("seller_ico", "buyer_ico"):
        ico = str(truth.get(side) or "")
        party = by_ico.get(ico)
        if party and party.startswith("synthetic-client-"):
            return party, ico
    return None, None


def sweep_and_verify(intake: pathlib.Path, image: pathlib.Path, truth: dict) -> dict:
    """Sweep the image into the queue, then let the ORACLE decide the verdict.
    Returns what happened, including the queue row's own shape."""
    (intake / "incoming").mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, intake / "incoming" / image.name)
    sw = _run([PY, str(REPO / "tools" / "invoice-vision-intake.py"), "--intake", str(intake)])
    said = ((sw.stderr or "") + (sw.stdout or "")).strip()[-300:]
    # rc=1 is the sweep's NORMAL outcome — "held for operator verify", the
    # Pulse finding it exists to raise. Only rc>=2 means it could not read the
    # estate (KEAP down or too slow, ollama unarmed), which is an environment
    # answer and not a verdict on the pipeline: the two must not share a bucket.
    if sw.returncode >= 2:
        return {"stage": "sweep", "ok": False, "env": True,
                "detail": said or f"exit {sw.returncode}, and it said nothing"}

    extracts = sorted((intake / "extracts").glob("*.extract.json"))
    if not extracts:
        return {"stage": "sweep", "ok": False, "detail": "no sidecar was produced"}
    sidecar = json.loads(extracts[-1].read_text(encoding="utf-8"))
    record = sidecar.get("record") or sidecar.get("deterministic") or {}
    hits = BENCH.score_extraction(record, truth)
    accuracy = round(sum(1 for v in hits.values() if v) / len(hits), 3) if hits else 0.0

    # The queue itself is the answer, not the exit code: a re-swept sidecar is
    # "already queued, newly queued 0", which is success wearing a zero.
    rows = {r.get("sidecar_id"): r for r in digest_absorb.read_rows("pending-invoice-verify")}
    row = rows.get(extracts[-1].name)
    verdict = "approve" if all(hits.values()) else "reject"
    vr = {"stage": "verify", "ok": True, "accuracy": accuracy, "verdict": verdict,
          "fields": hits, "queued": row is not None,
          "source_path": (row or {}).get("source_path", ""), "record": record}
    if row is None:
        vr.update(ok=False, detail=f"the sweep wrote no queue row for this sidecar ({said})")
        return vr
    vr["queue_slug"] = row["slug"]
    vv = _run([PY, str(REPO / "tools" / "invoice-verify.py"), verdict, row["slug"]])
    if vv.returncode != 0:
        vr.update(ok=False, detail=f"{verdict} failed: {vv.stderr[-300:]}")
    return vr


def absorb(intake: pathlib.Path, owner_ico: str | None) -> subprocess.CompletedProcess:
    cmd = [PY, str(REPO / "tools" / "digest-import-vision.py"), str(intake / "extracts"),
           "--absorb", "--fixture-mode"]
    if owner_ico:
        cmd += [f"--book-owner-ico={owner_ico}"]
    return _run(cmd)


def assert_books(truth: dict, owner: str | None, expect_booked: bool) -> dict:
    """What the estate now holds about this document — the half vision-bench
    cannot see. Identity, uniqueness, and a balanced entry."""
    doc_no = str(truth.get("id") or "")
    invoices = [r for r in digest_absorb.read_rows("invoice")
                if str(r.get("document_number") or "") == doc_no]
    out = {"booked": len(invoices), "identity_ok": None, "balanced": None, "slugs": []}
    out["slugs"] = sorted(str(r.get("slug")) for r in invoices)
    if not expect_booked:
        out["ok"] = len(invoices) == 0
        out["detail"] = "" if out["ok"] else "a rejected document reached the books"
        return out
    if len(invoices) != 1:
        out["ok"] = False
        out["detail"] = f"{len(invoices)} rows for one document (expected 1)"
        return out
    inv = invoices[0]
    want = nos_digest.invoice_slug(inv.get("book_owner"), inv.get("seller"),
                                   inv.get("document_number"))
    out["identity_ok"] = inv.get("slug") == want
    postings = [p for p in digest_absorb.read_rows("posting")
                if str(p.get("entry") or "").endswith(str(inv.get("slug")))]
    debit = sum(float(p.get("amount") or 0) for p in postings if p.get("direction") == "debit")
    credit = sum(float(p.get("amount") or 0) for p in postings if p.get("direction") == "credit")
    out["balanced"] = bool(postings) and round(debit - credit, 2) == 0
    out["ok"] = bool(out["identity_ok"]) and bool(out["balanced"])
    out["detail"] = "" if out["ok"] else (
        f"identity {out['identity_ok']}, balanced {out['balanced']} "
        f"(dr {debit} / cr {credit}, {len(postings)} posting(s))")
    return out


def teardown(slugs: list[str], tmp: pathlib.Path, queue_slug: str = "") -> str:
    """Remove exactly what this cycle booked — a bundle of the known slugs, not
    a whole-table reset, so a cycle can run beside real rows without touching
    them. Leaf-first ordering and the referrers probe are the teardown's own."""
    if not (slugs or queue_slug):
        return "nothing booked"
    invoices = set(slugs)
    bundle = {
        "invoice": [{"slug": s} for s in sorted(invoices)],
        "invoice-line": [{"slug": r["slug"]} for r in digest_absorb.read_rows("invoice-line")
                         if r.get("invoice") in invoices],
        "journal-entry": [{"slug": r["slug"]} for r in digest_absorb.read_rows("journal-entry")
                          if r.get("source") in invoices],
    }
    entries = {r["slug"] for r in bundle["journal-entry"]}
    bundle["posting"] = [{"slug": r["slug"]} for r in digest_absorb.read_rows("posting")
                         if r.get("entry") in entries]
    # The exercise's own queue row goes too: a nightly loop that accretes
    # pending rows buries the operator's real queue in its own rehearsal.
    if queue_slug:
        bundle["pending-invoice-verify"] = [{"slug": queue_slug}]
    path = tmp / "teardown.yml"
    path.write_text(yaml.safe_dump(bundle, sort_keys=False), encoding="utf-8")
    r = _run([PY, str(REPO / "tools" / "digest-teardown.py"), str(path), "--confirm"])
    return (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "?"


def cycle(n: int, plan: dict) -> dict:
    started = time.time()
    rec = {"n": n, **plan, "wall_clock_s": None}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pipeline-exercise-"))
    truth = truth_for(plan["doc"])
    owner, owner_ico = book_owner_of(truth)
    rec["book_owner"] = owner
    try:
        image = render(plan["doc"], plan["degrade"], plan["seed"], tmp / "render")
        intake = tmp / (owner or "unbooked")
        vr = sweep_and_verify(intake, image, truth)
        rec.update({k: vr[k] for k in ("accuracy", "verdict", "queued", "source_path")
                    if k in vr})
        rec["fields"] = vr.get("fields")
        if not vr.get("ok"):
            rec.update(ok=False, stage=vr.get("stage"), detail=vr.get("detail"),
                       env=bool(vr.get("env")))
            return rec
        # What the books held BEFORE this cycle. Only the difference is ours to
        # remove — the fixture documents are seeded rows, and a cycle that
        # exercised one used to delete it.
        before = {str(r.get("slug")) for r in digest_absorb.read_rows("invoice")}
        ab = absorb(intake, owner_ico)
        rec["absorb_rc"] = ab.returncode
        books = assert_books(truth, owner, expect_booked=vr["verdict"] == "approve")
        rec["books"] = books
        rec["ok"] = bool(books.get("ok"))
        rec["detail"] = books.get("detail", "")
        mine = [s for s in (books.get("slugs") or []) if s not in before]
        rec["created"] = mine
        rec["teardown"] = teardown(mine, tmp, vr.get("queue_slug", ""))
        return rec
    except Exception as exc:  # noqa: BLE001 — a cycle's failure is data, not a crash
        rec.update(ok=False, stage="cycle", detail=f"{type(exc).__name__}: {exc}")
        return rec
    finally:
        rec["wall_clock_s"] = round(time.time() - started, 1)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--planner", choices=["matrix", "agent"], default="matrix")
    ap.add_argument("--agent", default="pipeline-clerk",
                    help="agent name for --planner agent")
    ap.add_argument("--doc", help="force the document (skips the planner's choice)")
    ap.add_argument("--degrade", help="force the degradation profile")
    args = ap.parse_args(argv)

    if not DOCS:
        print(f"REFUSING: no *.image.txt fixtures under {FIXTURE}", file=sys.stderr)
        return 2
    if args.degrade and args.degrade not in DEGRADATIONS:
        print(f"REFUSING: unknown degradation {args.degrade!r} — have {DEGRADATIONS}",
              file=sys.stderr)
        return 2

    cov = load_coverage()
    cycles: list[dict] = []
    for n in range(1, args.cycles + 1):
        plan = plan_cycle(args.planner, cov, n, cycles, args.agent,
                          (args.doc, args.degrade))
        print(f"cycle {n}/{args.cycles}: {plan['doc']} · {plan['degrade']} "
              f"(seed {plan['seed']}) — {plan['reason']}")
        rec = cycle(n, plan)
        cycles.append(rec)
        cov[f"{plan['doc']}|{plan['degrade']}"] = cov.get(
            f"{plan['doc']}|{plan['degrade']}", 0) + 1
        save_coverage(cov)
        label = "held" if rec.get("ok") else ("COULD NOT RUN" if rec.get("env") else "FINDING")
        print(f"  {label}"
              f" · accuracy {rec.get('accuracy')} · {rec.get('verdict')}"
              f" · {rec.get('wall_clock_s')}s"
              + (f" · {rec['detail']}" if rec.get("detail") else ""))

    STATE.mkdir(parents=True, exist_ok=True)
    report = {
        "cycles": cycles,
        "held": sum(1 for c in cycles if c.get("ok")),
        "findings": [c for c in cycles if not c.get("ok") and not c.get("env")],
        "could_not_run": [c for c in cycles if c.get("env")],
        "coverage_cells": len(DOCS) * len(DEGRADATIONS),
        "cells_visited": sum(1 for v in cov.values() if v),
    }
    (STATE / "last-run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{report['held']}/{len(cycles)} cycle(s) held · "
          f"{report['cells_visited']}/{report['coverage_cells']} cells visited ever")
    if report["could_not_run"]:
        print(f"{len(report['could_not_run'])} cycle(s) COULD NOT RUN — the estate "
              f"was unreadable, not wrong:", file=sys.stderr)
        for c in report["could_not_run"]:
            print(f"  cycle {c['n']}: {c.get('detail')}", file=sys.stderr)
    if report["findings"]:
        return 3
    return 2 if report["could_not_run"] and not report["held"] else 0


if __name__ == "__main__":
    sys.exit(main())
