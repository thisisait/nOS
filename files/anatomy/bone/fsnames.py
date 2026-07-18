"""Bone filesystem-name hardening — a pure leaf/relpath sanitizer for the VFS.

The VFS `_resolve` realpath-∈-scope check (vfs.py) is the LOAD-BEARING
containment gate and stays exactly as-is. This module is DEFENSE IN DEPTH on
the orthogonal axis: the *shape* of a leaf name a user creates, renames, or
uploads. `_resolve` stops a name from escaping the user root; it does NOT stop a
name from being a Windows reserved device, a BiDi-spoofed homoglyph, a control
character smuggled into a filename, or an NFD/NFC duplicate of an existing file.

Incident this prevents: the operator requirement "bulletproof against XSS,
malformed filenames, hard UTF-8 everywhere". Before this, the write surfaces
(`/write`, `/mkdir`, `/move`, `/copy`, `/upload`) took a leaf with only
`os.path.basename` + realpath containment — so a filename like
`CON`, `report<U+202E>fdp.exe` (RTL-override spoof), `note<U+200B>.txt`
(zero-width), or a trailing-dot/space Windows footgun landed on disk verbatim
and rendered ambiguously (or dangerously) in the face browser.

`sanitize_leaf` NFC-normalizes and rejects the whole malformed matrix, raising
`LeafNameError` (a ValueError subclass) which the routers turn into HTTP 400.
It is pure and server-free, so it is unit-tested heavily on its own.
"""

from __future__ import annotations

import unicodedata

# Max bytes for a single path segment. 255 is the near-universal POSIX/ext4/APFS
# NAME_MAX; we measure the NFC UTF-8 encoding (what actually lands on disk).
_MAX_LEAF_BYTES = 255

# Windows reserved device names (case-insensitive, with or without an
# extension: `CON`, `con.txt`, `NUL.tar.gz` are all reserved). Kept even though
# Bone targets macOS/Linux: the doctrine tree is backup-synced and browsed
# cross-platform, and a `NUL` file is a portability landmine.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

# Dangerous formatting/invisible code points that make a name ambiguous or
# actively spoofable in a browser file list. Rejected anywhere in the name:
#   U+202A..U+202E  BiDi embedding/override (RTL filename-extension spoof)
#   U+2066..U+2069  BiDi isolates
#   U+200B..U+200F  zero-width space/joiners + LRM/RLM marks
#   U+FEFF          zero-width no-break space / BOM
_DANGEROUS_FORMAT_CHARS = frozenset(
    [chr(cp) for cp in range(0x202A, 0x202E + 1)]
    + [chr(cp) for cp in range(0x2066, 0x2069 + 1)]
    + [chr(cp) for cp in range(0x200B, 0x200F + 1)]
    + [chr(0xFEFF)]
)


class LeafNameError(ValueError):
    """Raised when a leaf name fails sanitization. Routers map it to HTTP 400.

    Carries a human-readable `reason` the router surfaces in the 400 detail so
    the face browser can tell the user *why* a filename was refused.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _has_control_chars(name: str) -> bool:
    """True if the name carries NUL or any C0/C1 control character.

    C0 = U+0000..U+001F, C1 = U+007F..U+009F. `unicodedata.category` returns
    'Cc' for exactly these control code points.
    """
    return any(ch == "\x00" or unicodedata.category(ch) == "Cc" for ch in name)


def sanitize_leaf(name: str, *, allow_leading_dot: bool = False) -> str:
    """Normalize and validate a SINGLE path segment (no separators).

    Returns the NFC-normalized safe name, or raises `LeafNameError` (a
    ValueError) with a `.reason`. This does NOT replace `_resolve`'s realpath
    containment — it runs *in addition* to it.

    `allow_leading_dot` opens the leading-dot gate for the few internal names
    the routers legitimately create (e.g. `.face`); user-facing callers keep it
    False so dotfiles cannot be silently minted from the browser.
    """
    if not isinstance(name, str):
        raise LeafNameError("name must be a string")

    # NFC first so every downstream check sees the canonical form and NFD/NFC
    # spellings of the same name collapse to one on-disk identity.
    name = unicodedata.normalize("NFC", name)

    if name == "":
        raise LeafNameError("empty name")
    if name in (".", ".."):
        raise LeafNameError("'.' and '..' are not valid names")

    if _has_control_chars(name):
        raise LeafNameError("name contains NUL or control characters")

    # Lone surrogates (category 'Cs') are not encodable UTF-8 — a filename that
    # carries one would explode `str.encode('utf-8')` downstream; refuse it here
    # with a clean 400 rather than a 500.
    if any(unicodedata.category(ch) == "Cs" for ch in name):
        raise LeafNameError("name contains an unpaired surrogate (invalid UTF-8)")

    if "/" in name or "\\" in name:
        raise LeafNameError("name must not contain a path separator")

    bad = sorted({ch for ch in name if ch in _DANGEROUS_FORMAT_CHARS})
    if bad:
        codes = ", ".join(f"U+{ord(ch):04X}" for ch in bad)
        raise LeafNameError(f"name contains disallowed formatting characters ({codes})")

    if not allow_leading_dot and name.startswith("."):
        raise LeafNameError("leading-dot (hidden) names are not allowed")

    # Windows footgun: a trailing dot or space is silently stripped by the Win32
    # layer, so `foo.` and `foo ` alias `foo` — refuse to create the ambiguity.
    if name != name.rstrip(". "):
        raise LeafNameError("name must not end with a dot or space")

    # Windows reserved device name — match on the stem before the FIRST dot,
    # case-insensitively (`com1.txt` is still reserved).
    stem = name.split(".", 1)[0].lower()
    if stem in _WINDOWS_RESERVED:
        raise LeafNameError(f"'{name}' is a reserved device name")

    if len(name.encode("utf-8")) > _MAX_LEAF_BYTES:
        raise LeafNameError(f"name too long (>{_MAX_LEAF_BYTES} bytes UTF-8)")

    return name


def sanitize_relpath(relpath: str, *, allow_leading_dot: bool = False) -> str:
    """Validate each segment of a relative path with `sanitize_leaf`.

    Returns the NFC-normalized, forward-slash-joined path. Empty segments from
    a trailing/duplicate slash are dropped. `.`/`..` segments are rejected by
    `sanitize_leaf` (belt-and-braces with `_resolve`, never the sole gate).

    This is a convenience for callers that want per-segment shape validation; it
    is NOT a containment check — `_resolve`'s realpath test remains that.
    """
    if relpath is None:
        raise LeafNameError("path is required")
    # Normalize the separator, then validate the meaningful segments.
    segments = [seg for seg in relpath.replace("\\", "/").split("/") if seg != ""]
    if not segments:
        raise LeafNameError("path is empty")
    return "/".join(sanitize_leaf(seg, allow_leading_dot=allow_leading_dot) for seg in segments)
