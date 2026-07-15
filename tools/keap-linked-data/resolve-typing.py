#!/usr/bin/env python3
"""keap-linked-data — typing-first slice of the KEAP external-enrichment epic.

Resolve each KEAP concept node to a Wikidata QID with a DISAMBIGUATION step
(not naive top-hit — the 2026-07-15 feasibility spike showed top-hit is ~40%
noisy, homonym-trapped: journals/plays/insect-genera win on exact label), then
pull P31 (instance-of) and bucket it into a KEAP render type + a schema.org-ish
class. Emits a reviewable artifact `qid-typing.json`; nothing lands in the
canonical/DB until the operator reviews quality.

Disambiguation is cheap: `wbsearchentities` already returns each candidate's
`description` (effectively a type gloss — "scientific journal" vs "branch of
mathematics"), so we score top-N candidates by description allow/deny keywords +
label match + lexical overlap with our node description — no per-candidate P31
fetch. P31 is fetched only for the FINAL chosen QIDs (batched) to produce typing.

Read-only against public Wikidata. Responses cached to --cache for resumability.
Design + spike: docs/roadmap.md (KEAP node metadata + external dataset linkage).

Usage:
  python3 resolve-typing.py --graph graph.json --out qid-typing.json [--limit N]
  # graph.json = GET http://127.0.0.1:8091/api/graph (nodes[].{id,name,level,description})
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request, urllib.parse
from collections import Counter

WD = "https://www.wikidata.org/w/api.php"
UA = "KEAP-enrichment/1.0 (research; pazny.develop@gmail.com)"

# --- type scoring on the candidate's Wikidata description (the cheap gloss) ---
DENY = re.compile(r"\b(journal|article|paper|play|film|movie|album|song|single|"
                  r"band|video game|novel|book|manga|anime|episode|series|"
                  r"genus|species|taxon|family of|order of|surname|given name|"
                  r"disambiguation|company|enterprise|brand|website|magazine|"
                  r"footballer|actor|actress|musician|painter|singer|writer)\b", re.I)
ALLOW = re.compile(r"\b(discipline|science|branch of|field of|area of|study of|"
                   r"subfield|theory|law of|principle|hypothesis|model|paradigm|"
                   r"process|phenomen|reaction|interaction|mechanism|method|"
                   r"technique|concept|notion|physical quantity|property|constant|"
                   r"class of|type of|form of|system of|study|analysis)\b", re.I)

# --- P31 types that mean "this is a specific publication/artwork/media instance",
#     never an abstract concept — a homonym trap that beat the label match. Reject. ---
REJECT_P31 = re.compile(r"\barticle\b|thesis|dissertation|preprint|painting|sculpture|"
                        r"comic|\bchapter\b|clinical trial|\bfilm\b|\balbum\b|\bsong\b|"
                        r"\bnovel\b|manga|anime|\bepisode\b|\bplay\b|magazine|newspaper|"
                        r"\bwebsite\b|video game|\bband\b|musical work|literary work|"
                        r"\bmovie\b|television series|photograph|drawing|poem\b|"
                        r"\bpatent\b|version, edition|scientific publication", re.I)

# --- P31 label -> KEAP render bucket (primary facet) + schema.org-ish class ---
BUCKETS = [  # (regex on P31 english label, keap_bucket, schema_type)
    (r"academic discipline|branch of|field of|\bscience\b|study of|subfield|specialty|academic major", "discipline", "Intangible"),
    (r"theory|\blaw\b|principle|hypothesis|paradigm|\bmodel\b|\beffect\b|conjecture|theorem", "theory", "Intangible"),
    (r"process|phenomen|reaction|interaction|mechanism|transition|\bmotion\b|\bcycle\b|economic activity|industry|human activity|\bactivity\b|\bhobby\b|human impact|environmental issue", "process", "Intangible"),
    (r"physical quantity|\bproperty\b|constant|\bunit\b|dimension|\bmeasure\b|form of energy", "quantity", "Intangible"),
    (r"chemical|compound|\belement\b|\bparticle\b|\bmaterial\b|substance|mineral|molecule|\bions?\b", "substance", "ChemicalSubstance"),
    (r"taxon|species|genus|organism|\bfamily\b|bacteri|\bplant\b|\banimal\b", "organism", "Taxon"),
    (r"human being|^human$|\bperson\b", "person", "Person"),
    (r"\bevent\b|\bwar\b|period|\bera\b|epoch|revolution|\bmovement\b|battle", "event", "Event"),
    (r"technolog|device|machine|\btool\b|software|algorithm|instrument|equipment|technique|\bcraft\b|\btrade\b|\bskill\b|profession|occupation", "technology", "Product"),
    (r"geograph|location|region|country|\bcity\b|body of water|mountain|\bplace\b|continent|settlement", "place", "Place"),
    (r"\bwork\b|document|\bbook\b|standard|framework|\blanguage\b", "work", "CreativeWork"),
]

SEM_W = 4.5  # weight of the semantic (embedding cosine) term in candidate scoring


def search_key(name):
    """Cache key for a node's wbsearchentities call — MUST match http_json()."""
    return urllib.parse.urlencode(sorted({
        "action": "wbsearchentities", "search": name, "language": "en",
        "format": "json", "limit": "6"}.items()))


def _normalize(v):
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def embed_ollama(texts, model, url, timeout=300):
    body = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/embed", data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    return [_normalize(e) for e in out["embeddings"]]


def build_semantic(nodes, cache, vectors_path, model, url, chunk=64):
    """{node_id: {qid: cosine}} — semantic closeness of our node's embedding to
    each candidate's Wikidata description gloss (embedded in the SAME nomic space).
    Kills wrong-sense label matches (Maritime->'region of Togo'). Pure-python
    cosine (768-dim dot) — no numpy dependency."""
    vres = json.load(open(vectors_path))
    vres = vres.get("data", vres)
    nv = {it["id"]: _normalize(it["vector"]) for it in vres.get("vectors", [])}
    cand, descs = {}, set()
    for n in nodes:
        d = cache.get(search_key(n["name"]))
        if not d:
            continue
        lst = [(h["id"], h.get("description", "")) for h in d.get("search", [])[:6]]
        cand[n["id"]] = lst
        descs.update(ds for _, ds in lst if ds)
    descs = sorted(descs)
    print(f"  semantic: embedding {len(descs)} unique candidate glosses...", file=sys.stderr)
    dvec = {}
    for i in range(0, len(descs), chunk):
        part = descs[i:i + chunk]
        embs = embed_ollama(part, model, url)
        for t, e in zip(part, embs):
            dvec[t] = e
    sem = {}
    for nid, lst in cand.items():
        base = nv.get(nid)
        if base is None:
            continue
        sem[nid] = {qid: _dot(base, dvec[ds]) for qid, ds in lst if ds in dvec}
    return sem


def http_json(params, cache, timeout=25, retries=3):
    key = urllib.parse.urlencode(sorted(params.items()))
    if key in cache:
        return cache[key]
    url = WD + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode())
            cache[key] = out
            time.sleep(0.12)
            return out
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def tokens(s):
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


def score_candidate(node_name, node_desc, cand):
    """Higher = better. cand from wbsearchentities."""
    label = cand.get("label", "")
    desc = cand.get("description", "")
    s = 0.0
    if label.strip().lower() == node_name.strip().lower():
        s += 3.0
    elif node_name.strip().lower() in label.strip().lower() or label.strip().lower() in node_name.strip().lower():
        s += 1.0
    if DENY.search(desc):
        s -= 4.0
    if ALLOW.search(desc):
        s += 2.0
    # lexical overlap between our description and the candidate gloss
    ov = tokens(node_desc) & tokens(desc)
    s += min(len(ov), 4) * 0.4
    return s, label, desc


def resolve(nodes, cache, limit=None, sem=None):
    picked = {}  # node_id -> {qid,label,desc,score,conf}
    todo = nodes[:limit] if limit else nodes
    for i, n in enumerate(todo):
        name = n["name"]
        d = http_json({"action": "wbsearchentities", "search": name,
                        "language": "en", "format": "json", "limit": "6"}, cache)
        hits = d.get("search", [])
        if not hits:
            picked[n["id"]] = {"qid": None, "conf": "none", "reason": "no-hit"}
            continue
        nsem = sem.get(n["id"], {}) if sem else {}
        scored = []
        for h in hits:
            s, label, desc = score_candidate(name, n.get("description", ""), h)
            s += SEM_W * nsem.get(h["id"], 0.0)
            scored.append((s, label, desc, h["id"]))
        scored.sort(key=lambda t: t[0], reverse=True)
        best_s, best_label, best_desc, best_qid = scored[0]
        cos = nsem.get(best_qid, None)
        exact = best_label.strip().lower() == name.strip().lower()
        allow = bool(ALLOW.search(best_desc)) and not DENY.search(best_desc)
        # a strong semantic mismatch vetoes even an exact label (wrong-sense trap)
        if sem and cos is not None and cos < 0.45:
            conf = "none"; best_qid = None; reason = "sem-veto"
        elif best_s < 0:
            conf = "none"; best_qid = None; reason = "all-denied"
        elif (exact or (sem and cos is not None and cos >= 0.62)) and allow:
            conf = "high"; reason = "exact/sem+type"
        elif exact or (allow and best_s >= 2.0):
            conf = "med"; reason = "exact|type+overlap"
        else:
            conf = "low"; reason = "weak"
        picked[n["id"]] = {"qid": best_qid, "label": best_label, "desc": best_desc,
                           "score": round(best_s, 2), "conf": conf, "reason": reason,
                           "cos": round(cos, 3) if cos is not None else None}
        if (i + 1) % 100 == 0:
            print(f"  ...resolved {i+1}/{len(todo)} (cache {len(cache)})", file=sys.stderr)
    return picked


def batched(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def add_typing(picked, cache):
    """Fetch P31 for chosen QIDs (batched), then P31-target labels, then bucket."""
    qids = sorted({p["qid"] for p in picked.values() if p.get("qid")})
    p31_of = {}
    for chunk in batched(qids, 45):
        d = http_json({"action": "wbgetentities", "ids": "|".join(chunk),
                        "format": "json", "props": "claims"}, cache)
        for qid, ent in d.get("entities", {}).items():
            tgt = []
            for c in ent.get("claims", {}).get("P31", []):
                try:
                    tgt.append(c["mainsnak"]["datavalue"]["value"]["id"])
                except (KeyError, TypeError):
                    pass
            p31_of[qid] = tgt
    # label the P31 target qids
    tgt_ids = sorted({t for ts in p31_of.values() for t in ts})
    lbl = {}
    for chunk in batched(tgt_ids, 45):
        d = http_json({"action": "wbgetentities", "ids": "|".join(chunk),
                        "format": "json", "props": "labels", "languages": "en"}, cache)
        for qid, ent in d.get("entities", {}).items():
            lbl[qid] = ent.get("labels", {}).get("en", {}).get("value", "")
    # bucket each node
    for p in picked.values():
        q = p.get("qid")
        if not q:
            continue
        types = [(t, lbl.get(t, "")) for t in p31_of.get(q, [])]
        p["p31"] = types
        # P31 post-filter: a publication/artwork instance is a homonym trap that
        # slipped the search-description deny (paper without an abstract gloss) —
        # reject outright, the node simply carries no confident external identity.
        if any(REJECT_P31.search(tl) for _, tl in types):
            p["qid"] = None; p["conf"] = "none"; p["reason"] = "p31-reject"
            p.pop("keap_type", None); p.pop("schema_type", None)
            continue
        bucket = schema = None
        for _, tlabel in types:
            for rx, b, sch in BUCKETS:
                if re.search(rx, tlabel, re.I):
                    bucket, schema = b, sch
                    break
            if bucket:
                break
        p["keap_type"] = bucket or "concept"
        p["schema_type"] = schema or "DefinedTerm"
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="graph.json")
    ap.add_argument("--out", default="qid-typing.json")
    ap.add_argument("--cache", default="wd-cache.json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--vectors", default=None,
                    help="node-embeddings json (GET /agent/v1/features/vectors) — enables semantic disambiguation")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--model", default="nomic-embed-text")
    ap.add_argument("--post", default=None,
                    help="KEAP API base (e.g. http://127.0.0.1:8091) — POST high+med tier to node_metadata")
    ap.add_argument("--token", default=os.environ.get("KEAP_AGENT_TOKEN_RW", ""),
                    help="RW agent bearer token for --post")
    a = ap.parse_args()

    g = json.load(open(a.graph))
    nodes = g.get("data", g)["nodes"]
    cache = json.load(open(a.cache)) if os.path.exists(a.cache) else {}
    print(f"resolving {len(nodes)} nodes (cache {len(cache)})...", file=sys.stderr)
    sem = None
    if a.vectors:
        sem_cache = a.vectors + ".sem.json"
        if os.path.exists(sem_cache):
            sem = json.load(open(sem_cache))
            print(f"  semantic: loaded {len(sem)} cached node-cosine maps", file=sys.stderr)
        else:
            # search cache must be warm first (semantic reads cached candidates)
            for n in (nodes[:a.limit] if a.limit else nodes):
                http_json({"action": "wbsearchentities", "search": n["name"],
                            "language": "en", "format": "json", "limit": "6"}, cache)
            sem = build_semantic(nodes[:a.limit] if a.limit else nodes, cache,
                                 a.vectors, a.model, a.ollama)
            json.dump(sem, open(sem_cache, "w"))
    try:
        picked = resolve(nodes, cache, a.limit, sem)
        add_typing(picked, cache)
    finally:
        json.dump(cache, open(a.cache, "w"))

    # attach node meta for the review artifact
    by_id = {n["id"]: n for n in nodes}
    rows = []
    for nid, p in picked.items():
        n = by_id[nid]
        rows.append({"id": nid, "name": n["name"], "level": n["level"], **p})
    rows.sort(key=lambda r: r["id"])
    json.dump({"count": len(rows), "nodes": rows}, open(a.out, "w"), indent=1, ensure_ascii=False)

    # stats
    conf = Counter(r["conf"] for r in rows)
    by_lvl = {}
    for r in rows:
        by_lvl.setdefault(r["level"], Counter())[r["conf"]] += 1
    typ = Counter(r.get("keap_type") for r in rows if r.get("qid"))
    N = len(rows)
    usable = conf["high"] + conf["med"]
    print(f"\n=== typing resolution over {N} nodes ===")
    for c in ("high", "med", "low", "none"):
        print(f"  {c:5}: {conf[c]:4}  ({100*conf[c]//N}%)")
    print(f"  USABLE (high+med): {usable} ({100*usable//N}%)")
    print("\n=== confidence by level ===")
    for lvl in sorted(by_lvl):
        c = by_lvl[lvl]
        tot = sum(c.values())
        print(f"  L{lvl}: {tot:4} nodes  high+med={c['high']+c['med']:4} ({100*(c['high']+c['med'])//tot}%)")
    print("\n=== KEAP type buckets (resolved nodes) ===")
    for t, n in typ.most_common():
        print(f"  {t:12}: {n}")
    print(f"\nwrote {a.out}")

    # optional: POST the high+med tier to the KEAP container (node_metadata layer)
    if a.post:
        payload = [{"node_id": r["id"], "qid": r["qid"], "keap_type": r.get("keap_type"),
                    "schema_type": r.get("schema_type"), "wd_label": r.get("label"),
                    "confidence": r["conf"]}
                   for r in rows if r["conf"] in ("high", "med") and r.get("qid")]
        if not a.token:
            print("keap-linked-data: --post needs --token (KEAP_AGENT_TOKEN_RW)", file=sys.stderr)
            return 1
        req = urllib.request.Request(a.post.rstrip("/") + "/agent/v1/metadata",
            data=json.dumps({"model": "wikidata", "metadata": payload}).encode(),
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {a.token}",
                     "x-keap-agent": "keap-linked-data"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
        out = out.get("data", out)
        print(f"posted {len(payload)} high+med rows -> upserted {out.get('upserted', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
