#!/usr/bin/env python3
"""How do I do X with nOS: the doc passages that answer it, and the steps for a named service.

READER. `--json "<question>"`. Splits docs/systems/*/README.md, docs/nos-cli.md,
README.md, docs/glossary.md (by heading) and the profiles/*.yml headers into
passages, ranks them by token overlap with the question (diacritics folded,
a small cs/en verb synonym map) and returns the top 3. When the question names
a manifest service: its install flag, enabled now (nos_identity, as
services-status.py), the config.yml line, and the converge/verify commands
whose tag is read from the include_role that runs under that flag.
It runs nothing. Exits 0 always; a source it could not read is named in `unknown`.
Gate: tests/anatomy/test_nos_guide_reader.py.
"""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nos_identity  # noqa: E402

TOP, TEXT_MAX = 3, 1200
FIXED_DOCS = ("docs/nos-cli.md", "README.md", "docs/glossary.md")
STOP = {"how", "do", "does", "i", "the", "a", "an", "to", "in", "on", "of", "is", "it", "what", "why", "and",
        "or", "my", "me", "can", "with", "for", "jak", "co", "to", "je", "se", "na", "v", "mam", "proc", "si"}
# Verb prefix -> the words a doc uses for it (Czech is inflected, so a prefix, not a word).
SYNONYMS = {
    ("zapn", "zapni", "zapin", "povol", "enable", "install", "nainstal", "instal"): ("enable", "install"),
    ("vypn", "vypni", "vypin", "zakaz", "disable", "odinstal", "uninstall"): ("disable",),
    ("aktualiz", "update", "upgrad", "povys"): ("update", "upgrade"),
    ("oprav", "fix", "repair"): ("fix",),
    ("cerven", "red"): ("red",),
}
DISABLE = SYNONYMS[next(k for k in SYNONYMS if "vypn" in k)]
CANON = {w: words[0] for words in SYNONYMS.values() for w in words}


def fold(s: str) -> str:
    """Lowercase, no diacritics, `-` and `_` as spaces."""
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[-_]", " ", "".join(c for c in s if not unicodedata.combining(c)))


def tokens(s: str) -> list[str]:
    f = fold(s)
    f = re.sub(r"\bturn on\b", "enable", re.sub(r"\bturn off\b", "disable", f))
    out = [w for w in re.findall(r"[a-z0-9]+", f) if w not in STOP]
    for w in list(out):
        for prefixes, words in SYNONYMS.items():
            if w.startswith(prefixes):
                out += words
    return out


def concepts(s: str) -> set[str]:
    """tokens() with each synonym group as one word, so "install" and "enable" match once."""
    return {CANON.get(w, w) for w in tokens(s)}


def _split_md(text: str) -> list[tuple[str, str]]:
    """(heading, body) per markdown heading; a `#` inside a code fence is not one."""
    out, head, body, fence = [], "", [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"#{1,6}\s+(.*)", line)
        if m:
            out.append((head, "\n".join(body).strip()))
            head, body = m.group(1).strip(), []
        else:
            body.append(line)
    out.append((head, "\n".join(body).strip()))
    return [(h, b) for h, b in out if b]


def _profile_header(text: str) -> list[tuple[str, str]]:
    lines = [re.sub(r"^#\s?", "", ln) for ln in text.splitlines()[:40] if ln.startswith("#")]
    lines = [ln for ln in lines if not re.fullmatch(r"[=\-\s]*", ln)]
    return [(lines[0].strip(), "\n".join(lines[1:]).strip())] if lines else []


def passages(unknown: list[str]) -> list[dict]:
    root = nos_identity.REPO
    files = [*sorted(root.glob("docs/systems/*/README.md")), *(root / p for p in FIXED_DOCS),
             *sorted(root.glob("profiles/*.yml"))]
    out = []
    for p in files:
        rel = str(p.relative_to(root))
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 — a reader names it, never dies on it
            unknown.append(rel)
            continue
        parts = _profile_header(text) if p.suffix == ".yml" else _split_md(text)
        out += [{"path": rel, "heading": h, "text": f"{h}\n\n{b}"[:TEXT_MAX]} for h, b in parts]
    return out


def rank(question: str, items: list[dict]) -> list[dict]:
    """Overlap weighted by rarity (idf): "n8n" outranks "install"; a heading or path hit counts twice."""
    q = concepts(question)
    bags = [(concepts(p["text"]), concepts(f"{p['path']} {p['heading']}")) for p in items]
    df = {w: sum(w in b or w in h for b, h in bags) for w in q}
    idf = {w: math.log((1 + len(items)) / (1 + n)) for w, n in df.items()}
    scored = []
    for p, (body, head) in zip(items, bags):
        score = sum(idf[w] for w in q & body) + 2 * sum(idf[w] for w in q & head)
        if score > 0:
            scored.append({**p, "score": round(score, 2)})
    return sorted(scored, key=lambda p: -p["score"])[:TOP]


def converge_tag(flag: str, unknown: list[str]) -> str | None:
    """The first tag of the first include/import_role whose `when` names the flag."""
    root = nos_identity.REPO
    found: list[str] = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            if any(k.endswith(("include_role", "import_role")) for k in node) \
                    and re.search(rf"\b{re.escape(flag)}\b", str(node.get("when", ""))):
                tags = node.get("tags")
                tags = [tags] if isinstance(tags, str) else tags or []
                found.extend(str(t) for t in tags[:1])
            for v in node.values():
                walk(v)
    for f in [root / "main.yml", *sorted((root / "tasks").rglob("*.yml"))]:
        try:
            walk(yaml.safe_load(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            unknown.append(str(f.relative_to(root)))
        if found:
            return found[0]
    return None


def service(question: str, unknown: list[str]) -> dict | None:
    try:
        rows = nos_identity.services()
    except Exception:  # noqa: BLE001
        unknown.append("state/manifest.yml")
        return None
    q = f" {' '.join(re.findall(r'[a-z0-9]+', fold(question)))} "
    hits = []
    for r in rows:
        flag = r.get("install_flag") or ""
        forms = {fold(r.get("id") or ""), fold(re.sub(r"^install_", "", flag))}
        forms |= {f.replace(" ", "") for f in forms}
        hits += [(len(f), r) for f in forms if f.strip() and f" {f} " in q]
    if not hits:
        return None
    row = max(hits, key=lambda h: h[0])[1]
    flag = row.get("install_flag")
    try:
        enabled = nos_identity.install_flags().get(flag)
    except Exception:  # noqa: BLE001
        unknown.append("config layers")
        enabled = None
    on = not (set(tokens(question)) & set(DISABLE))
    tag = converge_tag(flag, unknown)
    return {"id": row.get("id"), "install_flag": flag, "enabled": enabled,
            "config_line": f"{flag}: {'true' if on else 'false'}",
            "converge": f"nos --tags {tag}" if tag else "nos",
            "verify": f"nos --tags {tag},verify" if tag else "nos --tags verify"}


def collect(question: str) -> dict:
    unknown: list[str] = []
    found = rank(question, passages(unknown))
    return {"question": question, "passages": found, "service": service(question, unknown), "unknown": unknown}


def main() -> int:
    q = " ".join(a for a in sys.argv[1:] if a != "--json")
    try:
        out = collect(q)
    except Exception as e:  # noqa: BLE001
        out = {"question": q, "passages": [], "service": None, "unknown": [f"nos-guide: {type(e).__name__}"]}
    if "--json" in sys.argv[1:]:
        print(json.dumps(out))
        return 0
    for p in out["passages"]:
        print(f"== {p['path']} · {p['heading']}\n{p['text']}\n")
    if out["service"]:
        print(json.dumps(out["service"], indent=2))
    for u in out["unknown"]:
        print(f"UNKNOWN: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
