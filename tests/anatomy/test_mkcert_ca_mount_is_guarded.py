"""Anatomy gate — the mkcert root CA may only reach a container behind ONE guard.

Plan: docs/idea/13-relations.md §R5, row "Mkcert CA mount must be guarded"
      ("ours, fixable — make it structural, so the rule stops being a thing to
      remember").

THE RULE, WHICH UNTIL NOW LIVED ONLY IN PROSE. `CLAUDE.md` "Operator gotchas"
tells an author adding an Authentik-consuming role to wrap the mkcert root CA
volume mount AND its matching `*_CA_CERTS` env var in::

    {% if install_authentik | default(false)
          and (tenant_domain_is_local | default(true) | bool) %}

Both halves earn their place, and they fail differently:

  * without ``tenant_domain_is_local`` the container mounts a local development
    CA on a PUBLIC TLD, where the system Mozilla bundle already validates
    Authentik's Let's Encrypt chain — the regression class swept on 2026-05-03
    and re-explained at the top of nine of these fragments;
  * without ``install_authentik`` the container trusts an estate CA that nothing
    asked it to trust, and bind-mounts ``{{ stacks_dir }}/shared-certs/rootCA.pem``
    — a path ``tasks/stacks/core-up.yml:60-69`` writes only ``when`` ``mkcert
    -CAROOT`` returned 0, so on a host without mkcert Docker materialises the
    missing source as a DIRECTORY and the env var points a TLS client at it.

A gotcha paragraph cannot notice when an author forgets. Measured 2026-08-07
against pre-fix ``HEAD``, one author had: ``n8n-base`` carried both the mount
(line 13) and ``NODE_EXTRA_CA_CERTS`` (line 37) behind ``tenant_domain_is_local``
alone, with no ``install_authentik``. See the repair in the same commit.

WHY THE CHECK KEYS ON THE PATH AND NOT ON THE ENV-VAR NAME. The estate spells
this env var six ways already — ``NODE_EXTRA_CA_CERTS``, ``REQUESTS_CA_BUNDLE``,
``SSL_CERT_FILE``, ``AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL``,
``GF_AUTH_GENERIC_OAUTH_TLS_CLIENT_CA`` — and a name allow-list is the same
"remember to add yours" that this gate exists to delete. So the container paths
are DERIVED from the mount lines themselves and every line naming one is
checked, whatever it is called.

CEILING, NAMED. This reads the render's control flow, not the estate: it proves
the guard is written, not that the mount is correct for a given service. And a
mount expressed outside Jinja — an ``apps/<name>.yml`` manifest, which has no
``{% if %}`` to write — is reported as unguarded, because for that file it is.

CI-safe: pure source scan. No Docker, no network, no live host.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The one artifact this gate is about: the estate's mkcert root CA, copied to
#: `{{ stacks_dir }}/shared-certs/rootCA.pem` by tasks/stacks/core-up.yml.
HOST_CA = "shared-certs/rootCA.pem"

#: Both halves of the guard, by identifier. Order is not asserted; presence is.
REQUIRED_GUARD_IDENTS = ("install_authentik", "tenant_domain_is_local")

_TAG = re.compile(r"\{%-?\s*(\w+)([^%]*?)-?%\}")
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_BLOCK_OPENERS = {"for", "macro", "block", "with", "filter", "call", "raw"}

#: A bind mount of the host CA: `- <host>/shared-certs/rootCA.pem:<container>:ro`
_MOUNT = re.compile(re.escape(HOST_CA) + r":([^\s:]+)")


def _blank(text: str) -> str:
    """Same length, same newlines, no content — offsets and lines survive."""
    return re.sub(r"[^\n]", " ", text)


def _scan_set() -> list[Path]:
    """Every file that could carry a CA mount, including the ones that cannot
    express the guard — an unguardable mount is a finding, not an exemption."""
    out: list[Path] = []
    for pattern in ("files/anatomy/plugins/*/templates/*",
                    "roles/*/templates/**/*",
                    "templates/**/*",
                    "apps/*.yml"):
        out += [p for p in REPO.glob(pattern) if p.is_file()]
    return sorted(set(out))


def _guard_frames(text: str) -> tuple[str, list[tuple[str, ...]]]:
    """Flatten Jinja to (text, per-character enclosing `if`-expression stack).

    Offsets survive, so a line found in the flattened text is evaluated against
    the guard that lexically encloses IT. `{% else %}` and `{% elif %}` rewrite
    the frame they sit in rather than adding one — an `{% else %}` branch of a
    correct guard is the INVERSE of the guard, and reading it as guarded is how
    a CA mount could hide in the public-TLD branch.
    """
    text = _JINJA_COMMENT.sub(lambda m: _blank(m.group(0)), text)
    stack: list[dict] = []
    flat: list[str] = []
    frames: list[tuple[str, ...]] = []

    def push(seg: str) -> None:
        flat.append(seg)
        frames.extend([tuple(f["e"] for f in stack if f["t"] == "if")] * len(seg))

    pos = 0
    for m in _TAG.finditer(text):
        push(text[pos:m.start()])
        kw, expr = m.group(1), m.group(2).strip()
        if kw == "if":
            stack.append({"t": "if", "e": expr})
        elif kw == "elif" and stack and stack[-1]["t"] == "if":
            stack[-1]["e"] = "ELIF " + expr
        elif kw == "else" and stack and stack[-1]["t"] == "if":
            stack[-1]["e"] = "ELSE-OF " + stack[-1]["e"]
        elif kw in _BLOCK_OPENERS:
            stack.append({"t": kw, "e": ""})
        elif kw.startswith("end") and stack:
            stack.pop()
        push(_blank(m.group(0)))
        pos = m.end()
    push(text[pos:])
    return "".join(flat), frames


def _positively_mentions(expr: str, ident: str) -> bool:
    """True when `ident` is required TRUE by this expression.

    `{% if not install_authentik %}` mentions the identifier and means the
    opposite, so a substring test would certify the one shape that is exactly
    backwards. An `or` is equally disqualifying: `A or B` does not require A.
    """
    if " or " in f" {expr} ":
        return False
    for m in re.finditer(r"\b" + re.escape(ident) + r"\b", expr):
        before = expr[max(0, m.start() - 24):m.start()]
        if re.search(r"\bnot\s+\(?\s*$", before):
            continue
        return True
    return False


def _container_paths() -> set[str]:
    """Every in-container path the estate mounts the mkcert CA to."""
    paths: set[str] = set()
    for path in _scan_set():
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        paths.update(m.group(1) for m in _MOUNT.finditer(raw))
    return paths


def _references() -> list[tuple[Path, int, str, tuple[str, ...]]]:
    """(file, line, text, enclosing if-frames) for every live CA reference."""
    tokens = {HOST_CA} | _container_paths()
    found: list[tuple[Path, int, str, tuple[str, ...]]] = []
    for path in _scan_set():
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not any(t in raw for t in tokens):
            continue
        flat, frames = _guard_frames(raw)
        offset = 0
        for lineno, line in enumerate(flat.split("\n"), 1):
            start = offset
            offset += len(line) + 1
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not any(t in line for t in tokens):
                continue
            enclosing = frames[start] if start < len(frames) else ()
            found.append((path, lineno, stripped, enclosing))
    return found


# ── the gate ──────────────────────────────────────────────────────────────


def test_every_mkcert_ca_reference_sits_inside_the_two_part_guard():
    unguarded: list[str] = []
    for path, lineno, text, frames in _references():
        conj = " and ".join(frames)
        missing = [i for i in REQUIRED_GUARD_IDENTS
                   if not any(_positively_mentions(f, i) for f in frames)]
        inverted = [f for f in frames if f.startswith(("ELSE-OF ", "ELIF "))]
        if missing or inverted:
            rel = path.relative_to(REPO)
            why = (f"missing {missing}" if missing else "") + \
                  (f" inverted branch {inverted}" if inverted else "")
            unguarded.append(f"{rel}:{lineno}  {why.strip()}\n"
                             f"      line:  {text[:100]}\n"
                             f"      guard: {conj or '(none — renders always)'}")
    assert not unguarded, (
        "the mkcert root CA reaches a container outside the two-part guard "
        "`install_authentik and tenant_domain_is_local`. Without the TLD half "
        "a local dev CA is mounted on a public TLD and shadows the Let's "
        "Encrypt chain; without the install_authentik half the container "
        "bind-mounts a path core-up.yml writes only when mkcert exists.\n\n"
        + "\n".join(unguarded)
    )


def test_the_gate_actually_found_the_ca_surface():
    """A scan that resolves nothing certifies forever.

    The floors are the 2026-08-07 measurement minus headroom: 25 references
    across 15 files, mounted to 4 distinct container paths. They exist so that
    a glob typo, a rename of `shared-certs/`, or a move of the fragments out of
    `files/anatomy/plugins/` reports itself as scope loss instead of as a pass.
    """
    refs = _references()
    files = {p for p, _, _, _ in refs}
    paths = _container_paths()
    assert len(refs) >= 20, (
        f"only {len(refs)} mkcert CA references found (25 on 2026-08-07) — the "
        "scan set or the token derivation has lost the surface, and every "
        "assertion above is now vacuous"
    )
    assert len(files) >= 12, f"only {len(files)} files carry a CA reference"
    assert len(paths) >= 3, (
        f"container paths derived from mount lines: {sorted(paths)} — fewer "
        "than three means the mount regex stopped matching and the env-var "
        "side of the rule is no longer checked at all"
    )
