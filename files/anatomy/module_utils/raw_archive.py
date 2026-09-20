"""raw-archive-store — the shared archive_put/archive_get interface named by
docs/plans/raw-archive-store.md and state/digest-constitution.yml's
`raw-never-touches-knowledge` row (status: pending — the rule as a WHOLE also
needs the captures/proposals validators before it can flip to enforced; that
is a separate, larger piece than this module and is NOT this file's job).

The mechanism is already verified HONOR (2026-09-13, tools/raw-archive-probe.py
against live RustFS: PUT retain-until 200, version DELETE -> 403). This module
is the "one committed sentence" the plan said was missing: a thin, reusable
PUT/GET pair every digest importer calls BEFORE parse() derives anything —
raw bytes never enter the bundle IR (never a `check_bundle`/`absorb` concern).

Bucket: dedicated `raw-archive` (Object Lock enabled) — never `backups`, same
failure-domain caution the plan names. Key: `raw/<source>/<content-hash>`,
partitioned by digest family (`invoice`, later `device`) — the SAME shape
`device-extraction.raw_archive_ref` already reserves a column for
(state/keap-tables/device-extraction.table.yml), so a future generic
"resolve this ref" reader works for every family without a per-family branch.

EXPLICIT OPT-IN, not opt-out: both functions are a no-op (return None, never
touch the network) unless `RAW_ARCHIVE_ENABLED=1` is set. A host that happens
to have a live RustFS reachable (docker creds resolve) must NOT get silently
written to just because an importer or a test ran — this was caught live:
the first version of this module resolved creds whenever they were
discoverable, and running the offline test suite in dev put 7 real fixture
objects into the operator's actual `raw-archive` bucket, each now
COMPLIANCE-locked for 3650 days (unrecoverable). Default OFF closes that.

Fail-open once enabled: `archive_put`/`archive_get` still return None (never
raise) if creds are missing or the endpoint is unreachable — a digest
importer runs, gates, and absorbs exactly as before whether or not the
archive actually wrote.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

DEFAULT_ENDPOINT = "http://127.0.0.1:9010"
DEFAULT_REGION = "us-east-1"
BUCKET = "raw-archive"          # dedicated — never `backups` (same failure domain)
DOCKER_CONTAINER = "iiab-rustfs-1"


class HttpResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b""):
        self.status = status
        self.headers = headers
        self.body = body


Transport = Callable[[str, str, dict[str, str], bytes], HttpResponse]


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sigv4_headers(*, method: str, url: str, access_key: str, secret_key: str, region: str,
                   body: bytes, extra: dict[str, str] | None = None,
                   now: dt.datetime | None = None) -> dict[str, str]:
    """SigV4 signer — same algorithm as tools/raw-archive-probe.py's
    sigv4_headers (kept as a sibling copy, not a shared import: the probe is a
    standalone reader script, this is a library module other code imports)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    query = parsed.query
    amz_date = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    payload_hash = _sha256(body)
    headers = {"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash}
    if extra:
        headers.update({k.lower(): v for k, v in extra.items()})
    signed_names = sorted(headers)
    canonical_headers = "".join(f"{n}:{headers[n]}\n" for n in signed_names)
    signed_hdrs = ";".join(signed_names)
    canonical = f"{method}\n{path}\n{query}\n{canonical_headers}\n{signed_hdrs}\n{payload_hash}"
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{_sha256(canonical.encode())}"
    k_date = _sign(("AWS4" + secret_key).encode(), date_stamp)
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                               f"SignedHeaders={signed_hdrs}, Signature={signature}")
    return headers


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes) -> HttpResponse:
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return HttpResponse(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])},
                            exc.read() if exc.fp else b"")


def _creds_from_docker(container: str = DOCKER_CONTAINER) -> tuple[str, str] | None:
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container],
            text=True, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    env = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    access = env.get("RUSTFS_ACCESS_KEY") or env.get("MINIO_ROOT_USER")
    secret = env.get("RUSTFS_SECRET_KEY") or env.get("MINIO_ROOT_PASSWORD")
    return (access, secret) if access and secret else None


def resolve_creds(access: str | None, secret: str | None) -> tuple[str, str] | None:
    access = access or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = secret or os.environ.get("AWS_SECRET_ACCESS_KEY")
    if access and secret:
        return access, secret
    return _creds_from_docker()


def _enabled() -> bool:
    """Explicit opt-in ONLY. Absent/unset/anything-but-truthy = disabled — see
    the module docstring for why this is opt-in, not opt-out."""
    return os.environ.get("RAW_ARCHIVE_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _s3(transport: Transport, *, method: str, endpoint: str, path: str, query: str = "",
       access: str, secret: str, region: str, body: bytes = b"",
       extra: dict[str, str] | None = None) -> HttpResponse | None:
    url = endpoint.rstrip("/") + path + (("?" + query) if query else "")
    headers = _sigv4_headers(method=method, url=url, access_key=access, secret_key=secret,
                             region=region, body=body, extra=extra)
    try:
        return transport(method, url, headers, body)
    except OSError:
        return None


def archive_put(source: str, content: bytes, *, retain_days: int = 3650,
                endpoint: str | None = None, region: str = DEFAULT_REGION,
                access: str | None = None, secret: str | None = None,
                transport: Transport = urllib_transport, now: dt.datetime | None = None) -> str | None:
    """PUT `content` immutably at raw/<source>/<content-hash>, COMPLIANCE-locked
    for `retain_days`. Returns the content-hash key on success; None if the
    archive is disabled/unreachable/lacks creds — a caller MUST treat None as
    "not archived, proceed anyway", never as a reason to refuse the import
    (the raw-archive stage sits BEFORE parse(), outside check_bundle/absorb).
    Idempotent: re-archiving identical bytes PUTs the same key (S3 semantics,
    no error) — never mints a second copy of the same original."""
    if not _enabled():
        return None
    pair = resolve_creds(access, secret)
    if not pair:
        return None
    access, secret = pair
    endpoint = endpoint or os.environ.get("RAW_ARCHIVE_ENDPOINT", DEFAULT_ENDPOINT)
    h = content_hash(content)
    key = f"raw/{source}/{h}"
    retain = (now or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(days=retain_days)
    retain_s = retain.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Idempotent bucket create — a 409 (already owned) is fine, ignored below.
    _s3(transport, method="PUT", endpoint=endpoint, path=f"/{BUCKET}", access=access, secret=secret,
       region=region, extra={"x-amz-bucket-object-lock-enabled": "true"})
    put = _s3(transport, method="PUT", endpoint=endpoint, path=f"/{BUCKET}/{key}", access=access,
             secret=secret, region=region, body=content,
             extra={"x-amz-object-lock-mode": "COMPLIANCE", "x-amz-object-lock-retain-until-date": retain_s})
    if put is None or put.status >= 400:
        return None
    return h


def archive_get(content_hash_: str, *, source: str, endpoint: str | None = None,
                region: str = DEFAULT_REGION, access: str | None = None, secret: str | None = None,
                transport: Transport = urllib_transport) -> bytes | None:
    """GET the original bytes back by (source, content-hash). None on any
    failure — read path, same fail-open posture as archive_put."""
    if not _enabled():
        return None
    pair = resolve_creds(access, secret)
    if not pair:
        return None
    access, secret = pair
    endpoint = endpoint or os.environ.get("RAW_ARCHIVE_ENDPOINT", DEFAULT_ENDPOINT)
    got = _s3(transport, method="GET", endpoint=endpoint, path=f"/{BUCKET}/raw/{source}/{content_hash_}",
             access=access, secret=secret, region=region)
    if got is None or got.status >= 400:
        return None
    return got.body
