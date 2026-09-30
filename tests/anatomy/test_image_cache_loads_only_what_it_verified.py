"""The image cache saves once, loads only a tar whose checksum matches its lock.

Runs tools/nos-image-cache.py against a fake `docker` that keeps its image
store in a JSON file, so seed/load/verify are exercised end to end: a pruned
daemon gets its images back from the cache, a present image is not reloaded,
and a tampered tar is refused instead of fed to the daemon.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/nos-image-cache.py"

FAKE = r'''#!/usr/bin/env python3
import json, sys, os
st = os.environ["FAKE_STATE"]; s = json.load(open(st))
a = sys.argv[1:]
def save(): json.dump(s, open(st, "w"))
def digests(ref, i): return [ref] if "@" in ref else [ref.rsplit(":", 1)[0] + "@sha256:" + i[7:]]
if a[:2] == ["image", "ls"]:
    for ref, i in s["images"].items():
        if "@" in ref: print(f"{i}|{ref.split('@')[0]}|<none>")
        else: repo, tag = ref.rsplit(":", 1); print(f"{i}|{repo}|{tag}")
    print("sha256:dangling|<none>|<none>")
elif a[:2] == ["image", "inspect"]:
    x = a[-1]
    if x == "sha256:dangling": print(x + "|[]"); sys.exit(0)
    hit = [(r, i) for r, i in s["images"].items() if x in (r, i) and not (r.startswith("<anon>") and x == r)]
    if not hit: sys.exit(1)
    r, i = hit[0]; print(i + "|" + json.dumps(digests(r, i)))
elif a[0] == "save":
    ref = a[-1]; open(a[2], "w").write(json.dumps({"ref": ref, "id": s["images"][ref]}))
elif a[0] == "load":
    d = json.load(open(a[2]))
    # like the real daemon: a digest-pinned image comes back ANONYMOUS
    key = ("<anon>" + d["id"]) if "@" in d["ref"] else d["ref"]
    s["images"][key] = d["id"]; s["loads"] = s.get("loads", 0) + 1; save()
'''


def _env(tmp: Path, images: dict) -> dict:
    fake = tmp / "docker"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    state = tmp / "state.json"
    state.write_text(json.dumps({"images": images}))
    return {**os.environ, "NOS_DOCKER_BIN": str(fake), "FAKE_STATE": str(state)}


def _run(env: dict, root: Path, verb: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--root", str(root), verb],
                          capture_output=True, text=True, env=env)


def _state(env: dict) -> dict:
    return json.loads(Path(env["FAKE_STATE"]).read_text())


def test_a_pruned_daemon_gets_its_images_back(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    imgs = {"grafana/grafana:12": "sha256:aaa", "ghcr.io/x/y:1": "sha256:bbb",
            "grafana/mcp-grafana@sha256:ddd": "sha256:ddd"}          # digest-only, no tag
    env = _env(tmp_path, imgs)
    assert _run(env, root, "seed").returncode == 0
    lock = json.loads((root / "images/images.lock.json").read_text())
    assert set(lock["images"]) == set(imgs), "a digest-only image was skipped, or a dangling one taken"
    assert all(len(e["sha256"]) == 64 for e in lock["images"].values())

    Path(env["FAKE_STATE"]).write_text(json.dumps({"images": {}}))       # the leave prunes everything
    r = _run(env, root, "load")
    assert r.returncode == 0, r.stderr
    after = _state(env)["images"]
    assert after["grafana/grafana:12"] == "sha256:aaa" and after["ghcr.io/x/y:1"] == "sha256:bbb"
    assert "sha256:ddd" in after.values(), "the digest-pinned image was not loaded"
    assert "REFUSED" not in r.stderr, r.stderr
    assert _run(env, root, "load").stdout.strip().endswith("0 refused"), "a second load re-read an anonymous image"


def test_a_present_image_is_not_reloaded_and_seed_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    env = _env(tmp_path, {"redis:7": "sha256:ccc"})
    _run(env, root, "seed")
    assert "1 already cached" in _run(env, root, "seed").stdout
    assert _run(env, root, "load").returncode == 0
    assert _state(env).get("loads", 0) == 0


def test_a_tampered_tar_is_refused_not_loaded(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    env = _env(tmp_path, {"redis:7": "sha256:ccc"})
    _run(env, root, "seed")
    tar = next((root / "images").glob("*.tar"))
    tar.write_text(json.dumps({"ref": "redis:7", "id": "sha256:evil"}))
    Path(env["FAKE_STATE"]).write_text(json.dumps({"images": {}}))
    r = _run(env, root, "load")
    assert r.returncode == 1 and "REFUSED redis:7" in r.stderr
    assert _state(env)["images"] == {}, "a tar that fails its checksum reached the daemon"
    assert _run(env, root, "verify").returncode == 1


def test_the_cache_sits_outside_everything_a_removal_takes() -> None:
    import jinja2, re, yaml
    cfg = (REPO / "default.config.yml").read_text(encoding="utf-8")
    expr = re.search(r'^artifact_cache_dir: "(.*)"$', cfg, re.M).group(1)
    removal = (REPO / "tasks/removal-set.yml").read_text(encoding="utf-8")
    src = yaml.safe_load(removal)
    uninstall = next(t for t in src if "_uninstall_source" in str(t.get("ansible.builtin.set_fact", {})))
    for home, root in (("/Users/u", "/Users/u/nos"), ("/Users/u", "/Volumes/SSD1TB/nOS/data")):
        cache = jinja2.Environment().from_string(expr).render(nos_data_root=root)
        env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
        ctx = {"nos_data_root": root, "ansible_facts": {"env": {"HOME": home}}, "homebrew_prefix": "/opt/homebrew"}
        for raw in uninstall["ansible.builtin.set_fact"]["_uninstall_source"]:
            path = env.from_string(raw).render(**ctx)
            assert not (cache == path or cache.startswith(path.rstrip("/") + "/")), (cache, path)
    assert "{ var: artifact_cache_dir, level: never," in removal


def test_converge_loads_before_the_first_compose_up() -> None:
    import yaml
    tasks = yaml.safe_load((REPO / "tasks/stacks/core-up.yml").read_text(encoding="utf-8"))
    names = [t.get("name", "") for t in tasks]
    assert names.index("[Core] Load cached images the daemon lacks") < names.index("[Core] Start INFRA stack (docker compose up -d)")
