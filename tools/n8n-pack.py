#!/usr/bin/env python3
"""n8n packs: lint (CI), encryption-key (REM-202), sync (post.yml), watch (Pulse)."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
PACKS_DIR = REPO / "files" / "anatomy" / "n8n" / "packs"
PRIVATE = re.compile(
    r"127\.0\.0\.1|localhost|10\.\d+\.\d+\.\d+|192\.168\.|"
    r"172\.(1[6-9]|2\d|3[0-1])\."
)
SECRETISH = re.compile(
    r"(sk-|Bearer [A-Za-z0-9._-]{12,}|_pw_|api[_-]?key\s*[:=])", re.I
)
HOST_RE = re.compile(r"https?://([^/\"'\s]+)", re.I)
KEAP_HOST_MARK = re.compile(r"\$vars\.keapBase|keap_domain|\{\{\s*keap_domain")
CRON_RE = re.compile(r'"expression":\s*"([^"]+)"')

OWNER_SCOPES = [
    "workflow:create",
    "workflow:read",
    "workflow:update",
    "workflow:delete",
    "workflow:list",
    "credential:create",
    "credential:read",
    "credential:update",
    "credential:delete",
    "credential:list",
    "execution:read",
    "execution:list",
]


def load_packs(packs_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(packs_dir.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        doc["_path"] = path
        rows.append(doc)
    return rows


def workflow_path(pack: dict[str, Any]) -> Path:
    rel = pack["workflow"]
    return (pack["_path"].parent / rel).resolve()


def load_workflow(pack: dict[str, Any]) -> dict[str, Any]:
    return json.loads(workflow_path(pack).read_text(encoding="utf-8"))


def http_hosts(wf: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for node in wf.get("nodes") or []:
        params = node.get("parameters") or {}
        url = str(params.get("url") or "")
        found.update(m.group(1).split(":")[0].lower() for m in HOST_RE.finditer(url))
    return found


def cron_from_workflow(wf: dict[str, Any]) -> str | None:
    for node in wf.get("nodes") or []:
        if node.get("type") != "n8n-nodes-base.scheduleTrigger":
            continue
        rule = (node.get("parameters") or {}).get("rule") or {}
        for interval in rule.get("interval") or []:
            expr = interval.get("expression")
            if expr:
                return str(expr)
    blob = json.dumps(wf)
    m = CRON_RE.search(blob)
    return m.group(1) if m else None


def period_seconds(cron: str) -> int:
    parts = cron.split()
    if len(parts) != 5:
        return 24 * 3600
    if parts[4] in ("1-5", "MON-FRI", "mon-fri"):
        return 3 * 24 * 3600
    return 24 * 3600


def lint_pack(pack: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    pid = pack.get("id")
    if not pid:
        return ["missing id"]
    wf_file = workflow_path(pack)
    if not wf_file.is_file():
        return [f"{pid}: workflow missing: {wf_file}"]
    blob = wf_file.read_text(encoding="utf-8")
    wf = json.loads(blob)
    nos = (wf.get("meta") or {}).get("nos") or {}
    if nos.get("id") != pid:
        errs.append(f"{pid}: meta.nos.id={nos.get('id')!r} != pack id")
    if wf.get("active") is True:
        errs.append(f"{pid}: git graph is active: true")
    if SECRETISH.search(blob):
        errs.append(f"{pid}: secret-shaped literal in graph")
    if PRIVATE.search(blob):
        errs.append(f"{pid}: RFC-1918/loopback in graph")
    cron = pack.get("cron")
    got = cron_from_workflow(wf)
    if cron and got != cron:
        errs.append(f"{pid}: cron {cron!r} != schedule node {got!r}")
    egress_hosts = {e["host"].lower() for e in pack.get("egress") or []}
    processors = list(pack.get("gdpr", {}).get("processors") or [])
    for e in pack.get("egress") or []:
        party = e.get("processor")
        if party and party not in processors:
            errs.append(f"{pid}: egress processor {party!r} not in gdpr.processors")
        host = e["host"].lower()
        if host not in blob.lower():
            errs.append(f"{pid}: egress host {host} missing from graph")
    for host in http_hosts(wf):
        if host.startswith("$") or "keap" in host or host in egress_hosts:
            continue
        if KEAP_HOST_MARK.search(host):
            continue
        errs.append(f"{pid}: undeclared hop host {host}")
    if pack.get("keap_write"):
        if "$vars.keapBase" not in blob and "keap_domain" not in blob:
            errs.append(f"{pid}: keap_write but no keap host token")
        keap_nodes = [
            n
            for n in wf.get("nodes") or []
            if "keapBase" in json.dumps(n.get("parameters") or {})
            or "/agent/v1/" in json.dumps(n.get("parameters") or {})
        ]
        for n in keap_nodes:
            params = n.get("parameters") or {}
            url = str(params.get("url") or "")
            if "/agent/v1/" not in url:
                continue
            auth = params.get("authentication")
            gtype = params.get("genericAuthType")
            if auth != "genericCredentialType" or gtype != "httpHeaderAuth":
                errs.append(f"{pid}: KEAP node {n.get('name')} is not httpHeaderAuth")
            if "Authorization" in json.dumps(params.get("headerParameters") or {}):
                errs.append(f"{pid}: KEAP node {n.get('name')} has inline Authorization")
    return errs


def lint(packs_dir: Path) -> int:
    packs = load_packs(packs_dir)
    if not packs:
        print("no packs", file=sys.stderr)
        return 1
    errs = [e for p in packs for e in lint_pack(p)]
    for e in errs:
        print(e, file=sys.stderr)
    return 1 if errs else 0


def upsert_secret(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    quoted = json.dumps(value)
    line = f"{key}: {quoted}"
    pat = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    if pat.search(text):
        text = pat.sub(line, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def read_secret(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    val = doc.get(key) or ""
    return str(val)


def encryption_key(secrets_path: Path, config_path: Path) -> str:
    existing = read_secret(secrets_path, "n8n_encryption_key")
    if len(existing) >= 16:
        print("reused", file=sys.stderr)
        return existing
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
        key = str(cfg.get("encryptionKey") or "")
        if len(key) >= 16:
            upsert_secret(secrets_path, "n8n_encryption_key", key)
            print("adopted", file=sys.stderr)
            return key
    key = secrets.token_hex(32)
    upsert_secret(secrets_path, "n8n_encryption_key", key)
    print("minted", file=sys.stderr)
    return key


def _ssl() -> ssl.SSLContext:
    return ssl.create_default_context()


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    cookie: str = "",
    api_key: str = "",
) -> tuple[int, Any, str]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    if api_key:
        req.add_header("X-N8N-API-KEY", api_key)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, context=_ssl(), timeout=30) as resp:
            raw = resp.read()
            cookie_out = resp.headers.get("Set-Cookie", "")
            parsed = json.loads(raw.decode() or "null") if raw else None
            return resp.status, parsed, cookie_out
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode() or "null")
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
        return exc.code, parsed, ""


def cookie_from_set_cookie(set_cookie: str) -> str:
    if not set_cookie:
        return ""
    return set_cookie.split(";", 1)[0]


def n8n_login(base: str, email: str, password: str) -> str:
    status, payload, set_cookie = http_json(
        "POST",
        f"{base}/rest/login",
        body={"emailOrLdapLoginId": email, "password": password},
    )
    cookie = cookie_from_set_cookie(set_cookie)
    if status != 200 or not cookie:
        raise SystemExit(f"n8n login failed: {status} {payload}")
    return cookie


def mint_api_key(base: str, cookie: str) -> str:
    status, payload, _ = http_json(
        "POST",
        f"{base}/rest/api-keys",
        cookie=cookie,
        body={"label": "nOS playbook", "expiresAt": None, "scopes": OWNER_SCOPES},
    )
    if status not in (200, 201):
        raise SystemExit(f"n8n api-key mint failed: {status} {payload}")
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    key = data.get("rawApiKey") or data.get("apiKey") or ""
    if not key or str(key).startswith("n8n_api_•"):
        raise SystemExit(f"n8n api-key mint returned no raw key: {payload}")
    return str(key)


def api(
    method: str, base: str, path: str, api_key: str, body: Any = None
) -> tuple[int, Any]:
    status, payload, _ = http_json(
        method, f"{base}{path}", api_key=api_key, body=body
    )
    return status, payload


def unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def render_workflow(
    wf: dict[str, Any], keap_base: str, cred_id: str | None
) -> dict[str, Any]:
    blob = json.dumps(wf)
    if keap_base:
        blob = blob.replace("={{ $vars.keapBase }}", keap_base.rstrip("/"))
        blob = blob.replace("{{ $vars.keapBase }}", keap_base.rstrip("/"))
        blob = blob.replace("$vars.keapBase", keap_base.rstrip("/"))
    out = json.loads(blob)
    if PRIVATE.search(json.dumps(out)):
        raise SystemExit("rendered workflow still contains RFC-1918/loopback")
    if cred_id:
        cred = {"httpHeaderAuth": {"id": cred_id, "name": "nos-keap-rw"}}
        for node in out.get("nodes") or []:
            params = node.get("parameters") or {}
            if params.get("genericAuthType") == "httpHeaderAuth":
                node["credentials"] = cred
    out["active"] = False
    return out


def upsert_keap_cred(base: str, api_key: str, token: str) -> str:
    status, payload = api("GET", base, "/api/v1/credentials", api_key)
    rows = unwrap(payload) or []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if isinstance(row, dict) and row.get("name") == "nos-keap-rw":
            cid = str(row.get("id") or "")
            if cid:
                api(
                    "PATCH",
                    base,
                    f"/api/v1/credentials/{cid}",
                    api_key,
                    {
                        "name": "nos-keap-rw",
                        "type": "httpHeaderAuth",
                        "data": {
                            "name": "Authorization",
                            "value": f"Bearer {token}",
                        },
                    },
                )
                return cid
    status, payload = api(
        "POST",
        base,
        "/api/v1/credentials",
        api_key,
        {
            "name": "nos-keap-rw",
            "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": f"Bearer {token}"},
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"n8n credential upsert failed: {status} {payload}")
    data = unwrap(payload) or {}
    cid = str(data.get("id") or "")
    if not cid:
        raise SystemExit(f"n8n credential create returned no id: {payload}")
    return cid


def list_workflows(base: str, api_key: str) -> list[dict[str, Any]]:
    status, payload = api("GET", base, "/api/v1/workflows?limit=250", api_key)
    if status != 200:
        raise SystemExit(f"n8n list workflows failed: {status} {payload}")
    data = unwrap(payload) or []
    return data if isinstance(data, list) else []


def upsert_workflow(
    base: str, api_key: str, pack: dict[str, Any], rendered: dict[str, Any]
) -> None:
    existing = list_workflows(base, api_key)
    match = None
    for wf in existing:
        meta = (wf.get("meta") or {}).get("nos") or {}
        if meta.get("id") == pack["id"] or wf.get("name") == rendered.get("name"):
            match = wf
            break
    body = {
        "name": rendered["name"],
        "nodes": rendered["nodes"],
        "connections": rendered["connections"],
        "settings": rendered.get("settings") or {},
        "staticData": rendered.get("staticData"),
        "meta": rendered.get("meta") or {},
    }
    if match:
        wid = match["id"]
        body["active"] = bool(match.get("active"))
        status, payload = api("PUT", base, f"/api/v1/workflows/{wid}", api_key, body)
        if status not in (200, 201):
            raise SystemExit(f"n8n PUT workflow failed: {status} {payload}")
        return
    body["active"] = False
    status, payload = api("POST", base, "/api/v1/workflows", api_key, body)
    if status not in (200, 201):
        raise SystemExit(f"n8n POST workflow failed: {status} {payload}")


def cmd_sync(args: argparse.Namespace) -> int:
    secrets_path = Path(args.secrets)
    base = args.url.rstrip("/")
    email = os.environ.get("N8N_EMAIL") or args.email
    password = os.environ.get("N8N_PASSWORD") or ""
    keap_base = (os.environ.get("KEAP_BASE") or args.keap_base or "").rstrip("/")
    keap_token = os.environ.get("KEAP_TOKEN") or ""
    api_key = read_secret(secrets_path, "n8n_api_key")
    if not api_key:
        if not email or not password:
            raise SystemExit("n8n sync needs N8N_EMAIL+N8N_PASSWORD to mint the API key")
        cookie = n8n_login(base, email, password)
        api_key = mint_api_key(base, cookie)
        upsert_secret(secrets_path, "n8n_api_key", api_key)
    cred_id = None
    if keap_token:
        cred_id = upsert_keap_cred(base, api_key, keap_token)
    for pack in load_packs(Path(args.packs)):
        if pack.get("keap_write") and not (keap_base and cred_id):
            print(f"skip {pack['id']}: keap_write without KEAP_BASE/token", file=sys.stderr)
            continue
        wf = load_workflow(pack)
        rendered = render_workflow(wf, keap_base, cred_id)
        upsert_workflow(base, api_key, pack, rendered)
        print(pack["id"])
    return 0


def parse_when(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / (1000 if value > 10**12 else 1), tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def cmd_watch(args: argparse.Namespace) -> int:
    secrets_path = Path(args.secrets)
    api_key = os.environ.get("N8N_API_KEY") or read_secret(secrets_path, "n8n_api_key")
    base = args.url.rstrip("/")
    packs = {p["id"]: p for p in load_packs(Path(args.packs))}
    if not api_key:
        print("UNKNOWN: no n8n_api_key", file=sys.stderr)
        return 1
    status, payload = api("GET", base, "/api/v1/workflows?limit=250", api_key)
    if status != 200:
        print(f"UNKNOWN: n8n unreachable ({status})", file=sys.stderr)
        return 1
    workflows = unwrap(payload) or []
    findings: list[str] = []
    now = datetime.now(timezone.utc)
    for wf in workflows:
        meta = (wf.get("meta") or {}).get("nos") or {}
        pid = meta.get("id")
        if pid not in packs:
            continue
        if not wf.get("active"):
            continue
        pack = packs[pid]
        wid = wf.get("id")
        st, ex = api(
            "GET",
            base,
            f"/api/v1/executions?workflowId={wid}&limit=20",
            api_key,
        )
        if st != 200:
            findings.append(f"{pid}: executions unread {st}")
            continue
        rows = unwrap(ex) or []
        if not isinstance(rows, list):
            rows = []
        if not rows:
            findings.append(f"{pid}: stale (no executions)")
            continue
        last = rows[0]
        last_status = str(last.get("status") or last.get("finished") or "")
        if last_status in {"error", "crashed", "failed"} or last.get("finished") is False:
            findings.append(f"{pid}: last execution {last_status or 'failed'}")
        successes = [
            r
            for r in rows
            if str(r.get("status") or "") in {"success", "ok", "waiting"}
            or r.get("finished") is True
        ]
        last_ok = None
        for r in successes or rows:
            last_ok = parse_when(r.get("stoppedAt") or r.get("startedAt") or r.get("createdAt"))
            if last_ok:
                break
        cron = pack.get("cron") or ""
        slack = period_seconds(cron) * 2
        if last_ok is None or (now - last_ok).total_seconds() > slack:
            findings.append(f"{pid}: stale")
    if findings:
        for line in findings:
            print(line, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_lint = sub.add_parser("lint")
    p_lint.add_argument("--packs", default=str(PACKS_DIR))
    p_enc = sub.add_parser("encryption-key")
    p_enc.add_argument("--secrets", required=True)
    p_enc.add_argument("--config", required=True)
    p_sync = sub.add_parser("sync")
    p_sync.add_argument("--packs", default=str(PACKS_DIR))
    p_sync.add_argument("--url", default="http://127.0.0.1:5678")
    p_sync.add_argument("--secrets", required=True)
    p_sync.add_argument("--email", default="")
    p_sync.add_argument("--keap-base", default="")
    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--packs", default=str(PACKS_DIR))
    p_watch.add_argument("--url", default="http://127.0.0.1:5678")
    p_watch.add_argument("--secrets", default=os.path.expanduser("~/.nos/secrets.yml"))
    args = parser.parse_args(argv)
    if args.cmd == "lint":
        return lint(Path(args.packs))
    if args.cmd == "encryption-key":
        print(encryption_key(Path(args.secrets), Path(args.config)))
        return 0
    if args.cmd == "sync":
        return cmd_sync(args)
    if args.cmd == "watch":
        return cmd_watch(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
