#!/usr/bin/env python3
"""Sync this box's knowledge into Open WebUI and keep an "nOS Assistant" model on it.

What users get: a model in the picker ("nOS Assistant") that answers "how do I
… on this machine" from the SAME sources the /kb/ pages are built from, plus
the live roadmap and the model list — so the answer is the runbook, not a
guess. Sources (all read-only, all local):

    kb/*.md                         the knowledge base pages (hostname rendered)
    README.md                       the recipe
    /srv/nos/files/anatomy/skills   the nOS skill library (SKILL.md per skill)
    KEAP /agent/v1 (RO token)       the roadmap rows, regenerated every run
    ollama list                     what models exist

Idempotent: a state file remembers each document's sha256 + Open WebUI file
id; unchanged documents are skipped, changed ones replaced, removed ones
deleted from the knowledge base. Stdlib only (urllib) — no requests dep.

    webui-kb-sync.py                # needs /etc/nos/openwebui.env (OPENWEBUI_API_KEY=…)
    webui-kb-sync.py --dry-run

The API key is an ADMIN's key, created in Open WebUI: Settings → Account →
API keys (admin must allow API keys under Admin → Settings). Knowledge and
model are created PUBLIC so every user sees them.
"""
import argparse
import hashlib
import io
import json
import mimetypes
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ENV_FILE = "/etc/nos/openwebui.env"
STATE = pathlib.Path("/var/lib/nos-dgx/webui-kb.json")
RT = pathlib.Path(os.environ.get("NOS_DGX_RT", "/srv/nos-dgx"))
SRC = pathlib.Path(os.environ.get("NOS_SRC", "/srv/nos"))


def load_env(path):
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)
    except OSError:
        pass


load_env(ENV_FILE)
load_env("/etc/nos/keap.env")
URL = os.environ.get("OPENWEBUI_URL", "http://127.0.0.1:12000").rstrip("/")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
BASE_MODEL = os.environ.get("OPENWEBUI_BASE_MODEL", "")     # empty = pick the first ollama model
SHORT = os.environ.get("NOS_SHORT", subprocess.run(["hostname", "-s"], capture_output=True, text=True).stdout.strip())
HOST = f"{SHORT}.local"
KB_NAME = f"nOS on {SHORT}"
MODEL_ID = "nos-assistant"

SYSTEM_PROMPT = f"""You are the nOS Assistant for the machine "{SHORT}" (an NVIDIA DGX Spark running a minimal nOS: KEAP DataTables, Open WebUI on local Ollama models, JupyterHub, n8n, per-user rootless Docker, restic backups).

Answer questions about how to use and operate THIS machine from the attached knowledge (the knowledge-base pages, the recipe README, the nOS skill library, the live roadmap and the model list). Rules:
- Answer in the language the user writes in.
- Prefer exact commands, paths, ports and page names from the knowledge; name the knowledge-base page you took it from (e.g. "see First login"). If the knowledge does not cover it, say so plainly instead of guessing.
- Services: KEAP https://{HOST}:8443 (DataTables; Linux login), Chat https://{HOST}:8444, Notebooks https://{HOST}:8445, Backups https://{HOST}:8446 (admin), Automation https://{HOST}:8447, this KB https://{HOST}/kb/.
- Roles: `nos-users` = tier 3 (read tables, own Lab, own rootless Docker); `nos-maintainers` = write token, run the stack; `admin` = the operator. Never tell a user to join the `docker` or `sudo` group.
- The DataTables: `roadmap` (the plan; `status` is a claim, `verified` is a probe's verdict — never conflate) and `current-state` (the claim board). Reading is `nos dtt status` in a shell or the `nos_tables` tool if it is enabled in this chat; filing a row is `nos dtt capture`, then commit + push in ~/nos-seed, then `nos dtt seed`.
- Secrets: never ask for or print tokens, passwords or keys.
"""


def api(method, path, body=None, headers=None, raw=None, content_type=None):
    h = {"Authorization": f"Bearer {KEY}", "Accept": "application/json"}
    data = None
    if raw is not None:
        data = raw
        h["Content-Type"] = content_type
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(f"{URL}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read()
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        txt = e.read()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt[:300].decode(errors="replace")}


def multipart(fields, filename, content, extra_fields=None):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in (extra_fields or {}).items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    ctype = mimetypes.guess_type(filename)[0] or "text/markdown"
    out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
    out.write(content)
    out.write(f"\r\n--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


# ── the documents ───────────────────────────────────────────────────────────
def render(text: str) -> str:
    return text.replace("__HOST__", HOST).replace("__SHORT__", SHORT)


def strip_frontmatter(text: str):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1], parts[2]
    return "", text


def documents():
    docs = {}
    for f in sorted((RT / "kb").glob("*.md")):
        fm, body = strip_frontmatter(f.read_text(encoding="utf-8"))
        title = next((l.split(":", 1)[1].strip().strip('"') for l in fm.splitlines() if l.startswith("title:")), f.stem)
        docs[f"kb-{f.stem}.md"] = render(f"# {title}\n\n(Knowledge-base page \"{title}\" — https://{HOST}/kb/{f.stem}.html)\n{body}")
    readme = RT / "README.md"
    if readme.exists():
        docs["recipe-README.md"] = render(readme.read_text(encoding="utf-8"))
    for f in sorted((SRC / "files/anatomy/skills").glob("*/SKILL.md")):
        docs[f"skill-{f.parent.name}.md"] = f"(nOS skill \"{f.parent.name}\" — the procedure agents and users follow)\n\n" + f.read_text(encoding="utf-8")
    # live roadmap
    tok, base = os.environ.get("KEAP_AGENT_TOKEN_RO", ""), os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091")
    if tok:
        try:
            req = urllib.request.Request(f"{base}/agent/v1/tables/roadmap/rows", headers={"Authorization": f"Bearer {tok}"})
            d = json.load(urllib.request.urlopen(req, timeout=20))
            d = d.get("data", d)
            rows = d.get("rows", []) if isinstance(d, dict) else d
            lines = [f"# nOS roadmap on {SHORT} (live, {time.strftime('%Y-%m-%d %H:%M')})", "",
                     "Every row of the `roadmap` DataTable in KEAP. `status` is a claim; `verified` is a probe's verdict.", ""]
            for r in rows:
                v = r.get("values", r)
                lines += [f"## {v.get('title','?')}  (`{v.get('slug','?')}`)",
                          f"- status: {v.get('status','?')} · track: {v.get('track','?')} · parent: {v.get('parent') or '—'} · verified: {v.get('verified') or 'unverified'}",
                          "", str(v.get("body", "")).strip(), ""]
            docs["live-roadmap.md"] = "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            print(f"  roadmap: unreadable ({e}) — kept the previous copy if any")
    # models
    ollama = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                            env={**os.environ, "OLLAMA_HOST": os.environ.get("OLLAMA_HOST", "http://172.17.0.1:11434")})
    if ollama.returncode == 0:
        docs["live-models.md"] = (f"# Local models on {SHORT} (Ollama, live)\n\nThese are the models Chat, notebooks and n8n can use. "
                                  f"Pulling a new one is an admin action.\n\n```\n{ollama.stdout}```\n")
    return docs


def pick_base(ids):
    """A sane default base model for an assistant that answers from documents.

    Not "the first in the list": on this box that was a 2-bit 'heretic' build.
    Skip uncensored/abliterated variants and Q2 quantisations, prefer the
    families that follow instructions and cite well, prefer the one that fits
    the GPU beside other users (a 120B MXFP4 model takes most of 121 GB).
    Override with OPENWEBUI_BASE_MODEL in /etc/nos/openwebui.env.
    """
    bad = ("heretic", "uncensored", "abliterated", "nsfw", "q2_k", ":q2", "-q2")
    cands = [i for i in ids if i and ":" in i and not i.startswith(MODEL_ID) and not any(b in i.lower() for b in bad)]
    for pref in ("qwen3.5", "qwen3", "gemma", "llama", "mistral", "gpt-oss"):
        for i in cands:
            if i.lower().startswith(pref):
                return i
    return cands[0] if cands else None


# ── sync ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not KEY:
        sys.exit(f"no OPENWEBUI_API_KEY — create an admin API key in Open WebUI (Settings → Account) and put it in {ENV_FILE}")
    st, me = api("GET", "/api/v1/auths/")
    if st != 200:
        sys.exit(f"Open WebUI rejected the key ({st}): {me}")
    print(f"as {me.get('email')} ({me.get('role')}) at {URL}")
    if me.get("role") != "admin":
        sys.exit("the key must belong to an admin (knowledge + model are created public)")

    state = json.loads(STATE.read_text()) if STATE.exists() else {"files": {}}
    docs = documents()
    print(f"{len(docs)} document(s)")

    # knowledge base: the one the state file remembers, else by name — and the
    # list endpoint answers {"items": [...], "total": n}, not a bare list (the
    # first version read a bare list, saw nothing, and created a duplicate).
    kb = None
    if state.get("knowledge_id"):
        st, k = api("GET", f"/api/v1/knowledge/{state['knowledge_id']}")
        kb = k if st == 200 and k.get("id") else None
    if not kb:
        st, kbs = api("GET", "/api/v1/knowledge/")
        items = kbs if isinstance(kbs, list) else (kbs.get("items") or kbs.get("data") or [])
        same = [k for k in items if k.get("name") == KB_NAME]
        if len(same) > 1:
            print(f"WARNING: {len(same)} knowledge bases named {KB_NAME!r}; using the fullest, delete the others in Open WebUI")
        kb = max(same, key=lambda k: k.get("file_count", len(k.get("files") or []))) if same else None
    if not kb:
        if a.dry_run:
            print(f"[dry] would create knowledge base {KB_NAME!r}")
            return 0
        st, kb = api("POST", "/api/v1/knowledge/create",
                     {"name": KB_NAME, "description": f"How to use and operate nOS on {SHORT}: the knowledge-base pages, the recipe, the skill library, the live roadmap and model list. Synced by webui-kb-sync.py.",
                      "access_control": None})
        if st != 200:
            sys.exit(f"knowledge create failed ({st}): {kb}")
        print(f"created knowledge base {KB_NAME!r} ({kb['id']})")
    kid = kb["id"]
    state["knowledge_id"] = kid

    # files: add / replace / remove
    changed = 0
    for name, text in docs.items():
        sha = hashlib.sha256(text.encode()).hexdigest()
        prev = state["files"].get(name)
        if prev and prev.get("sha") == sha:
            continue
        if a.dry_run:
            print(f"[dry] {'replace' if prev else 'add'} {name}")
            continue
        if prev:
            api("POST", f"/api/v1/knowledge/{kid}/file/remove", {"file_id": prev["id"]})
            api("DELETE", f"/api/v1/files/{prev['id']}")
        raw, ctype = multipart({}, name, text.encode(), {"knowledge_id": kid} if False else None)
        st, f = api("POST", "/api/v1/files/", raw=raw, content_type=ctype)
        if st != 200:
            print(f"  upload {name} failed ({st}): {f}"); continue
        fid = f["id"]
        for _ in range(90):
            st, s = api("GET", f"/api/v1/files/{fid}/process/status")
            if s.get("status") in ("completed", "failed") or st == 404:
                break
            time.sleep(2)
        if s.get("status") == "failed":
            print(f"  processing {name} failed: {s.get('error')}"); continue
        st, r = api("POST", f"/api/v1/knowledge/{kid}/file/add", {"file_id": fid})
        if st != 200:
            print(f"  add {name} failed ({st}): {r}"); continue
        state["files"][name] = {"id": fid, "sha": sha}
        changed += 1
        print(f"  {'replaced' if prev else 'added'} {name}")
    for name in list(state["files"]):
        if name not in docs:
            if a.dry_run:
                print(f"[dry] remove {name}"); continue
            api("POST", f"/api/v1/knowledge/{kid}/file/remove", {"file_id": state['files'][name]['id']})
            api("DELETE", f"/api/v1/files/{state['files'][name]['id']}")
            del state["files"][name]; changed += 1
            print(f"  removed {name}")
    if not a.dry_run:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))

    # the assistant model
    st, models = api("GET", "/api/models")
    ids = [m.get("id") for m in (models.get("data", []) if isinstance(models, dict) else [])]
    base = BASE_MODEL or pick_base(ids)
    if not base:
        print("no base model visible to Open WebUI — is Ollama connected? (Admin → Settings → Connections)"); return 1
    st, kbfull = api("GET", f"/api/v1/knowledge/{kid}")
    body = {"id": MODEL_ID, "name": "nOS Assistant", "base_model_id": base,
            "meta": {"description": f"Ask how to use and operate nOS on {SHORT}. Answers from the knowledge base, the recipe, the skills, the live roadmap.",
                     "profile_image_url": "/static/favicon.png", "suggestion_prompts": [
                         {"content": "How do I log in for the first time and trust the certificate?"},
                         {"content": "How do I run two PHP versions side by side with my rootless Docker?"},
                         {"content": "What is on the roadmap right now and what does 'verified' mean?"},
                         {"content": "Jak si v notebooku pustím GPU a přečtu roadmap tabulku?"}],
                     "knowledge": [kbfull] if st == 200 else [], "capabilities": {"vision": False, "usage": True, "citations": True}},
            "params": {"system": SYSTEM_PROMPT}, "access_control": None, "is_active": True}
    if a.dry_run:
        print(f"[dry] would upsert model {MODEL_ID} on base {base}"); return 0
    st, cur = api("GET", f"/api/v1/models/model?id={MODEL_ID}")
    if st == 200 and cur:
        st, r = api("POST", f"/api/v1/models/model/update?id={MODEL_ID}", body)
        print(f"model {MODEL_ID}: {'updated' if st == 200 else f'update failed ({st}): {r}'} (base {base})")
    else:
        st, r = api("POST", "/api/v1/models/create", body)
        print(f"model {MODEL_ID}: {'created' if st == 200 else f'create failed ({st}): {r}'} (base {base})")
    print(f"done: {changed} document(s) changed, knowledge {kid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
