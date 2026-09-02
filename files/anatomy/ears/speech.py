#!/usr/bin/env python3
"""Saying things out loud — including the one thing that is hard to say.

TWO JOBS, AND THE SECOND IS THE WHOLE POINT.

1. Speak Czech or English through macOS `say`. Zero dependencies, both voices
   already on the host, and one voice name per language in
   files/anatomy/ears/wording.yml — which is the seam a cloned voice slots into later
   without touching anything else here.

2. Turn a cortex-lang chain into a sentence. `@input | map(tax:02.02) | rank()`
   read character by character is noise, and NOISE THAT SOUNDS LIKE AN ANSWER
   IS WORSE THAN SILENCE, because the operator is being asked to approve an
   action from what they heard. So the chain is verbalised from the wording
   table, or it is not spoken at all.

THREE RULES THIS FILE ENFORCES, each because the alternative is a confident
wrong noise:

  * FAIL CLOSED. An opcode or namespace with no wording refuses the WHOLE
    chain. There is no fallback to raw syntax — half English, half punctuation
    is the most misleading output available.
  * IDENTIFIERS ARE SPELLED. `tax:02.02` is said "nula dva tečka nula dva", not
    "two point zero two", because the second is a different node from the one on
    the screen and the operator is approving by ear.
  * A MUTATING CHAIN SAYS SO LAST. The final clause is "this changes
    something", in the operator's own language, where it cannot be missed.

    python3 speech.py "@input | map(tax:02.02) | rank()"      # print + speak
    python3 speech.py --lang=en --quiet "@input | rank()"      # print only
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

import yaml

REPO_WORDING = pathlib.Path(
    os.environ.get("EARS_WORDING",
                   pathlib.Path(__file__).resolve().parent / "wording.yml"))

#: Opcodes that change something. Kept in sync with the cortex registry's
#: `mutating` flags by tests/anatomy/test_speech_mutating_matches_registry.py.
MUTATING = {"link", "insert", "update", "delete", "preserve", "route", "review",
            "delegate"}

#: Czech-only letters. Cheap, and it is the right cheap: the operator speaks
#: one of two languages, and every Czech sentence of any length carries one.
#: ponytail: if a third language ever lands, this becomes a real detector.
_CS_LETTERS = set("ěščřžýáíéúůťďňó")
_CS_WORDS = {"a", "je", "na", "co", "kolik", "kde", "ukaz", "ukaž", "zaloz",
             "založ", "smaz", "smaž", "jak", "ktery", "který", "ano", "ne"}


def load_wording(path: pathlib.Path | None = None) -> dict:
    return yaml.safe_load((path or REPO_WORDING).read_text(encoding="utf-8"))


def detect_lang(text: str, default: str = "cs") -> str:
    low = text.lower()
    if any(ch in _CS_LETTERS for ch in low):
        return "cs"
    if _CS_WORDS & set(re.findall(r"\w+", low)):
        return "cs"
    return "en" if re.search(r"[a-z]", low) else default


def spell(identifier: str, lang: str, wording: dict) -> str:
    """Digits and separators become words; anything else is said as written."""
    table = wording["digits"][lang]
    if not re.fullmatch(r"[0-9.\-_]+", identifier):
        return identifier
    return " ".join(table.get(ch, ch) for ch in identifier)


class Unspeakable(Exception):
    """The chain contains something this table has no words for."""


def _operand(raw: str, lang: str, wording: dict) -> str:
    if ":" not in raw:
        return raw
    ns, _, ident = raw.partition(":")
    phrase = wording["namespaces"].get(ns)
    if not phrase or lang not in phrase:
        raise Unspeakable(f"namespace {ns!r} has no {lang} wording")
    return phrase[lang].replace("{id}", spell(ident, lang, wording))


def verbalise(chain: str, lang: str, wording: dict | None = None) -> str:
    """A cortex-lang chain as one sentence. Raises Unspeakable rather than guess."""
    wording = wording or load_wording()
    stages, mutating = [], False

    for raw_stage in chain.split("|"):
        stage = raw_stage.strip()
        if not stage or stage.startswith("@"):
            continue
        match = re.match(r"([a-z]+)\s*\((.*)\)\s*$", stage) or re.match(r"([a-z]+)\s*$", stage)
        if not match:
            raise Unspeakable(f"cannot parse stage {stage!r}")
        opcode = match.group(1)
        args = match.group(2) if match.lastindex and match.lastindex > 1 else ""

        spec = wording["opcodes"].get(opcode)
        if not spec or lang not in spec:
            raise Unspeakable(f"opcode {opcode!r} has no {lang} wording")
        mutating = mutating or opcode in MUTATING

        operand, raw_id, params = "", "", []
        for arg in [a.strip() for a in args.split(",") if a.strip()]:
            if arg.startswith("?"):
                key, _, value = arg[1:].partition("=")
                phrase = wording["params"].get(key)
                if not phrase or lang not in phrase:
                    raise Unspeakable(f"param {key!r} has no {lang} wording")
                if key == "commit" and value.strip('"').lower() != "true":
                    continue
                params.append(phrase[lang].replace("{value}", value.strip('"')))
            else:
                operand = _operand(arg, lang, wording)
                raw_id = spell(arg.partition(":")[2] or arg, lang, wording)

        text = spec[lang].replace("{operand}", operand)
        # `{id}` appears in stages whose operand IS the identifier (delegate).
        # It takes the BARE id, not the namespace phrase — handing it `operand`
        # produced "hand it to the agent agent jeff", measured 2026-08-31.
        if "{id}" in text:
            text = text.replace("{id}", raw_id or operand or "?")
        stages.append(text + "".join(params))

    if not stages:
        raise Unspeakable("no stages to say")

    sentence = wording["prefix"][lang] + wording["join"][lang].join(stages)
    return sentence + (wording["mutating_suffix"][lang] if mutating else ".")


def say(text: str, lang: str, wording: dict | None = None, block: bool = True) -> bool:
    """Speak, and report whether it actually happened. False is not an error —
    it is the answer, and the caller prints the text instead of assuming ears."""
    wording = wording or load_wording()
    voice = (wording.get("voices") or {}).get(lang)
    if not voice or not text.strip():
        return False
    cmd = ["say"] + (["-v", voice] if voice else []) + [text]
    try:
        proc = subprocess.run(cmd, capture_output=True) if block \
            else subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return False
    return proc.returncode == 0 if block else True


def speak_answer(prose: str, chain: str | None, lang: str | None = None,
                 wording: dict | None = None) -> dict:
    """What the operator hears for one answer: the prose, then the proposal.

    Returns what was said and what could NOT be said, because a launcher that
    reported success while the chain stayed silent would be the estate's own
    favourite defect wearing a new hat.
    """
    wording = wording or load_wording()
    lang = lang or detect_lang(prose or chain or "")
    spoken, refused = [], None

    if prose.strip():
        spoken.append(prose.strip())
    if chain:
        try:
            spoken.append(verbalise(chain, lang, wording))
        except Unspeakable as exc:
            refused = str(exc)
            spoken.append(wording["refusal"][lang])

    text = " ".join(spoken)
    return {"lang": lang, "text": text, "spoken": say(text, lang, wording),
            "unspeakable": refused}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chain")
    ap.add_argument("--lang", default=None)
    ap.add_argument("--quiet", action="store_true", help="print, do not speak")
    args = ap.parse_args()

    wording = load_wording()
    lang = args.lang or detect_lang(args.chain)
    try:
        text = verbalise(args.chain, lang, wording)
    except Unspeakable as exc:
        print(f"unspeakable: {exc}", file=sys.stderr)
        print(wording["refusal"][lang])
        return 3
    print(text)
    if not args.quiet and not say(text, lang, wording):
        print("(nothing spoke — no `say` or no voice for this language)",
              file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
