#!/usr/bin/env python3
"""A Paperclip company declared in a repo, made real through Paperclip's API.

The company file (e.g. hnedweb/ssot/company.yml) wins over Paperclip: names, titles,
roles, reporting lines, model, monthly budget, concurrency, paused/active and each
agent's AGENTS.md. Work state (issues, comments, documents) stays Paperclip's.

    paperclip-company.py login                     # board key via Paperclip's approval link
    paperclip-company.py plan  <company.yml>       # the difference, writes nothing
    paperclip-company.py apply <company.yml> [--confirm]

Prompts live next to the file at ../agents/<name>/AGENTS.md; {{KEY}} is replaced by
the text of `include: {KEY: path}`. Only the API is written, never Paperclip's db.
Exit: 0 ok (plan: nothing to change), 1 plan has changes, 2 Paperclip unreachable or
a write failed, 3 refused (no key, bad file).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

import yaml

API = os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3006").rstrip("/") + "/api"
PUBLIC = os.environ.get("PAPERCLIP_PUBLIC_URL", "https://paperclip.pazny.eu").rstrip("/")
KEY_FILE = pathlib.Path(os.environ.get("PAPERCLIP_BOARD_KEY_FILE", "~/.nos/paperclip-board.token")).expanduser()
PROMPT = "AGENTS.md"


class Failed(Exception):
    pass


def call(method, path, body=None, key=None):
    hdr = {"content-type": "application/json"}
    if key:
        hdr["authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, data=data, headers=hdr, method=method),
                                    timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise Failed(f"{method} {path}: HTTP {e.code} {e.read()[:300].decode(errors='replace')}") from None
    except (urllib.error.URLError, OSError) as e:
        raise Failed(f"{method} {path}: {e}") from None


def login(company_id):
    ch = call("POST", "/cli-auth/challenges", {"command": "paperclip-company", "clientName": "nOS",
                                              "requestedCompanyId": company_id})
    # approvalUrl carries the loopback base we called; the board's session lives on the public host
    print(f"Open and approve (signed in as the board):\n  {PUBLIC + ch['approvalPath']}")
    for _ in range(600):
        time.sleep(1)
        st = call("GET", f"/cli-auth/challenges/{ch['id']}?token={ch['token']}")
        if st.get("status") == "approved":
            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            KEY_FILE.write_text(ch["boardApiToken"])
            KEY_FILE.chmod(0o600)
            print(f"approved; key saved to {KEY_FILE}")
            return 0
        if st.get("status") in ("cancelled", "expired", "rejected"):
            print(f"challenge {st['status']}")
            return 3
    print("timed out waiting for approval")
    return 3


def desired(path):
    doc = yaml.safe_load(path.read_text())
    root = path.parent.parent                       # ssot/company.yml -> repo root
    inc = {k: (root / v).read_text().rstrip() for k, v in (doc.get("include") or {}).items()}
    d = doc.get("defaults") or {}
    out = {}
    for name, a in doc["agents"].items():
        a = {**d, **(a or {})}
        text = (root / "agents" / name / PROMPT).read_text()
        text = re.sub(r"\{\{(\w+)\}\}", lambda m: inc[m.group(1)], text)
        out[name] = {**a, "prompt": text}
    return doc["company"], out


def plan(company, want, key):
    have = {a["id"]: a for a in call("GET", f"/companies/{company['id']}/agents", key=key)}
    by_name = {a["name"]: a["id"] for a in have.values()}
    ids = {n: w.get("id") or by_name.get(n) for n, w in want.items()}
    steps = []
    co = call("GET", f"/companies/{company['id']}", key=key)
    cents = round(company["budget_usd"] * 100)
    if co.get("budgetMonthlyCents") != cents:
        steps.append(("company", None, {"budgetMonthlyCents": cents}, f"budget {co.get('budgetMonthlyCents')} -> {cents}"))
    for name, w in want.items():
        aid = ids[name]
        boss = ids.get(w["reports_to"]) if w.get("reports_to") else None
        heartbeat = {"enabled": False, "wakeOnDemand": True, "maxConcurrentRuns": w["max_concurrent_runs"]}
        fields = {"name": name, "title": w["title"], "role": w["role"], "reportsTo": boss,
                  "budgetMonthlyCents": round(w["budget_usd"] * 100)}
        if aid is None:
            steps.append(("create", name, {**fields, "adapterType": w["adapter"],
                                           "adapterConfig": {"model": w["model"], "dangerouslySkipPermissions": True},
                                           "runtimeConfig": {"heartbeat": heartbeat},
                                           "instructionsBundle": {"files": {PROMPT: w["prompt"]}}}, "new agent"))
            continue
        a = have[aid]
        diff = {k: v for k, v in fields.items() if a.get(k) != v}
        if (a.get("adapterConfig") or {}).get("model") != w["model"]:
            diff["adapterConfig"] = {"model": w["model"]}
        hb = (a.get("runtimeConfig") or {}).get("heartbeat") or {}
        if any(hb.get(k) != v for k, v in heartbeat.items()):
            diff["runtimeConfig"] = {**(a.get("runtimeConfig") or {}), "heartbeat": {**hb, **heartbeat}}
        if diff:
            steps.append(("patch", name, diff, ", ".join(sorted(diff))))
        cur = call("GET", f"/agents/{aid}/instructions-bundle/file?path={PROMPT}", key=key).get("content")
        if cur != w["prompt"]:
            steps.append(("prompt", name, {"path": PROMPT, "content": w["prompt"]}, f"{PROMPT} {len(cur or '')} -> {len(w['prompt'])} chars"))
        status = a.get("status")
        if status == "error" and w["state"] == "active":
            steps.append(("clear-error", name, None, "status error -> idle"))
        if w["state"] == "paused" and status != "paused":
            steps.append(("pause", name, None, f"status {status} -> paused"))
        if w["state"] == "active" and status == "paused":
            steps.append(("resume", name, None, "status paused -> active"))
    return ids, steps


ORDER = {"pause": 0, "clear-error": 2, "resume": 2}   # stop first, wake last: a new prompt never meets an old run


def apply(company, ids, steps, key):
    for kind, name, body, why in sorted(steps, key=lambda s: ORDER.get(s[0], 1)):
        if kind == "company":
            call("PATCH", f"/companies/{company['id']}", body, key)
        elif kind == "create":
            ids[name] = call("POST", f"/companies/{company['id']}/agents", body, key)["id"]
        elif kind == "patch":
            call("PATCH", f"/agents/{ids[name]}", body, key)
        elif kind == "prompt":
            call("PUT", f"/agents/{ids[name]}/instructions-bundle/file", body, key)
        else:                                       # clear-error / pause / resume
            call("POST", f"/agents/{ids[name]}/{kind}", {}, key)
        print(f"  done  {kind:<11} {name or company['name']}: {why}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("verb", choices=["login", "plan", "apply"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--company-id")
    args = ap.parse_args()
    if args.verb == "login":
        return login(args.company_id)
    if not args.file:
        print("plan/apply need the company file"); return 3
    if not KEY_FILE.exists():
        print(f"no board key at {KEY_FILE}; run: paperclip-company.py login"); return 3
    key = KEY_FILE.read_text().strip()
    try:
        company, want = desired(pathlib.Path(args.file).resolve())
        ids, steps = plan(company, want, key)
        for kind, name, _, why in steps:
            print(f"  {kind:<11} {name or company['name']}: {why}")
        if not steps:
            print("nothing to change"); return 0
        if args.verb == "plan" or not args.confirm:
            print(f"DRY RUN — {len(steps)} change(s); apply --confirm writes them"); return 1
        apply(company, ids, steps, key)
        if any(s[0] == "create" for s in steps):   # a reports_to naming a new agent resolves only now
            apply(company, *plan(company, want, key), key)
        return 0
    except (Failed, KeyError, FileNotFoundError, yaml.YAMLError) as e:
        print(f"FAILED: {e}"); return 2


if __name__ == "__main__":
    sys.exit(main())
