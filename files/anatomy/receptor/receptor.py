#!/usr/bin/env python3
"""The receptor: a host login reaches KEAP's human door as the person it maps to.

A unix-socket HTTP relay in front of KEAP's loopback publish. The kernel names
the caller's uid (SO_PEERCRED on Linux, LOCAL_PEERCRED on macOS); the uid's
login is looked up in the identity map (~/.nos/identity-map.yml, rendered by
roles/pazny.receptor; JSON, which is YAML), shape {"logins": {<login>:
{"username", "groups": [...]}}}. A login not in the map is refused, never
defaulted. Client X-Authentik-* and x-keap-proxy-secret are dropped; the
receptor injects the person's headers plus the proxy secret only it holds.
It relays GET/HEAD on /api only, and refuses a head it would split differently
than an upstream might (bare CR/LF, NUL, folds, non-token names, two lengths).

    receptor.py --socket ~/.nos/keap-identity.sock [--map ~/.nos/identity-map.yml] [--upstream 127.0.0.1:8091]

Env: KEAP_PROXY_SHARED_SECRET. Unset = every call refused (503).
Stdlib only, python 3.9; one request per connection (Connection: close).
Sibling: bootstrap/minimal-linux-dgx/identity/keap-identity.py (Linux groups -> tier).
The Thalamus will take this job and read the same map.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pwd
import re
import socket
import struct
import sys
import time

SECRET = os.environ.get("KEAP_PROXY_SHARED_SECRET", "")
DROP = ("x-authentik-", "x-keap-proxy-secret", "connection", "proxy-connection", "keep-alive", "upgrade")
REASON = {400: "Bad Request", 403: "Forbidden", 405: "Method Not Allowed", 502: "Bad Gateway",
          503: "Service Unavailable"}
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")  # RFC 7230 header-name


def malformed(head: bytes) -> str | None:
    """Why this request head is refused, or None. An upstream that splits a head
    differently than we do would see headers we never vetted."""
    raw = head[:-4]
    if b"\0" in raw or b"\r" in raw.replace(b"\r\n", b"") or b"\n" in raw.replace(b"\r\n", b""):
        return "bare CR, LF or NUL in the request head"
    lengths = 0
    for h in raw.decode("latin-1").split("\r\n")[1:]:
        if h[:1] in (" ", "\t"):
            return "folded header line"
        k, sep, _ = h.partition(":")
        if not sep or not TOKEN.fullmatch(k):
            return "header name is not a token"
        lengths += k.lower() == "content-length"
    return "duplicate Content-Length" if lengths > 1 else None


def bad_target(target: str) -> bool:
    """Only origin-form /api paths, with nothing an upstream might normalise elsewhere."""
    path = target.split("?", 1)[0]
    segs = path.split("/")
    return (not (path == "/api" or path.startswith("/api/")) or "//" in path or "\\" in target
            or "." in segs or ".." in segs or any(e in path.lower() for e in ("%2e", "%2f", "%5c")))


def peer_uid(sock) -> int:
    """The connecting process's uid, as the kernel reports it."""
    if hasattr(socket, "SO_PEERCRED"):  # Linux: struct ucred {pid, uid, gid}
        _pid, uid, _gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return uid
    if hasattr(socket, "LOCAL_PEERCRED"):  # macOS: SOL_LOCAL=0, struct xucred {version, uid, ...}
        return struct.unpack("2I", sock.getsockopt(0, socket.LOCAL_PEERCRED, 76)[:8])[1]
    raise OSError("no peer credentials on this platform")


def person(login: str, map_path: str) -> dict | None:
    """The map's entry for a login, or None (unknown, unreadable or malformed)."""
    try:
        with open(map_path, encoding="utf-8") as f:
            entry = (json.load(f).get("logins") or {}).get(login)
        user, groups = entry["username"], entry["groups"]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    vals = [user, *groups] if isinstance(groups, list) else []
    if not user or not vals or not all(isinstance(v, str) and v and not any(c in v for c in "\r\n,") for v in vals):
        return None
    return {"username": user, "groups": groups}


async def reply(writer, status: int, text: str):
    body = json.dumps({"success": False, "error": text}).encode()
    writer.write(f"HTTP/1.1 {status} {REASON.get(status, 'Error')}\r\nContent-Type: application/json\r\n"
                 f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
    await writer.drain()
    writer.close()


async def handle(reader, writer, upstream: tuple, map_path: str):
    t0 = time.time()
    try:
        login = pwd.getpwuid(peer_uid(writer.get_extra_info("socket"))).pw_name
    except (OSError, KeyError):
        login = None
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, asyncio.LimitOverrunError):
        writer.close()
        return
    lines = head.decode("latin-1").split("\r\n")
    request_line = lines[0]
    parts = request_line.split(" ")
    why = malformed(head) or (None if len(parts) == 3 and parts[2].startswith("HTTP/1.") else "bad request line")
    if why or bad_target(parts[1]):
        print(f"400 {login or '?'} {request_line!r}", flush=True)
        await reply(writer, 400, why or "only /api paths are relayed")
        return
    # Read verbs only: the one consumer is OpenHuman, read-only by contract; approved
    # writes will take the Thalamus's own proxy-secret path (operator ruling 2026-10-11).
    if parts[0] not in ("GET", "HEAD"):
        print(f"405 {login or '?'} {request_line}", flush=True)
        await reply(writer, 405, f"{parts[0]} is not relayed; the receptor serves reads only")
        return
    who = person(login, map_path) if login else None
    if not who:
        print(f"403 {login or '?'} {request_line}", flush=True)
        await reply(writer, 403, f"{login or 'unknown uid'} is not in the identity map")
        return
    if not SECRET:
        await reply(writer, 503, "receptor holds no KEAP proxy secret")
        return
    hdrs, length = [], 0
    for h in lines[1:]:
        k, _, v = h.partition(":")
        kl = k.strip().lower()
        if not h or any(kl.startswith(d) for d in DROP):
            continue
        if kl == "transfer-encoding":  # our clients never chunk; refusing beats relaying a smuggle
            await reply(writer, 403, "chunked request bodies are not relayed")
            return
        if kl == "content-length":
            if not v.strip().isdigit():
                await reply(writer, 403, "bad Content-Length")
                return
            length = int(v.strip())
        hdrs.append(h)
    hdrs += [f"X-Authentik-Username: {who['username']}", f"X-Authentik-Name: {who['username']}",
             f"X-Authentik-Groups: {','.join(who['groups'])}", f"x-keap-proxy-secret: {SECRET}",
             "Connection: close"]
    try:
        ur, uw = await asyncio.wait_for(asyncio.open_connection(*upstream), timeout=10)
    except (OSError, asyncio.TimeoutError) as e:
        await reply(writer, 502, f"KEAP unreachable: {e}")
        return
    uw.write(("\r\n".join([request_line] + hdrs) + "\r\n\r\n").encode("latin-1"))
    remaining = length
    while remaining > 0:
        chunk = await reader.read(min(65536, remaining))
        if not chunk:
            break
        uw.write(chunk)
        remaining -= len(chunk)
    await uw.drain()
    status, first = "?", True
    try:
        while chunk := await ur.read(65536):
            if first:
                status, first = (chunk.split(b" ", 2)[1].decode(errors="replace") if b" " in chunk else "?"), False
            writer.write(chunk)
            await writer.drain()
    finally:
        uw.close()
        writer.close()
    print(f"{status} {login} as {who['username']} {request_line} {int((time.time() - t0) * 1000)}ms", flush=True)


async def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--socket", required=True)
    ap.add_argument("--map", default=os.path.expanduser("~/.nos/identity-map.yml"))
    ap.add_argument("--upstream", default="127.0.0.1:8091")
    a = ap.parse_args()
    host, port = a.upstream.rsplit(":", 1)
    try:
        os.unlink(a.socket)
    except FileNotFoundError:
        pass
    os.umask(0o177)  # the socket is born 0600: no window where another uid may connect
    server = await asyncio.start_unix_server(lambda r, w: handle(r, w, (host, int(port)), a.map),
                                             path=a.socket, limit=1 << 20)
    os.chmod(a.socket, 0o600)
    print(f"receptor: {a.socket} -> {a.upstream} (map {a.map}, secret {'set' if SECRET else 'UNSET'})", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
