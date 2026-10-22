"""Bone on several addresses: uvicorn takes one --host, a Server takes many bound sockets.

    serve.py --port 8099 --host 127.0.0.1 --host 172.17.0.1

Host callers dial 127.0.0.1; on Linux containers dial host.docker.internal, which is the docker
bridge address, not loopback (tests/anatomy/test_container_host_doors.py). A non-loopback address
binds with IP_FREEBIND, so Bone starts before docker0 exists and answers there once it does.
"""
from __future__ import annotations

import argparse
import socket

import uvicorn

IP_FREEBIND = getattr(socket, "IP_FREEBIND", 15)  # Linux; macOS runs the plist's plain uvicorn


def bind(host: str, port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if host != "127.0.0.1":
        s.setsockopt(socket.IPPROTO_IP, IP_FREEBIND, 1)
    s.bind((host, port))
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", action="append", required=True)
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    socks = [bind(h, a.port) for h in dict.fromkeys(a.host)]
    uvicorn.Server(uvicorn.Config("main:app", port=a.port)).run(sockets=socks)


if __name__ == "__main__":
    main()
