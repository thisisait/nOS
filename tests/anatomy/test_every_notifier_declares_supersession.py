"""A notifier must say whether its message retires the last one.

WHAT THE INBOX MEASURED, 2026-08-27: 64 unread, 11 of them CRITICAL or HIGH,
the oldest 33 days old — and 206 of 212 rows carrying no `supersede_key` at all.

The retirement machinery was not broken. On the two classes that used it, it was
exact: notification 183 retired by 194, three `backup-nightly-result` rows
retired leaving precisely one live. It simply reached 3% of the traffic, because
every other emitter omitted the argument and omission was indistinguishable from
a decision.

So `S2 diff` filed six identical rows over six nights, three of them unread for
nine days, each a restatement of one standing verdict that only the newest could
answer truthfully. **The inbox did not grow because nobody read it. It grew
because almost nothing could leave.**

WHAT IS PINNED. Every call site declares — either a class id (this message is
the current answer to a standing question; retire the earlier ones) or the
literal `none` (this is a distinct occurrence; keep them all). Silence is not a
third option, because silence is what 97% of the rows were.

WHY THE GATE AND NOT A RUNTIME REFUSAL. `nos-notify.sh` still sends when the
argument is missing, deliberately: a lost notification is worse than an
accumulating one, and the sender must never fail its caller (it runs at
login-time settle). The refusal belongs here, at commit time, where it costs
nothing and the author is still holding the context.

WHAT IT CANNOT SEE. Whether a key is the RIGHT key. Two emitters sharing one
class would retire each other's news, and only reading the messages tells you
that. This checks that somebody decided, not that they decided well.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
NOTIFIER = "nos-notify.sh"

#: Where a call site can live. Kept explicit so a new tree of scripts is a
#: deliberate addition rather than a silent gap.
ROOTS = ["files/anatomy/scripts", "files/anatomy/plugins", "tasks", "tools", "roles"]

#: Bone's own rule for a class id (files/anatomy/bone/notifications.py), so a
#: key that would be rejected at runtime is rejected here first.
KEY = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,62}[a-z0-9]$")


def _shell_sites() -> list[tuple[pathlib.Path, int, str]]:
    """Every shell/YAML invocation of the notifier, with its full command."""
    out = []
    for root in ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in (".sh", ".yml", ".yaml"):
                continue
            if path.name == NOTIFIER:
                continue                       # the sender is not a call site
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines):
                if NOTIFIER not in line or line.lstrip().startswith("#"):
                    continue
                # NOT EVERY MENTION IS A CALL: env declarations
                # (`NOS_NOTIFY_BIN: <path>`) and `files:` list entries name
                # the path without invoking it — flagging them sends a reader
                # to fix code that is already right.
                stripped = line.strip()
                if re.match(r"^[A-Z_]+:\s", stripped):        # env assignment
                    continue
                if re.match(r"^-\s*\S*" + re.escape(NOTIFIER) + r"\s*$", stripped):
                    continue                                   # YAML list entry
                # Join until the command actually ends — trailing backslash OR
                # unclosed quote. tasks/backup.yml carries a real newline
                # inside a quoted argument, so stopping at line-end reads a
                # five-argument call as three.
                cmd, j = line, i
                while j + 1 < len(lines) and (
                        cmd.rstrip().endswith("\\") or cmd.count('"') % 2):
                    j += 1
                    cmd += "\n" + lines[j]
                # An invocation has something after the path; a mention does not.
                if not _args(cmd):
                    continue
                out.append((path, i + 1, cmd))
    return out


def _args(cmd: str) -> list[str]:
    """The notifier's positional arguments, quoted or bare.

    Split on the notifier name AND the quote that closes its path — otherwise
    `"{{ playbook_dir }}/.../nos-notify.sh" high \\` leaves a stray `"` that
    pairs with the next one and shifts every argument by one. That is how the
    first cut read `tasks/backup.yml` as having two arguments.
    """
    tail = cmd.split(NOTIFIER, 1)[1]
    if tail.startswith('"'):
        tail = tail[1:]
    # `$( … )` IS OPAQUE — one blob of text for argument counting.
    # tasks/backup.yml embeds `$(tail … 2>/dev/null)` whose inner quote and
    # `2>` otherwise end the scan early (five arguments read as three).
    depth, out_chars = 0, []
    i = 0
    while i < len(tail):
        if tail.startswith("$(", i):
            depth += 1
            out_chars.append("\x00")          # placeholder, never a quote
            i += 2
            continue
        if depth and tail[i] == ")":
            depth -= 1
            i += 1
            continue
        out_chars.append("\x00" if depth else tail[i])
        i += 1
    tail = "".join(out_chars)

    args, buf, quote = [], "", None
    for ch in tail:
        if quote:
            if ch == quote:
                args.append(buf)
                buf, quote = "", None
            else:
                buf += ch
        elif ch in "\"'":
            quote = ch
        elif ch in " \t\n\\":
            if buf:
                args.append(buf)
                buf = ""
        elif ch in "|>;&":                 # `|| true`, `>> log`, `2>&1` end it
            if buf:
                args.append(buf)
            return args
        else:
            buf += ch
    if buf:
        args.append(buf)
    return args


def _python_sites() -> list[tuple[pathlib.Path, int, list[str]]]:
    """subprocess argv lists whose head is the notifier binary.

    Read from the AST. Matching the text would count the docstrings that
    describe NOS_NOTIFY_BIN as if they were calls — a detector reporting a
    description as the fact, which this tree has paid for repeatedly.
    """
    out = []
    for root in ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:                              # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.List) or not node.elts:
                    continue
                head = node.elts[0]
                name = (getattr(head, "id", None) or getattr(head, "attr", None) or
                        (head.value if isinstance(head, ast.Constant) else None))
                # The binary always arrives through a NAME in this tree, but not
                # always the same one: `NOTIFY_BIN` at three call sites and
                # `bin_path` at the S2 emitter, which takes it as a parameter.
                by_name = isinstance(name, str) and re.search(
                    r"(?i)notify_bin|notifier|bin_path", name) is not None
                # AND BY SHAPE, because the name is not always there: the S2
                # emitter — this gate's motivating case — builds `[bin_path,
                # severity, …]` with no NOTIFY_BIN spelling, so name-matching
                # alone left the suite green when its key was deleted
                # (found by mutation, not review).
                sev = (node.elts[1].value
                       if len(node.elts) > 1 and isinstance(node.elts[1], ast.Constant)
                       else None)
                # The head must be a VARIABLE: `["diskutil", "info", …]`
                # matched the severity rule alone (`info` is both a severity
                # and a subcommand), and every real notifier call passes the
                # binary through a name, never a literal path.
                by_shape = (sev in ("critical", "high", "medium", "low", "info")
                            and isinstance(head, ast.Name))
                if not (by_name or by_shape):
                    continue
                out.append((path, node.lineno, [
                    e.value if isinstance(e, ast.Constant) else "<expr>"
                    for e in node.elts]))
    return out


#: Files known to emit notifications on 2026-08-27. The detector must keep
#: finding every one of them.
MUST_FIND = {
    "cortex-corpus-diff.py", "keap-lint.py", "keap-consolidate.py",
    "cortex-fs-sync.py", "nos-os-resume.sh", "backup.yml",
}


def test_the_detector_still_sees_every_known_emitter():
    """COVERAGE, pinned — because a detector that quietly stops finding a call
    site reports green about a file it never read.

    This assertion exists because it happened. The first cut matched only the
    literal name `NOTIFY_BIN`, and `cortex-corpus-diff.py` — the S2 emitter,
    the one whose six unretired rows motivated this entire gate — passes its
    binary as a parameter called `bin_path`. Deleting that emitter's key left
    the suite GREEN. A mutation found it; nothing else would have.

    A vacuous-pass check ('did we find ANY sites') would not have caught it
    either: the other three python sites were found, so the count was non-zero
    and everything looked fine.
    """
    found = {p.name for p, _, _ in _shell_sites()} | {p.name for p, _, _ in _python_sites()}
    missing = sorted(MUST_FIND - found)
    assert not missing, (
        f"the detector no longer finds {missing}. Either the emitter moved (update "
        "MUST_FIND with the new name) or the discovery rule narrowed and is now "
        "silently skipping a file it used to check — which is the failure this "
        "assertion was written for.")


@pytest.mark.parametrize("path,line,cmd",
                         [(p, l, c) for p, l, c in _shell_sites()],
                         ids=[f"{p.name}:{l}" for p, l, _ in _shell_sites()])
def test_a_shell_call_declares_supersession(path, line, cmd):
    """Five positional arguments, the fifth being a key or `none`."""
    args = _args(cmd)
    rel = path.relative_to(REPO)
    assert len(args) >= 4, (
        f"{rel}:{line} calls the notifier with {len(args)} quoted argument(s); "
        "severity, title, body and channels are all required before a key")
    key = args[4] if len(args) >= 5 else None
    assert key is not None, (
        f"{rel}:{line} passes no supersede argument. Decide: a class id if this "
        "message is the current answer to a standing question (the next one "
        "retires it), or the literal `none` if it is a distinct occurrence. "
        "Silence is what 206 of 212 inbox rows were on 2026-08-27.")
    assert key == "none" or KEY.match(key), (
        f"{rel}:{line} passes {key!r}, which Bone's class-id rule would reject "
        f"at runtime (files/anatomy/bone/notifications.py). Use `none` or "
        "[a-z0-9][a-z0-9_.:-]*[a-z0-9].")


@pytest.mark.parametrize("path,line,argv",
                         [(p, l, a) for p, l, a in _python_sites()],
                         ids=[f"{p.name}:{l}" for p, l, _ in _python_sites()])
def test_a_python_call_declares_supersession(path, line, argv):
    rel = path.relative_to(REPO)
    assert len(argv) >= 6, (
        f"{rel}:{line} builds {argv} — a sixth element (the supersede key, or "
        "the literal 'none') is missing. The nightly S2 diff filed six identical "
        "rows over six nights this way, three unread for nine days.")
    key = argv[5]
    assert key == "none" or (isinstance(key, str) and KEY.match(key)), (
        f"{rel}:{line} passes {key!r} as the class id; Bone would reject it.")


def test_the_sender_treats_none_as_a_declaration_not_a_class():
    """`none` must be stripped before it reaches Bone. Bone's regex accepts the
    word, so a `none` forwarded as a key would put every caller that declared
    'distinct occurrence' into ONE class, retiring each other — the exact
    opposite of what the caller asked for."""
    src = (REPO / "files/anatomy/scripts" / NOTIFIER).read_text(encoding="utf-8")
    assert re.search(r'\[\s*"\$supersede"\s*=\s*"none"\s*\]\s*&&\s*supersede=""', src), (
        "nos-notify.sh no longer collapses the literal `none` to an empty key "
        "before building the payload")
