#!/usr/bin/env python3
"""What we said the night would do, beside what it did.

WHY THIS EXISTS. This estate has eleven readers and no memory. Every morning
someone runs them, sees green, and is reassured — but a reading with no PRIOR
EXPECTATION cannot surprise anyone, and the only readings worth the run are the
ones that can. On 2026-08-23 `sec-transport-pg` flipped to `confirmed` and was
read as the system self-verifying; it had flipped on a sampling accident, and
nothing recorded that anyone had expected it to flip at all.

That is `docs/hidden_fees/29` one level up. Fee 29's rule is that a condition
under which a measurement means nothing belongs in the DATA rather than in a
sentence beside it. An expectation is the same move applied to time: state
before the night what each reading should say afterwards, and let the morning
be a comparison instead of an impression.

    tools/night-watch.py --record "pre-converge 2026-08-24"
    tools/night-watch.py --check

WHAT AN EXPECTATION IS. Authored, never derived. `state/night-watch.json` holds
the readings this tool took plus an `expect` block a human or agent WROTE, each
entry carrying a reason. Deriving the expectation from the reading would make
every night trivially successful, which is the defect this file is against.

FIVE VERDICTS, and UNEXPECTED is the one that earns the tool:

    MET         predicted to change, and changed
    HELD        predicted to stay put, and did — a control that held
    UNMET       the prediction did not come true, either way round
    UNEXPECTED  changed with no prediction — the interesting column
    STABLE      no prediction, no change

An UNEXPECTED is not a failure. It is the thing nobody would have looked for,
which is exactly what an unattended night is for producing.

WHAT IT WILL NOT DO. Write to the estate. It runs the same probes
`tools/roadmap-verify.py` runs and the same readers a session starts with; it
records their output and nothing else. Exit 0 always — it reports, and a
reporter that exits non-zero is a gate wearing a reader's name.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
STATE = REPO / "state/night-watch.json"
PROBES = REPO / "state/roadmap-probes.yml"

#: Readers whose one-line summary is worth carrying beside the probe verdicts.
#: Command → the line to keep. Deliberately few: a record nobody reads is the
#: Snapshot table this estate deleted on 2026-08-23 for lying in the
#: reassuring direction.
READERS = {
    "red": ["tools/red-status.py"],
    "queue": ["tools/rem-status.py"],
    "loop": ["tools/loop-status.py"],
    # Container health — the reading that was MISSING on 2026-08-22, when
    # Nextcloud and FreeScout were both down and no morning reader said so.
    # red-status.py cannot carry this by charter (files and local SQLite only,
    # no daemons); this tool already talks to Docker via the tls probes, so it
    # is the honest home until container health becomes a declared source fed
    # from a file. The summary line comes FIRST so `head` is the comparison;
    # awk refuses an empty docker read rather than printing "0 not-clean of 0"
    # — absence must never read as health.
    "containers": ["bash", "-c",
                   "docker ps -a --format '{{.Names}}\t{{.State}}\t{{.Status}}'"
                   " | awk -F'\t' '{t++; if ($2!=\"running\" || $3 ~ /unhealthy/)"
                   " {b++; bad=bad\" \"$1}}"
                   " END{if(!t){print \"docker unreadable - container state UNKNOWN\"; exit 3}"
                   " printf \"%d not-clean%s\\nof %d containers\\n\", b, bad, t}'"],
}

TIMEOUT = 300


def _run(argv: list[str], shell: bool = False) -> tuple[int, str]:
    try:
        p = subprocess.run(
            argv if not shell else ["bash", "-c", argv[0]],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=REPO)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {TIMEOUT}s"
    except OSError as exc:                                      # pragma: no cover
        return 126, str(exc)
    return p.returncode, (p.stdout or p.stderr).strip()


def read_probes() -> dict:
    """Every roadmap probe's exit code and the verdict it echoes.

    The verdict matters more than the code: nine probes used to swallow theirs
    inside `test "$(…)"` and stored empty evidence (`docs/hidden_fees/29`).
    """
    import yaml
    probes = yaml.safe_load(PROBES.read_text(encoding="utf-8")) or {}
    out = {}
    for key, cmd in sorted(probes.items()):
        if not isinstance(cmd, str):
            continue
        rc, said = _run([cmd], shell=True)
        out[key] = {"done": rc == 0, "said": said.splitlines()[-1][:120] if said else ""}
    return out


def read_readers() -> dict:
    out = {}
    for name, argv in READERS.items():
        rc, said = _run(argv)
        head = [ln for ln in said.splitlines() if ln.strip()]
        out[name] = {"rc": rc, "head": head[0][:160] if head else ""}
    return out


def snapshot() -> dict:
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "probes": read_probes(),
            "readers": read_readers()}


def cmd_record(label: str) -> int:
    prior = json.loads(STATE.read_text()) if STATE.exists() else {}
    snap = snapshot()
    snap["label"] = label
    # An `expect` block already present is CARRIED, never regenerated: it is
    # authored, and re-deriving it from tonight's reading would make every
    # morning agree with itself.
    snap["expect"] = prior.get("expect", {})
    STATE.write_text(json.dumps(snap, indent=2) + "\n")
    n_done = sum(1 for v in snap["probes"].values() if v["done"])
    print(f"recorded {len(snap['probes'])} probes ({n_done} done), "
          f"{len(snap['readers'])} readers → {STATE.relative_to(REPO)}")
    if not snap["expect"]:
        print("NO EXPECTATIONS AUTHORED. Add an `expect` block naming what the "
              "night should change and WHY, or tomorrow is an impression.")
    return 0


def cmd_check() -> int:
    if not STATE.exists():
        print(f"no record at {STATE.relative_to(REPO)} — run --record first")
        return 0
    before = json.loads(STATE.read_text())
    now = snapshot()
    expect = before.get("expect", {})

    lines, met, unmet, unexpected = [], 0, 0, 0
    keys = sorted(set(before["probes"]) | set(now["probes"]))
    for k in keys:
        was = before["probes"].get(k, {})
        isnow = now["probes"].get(k, {})
        changed = was.get("done") != isnow.get("done") or was.get("said") != isnow.get("said")
        want = expect.get(k)
        if want:
            # KIND IS A FIELD, NOT A READING OF THE PROSE. The first cut had
            # only "an expectation predicts a change", so every `stays DONE`
            # prediction that HELD was reported UNMET — the tool calling its
            # own control a failure. Inferring "hold" from words like "stays"
            # would be a detector matching prose, which is this repository's
            # most repeated defect.
            kind = want.get("kind", "change")
            why = want.get("why", "")
            held = (kind == "hold" and not changed) or (kind == "change" and changed)
            if held:
                met += 1
                verb = "HELD" if kind == "hold" else "MET "
                shown = (f"still {isnow.get('said','')!r}" if kind == "hold"
                         else f"{was.get('said','')!r} -> {isnow.get('said','')!r}")
                lines.append(f"  {verb}        {k}: {shown}")
            else:
                unmet += 1
                shown = (f"{was.get('said','')!r} -> {isnow.get('said','')!r}"
                         if changed else f"still {isnow.get('said','')!r}")
                lines.append(f"  UNMET       {k}: {shown}")
                lines.append(f"              expected to {kind}: {why}")
        elif changed:
            unexpected += 1
            lines.append(f"  UNEXPECTED  {k}: {was.get('said','')!r} -> {isnow.get('said','')!r}")

    judged = set(k for k in expect if k in before["probes"] or k in now["probes"])
    for name in sorted(set(before["readers"]) | set(now["readers"])):
        w, i = before["readers"].get(name, {}), now["readers"].get(name, {})
        changed = w.get("head") != i.get("head")
        # Readers are judged through the SAME expect block, keyed `reader:<x>`.
        # The first cut never consulted expect here, so a `reader:red`
        # expectation was unfalsifiable by construction: the tool could report
        # the change as UNEXPECTED but never as MET or UNMET — an authored
        # prediction the morning could not grade.
        want = expect.get(f"reader:{name}")
        if want:
            judged.add(f"reader:{name}")
            kind = want.get("kind", "change")
            held = (kind == "hold" and not changed) or (kind == "change" and changed)
            if held:
                met += 1
                verb = "HELD" if kind == "hold" else "MET "
                lines.append(f"  {verb}        reader:{name}: "
                             + (f"still {i.get('head','')!r}" if kind == "hold"
                                else f"{w.get('head','')!r} -> {i.get('head','')!r}"))
            else:
                unmet += 1
                shown = (f"{w.get('head','')!r} -> {i.get('head','')!r}"
                         if changed else f"still {i.get('head','')!r}")
                lines.append(f"  UNMET       reader:{name}: {shown}")
                lines.append(f"              expected to {kind}: {want.get('why', '')}")
        elif changed:
            unexpected += 1
            lines.append(f"  UNEXPECTED  reader:{name}")
            lines.append(f"              was: {w.get('head','')}")
            lines.append(f"              now: {i.get('head','')}")

    # An expectation that names nothing recorded is a prediction nobody can
    # grade — say so rather than counting it among the authored ones silently.
    for k in sorted(set(expect) - judged):
        lines.append(f"  UNJUDGEABLE {k}: names no probe or reader in the record")

    print(f"night-watch: recorded {before.get('label','?')} at {before.get('at','?')}")
    print("\n".join(lines) if lines else "  nothing moved, and nothing was expected to")
    print(f"\n  {met} met · {unmet} UNMET · {unexpected} unexpected "
          f"· {len(expect)} expectation(s) authored")
    if unmet:
        print("  an UNMET is the useful kind of wrong: something was predicted "
              "and did not happen, which is a fact about the estate rather than "
              "about the reader.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", metavar="LABEL", help="capture readings now")
    g.add_argument("--check", action="store_true", help="compare against the record")
    args = ap.parse_args()
    return cmd_record(args.record) if args.record else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
