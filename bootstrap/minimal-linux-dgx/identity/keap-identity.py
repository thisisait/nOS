#!/usr/bin/env python3
"""The identity outpost: the shell login IS the KEAP login.

A unix-socket HTTP proxy in front of KEAP's loopback publish. Whoever connects
is identified by the kernel (SO_PEERCRED → uid), never by a header or a
secret they hold: the outpost maps uid → login → Linux groups → nOS tier,
injects the X-Authentik-* identity headers plus the x-keap-proxy-secret (which
only THIS process holds), and forwards to 127.0.0.1:8091. Any identity header
the caller sent is dropped. The result is the same identity a browser gets
through nginx + PAM — one model, both doors (datatables spec §4).

    keap-identity.py --socket /run/nos-dgx/keap-identity.sock [--upstream 127.0.0.1:8091]

Env: KEAP_PROXY_SHARED_SECRET (from /etc/nos/keap-proxy.env via the unit),
NOS_HOST (for the e-mail suffix; default <hostname>.local).

Tier mapping mirrors nginx's $nos_groups map, but from Linux groups — the
single roster: nos-maintainers → nos-providers,nos-admins (tier 1);
nos-managers → nos-managers (tier 2); nos-users → nos-users (tier 3);
anyone else → 403, the outpost is not a door for strangers.

Stdlib only; one request per connection (Connection: close both ways) — the
callers (tools/keap_api.py, curl --unix-socket) open a connection per request.
"""
import argparse
import asyncio
import grp
import os
import pwd
import socket
import struct
import sys
import time

SECRET = os.environ.get("KEAP_PROXY_SHARED_SECRET", "")
HOST = os.environ.get("NOS_HOST") or (socket.gethostname().split(".")[0] + ".local")
DROP = ("x-authentik-", "x-keap-proxy-secret", "connection", "proxy-connection", "keep-alive", "upgrade")


def tier_groups(login: str) -> str | None:
    try:
        primary = grp.getgrgid(pwd.getpwnam(login).pw_gid).gr_name
    except KeyError:
        return None
    mine = {primary} | {g.gr_name for g in grp.getgrall() if login in g.gr_mem}
    if "nos-maintainers" in mine:
        return "nos-providers,nos-admins"
    if "nos-managers" in mine:
        return "nos-managers"
    if "nos-users" in mine:
        return "nos-users"
    return None


def peer_login(writer: asyncio.StreamWriter) -> str | None:
    sock = writer.get_extra_info("socket")
    try:
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        return pwd.getpwuid(uid).pw_name
    except (OSError, KeyError):
        return None


async def reply(writer, status: int, text: str):
    body = ('{"success":false,"error":"%s"}' % text.replace('"', "'")).encode()
    writer.write(f"HTTP/1.1 {status} {'Forbidden' if status == 403 else 'Bad Gateway' if status == 502 else 'Bad Request'}\r\n"
                 f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
    await writer.drain()
    writer.close()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, upstream: tuple[str, int]):
    login = peer_login(writer)
    t0 = time.time()
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, asyncio.LimitOverrunError):
        writer.close(); return
    lines = head.decode("latin-1").split("\r\n")
    request_line = lines[0]
    groups = tier_groups(login) if login else None
    if not groups:
        print(f"403 {login or '?'} {request_line}", flush=True)
        await reply(writer, 403, f"{login or 'unknown uid'} is not in nos-users"); return
    hdrs = []
    length = 0
    chunked = False
    for h in lines[1:]:
        if not h:
            continue
        k, _, v = h.partition(":")
        kl = k.strip().lower()
        if any(kl.startswith(d) for d in DROP):
            continue
        if kl == "content-length":
            length = int(v.strip() or 0)
        if kl == "transfer-encoding" and "chunked" in v.lower():
            chunked = True
        hdrs.append(h)
    hdrs += [
        f"X-Authentik-Username: {login}",
        f"X-Authentik-Email: {login}@{HOST}",
        f"X-Authentik-Name: {login}",
        f"X-Authentik-Groups: {groups}",
        f"X-Authentik-Uid: ",
        "Connection: close",
    ]
    if SECRET:
        hdrs.append(f"x-keap-proxy-secret: {SECRET}")
    try:
        ur, uw = await asyncio.wait_for(asyncio.open_connection(*upstream), timeout=10)
    except (OSError, asyncio.TimeoutError) as e:
        await reply(writer, 502, f"KEAP unreachable: {e}"); return
    uw.write(("\r\n".join([request_line] + hdrs) + "\r\n\r\n").encode("latin-1"))
    if chunked:
        # relay until the client is done sending (our clients never chunk; kept for completeness)
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            uw.write(chunk)
            if chunk.endswith(b"0\r\n\r\n"):
                break
    elif length:
        remaining = length
        while remaining > 0:
            chunk = await reader.read(min(65536, remaining))
            if not chunk:
                break
            uw.write(chunk); remaining -= len(chunk)
    await uw.drain()
    status = "?"
    first = True
    try:
        while True:
            chunk = await ur.read(65536)
            if not chunk:
                break
            if first:
                status = chunk.split(b" ", 2)[1].decode(errors="replace") if b" " in chunk else "?"
                first = False
            writer.write(chunk)
            await writer.drain()
    finally:
        uw.close(); writer.close()
    print(f"{status} {login} [{groups.split(',')[0]}] {request_line} {int((time.time()-t0)*1000)}ms", flush=True)


async def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--socket", required=True)
    ap.add_argument("--upstream", default="127.0.0.1:8091")
    a = ap.parse_args()
    host, port = a.upstream.rsplit(":", 1)
    up = (host, int(port))
    try:
        os.unlink(a.socket)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(lambda r, w: handle(r, w, up), path=a.socket, limit=1 << 20)
    os.chmod(a.socket, 0o666)
    print(f"keap-identity: {a.socket} → {a.upstream} (host {HOST}, secret {'set' if SECRET else 'UNSET'})", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
