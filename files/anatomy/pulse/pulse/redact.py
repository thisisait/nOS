"""Pulse stdout/stderr scrub: files/anatomy/contracts/redact.yml as code.

The contract specifies an ALGORITHM, not regexes; medulla/src/pulse/redact.rs
is the same algorithm, char for char, and both are held to
files/anatomy/contracts/redact.fixture.json. Every secret becomes `<REDACTED>`
(no length); the label that named it stays.

Used by pulse/daemon.py (stdout, stderr, the daemon-exception message) and
scripts/stack-health-probe.py.
"""

from __future__ import annotations

import string

R = "<REDACTED>"

#: A key segment equal to one of these makes the key secret-shaped.
STRONG = frozenset((
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "HMAC", "JWT",
    "CREDENTIAL", "CREDENTIALS", "PASSPHRASE"))
#: ...and these only beside another segment: PWD alone is the shell's cwd, PASS alone a test verdict.
WEAK = frozenset(("PASS", "PWD", "KEY", "AUTH", "BEARER", "COOKIE"))
#: Keys that name or locate a secret, or index rows (contract: allow).
BENIGN_KEYS = frozenset(("SORT_KEY", "PRIMARY_KEY", "FOREIGN_KEY"))
BENIGN_TAILS = frozenset(("NAME", "TYPE", "FILE", "PATH", "URL", "ERROR", "EXCEPTION"))

FLAGS = ("password", "passwd", "api-key", "api_key", "apikey", "secret", "bearer", "token", "pass", "pwd")
SCHEMES = ("bearer", "basic", "digest", "token", "apikey")
BEARER_MIN = 16
#: Shorter known values would eat ordinary words; six is the floor every minted secret clears.
KNOWN_MIN = 6

_KEY = frozenset(string.ascii_letters + string.digits + "_.-")
_QUOTES = "\"'"


def _space(c: str) -> bool:
	return c.isspace()


def _hspaces(t: str, i: int) -> int:
	"""Past the gap around a separator: whitespace, never a line end."""
	while i < len(t) and _space(t[i]) and t[i] not in "\r\n":
		i += 1
	return i


def _lit(t: str, i: int, word: str) -> bool:
	"""ASCII `word` (lower case) at `i`, ASCII case-insensitive."""
	return t[i:i + len(word)].lower() == word and t[i:i + len(word)].isascii()


def _word(c: str) -> bool:
	return c.isalnum() or c == "_"


def _segments(key: str) -> list[str]:
	segs, cur = [], ""
	for c in key:
		if c in "_.-":
			segs.append(cur)
			cur = ""
			continue
		if cur and ((cur[-1].islower() and c.isupper()) or (cur[-1].isdigit() != c.isdigit())):
			segs.append(cur)
			cur = ""
		cur += c
	segs.append(cur)
	return [s.upper() for s in segs if s]


def secret_key(key: str) -> bool:
	segs = _segments(key)
	if not segs or "_".join(segs) in BENIGN_KEYS or segs[-1] in BENIGN_TAILS or segs[-2:] == ["KEY", "ID"]:
		return False
	return any(s in STRONG for s in segs) or (len(segs) > 1 and any(s in WEAK for s in segs))


def _value(t: str, i: int):
	"""(start, end) of the value at `i`: inside its quotes, to the matching one on the line; else a run to whitespace."""
	if i >= len(t) or _space(t[i]):
		return None
	if t[i] in _QUOTES:
		j = i + 1
		while j < len(t) and t[j] != t[i] and t[j] != "\n":
			j += 2 if t[j] == "\\" else 1
		if j < len(t) and t[j] == t[i]:
			return (i + 1, j) if j > i + 1 else None
	j = i
	while j < len(t) and not _space(t[j]):
		j += 1
	return i, j


def _token(t: str, i: int) -> int:
	while i < len(t) and not _space(t[i]) and t[i] not in "\"',;":
		i += 1
	return i


def _line_end(t: str, i: int) -> int:
	while i < len(t) and t[i] not in "\r\n":
		i += 1
	return i


_B64URL = frozenset(string.ascii_letters + string.digits + "_-")
_IDENT = frozenset(string.ascii_letters + string.digits + "_")
VENDOR = ("sk-ant-", "github_pat_", "glpat-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "xoxa-", "xoxb-", "xoxp-")
VENDOR_MIN = 8
_AKIA = frozenset(string.ascii_uppercase + string.digits)


def _run(t: str, i: int, ok) -> int:
	while i < len(t) and t[i] in ok:
		i += 1
	return i


def _pem(t: str, p: int):
	if not t.startswith("-----BEGIN ", p):
		return None
	h, nl = t.find("PRIVATE KEY-----", p + 11), t.find("\n", p + 11)
	if h < 0 or 0 <= nl < h:
		return None
	e = t.find("-----END ", h)
	k = t.find("PRIVATE KEY-----", e) if e >= 0 else -1
	return p, (k + 16 if k >= 0 else len(t))


def _jwt(t: str, p: int):
	j = p
	for part in range(3):
		if part < 2 and not t.startswith("eyJ", j):
			return None
		e = _run(t, j, _B64URL)
		if part < 2 and (e - j < 4 or e >= len(t) or t[e] != "."):
			return None
		j = e + 1 if part < 2 else e
	return p, j


def _vendor(t: str, p: int):
	for pre in VENDOR:
		if t.startswith(pre, p):
			v = p + len(pre)
			e = _run(t, v, _B64URL)
			return (v, e) if e - v >= VENDOR_MIN else None
	if t.startswith("AKIA", p) and _run(t, p + 4, _AKIA) == p + 20 and not (p + 20 < len(t) and t[p + 20].isascii() and t[p + 20].isalnum()):
		return p + 4, p + 20
	return None


def _legacy_pw(t: str, p: int):
	"""`<prefix>_pw_<name>`: the prefix is the secret; the name says which credential."""
	if p > 0 and t[p - 1] in _IDENT:
		return None
	e = _run(t, p, _IDENT)
	k = t.find("_pw_", p, e)
	return (p, k) if k > p and k + 4 < e else None


def _userinfo(t: str, p: int):
	"""`scheme://user:pw@host`: the pw, up to the authority's last @."""
	if not t.startswith("://", p) or p == 0 or not (t[p - 1].isascii() and t[p - 1].isalpha()):
		return None
	a = p + 3
	while a < len(t) and not _space(t[a]) and t[a] not in "/?#\"'":
		a += 1
	at, colon = t.rfind("@", p + 3, a), t.find(":", p + 3, a)
	return (colon + 1, at) if 0 <= colon < at - 1 else None


def _shape(t: str, p: int):
	if p > 0 and t[p - 1] in _B64URL and t[p] != ":":
		return None
	for m in (_pem, _jwt, _vendor, _legacy_pw, _userinfo):
		hit = m(t, p)
		if hit:
			return hit
	return None


def _header_colon(t: str, j: int) -> int | None:
	"""After a header name: optional quote, spaces, `:`, spaces, optional quote."""
	j = _hspaces(t, j + (j < len(t) and t[j] in _QUOTES))
	if j >= len(t) or t[j] != ":":
		return None
	j = _hspaces(t, j + 1)
	return j + (j < len(t) and t[j] in _QUOTES)


def _header(t: str, p: int):
	if p > 0 and t[p - 1].isascii() and t[p - 1].isalpha():
		return None
	if _lit(t, p, "authorization"):
		j = _header_colon(t, p + 13)
		scheme = next((s for s in SCHEMES if j is not None and _lit(t, j, s)), None)
		if scheme is None:
			return None
		v = _hspaces(t, j + len(scheme))
		if v == j + len(scheme):
			return None
		end = _line_end(t, v) if scheme == "digest" else _token(t, v)
		return (v, end) if end > v else None
	if _lit(t, p, "cookie"):
		v = _header_colon(t, p + 6)
		end = _line_end(t, v) if v is not None else v
		return (v, end) if v is not None and end > v else None
	return None


def _bearer(t: str, p: int):
	if (p > 0 and _word(t[p - 1])) or not _lit(t, p, "bearer"):
		return None
	v = p + 6
	while v < len(t) and _space(t[v]):
		v += 1
	end = _token(t, v)
	return (v, end) if v > p + 6 and end - v >= BEARER_MIN else None


def _cli(t: str, p: int):
	if t[p] != "-" or (p > 0 and t[p - 1] in _KEY):
		return None
	k = p + 1 + (p + 1 < len(t) and t[p + 1] == "-")
	for flag in FLAGS:
		s = k + len(flag)
		if not _lit(t, k, flag) or s >= len(t) or not (t[s] == "=" or _hspaces(t, s) > s):
			continue
		v = s + 1 if t[s] == "=" else _hspaces(t, s)
		if t[s] != "=" and v < len(t) and t[v] == "-":
			return None
		return _value(t, v)
	return None


def _kv(t: str, p: int):
	if t[p] not in _KEY or (p > 0 and t[p - 1] in _KEY):
		return None
	r = p
	while r < len(t) and t[r] in _KEY:
		r += 1
	j = _hspaces(t, r + (r < len(t) and t[r] in _QUOTES))
	if j >= len(t) or t[j] not in "=:" or (j + 1 < len(t) and t[j + 1] == t[j]):
		return None
	v = _hspaces(t, j + 1)
	return _value(t, v) if secret_key(t[p:r]) else None


def _sub(t: str, match) -> str:
	out, i = [], 0
	while i < len(t):
		m = match(t, i)
		if m:
			out.append(t[i:m[0]] + R)
			i = m[1]
		else:
			out.append(t[i])
			i += 1
	return "".join(out)


def _known(text: str, known) -> str:
	"""Every exact occurrence of a value the runner handed the job, longest first."""
	vals = {str(v) for v in known if v and len(str(v)) >= KNOWN_MIN and str(v) not in R}
	for v in sorted(vals, key=lambda v: (-len(v), v)):
		text = text.replace(v, R)
	return text


def scrub_text(s: str | None, known=()) -> str:
	"""The known values, then every layer of the contract in its order. Idempotent; None and "" give ""."""
	# ponytail: a pure-Python char scan, ~1.6 s per MB on the job's own thread; a C scan if a job floods.
	if not s:
		return ""
	text = _known(str(s), known)
	for layer in (_shape, _header, _bearer, _cli, _kv):
		text = _sub(text, layer)
	return text
