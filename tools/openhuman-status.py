#!/usr/bin/env python3
"""Is OpenHuman on this Mac set up to stay on this Mac?

Reads every OpenHuman profile config (~/.openhuman/users/*/config.toml), the
app bundle, the process table and `lsof`, and reports profiles, privacy mode,
analytics, updater, model route, memory, MCP servers, install, running, egress
and a second Ollama — each as OK / RED / UNKNOWN with the source it read. Step 0 of roadmap row `openhuman`;
the recipe is docs/systems/openhuman/README.md.

Reads only. Exit 0 always. A source it cannot read is UNKNOWN, never green.
It does not need the app: with nothing installed every config line is UNKNOWN.

Usage:
    tools/openhuman-status.py [--json]
    tools/openhuman-status.py --selftest      # fixture configs, no app needed
Env (tests): NOS_OPENHUMAN_DIR (default ~/.openhuman), NOS_OPENHUMAN_APP,
NOS_OPENHUMAN_CASKROOM, NOS_OPENHUMAN_PROVIDER (ollama | claude-code, the declared one),
NOS_OPENHUMAN_OLLAMA_PREFIX (default /opt/homebrew: where the one Ollama lives).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

try:
    import tomllib
except ImportError:  # python < 3.11: every config line becomes UNKNOWN
    tomllib = None

OK, RED, UNKNOWN = "OK", "RED", "UNKNOWN"
HOME = pathlib.Path.home()
LOCAL_PREFIXES = ("ollama:", "lmstudio:", "mlx:", "omlx:", "local-openai:")
WORKLOADS = ("chat_provider", "reasoning_provider", "agentic_provider", "coding_provider")
# Background workloads: unset means cloud. learning_provider is retired after v0.64.10, so judged only when present.
BACKGROUND = ("memory_provider", "embeddings_provider")
OLLAMA_PORT = "11434"


def root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("NOS_OPENHUMAN_DIR", HOME / ".openhuman"))


def profiles(base: pathlib.Path) -> list[pathlib.Path]:
    """Every profile config: the app makes users/local-<host slug> on "login locally", not users/local."""
    found = sorted(base.glob("users/*/config.toml"))
    return found or ([base / "config.toml"] if (base / "config.toml").is_file() else [])


def config_path(base: pathlib.Path) -> pathlib.Path | None:
    """The loader's order: active_user.toml's user, then the pre-login `local` user."""
    user = None
    marker = base / "active_user.toml"
    if marker.is_file() and tomllib:
        try:
            user = tomllib.loads(marker.read_text()).get("user_id")
        except (OSError, tomllib.TOMLDecodeError):
            user = None
    for cand in ([base / "users" / str(user) / "config.toml"] if user else []) + [
            base / "users" / "local" / "config.toml", base / "config.toml"]:
        if cand.is_file():
            return cand
    return None


def _get(cfg: dict, dotted: str, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _loopback(url: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def judge_config(cfg: dict | None, src: str, provider: str | None = None) -> list[dict]:
    """Config lines. Missing keys are judged at OpenHuman's documented defaults.
    provider `claude-code` (NOS_OPENHUMAN_PROVIDER, the declared choice) expects privacy
    `standard` and allows `claude-code:` routes; any other cloud route stays RED."""
    claude = (provider or os.environ.get("NOS_OPENHUMAN_PROVIDER", "ollama")) == "claude-code"
    allowed = LOCAL_PREFIXES + (("claude-code:",) if claude else ())
    names = ("privacy mode", "analytics", "usage sharing", "core updater", "model route",
             "memory", "gitbooks MCP (remote)")
    if cfg is None:
        return [line(n, UNKNOWN, "no config.toml read", src) for n in names]
    out = []
    mode = _get(cfg, "privacy.mode", "standard")
    want = "standard" if claude else "local_only"
    out.append(line("privacy mode", OK if mode == want else RED, f"mode={mode} (declared: {want})", src))
    for name, key in (("analytics", "observability.analytics_enabled"),
                      ("usage sharing", "observability.share_usage_data")):
        val = _get(cfg, key, True)
        out.append(line(name, RED if val else OK, f"{key.split('.')[1]}={str(val).lower()}", src))
    upd = _get(cfg, "update.enabled", True)
    mut = _get(cfg, "update.rpc_mutations_enabled", True)
    out.append(line("core updater", OK if not upd and not mut else RED,
                    f"enabled={str(upd).lower()} rpc_mutations={str(mut).lower()}", src))
    routes = {w: _get(cfg, w) or "cloud" for w in WORKLOADS}
    cloud = [w for w, v in routes.items() if not str(v).startswith(allowed)]
    base_url = _get(cfg, "local_ai.base_url")
    remote_base = bool(base_url) and not _loopback(base_url)
    detail = f"chat={routes['chat_provider']} local_ai.base_url={base_url or 'default'}"
    out.append(line("model route", RED if cloud or remote_base else OK,
                    detail + (f"; on the cloud route: {', '.join(cloud)}" if cloud else ""), src))
    # memory.auto_save is the v0.64.10 schema switch (default on); conversations/recall are
    # not schema keys there (the app drops them on save), so they count only when present.
    auto = _get(cfg, "memory.auto_save", True)
    conv = auto or _get(cfg, "memory.conversations.enabled", False)
    recall = _get(cfg, "memory.recall.enabled", False)
    sources = _get(cfg, "memory.sources", []) or []
    bg = {w: _get(cfg, w) or "cloud" for w in BACKGROUND}
    if "learning_provider" in cfg:
        bg["learning_provider"] = cfg["learning_provider"] or "cloud"
    bg_cloud = [w for w, v in bg.items() if not str(v).startswith(LOCAL_PREFIXES)]
    emb = _get(cfg, "memory.embedding_provider", "cloud")
    if emb in ("cloud", "managed", "openhuman"):
        bg_cloud.append(f"memory.embedding_provider={emb}")
    out.append(line("memory", RED if conv or recall or sources or bg_cloud else OK,
                    f"auto_save={str(auto).lower()} conversations="
                    f"{str(conv).lower()} recall={str(recall).lower()} sources={len(sources)}"
                    + (f"; on the cloud route: {', '.join(bg_cloud)}" if bg_cloud else ""), src))
    gb = _get(cfg, "gitbooks.enabled", True)
    out.append(line("gitbooks MCP (remote)", RED if gb else OK, f"enabled={str(gb).lower()}", src))
    return out


def judge_mcp(base: pathlib.Path, cfg: dict | None, raw: str) -> dict:
    """Servers from config.toml and the mcp_clients SQLite store; RED if the RW token is in either."""
    names = [s.get("name", "?") for s in (_get(cfg or {}, "mcp_client.servers", []) or [])
             if isinstance(s, dict)]
    dbs = sorted(base.glob("**/mcp_clients.db"))
    srcs = []
    leaked = "KEAP_AGENT_TOKEN_RW" in raw
    for db in dbs:
        srcs.append(str(db))
        try:
            leaked |= b"KEAP_AGENT_TOKEN_RW" in db.read_bytes()
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for (tbl,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                cols = [c[1] for c in con.execute(f"PRAGMA table_info('{tbl}')")]
                if "server" in tbl and "name" in cols:
                    names += [r[0] for r in con.execute(f"SELECT name FROM '{tbl}'")]
            con.close()
        except (OSError, sqlite3.Error):
            return line("MCP servers", UNKNOWN, f"unreadable store {db}", str(db))
    src = ", ".join(srcs) or "config.toml [[mcp_client.servers]]"
    if leaked:
        return line("MCP servers", RED, "KEAP_AGENT_TOKEN_RW is named in the store — RO only", src)
    if cfg is None and not srcs:
        return line("MCP servers", UNKNOWN, "no config and no mcp_clients.db", src)
    return line("MCP servers", OK, ", ".join(sorted(set(names))) or "none registered", src)


def judge_lsof(text: str | None) -> dict:
    """`lsof -nP -i` rows for OpenHuman processes: any non-loopback peer or listener is RED."""
    src = "lsof -nP -iTCP -iUDP"
    if text is None:
        return line("egress", UNKNOWN, "lsof unavailable", src)
    rows = [r.split() for r in text.splitlines()[1:] if r.lower().startswith("openhuman")]
    if not rows:
        return line("egress", UNKNOWN, "no OpenHuman socket open — nothing observed", src)
    bad = []
    for r in rows:
        name = r[8] if len(r) > 8 else ""
        peer = name.split("->", 1)[1] if "->" in name else name
        if peer.startswith("*:") or not _loopback("x://" + peer):
            bad.append(f"{r[0]} {name}")
    if bad:
        return line("egress", RED, "non-loopback: " + "; ".join(sorted(set(bad))[:6]), src)
    return line("egress", OK, f"{len(rows)} socket(s), all loopback (a snapshot, not a window)", src)


def judge_ollama(comms: str | None, listeners: str | None, prefix: str, path_dirs: list[str]) -> dict:
    """One Ollama, under `prefix`, on :11434. Another binary, process or port is a second habitat."""
    src = f"ps -axo comm, lsof -iTCP -sTCP:LISTEN -c ollama, PATH, /Applications/Ollama.app; allowed {prefix}"
    if comms is None:
        return line("second Ollama", UNKNOWN, "ps unreadable", src)
    pre = prefix.rstrip("/") + "/"
    bins = {str(pathlib.Path(d) / "ollama") for d in path_dirs if (pathlib.Path(d) / "ollama").exists()}
    bins |= {c.strip() for c in comms.splitlines() if pathlib.Path(c.strip()).name.lower() == "ollama"}
    if pathlib.Path("/Applications/Ollama.app").exists():
        bins.add("/Applications/Ollama.app")
    bad = sorted(b for b in bins if not b.startswith(pre))
    ports = sorted({r.split()[8].rsplit(":", 1)[-1] for r in (listeners or "").splitlines()[1:] if len(r.split()) > 8})
    bad += [f"listening on :{p}" for p in ports if p != OLLAMA_PORT]
    seen = f"binaries: {', '.join(sorted(bins)) or 'none'}; ports: {', '.join(ports) or 'none'}"
    return line("second Ollama", RED if bad else OK, ("outside the one Ollama: " + "; ".join(bad) + " — ")
                * bool(bad) + seen, src)


def line(check: str, state: str, detail: str, source: str) -> dict:
    return {"check": check, "state": state, "detail": detail, "source": source}


def _run(argv: list[str]) -> str | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def collect() -> list[dict]:
    base = root()
    app = pathlib.Path(os.environ.get("NOS_OPENHUMAN_APP", "/Applications/OpenHuman.app"))
    cask = pathlib.Path(os.environ.get("NOS_OPENHUMAN_CASKROOM", "/opt/homebrew/Caskroom/openhuman"))
    out = [line("installed", OK, ("app present" if app.exists() else "no app")
                + (", via brew cask" if cask.is_dir() else ""), f"{app}, {cask}")]
    ps = _run(["ps", "-axo", "comm="])
    procs = [p for p in (ps or "").splitlines() if "openhuman" in p.lower()]
    out.append(line("running", UNKNOWN if ps is None else OK,
                    f"{len(procs)} process(es)" if ps is not None else "ps unreadable", "ps -axo comm"))
    paths = profiles(base)
    active = config_path(base)
    out.append(line("profiles", OK if paths else UNKNOWN,
                    (", ".join(p.parent.name for p in paths) or "no users/*/config.toml")
                    + (f"; active: {active.parent.name}" if active else ""), f"{base / 'users'}, {base / 'active_user.toml'}"))
    servers, raws = [], []
    for path in paths or [None]:
        cfg, raw, src = None, "", str(path or base / "users/local/config.toml")
        if path and tomllib:
            try:
                raw = path.read_text()
                cfg = tomllib.loads(raw)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                src += f" ({type(exc).__name__})"
        name = path.parent.name if path else "local"
        out += [dict(r, detail=f"[{name}] {r['detail']}") for r in judge_config(cfg, src)]
        servers += _get(cfg or {}, "mcp_client.servers", []) or []
        raws.append(raw)
    cfg = {"mcp_client": {"servers": servers}} if any(raws) else None
    raw = "\n".join(raws)
    out.append(line("desktop updater", UNKNOWN if app.exists() else OK,
                    "Tauri updater active, no documented switch — watch egress to github.com"
                    if app.exists() else "no app", "upstream tauri.conf.json plugins.updater"))
    out.append(judge_mcp(base, cfg, raw))
    out.append(judge_lsof(_run(["lsof", "-nP", "-iTCP", "-iUDP"]) if procs else ""))
    out.append(judge_ollama(_run(["ps", "-axo", "comm="]),
                            _run(["lsof", "-nP", "-a", "-iTCP", "-sTCP:LISTEN", "-c", "ollama"]),
                            os.environ.get("NOS_OPENHUMAN_OLLAMA_PREFIX", "/opt/homebrew"),
                            os.environ.get("PATH", "").split(os.pathsep)))
    return out


def selftest() -> None:
    good = """memory_provider = "ollama:hermes3:8b"\nembeddings_provider = "ollama:nomic-embed-text"
chat_provider = "ollama:hermes3:8b"\nreasoning_provider = "ollama:hermes3:8b"
agentic_provider = "ollama:hermes3:8b"\ncoding_provider = "ollama:hermes3:8b"
[privacy]\nmode = "local_only"\n[observability]\nanalytics_enabled = false\nshare_usage_data = false
[update]\nenabled = false\nrpc_mutations_enabled = false\n[gitbooks]\nenabled = false
[local_ai]\nbase_url = "http://127.0.0.1:11434"\n[memory]\nauto_save = false\nembedding_provider = "ollama"\n"""
    states = lambda cfg: {r["check"]: r["state"] for r in judge_config(cfg, "fixture")}  # noqa: E731
    states_detail = lambda cfg: next(r["detail"] for r in judge_config(cfg, "f") if r["check"] == "memory")  # noqa: E731
    assert set(states(tomllib.loads(good)).values()) == {OK}, states(tomllib.loads(good))
    assert set(states({}).values()) == {RED}, states({})          # documented defaults
    assert set(states(None).values()) == {UNKNOWN}
    cc = tomllib.loads(good.replace("ollama:hermes3:8b", "claude-code:sonnet").replace('"local_only"', '"standard"'))
    by = lambda p: {r["check"]: r["state"] for r in judge_config(cc, "f", p)}  # noqa: E731
    assert by("claude-code")["model route"] == OK and by("claude-code")["privacy mode"] == OK
    assert by("ollama")["model route"] == RED and by("ollama")["privacy mode"] == RED
    assert judge_lsof("COMMAND PID\nOpenHuman 1 u 3u IPv4 0 0t0 TCP 127.0.0.1:5->127.0.0.1:11434 (ESTABLISHED)")["state"] == OK
    assert judge_lsof("COMMAND PID\nOpenHuman 1 u 3u IPv4 0 0t0 TCP 10.0.0.2:5->140.82.112.3:443 (ESTABLISHED)")["state"] == RED
    assert judge_lsof("COMMAND PID\nopenhuman 1 u 3u IPv4 0 0t0 TCP *:7788 (LISTEN)")["state"] == RED
    assert judge_lsof(None)["state"] == UNKNOWN and judge_lsof("")["state"] == UNKNOWN
    vendor = tomllib.loads(good.replace('embeddings_provider = "ollama:nomic-embed-text"', 'embeddings_provider = "cloud"'))
    assert "embeddings_provider" in states_detail(vendor)
    assert states(tomllib.loads(good.replace("auto_save = false", "auto_save = true")))["memory"] == RED
    assert states(tomllib.loads(good + "[memory.recall]\nenabled = true\n"))["memory"] == RED
    lis = "COMMAND PID USER FD TYPE DEVICE SIZE NODE NAME\nollama 1 u 3u IPv4 0 0t0 TCP 127.0.0.1:{} (LISTEN)"
    assert judge_ollama("/opt/homebrew/bin/ollama\n", lis.format(11434), "/opt/homebrew", [])["state"] == OK
    assert judge_ollama("/usr/local/bin/ollama\n", "", "/opt/homebrew", [])["state"] == RED
    assert judge_ollama("/opt/homebrew/bin/ollama\n", lis.format(11435), "/opt/homebrew", [])["state"] == RED
    assert judge_ollama(None, None, "/opt/homebrew", [])["state"] == UNKNOWN
    with tempfile.TemporaryDirectory() as d:
        base = pathlib.Path(d)
        assert config_path(base) is None
        (base / "users/local").mkdir(parents=True)
        (base / "users/local/config.toml").write_text(good)
        assert config_path(base) == base / "users/local/config.toml"
        assert judge_mcp(base, {}, 'env = { KEAP_AGENT_TOKEN_RW = "x" }')["state"] == RED
        assert judge_mcp(base, None, "")["state"] == UNKNOWN
    print("selftest ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        if tomllib is None:
            print("selftest skipped: no tomllib (python < 3.11)")
            return 0
        selftest()
        return 0
    rows = collect()
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['state']:<8} {r['check']:<22} {r['detail']}  [{r['source']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
