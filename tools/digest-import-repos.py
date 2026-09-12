#!/usr/bin/env python3
"""digest-import-repos — the SECOND digest importer (git repos → software estate).

Proves the importer interface generalises off CSV: same nos_digest.run_importer
harness, a wholly different source. Walks a directory of repositories, reads each
one's git metadata + dependency manifests, and emits the repo → application →
package rowRef chain, with every repo OWNED by a party resolved against the live
party spine (party-resolver) — so a repo whose owner was already imported reuses
that party row instead of forking it (the cross-source dedup the CSV scaffold did
not exercise).

  tools/digest-import-repos.py state/fixtures/repos-fixture             # gate + print (no writes)
  tools/digest-import-repos.py state/fixtures/repos-fixture --absorb    # upsert into KEAP

Each repo is an immediate subdirectory carrying a `nos-repo.yml` sidecar
(owner{ico|name}, remote, head) + dependency manifests. The sidecar is the parse
stage's git-metadata source; a live run would read `git -C <dir>` instead — a
one-line swap in _repo_meta(). Owners that do not resolve to a KNOWN party go to
review (repos are not an authoritative party registry — they never mint a party).

DRY by default. --absorb upserts by slug, skipping present. Tear down with
tools/digest-teardown.py on the printed bundle. Exit 0 · 1 gate refused · 2 KEAP.

Manifests parsed (minimal): package.json (npm), requirements.txt (pypi), go.mod (go).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import absorb, build_party_index  # noqa: E402
import nos_digest  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"


def _slug(*parts: str) -> str:
    s = "-".join(str(p) for p in parts if p)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-+", "-", s)


# ── manifest parsers: name -> (version, ecosystem). Only parse stage code. ────
def _parse_package_json(text: str) -> list[tuple[str, str, str]]:
    data = json.loads(text)
    out = []
    for section in ("dependencies", "devDependencies"):
        for name, ver in (data.get(section) or {}).items():
            out.append((name, str(ver), "npm"))
    return out


def _parse_requirements_txt(text: str) -> list[tuple[str, str, str]]:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(?:[=<>!~]=+\s*([0-9][^\s;]*))?", line)
        if m:
            out.append((m.group(1), m.group(2) or "", "pypi"))
    return out


def _parse_go_mod(text: str) -> list[tuple[str, str, str]]:
    out, in_block = [], False
    for line in text.splitlines():
        line = line.split("//", 1)[0].strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        m = re.match(r"^(?:require\s+)?(\S+)\s+(v\S+)$", line)
        if m and (in_block or line.startswith("require ")):
            out.append((m.group(1), m.group(2), "go"))
    return out


_MANIFESTS = {"package.json": _parse_package_json,
              "requirements.txt": _parse_requirements_txt,
              "go.mod": _parse_go_mod}


class RepoImporter:
    """A directory of repos → repo/application/package rows, owners resolved to
    the shared party spine. Format knowledge only; the harness owns the gate."""

    name = "repos"
    version = "0.1.0"

    def __init__(self, source_id: str, party_index: dict, *, fixture_mode: bool = False):
        self.source_id = source_id
        self.party_index = party_index
        # fixture_mode lets a synthetic-range IČO (000001xx) resolve — the fixture
        # party spine uses them by rule (docs/idea/15). A real run leaves it False,
        # so a synthetic IČO in real repo metadata is refused as a data error.
        self.fixture_mode = fixture_mode
        self.skipped: list[str] = []

    def _repo_meta(self, repo_dir: pathlib.Path) -> dict | None:
        sidecar = repo_dir / "nos-repo.yml"
        if not sidecar.exists():
            return None   # a live run would read `git -C` here instead
        return yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}

    def parse(self, root) -> list[dict]:
        root = pathlib.Path(root)
        records = []
        for repo_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = self._repo_meta(repo_dir)
            if meta is None:
                self.skipped.append(f"{repo_dir.name}: no nos-repo.yml sidecar")
                continue
            apps = []
            for manifest in sorted(repo_dir.rglob("*")):
                if manifest.name not in _MANIFESTS:
                    continue
                try:
                    pkgs = _MANIFESTS[manifest.name](manifest.read_text(encoding="utf-8"))
                except (ValueError, OSError) as exc:
                    self.skipped.append(f"{repo_dir.name}/{manifest.name}: unparsable ({exc})")
                    continue
                apps.append({"path": str(manifest.parent.relative_to(repo_dir)),
                             "manifest": manifest.name, "packages": pkgs})
            records.append({"repo_name": repo_dir.name, "meta": meta, "apps": apps})
        return records

    def normalize(self, records: list[dict]) -> list[dict]:
        out = []
        for r in records:
            owner = r["meta"].get("owner") or {}
            ref = {"kind": "org", "ico": owner.get("ico"), "legal_name": owner.get("name")}
            res = nos_digest.resolve_party(ref, self.party_index, source_authoritative=False,
                                           fixture_mode=self.fixture_mode)
            if res["status"] != "resolved":
                self.skipped.append(
                    f"{r['repo_name']}: owner unresolved ({res['status']}: {res['reason']}) "
                    "— repos never mint a party, routed to review")
                continue
            r["owner_slug"] = res["slug"]
            r["owner_name"] = owner.get("name") or res["slug"]
            out.append(r)
        return out

    def compose(self, records: list[dict]) -> dict:
        parties: dict[str, dict] = {}
        repos, apps, packages = [], [], []
        for r in records:
            # party STUB so the bundle is self-contained (check_bundle resolves the
            # rowRef in-bundle); absorb skips it as already-present — the resolved
            # owner is never overwritten, only referenced. Same self-contained
            # discipline the Kolben fixture uses (party travels with its domain rows).
            parties.setdefault(r["owner_slug"], {
                "slug": r["owner_slug"], "legal_name": r["owner_name"],
                "party_kind": "org", "country": r["meta"].get("country", "CZ")})
            repo_slug = _slug("repo", r["owner_slug"], r["repo_name"])
            repos.append({"slug": repo_slug, "name": r["repo_name"], "party": r["owner_slug"],
                          "remote": r["meta"].get("remote", ""), "head_sha": r["meta"].get("head", "")})
            for a in r["apps"]:
                app_slug = _slug("app", repo_slug, a["path"] or "root")
                apps.append({"slug": app_slug, "name": f"{r['repo_name']}/{a['path'] or '.'}",
                             "repo": repo_slug, "path": a["path"], "archetype": a["manifest"]})
                for (pname, pver, eco) in a["packages"]:
                    packages.append({"slug": _slug("pkg", app_slug, eco, pname),
                                     "name": pname, "application": app_slug, "version": pver,
                                     "ecosystem": eco, "is_direct": "direct"})
        # dependency order: party -> repo -> application -> package
        return {"party": list(parties.values()), "repo": repos,
                "application": apps, "package": packages}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="a directory whose immediate subdirs are repos")
    ap.add_argument("--source-id", help="provenance source id (default: the dir name)")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default dry)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, dry)")
    ap.add_argument("--fixture-mode", action="store_true",
                    help="resolve synthetic-range IČOs (000001xx) — for the fixture spine only")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.is_absolute():
        root = REPO / root
    try:
        index = build_party_index()
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: cannot build party index from KEAP ({exc})", file=sys.stderr)
        return 2

    importer = RepoImporter(args.source_id or root.name, index, fixture_mode=args.fixture_mode)
    bundle, errors = nos_digest.run_importer(importer, str(root), TABLES_DIR)
    # the importer walks `root`; raw hash of the dir name is a weak provenance
    # anchor here (per-repo head_sha is the real one on each row's _prov content).

    for s in importer.skipped:
        print(f"skip {s}", file=sys.stderr)
    if errors:
        print("GATE REFUSED the bundle — nothing absorbed:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    n = sum(len(v) for v in bundle["deterministic"].values())
    print(f"gate OK: {n} row(s) across {len(bundle['deterministic'])} table(s)"
          f"{'  (DRY)' if not args.absorb else ''}", file=sys.stderr)

    if args.absorb:
        return absorb(bundle)
    text = yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True)
    out = args.out and (REPO / args.out if not pathlib.Path(args.out).is_absolute()
                        else pathlib.Path(args.out))
    out.write_text(text) if out else print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
