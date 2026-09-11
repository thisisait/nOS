#!/usr/bin/env python3
"""party-graph — the kmenová-data (master-data) view: a party and everything wired to it.

Visual control for the digest organ (data-graph-view). Walks the LIVE rowRef graph
around a party — its tax/address/contact facets, its repos/projects/invoices and
their children — and renders it as a mermaid diagram (the party in the centre). The
same {nodes, edges} shape (--dump json) a face Svelte-Flow view will consume later;
this is the zero-build, zero-dependency first surface so the connections are visible
today. Reader only — it never writes.

  tools/party-graph.py synthetic-mesto-lipno              # mermaid to stdout
  tools/party-graph.py synthetic-mesto-lipno --out g.md   # write a ```mermaid``` doc
  tools/party-graph.py synthetic-mesto-lipno --dump json  # {nodes, edges} for a shaper

Exit 0 ok · 2 KEAP unreadable.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from keap_api import proxy_header  # noqa: E402
import nos_digest  # noqa: E402

AGENT = "http://127.0.0.1:8091/agent/v1/tables"
TABLES_DIR = REPO / "state" / "keap-tables"


def _ro_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RO", "").strip()
    if tok:
        return tok
    return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RO"],
                          capture_output=True, text=True).stdout.strip()


def _reader(hdr):
    def read(table):
        req = urllib.request.Request(f"{AGENT}/{table}/rows", headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            raise
        return (d.get("data") or {}).get("rows") or d.get("rows") or []
    return read


def to_mermaid(graph: dict, party_slug: str) -> str:
    ids = {}   # node-id -> mermaid-safe id
    lines = ["graph LR"]
    for i, n in enumerate(graph["nodes"]):
        mid = f"n{i}"
        ids[n["id"]] = mid
        label = f'{n["label"]}<br/><small>{n["table"]}</small>'.replace('"', "'")
        shape = f'{mid}(["{label}"])' if n["slug"] == party_slug else f'{mid}["{label}"]'
        lines.append(f"  {shape}")
    for e in graph["edges"]:
        f, t = ids.get(e["from"]), ids.get(e["to"])
        if f and t:
            lines.append(f"  {f} -->|{e['column']}| {t}")
    center = ids.get(f"party:{party_slug}")
    if center:
        lines.append(f"  classDef master fill:#1a7f6e,stroke:#0d3f36,color:#fff,font-weight:bold;")
        lines.append(f"  class {center} master;")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("party", help="the party slug at the centre (kmenová data)")
    ap.add_argument("--out", help="write a ```mermaid``` markdown doc here")
    ap.add_argument("--dump", choices=["json"], help="emit {nodes, edges} instead of mermaid")
    args = ap.parse_args()

    hdr = {"Authorization": f"Bearer {_ro_token()}", **proxy_header()}
    try:
        graph = nos_digest.party_graph(args.party, _reader(hdr), TABLES_DIR)
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP unreadable ({exc})", file=sys.stderr)
        return 2

    if args.dump == "json":
        print(json.dumps(graph, indent=2, ensure_ascii=False))
        return 0

    mm = to_mermaid(graph, args.party)
    print(f"party graph: {len(graph['nodes'])} node(s), {len(graph['edges'])} edge(s)",
          file=sys.stderr)
    doc = f"# Kmenová data — {args.party}\n\n```mermaid\n{mm}\n```\n"
    if args.out:
        p = REPO / args.out if not pathlib.Path(args.out).is_absolute() else pathlib.Path(args.out)
        p.write_text(doc, encoding="utf-8")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
