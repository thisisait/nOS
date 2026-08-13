"""Anatomy gate: when the fallback model answers, the record says so.

THE DEFECT, read from the source on 2026-08-13.

`Runner::run()` writes `agent_sessions.model_uri` at session OPEN, from
`$llm->identifier()` — the PRIMARY client, before a single call has been made.
`callWithRetry()` then had two independent fallback paths (an unrecognised
error phrase, and exhausted transient retries) and BOTH returned the fallback's
response with no trace that a different model produced it. The session,
the events, and anything reading them attributed the fallback's output to the
primary.

WHY THAT IS NOT A COSMETIC MISLABEL. The `events` table is WORM-triggered and
hash-chained (`AuditChain`), and the RFL corpus has no provenance column and no
relabelling path. Provenance is either correct at write time or wrong for good.
Every agent profile in this repo declares a fallback, so the path is reachable
today, not hypothetically after MiniMax is armed.

RULING 2 (docs/minimax-groundwork.md) chose fail-closed classification — an
error phrase the classifier does not recognise stays PERMANENT and is not
retried — explicitly on the condition that the unmatched message be LOGGED, so
a foreign backend's real phrasings can be learned from one outage rather than
guessed from documentation nobody verified. `ClaudeCliAdapter` matches three
Anthropic strings; everything else takes the fallback path, and until this
change took it in silence.

WHAT IS PINNED: that both paths go through one place, that the place records
who served and emits the message it could not classify, and that the session's
attribution is corrected at END — where an answer exists — rather than left as
written at open, where none does.

WHAT THIS CANNOT DO: prove the runtime behaves this way. AgentKit has no PHP
unit harness in this repo (`wing/tests/` is Playwright e2e only), and the
runtime that drives the estate's ceremonies is still the shell bridge. Shape
here; effect belongs to the spine's supervised parallel run.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files/anatomy/wing/app/AgentKit/Runner.php"


def _source() -> str:
    return RUNNER.read_text(encoding="utf-8")


def _method(src: str, signature: str) -> str:
    """The body of one method, from its signature to the next one."""
    start = src.index(signature)
    nxt = src.find("\n\tprivate function ", start + len(signature))
    alt = src.find("\n\tpublic function ", start + len(signature))
    end = min(x for x in (nxt, alt, len(src)) if x > 0)
    return src[start:end]


def test_both_fallback_paths_go_through_one_place():
    """Two call sites drifting apart is how one of them lost its event."""
    src = _source()
    body = _method(src, "private function callWithRetry(")
    assert body.count("serveFallback(") == 2, (
        "callWithRetry no longer routes BOTH fallback paths (unrecognised "
        f"error, exhausted retries) through serveFallback — found "
        f"{body.count('serveFallback(')}. A path that builds its own fallback "
        "client answers without recording that it did."
    )
    assert "fromUri($agent->modelFallbackUri)" not in body, (
        "callWithRetry builds a fallback client directly again, bypassing the "
        "one place that records the substitution."
    )


def test_the_fallback_records_who_actually_answered():
    src = _source()
    body = _method(src, "private function serveFallback(")
    assert re.search(r"\$this->servedByUri\s*=\s*\$fallback->identifier\(\)", body), (
        "serveFallback no longer records the identifier of the client that "
        "answered. Without it the session keeps the primary's name, which is "
        "written at open before anything has answered at all."
    )


def test_the_unmatched_message_is_emitted_verbatim():
    """Ruling 2's condition: fail closed, but say what you could not classify."""
    src = _source()
    body = _method(src, "private function serveFallback(")
    assert "agent_model_fallback" in body, (
        "the fallback no longer emits an event. Engagement becomes invisible "
        "again — the state ruling 2 accepted fail-closed classification to "
        "escape."
    )
    assert "unmatched_message" in body and "getMessage()" in body, (
        "the event no longer carries the unclassified error message. That "
        "string is the only evidence from which a real rule for a foreign "
        "backend's phrasing could ever be written."
    )


def test_the_session_attribution_is_corrected_at_the_end():
    src = _source()
    assert re.search(
        r"servedByUri\s*!==\s*null\s*\?\s*\['model_uri'\s*=>\s*\$this->servedByUri\]",
        src,
    ), (
        "endSession no longer patches `model_uri` with the client that served. "
        "The value written at session open is the primary's, chosen before any "
        "call was made, and the events it feeds are hash-chained — so leaving "
        "it is a permanent misattribution, not a stale field."
    )


def test_the_ordinary_session_is_left_alone():
    """A primary-served run must not be patched, or `null` becomes a claim."""
    src = _source()
    assert "private ?string $servedByUri = null;" in src, (
        "the served-by marker is no longer nullable-by-default; a run the "
        "primary served must stay distinguishable from one where a fallback "
        "served unnoticed."
    )
    run_body = _method(src, "public function run(")
    assert "$this->servedByUri = null;" in run_body, (
        "run() no longer resets the marker. A second sequential session in the "
        "same process would inherit the first one's fallback attribution."
    )
