#!/usr/bin/env python3
"""Does this S3 endpoint honor Object Lock COMPLIANCE, or only accept the headers?

A clone that 200s PutObjectRetention and then still deletes the version is the
false-green this estate already named on the raw-archive-store row. This probe
writes one tiny object, asks to delete that version, and reports what happened.

Usage:
    tools/raw-archive-probe.py              # live, creds from env or docker
    tools/raw-archive-probe.py --dry-run    # no network; UNVERIFIED
    tools/raw-archive-probe.py --json

Exit 0 always: this is a reader. The pytest gate is what goes red on a WORM
claim without a 403.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

DEFAULT_ENDPOINT = "http://127.0.0.1:9010"
DEFAULT_REGION = "us-east-1"
WORM_DELETE_CODES = frozenset({403, 409})
DOCKER_CONTAINER = "iiab-rustfs-1"

HONOR = "HONOR"
NON_HONOR = "NON_HONOR"
UNSUPPORTED = "UNSUPPORTED"
UNVERIFIED = "UNVERIFIED"


class HttpResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b""):
        self.status = status
        self.headers = headers
        self.body = body


Transport = Callable[[str, str, dict[str, str], bytes], HttpResponse]


class ProbeError(RuntimeError):
    pass


def assert_worm_claim(claimed_worm: bool, delete_status: int | None) -> None:
    """Gate: a WORM claim without a 403 (or 409) on version-delete is a lie."""
    if claimed_worm and delete_status not in WORM_DELETE_CODES:
        raise AssertionError(
            f"claimed WORM but delete returned {delete_status!r}, not 403"
        )


def classify(
    *,
    live: bool,
    lock_status: int | None,
    put_status: int | None,
    delete_status: int | None,
) -> str:
    if not live:
        return UNVERIFIED
    if lock_status is None:
        return UNVERIFIED
    if lock_status >= 400 and lock_status != 409:
        return UNSUPPORTED
    if put_status is None:
        return UNVERIFIED
    if put_status >= 400:
        return UNSUPPORTED
    if delete_status is None:
        return UNVERIFIED
    if delete_status in WORM_DELETE_CODES:
        return HONOR
    return NON_HONOR


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4_headers(
    *,
    method: str,
    url: str,
    access_key: str,
    secret_key: str,
    region: str,
    body: bytes,
    extra: dict[str, str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    query = parsed.query
    amz_date = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    payload_hash = _sha256(body)
    headers = {
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }
    if extra:
        headers.update({k.lower(): v for k, v in extra.items()})
    signed_names = sorted(headers)
    canonical_headers = "".join(f"{n}:{headers[n]}\n" for n in signed_names)
    signed_hdrs = ";".join(signed_names)
    canonical = (
        f"{method}\n{path}\n{query}\n{canonical_headers}\n{signed_hdrs}\n{payload_hash}"
    )
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{_sha256(canonical.encode())}"
    )
    k_date = _sign(("AWS4" + secret_key).encode(), date_stamp)
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_hdrs}, Signature={signature}"
    )
    return headers


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes
) -> HttpResponse:
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return HttpResponse(
                status=resp.status,
                headers={k.lower(): v for k, v in resp.headers.items()},
                body=resp.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])},
            body=exc.read() if exc.fp else b"",
        )
    except OSError as exc:
        raise ProbeError(f"endpoint unreachable: {exc}") from exc


def creds_from_docker(container: str = DOCKER_CONTAINER) -> tuple[str, str] | None:
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    env = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    access = env.get("RUSTFS_ACCESS_KEY") or env.get("MINIO_ROOT_USER")
    secret = env.get("RUSTFS_SECRET_KEY") or env.get("MINIO_ROOT_PASSWORD")
    if access and secret:
        return access, secret
    return None


def resolve_creds(access: str | None, secret: str | None) -> tuple[str, str] | None:
    access = access or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = secret or os.environ.get("AWS_SECRET_ACCESS_KEY")
    if access and secret:
        return access, secret
    return creds_from_docker()


class ProbeResult:
    def __init__(
        self,
        verdict: str,
        live: bool,
        endpoint: str,
        lock_status: int | None = None,
        put_status: int | None = None,
        delete_status: int | None = None,
        version_id: str | None = None,
        notes: list[str] | None = None,
    ):
        self.verdict = verdict
        self.live = live
        self.endpoint = endpoint
        self.lock_status = lock_status
        self.put_status = put_status
        self.delete_status = delete_status
        self.version_id = version_id
        self.notes = notes or []

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "live": self.live,
            "endpoint": self.endpoint,
            "lock_status": self.lock_status,
            "put_status": self.put_status,
            "delete_status": self.delete_status,
            "version_id": self.version_id,
            "notes": self.notes,
        }


def _s3(
    transport: Transport,
    *,
    method: str,
    endpoint: str,
    path: str,
    query: str,
    access: str,
    secret: str,
    region: str,
    body: bytes = b"",
    extra: dict[str, str] | None = None,
) -> HttpResponse:
    url = endpoint.rstrip("/") + path + (("?" + query) if query else "")
    headers = sigv4_headers(
        method=method,
        url=url,
        access_key=access,
        secret_key=secret,
        region=region,
        body=body,
        extra=extra,
    )
    return transport(method, url, headers, body)


def run_probe(
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    region: str = DEFAULT_REGION,
    access: str | None = None,
    secret: str | None = None,
    dry_run: bool = False,
    transport: Transport = urllib_transport,
    now: dt.datetime | None = None,
    bucket: str | None = None,
) -> ProbeResult:
    notes: list[str] = []
    if dry_run:
        notes.append("dry-run: no request sent")
        return ProbeResult(verdict=UNVERIFIED, live=False, endpoint=endpoint, notes=notes)

    pair = resolve_creds(access, secret)
    if not pair:
        notes.append("no S3 creds (env AWS_* or docker inspect of iiab-rustfs-1)")
        return ProbeResult(verdict=UNVERIFIED, live=False, endpoint=endpoint, notes=notes)

    access, secret = pair
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%d%H%M%S")
    bucket = bucket or f"raprobe-{stamp}"
    key = f"raw/probe/{stamp}.txt"
    payload = b"raw-archive-probe\n"
    retain = (now or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(minutes=15)
    retain_s = retain.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    lock = _s3(
        transport,
        method="PUT",
        endpoint=endpoint,
        path=f"/{bucket}",
        query="",
        access=access,
        secret=secret,
        region=region,
        extra={"x-amz-bucket-object-lock-enabled": "true"},
    )
    notes.append(f"CreateBucket object-lock header -> {lock.status}")

    put = _s3(
        transport,
        method="PUT",
        endpoint=endpoint,
        path=f"/{bucket}/{key}",
        query="",
        access=access,
        secret=secret,
        region=region,
        body=payload,
        extra={
            "content-type": "text/plain",
            "x-amz-object-lock-mode": "COMPLIANCE",
            "x-amz-object-lock-retain-until-date": retain_s,
        },
    )
    notes.append(f"PutObject COMPLIANCE retain-until {retain_s} -> {put.status}")
    version = put.headers.get("x-amz-version-id")

    delete_status = None
    if put.status < 400:
        q = f"versionId={urllib.parse.quote(version, safe='')}" if version else ""
        delete = _s3(
            transport,
            method="DELETE",
            endpoint=endpoint,
            path=f"/{bucket}/{key}",
            query=q,
            access=access,
            secret=secret,
            region=region,
        )
        delete_status = delete.status
        notes.append(
            f"DeleteObject versionId={version or '(none)'} -> {delete.status}"
        )
        if delete.status not in WORM_DELETE_CODES:
            notes.append(
                "NON-HONOR: lock headers were accepted but the version still deleted"
            )

    verdict = classify(
        live=True,
        lock_status=lock.status,
        put_status=put.status,
        delete_status=delete_status,
    )
    return ProbeResult(
        verdict=verdict,
        live=True,
        endpoint=endpoint,
        lock_status=lock.status,
        put_status=put.status,
        delete_status=delete_status,
        version_id=version,
        notes=notes,
    )


def render(result: ProbeResult) -> str:
    lines = [
        f"verdict: {result.verdict}",
        f"live: {result.live}",
        f"endpoint: {result.endpoint}",
        f"lock_status: {result.lock_status}",
        f"put_status: {result.put_status}",
        f"delete_status: {result.delete_status}",
        f"version_id: {result.version_id}",
    ]
    lines.extend(f"note: {n}" for n in result.notes)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default=os.environ.get("RAW_ARCHIVE_S3_ENDPOINT", DEFAULT_ENDPOINT))
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--access-key", default=None)
    p.add_argument("--secret-key", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--claim-worm", action="store_true", help="fail the claim-check if delete is not 403")
    args = p.parse_args(argv)
    try:
        result = run_probe(
            endpoint=args.endpoint,
            region=args.region,
            access=args.access_key,
            secret=args.secret_key,
            dry_run=args.dry_run,
        )
    except ProbeError as exc:
        result = ProbeResult(
            verdict=UNVERIFIED,
            live=False,
            endpoint=args.endpoint,
            notes=[str(exc)],
        )
    if args.claim_worm:
        try:
            assert_worm_claim(True, result.delete_status)
        except AssertionError as exc:
            print(render(result), end="")
            print(f"gate: {exc}", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(render(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
