#!/usr/bin/env python3
"""Score what a push would carry before it leaves — signals first, then a local model.

Doctrine: ssot/doctrine/session-threat-model.md (the attacker is the assistant
session). Aspects are docs/review/threat-checklist.md sections 1-6.

  1. Deterministic signals from the exact push range (commits on HEAD that no
     `<remote>/*` ref has yet), each with file:line. Never the line itself.
  2. A small LOCAL Ollama model reads the signals plus a bounded, redacted diff
     excerpt and returns per-aspect scores 0-100 in strict JSON. Anything else
     is UNAVAILABLE — never a guessed number. keep_alive 0: unloaded at once.
  3. A terminal bar chart, the evidence, and the SHA-256 of this file and its
     prompt. One JSONL record per run in ~/.nos/events/prepush-scores.jsonl
     (scores, signal labels, hashes, range — no diff text, no reasons).

Advisory: exit 0 always, except `--strict`, which exits 3 when any aspect
reaches `--threshold`. These are scores, not probabilities: uncalibrated.

Ceiling: this file runs as the same user as the session it watches; that
session can rewrite it. The printed hash is the operator's tripwire, not a lock.

Usage:
    tools/prepush-score.py                     # the push range vs origin
    tools/prepush-score.py --range HEAD~10..HEAD --model off
    tools/prepush-score.py --strict --threshold 70
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
PROMPT = HERE.with_name("prepush-score.prompt.txt")
LOG = Path.home() / ".nos" / "events" / "prepush-scores.jsonl"
OLLAMA = "http://127.0.0.1:11434"
# A resident 14B starves KEAP on this host (memory: local-model-budget). Small, unloaded after.
DEFAULT_MODEL = os.environ.get("NOS_PREPUSH_MODEL", "hermes3:8b")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

ASPECTS = [
    ("wider", "1 what runs got wider"),
    ("supply", "2 supply chain"),
    ("secrets", "3 secrets"),
    ("agent", "4 agent power"),
    ("laundering", "5 self-review laundering"),
    ("session", "6 session compromise"),
]

CHECKER = ("tools/prepush-score.py", "tools/prepush-score.prompt.txt", "tools/nos-push")
GATE_PATH = re.compile(r"^tests/|allow.?list|ratchet|^files/anatomy/apex/|^\.coderabbit\.yaml$"
                       r"|^docs/review/threat-checklist\.md$")
# Converged by the playbook: declared, readable by undeclared-status. Half weight, not zero.
CONVERGED = re.compile(r"^(roles|tasks|handlers)/|^main\.yml$")
COMMENT = re.compile(r"^\s*(#(?!!)|//|--\s|\*|;|<!--)")
ASSERT = re.compile(r"\bassert\b|self\.assert\w+\(|pytest\.raises")
DOC = re.compile(r"\.(md|txt|rst)$")
# Text an agent obeys is code for this threat model, even when it is markdown.
AGENT_TEXT = re.compile(r"(^|/)(CLAUDE|AGENTS)\.md$|^\.claude/|^files/anatomy/agents/|(^|/)SKILL\.md$")

# (aspects, weight, label, path regex)
PATH_RULES = [
    (("session",), 40, "assistant settings/hooks/MCP changed", r"^\.claude/(settings|hooks)|(^|/)\.mcp\.json$"),
    (("session",), 30, "agent instructions changed (a session can plant orders here)", AGENT_TEXT.pattern),
    (("session", "wider"), 40, "persistence surface (launchd/cron/shell rc/git hook)",
     r"LaunchAgents|LaunchDaemons|\.plist(\.j2)?$|cron|(^|/)\.(zshrc|bashrc|zprofile|bash_profile|profile)$"
     r"|githooks|^\.husky/"),
    (("supply",), 15, "package manifest changed",
     r"(^|/)(package(-lock)?\.json|composer\.(json|lock)|requirements[^/]*\.txt|pyproject\.toml"
     r"|Cargo\.(toml|lock)|Brewfile|go\.(mod|sum)|Gemfile(\.lock)?)$"),
]

# (aspects, weight, label, added-line regex)
LINE_RULES = [
    (("wider",), 25, "docker.sock / privileged / host network",
     r"docker\.sock|privileged:\s*true|network_mode:\s*[\"']?host|cap_add:|pid:\s*[\"']?host"),
    (("wider",), 10, "published port", r"^\s*ports:\s*$|^\s*-\s*[\"']?\d{2,5}:\d{2,5}"),
    (("wider", "session"), 40, "persistence (launchd/cron/shell rc/git hook)",
     r"launchctl\s+(load|bootstrap|enable)|LaunchAgents|RunAtLoad|StartInterval|crontab\s|"
     r"core\.hooksPath|\.git/hooks|>>\s*\S*\.(zshrc|bashrc|zprofile|bash_profile|profile)\b"),
    (("wider", "session"), 20, "Pulse job declared or inserted", r"^\s*pulse:\s*$|pulse_jobs"),
    (("supply",), 20, "image without @sha256 digest", r"^\s*image:\s*(?!.*@sha256:)\S+"),
    (("supply",), 50, "curl|sh style install", r"(curl|wget)[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b|(ba|z)?sh\s*<\(\s*(curl|wget)"),
    (("supply",), 15, "package install", r"\b(pip3?|npm|pnpm|yarn|brew|cargo|composer|gem)\s+(install|add|require)\b"),
    (("supply",), 10, "local build becomes a running image", r"--build\b|_src_dir"),
    (("secrets",), 30, "secret store path", r"\.nos/secrets|credentials\.yml|secrets\.ya?ml|\.git-credentials|\.netrc"),
    (("secrets",), 60, "keychain read", r"\bsecurity\s+(find-(generic|internet)-password|dump-keychain|export)\b"),
    (("secrets",), 50, "browser or key store", r"Login Data|Cookies\.binarycookies|key4\.db|logins\.json|\.ssh/id_|\.aws/credentials|\.gnupg"),
    (("secrets",), 30, "binary path taken from the environment", r"\b[A-Z][A-Z0-9_]*_BIN\b\s*[:=]|(environ|getenv|ENV)[^\n]*_BIN\b"),
    (("agent",), 50, "permission bypass", r"bypassPermissions|dangerously-skip-permissions"),
    (("agent",), 20, "agent tool/dir scope", r"--allowedTools|allowed_tools|--add-dir"),
    (("agent",), 25, "MCP server", r"mcpServers|\.mcp\.json"),
    (("laundering",), 30, "test skipped or xfailed", r"pytest\.mark\.(skip|xfail)|pytest\.skip\(|@unittest\.skip"),
    (("session",), 50, "raw socket egress", r"/dev/tcp/|\b(nc|ncat|socat)\s+\S+\s+\d{2,5}\b"),
    (("session",), 40, "new git remote or push target", r"git\s+remote\s+(add|set-url)|git\s+push\s+\S*https?://"),
    (("session",), 40, "long base64-like blob", r"[A-Za-z0-9+/]{160,}={0,2}"),
    (("session",), 30, "decode-and-run", r"base64\s+(-d|--decode)|b64decode|atob\(|fromCharCode|(\\x[0-9a-fA-F]{2}){8,}"),
    (("session",), 15, "dynamic eval", r"\beval\s*[\(\"'$]|\bexec\s*\("),
    (("session",), 25, "date-gated branch (dormant trigger?)",
     r"(date|time|now)\W.{0,60}(>=|<=|>|<|==).{0,20}20\d\d-\d\d-\d\d"),
    (("session",), 15, "user/host-gated branch", r"\b(whoami|hostname|gethostname|getuser|\$USER|\$HOSTNAME)\b.{0,30}(==|!=|=~)"),
]
_PATH_RULES = [(a, w, label, re.compile(rx)) for a, w, label, rx in PATH_RULES]
_LINE_RULES = [(a, w, label, re.compile(rx)) for a, w, label, rx in LINE_RULES]
URL = re.compile(r"https?://(?:[^@/\s\"']+@)?([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
LOCAL_HOST = re.compile(r"^(localhost|127\.|0\.0\.0\.0)|\.(local|test|example|invalid|lan)$|^example\.(com|org|net)$")

_SECRET_KV = re.compile(r"(?i)((?:pass(?:word)?|secret|token|api[_-]?key|private[_-]?key|_pw)\w*[\"']?\s*[:=]\s*)"
                        r"([\"']?)[^\s\"']+")
_LONG = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)


def redact(text: str) -> str:
    text = _PEM.sub("<redacted:pem>", text)
    text = _SECRET_KV.sub(r"\1\2<redacted>", text)
    return _LONG.sub(lambda m: f"<redacted:{len(m.group())}>", text)


def _git(repo: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and out.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {out.stderr.strip()[:200]}")
    return out.stdout


def push_range(repo: Path, remote: str) -> tuple[str, str, int] | None:
    """(base, head, commits) of what `git push <remote>` would carry; None if nothing."""
    commits = _git(repo, "rev-list", "--reverse", "HEAD", "--not", f"--remotes={remote}").split()
    if not commits:
        return None
    parent = _git(repo, "rev-parse", "--verify", "-q", f"{commits[0]}^", check=False).strip()
    return parent or EMPTY_TREE, _git(repo, "rev-parse", "HEAD").strip(), len(commits)


def _diff(repo: Path, base: str, head: str) -> dict[str, dict]:
    """path -> {status, added:[(lineno, text)], deleted:[(lineno, text)], binary, exec}."""
    files: dict[str, dict] = {}
    cur: dict | None = None
    old = new = 0
    raw = _git(repo, "diff", "--no-color", "--no-ext-diff", "-U0", "-M", base, head)
    for line in raw.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
            cur = files.setdefault(path, {"status": "M", "added": [], "deleted": [],
                                          "binary": False, "exec": False})
        elif cur is None:
            continue
        elif line.startswith("new file mode"):
            cur["status"] = "A"
            cur["exec"] = line.endswith("755")
        elif line.startswith("new mode") and line.endswith("755"):
            cur["exec"] = True
        elif line.startswith("deleted file mode"):
            cur["status"] = "D"
        elif line.startswith("Binary files"):
            cur["binary"] = True
        elif line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            old, new = int(m.group(1)), int(m.group(2))
        elif line.startswith("+") and not line.startswith("+++"):
            cur["added"].append((new, line[1:]))
            new += 1
        elif line.startswith("-") and not line.startswith("---"):
            cur["deleted"].append((old, line[1:]))
            old += 1
    return files


def _sig(aspects, weight, label, path, line):
    return {"aspects": list(aspects), "weight": weight, "label": label, "file": path, "line": line}


def collect(repo: Path, base: str, head: str) -> dict:
    files = _diff(repo, base, head)
    signals: list[dict] = []
    gates = {p for p in files if GATE_PATH.search(p)}
    code = {p for p in files if p not in gates and not (DOC.search(p) and not AGENT_TEXT.search(p))}

    for path, f in files.items():
        first = (f["added"] or f["deleted"] or [(0, "")])[0][0]
        if path in CHECKER:
            signals.append(_sig(("session",), 80, "checker changed in this push", path, first))
            continue  # its own patterns would match themselves
        for aspects, w, label, rx in _PATH_RULES:
            if rx.search(path) and (f["status"] == "A" or "persistence" not in label):
                signals.append(_sig(aspects, int(w * (0.5 if CONVERGED.search(path) else 1)), label, path, first))
        if f["binary"]:
            signals.append(_sig(("supply", "session"), 30, "binary blob", path, 0))
        if f["exec"]:
            signals.append(_sig(("wider",), 20, "new executable", path, first))
        if DOC.search(path) and not AGENT_TEXT.search(path):
            continue  # prose quoting a secret path is not a read of it
        is_test = path.startswith("tests/")
        scale = 0.5 if CONVERGED.search(path) else 1.0
        for n, text in f["added"]:
            comment = COMMENT.match(text) and not AGENT_TEXT.search(path)
            for aspects, w, label, rx in _LINE_RULES:
                if is_test and "laundering" not in aspects:
                    continue  # a gate spelling the pattern it checks for is not the act
                if comment and "blob" not in label:
                    continue  # a comment naming a pattern runs nothing; a blob still counts
                if rx.search(text):
                    signals.append(_sig(aspects, int(w * scale), label, path, n))
            if not is_test:
                for host in URL.findall(text):
                    if not LOCAL_HOST.search(host) and _new_host(repo, base, host):
                        signals.append(_sig(("session",), 20, f"new network endpoint {host}", path, n))

    for gate in sorted(gates):
        f = files[gate]
        if f["status"] == "A":
            continue  # a new gate weakens nothing
        names = _named_code(repo, base, gate, code)
        net = sum(1 for _, t in f["added"] if ASSERT.search(t)) - sum(1 for _, t in f["deleted"] if ASSERT.search(t))
        lost = next((n for n, t in f["deleted"] if ASSERT.search(t)), 0)
        line = lost or (f["deleted"] or f["added"] or [(0, "")])[0][0]
        if net < 0 and names:
            signals.append(_sig(("laundering",), 60, f"gate lost {-net} assertion(s) in the same range as "
                                f"{names[0]} it names", gate, line))
        elif net < 0:
            signals.append(_sig(("laundering",), 25, f"gate lost {-net} assertion(s)", gate, line))
        elif names:
            signals.append(_sig(("laundering",), 10, "gate edited with code it names", gate, line))

    # Dedupe per (label, file); keep the first line as evidence.
    seen, uniq = set(), []
    for s in sorted(signals, key=lambda s: (-s["weight"], s["file"], s["line"])):
        key = (s["label"], s["file"])
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    det = {a: _aggregate([s for s in uniq if a in s["aspects"]]) for a, _ in ASPECTS}
    return {"base": base, "head": head, "files": len(files), "signals": uniq, "det": det,
            "excerpt": _excerpt(files, uniq)}


def _aggregate(signals: list[dict]) -> int:
    """Strongest signal per label, halved for each next label: forty files carrying
    one pattern are one finding, three different patterns are three."""
    best: dict[str, int] = {}
    for s in signals:
        label = re.sub(r" (in the same range as|endpoint) .*", "", s["label"])
        best[label] = max(best.get(label, 0), s["weight"])
    return min(100, int(sum(w / 2 ** i for i, w in enumerate(sorted(best.values(), reverse=True)))))


def _new_host(repo: Path, base: str, host: str) -> bool:
    if base == EMPTY_TREE:
        return True
    out = subprocess.run(["git", "-C", str(repo), "grep", "-q", "-F", host, base, "--"], capture_output=True)
    return out.returncode == 1


def _named_code(repo: Path, base: str, gate: str, code: set[str]) -> list[str]:
    text = _git(repo, "show", f"{base}:{gate}", check=False)
    hits = []
    for p in sorted(code):
        stem = Path(p).stem
        if p in text or (len(stem) >= 5 and stem in text):
            hits.append(p)
    return hits


def _excerpt(files: dict, signals: list[dict], budget: int = 6000) -> str:
    """Added/removed lines around the signals first, then the rest; redacted, bounded."""
    order = list(dict.fromkeys([s["file"] for s in signals] + sorted(files)))
    out, size = [], 0
    for path in order:
        f = files[path]
        rows = [f"+{n}: {t}" for n, t in f["added"][:40]] + [f"-{n}: {t}" for n, t in f["deleted"][:20]]
        chunk = redact(f"### {path}\n" + "\n".join(r[:200] for r in rows)) + "\n"
        if size + len(chunk) > budget:
            break
        out.append(chunk)
        size += len(chunk)
    return "".join(out)


def _ollama(model: str, prompt: str) -> str:
    schema = {"type": "object", "required": [a for a, _ in ASPECTS], "properties": {
        a: {"type": "object", "required": ["score", "reason"],
            "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}}}
        for a, _ in ASPECTS}}
    body = {"model": model, "prompt": prompt, "stream": False, "format": schema, "keep_alive": 0,
            "options": {"temperature": 0, "seed": 1, "num_ctx": 8192}}
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["response"]


def ask_model(report: dict, model: str, call=None) -> dict:
    call = call or _ollama
    sig = "\n".join(f"- [{','.join(s['aspects'])}] w{s['weight']} {s['label']} @ {s['file']}:{s['line']}"
                    for s in report["signals"]) or "- none"
    prompt = (PROMPT.read_text().replace("{signals}", redact(sig))
              .replace("{excerpt}", report["excerpt"] or "(empty)"))
    try:
        data = json.loads(call(model, prompt))
        scores = {}
        for a, _ in ASPECTS:
            row = data[a]
            score = row["score"]
            if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
                raise ValueError(f"{a}: score {score!r} outside 0-100")
            scores[a] = {"score": score, "reason": redact(str(row["reason"]).splitlines()[0][:120]
                                                          if str(row["reason"]).strip() else "")}
    except Exception as exc:  # noqa: BLE001 — every failure is the same answer: no score
        return {"model": model, "status": "UNAVAILABLE", "why": redact(f"{type(exc).__name__}: {exc}")[:160]}
    # 0 against strong evidence is a model that did not read it, not a verdict
    # (hermes3:8b, 2026-10-04: all zeros against 62 signals, shown as "ok").
    ignored = [a for a, _ in ASPECTS if report["det"].get(a, 0) >= 40 and scores[a]["score"] == 0]
    if ignored:
        return {"model": model, "status": "UNAVAILABLE",
                "why": f"model scored 0 where signals are >=40 ({', '.join(ignored)}) — evidence ignored"}
    return {"model": model, "status": "ok", "scores": scores}


def _bar(score: int, width: int = 20) -> str:
    full = round(score * width / 100)
    return "█" * full + "░" * (width - full)


def render(report: dict, result: dict, hashes: dict, rng: str = "", notes: tuple = ()) -> str:
    out = [f"prepush-score  {rng or report['base'][:8] + '..' + report['head'][:8]}  "
           f"({report['files']} files)"]
    if result.get("status") == "ok":
        out.append(f"{'aspect':26} {'signals':26} model ({result['model']})")
    else:
        out.append(f"{'aspect':26} {'signals':26} model {result.get('model', '')} UNAVAILABLE"
                   f" — {result.get('why', 'not asked')}")
    for a, name in ASPECTS:
        d = report["det"][a]
        row = f"{name:26} {_bar(d)} {d:3d}  "
        if result.get("status") == "ok":
            m = result["scores"][a]
            row += f"{_bar(m['score'], 12)} {m['score']:3d}  {m['reason']}"
        else:
            row += "—"
        out.append(row)
    out.append("")
    out.append(f"evidence ({len(report['signals'])} signal(s)):" if report["signals"] else "evidence: no signals")
    for s in report["signals"][:30]:
        out.append(f"  w{s['weight']:<3} {'/'.join(s['aspects']):18} {s['file']}:{s['line']}  {s['label']}")
    if len(report["signals"]) > 30:
        out.append(f"  … {len(report['signals']) - 30} more in the JSONL record")
    out.append("")
    out.append(f"checker sha256 {hashes['checker']}")
    out.append(f"prompt  sha256 {hashes['prompt']}")
    out.extend(notes)
    out.append("Scores, not probabilities: uncalibrated, advisory (v0). Same-user code can rewrite this check —"
               " ssot/doctrine/session-threat-model.md §5.")
    return "\n".join(out)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def _notes(repo: Path, hashes: dict, log: Path) -> list[str]:
    notes = []
    for rel, key in (("tools/prepush-score.py", "checker"), ("tools/prepush-score.prompt.txt", "prompt")):
        committed = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"], capture_output=True)
        if committed.returncode == 0 and hashlib.sha256(committed.stdout).hexdigest() != hashes[key]:
            notes.append(f"!! {rel} differs from HEAD — the running checker is not the committed one")
    try:
        last = json.loads(log.read_text().splitlines()[-1])
        if last.get("checker_sha256") != hashes["checker"]:
            notes.append("!! checker hash changed since the last recorded run")
    except (OSError, ValueError, IndexError):
        pass
    return notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(HERE.parents[1]))
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--range", help="BASE..HEAD instead of the push range")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model, or 'off'")
    ap.add_argument("--strict", action="store_true", help="exit 3 when any aspect reaches --threshold")
    ap.add_argument("--threshold", type=int, default=70)
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args(argv)
    repo, log = Path(args.repo), Path(args.log)

    if args.range:
        base, head = args.range.split("..", 1)
        base, head = (_git(repo, "rev-parse", r).strip() for r in (base, head))
        commits = len(_git(repo, "rev-list", f"{base}..{head}").split())
    else:
        found = push_range(repo, args.remote)
        if not found:
            print(f"prepush-score: nothing to push vs {args.remote}")
            return 0
        base, head, commits = found
    report = collect(repo, base, head)
    result = ({"model": "off", "status": "UNAVAILABLE", "why": "--model off"} if args.model == "off"
              else ask_model(report, args.model))
    hashes = {"checker": _sha(HERE), "prompt": _sha(PROMPT)}
    rng = f"{base[:8]}..{head[:8]} ({commits} commit(s))"
    print(render(report, result, hashes, rng, tuple(_notes(repo, hashes, log))))

    worst = max([*report["det"].values(), *(m["score"] for m in result.get("scores", {}).values())])
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base": base, "head": head,
              "commits": commits, "checker_sha256": hashes["checker"], "prompt_sha256": hashes["prompt"],
              "det": report["det"], "model": result.get("model"), "model_status": result["status"],
              "model_scores": {a: m["score"] for a, m in result.get("scores", {}).items()},
              "signals": [{k: s[k] for k in ("aspects", "weight", "label", "file", "line")}
                          for s in report["signals"]],
              "strict": args.strict, "worst": worst}
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"prepush-score: could not record ({exc.__class__.__name__})", file=sys.stderr)
    if args.strict and worst >= args.threshold:
        print(f"prepush-score --strict: refusing, an aspect scored {worst} >= {args.threshold}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
