"""A PR a workflow opens must trigger CI: it is pushed and opened with a GitHub App token.

GitHub starts no workflow for events made with GITHUB_TOKEN, so the nightly frankenphp re-pin
PR (11-04) showed no checks. Every job that runs `gh pr create` mints an App token with
actions/create-github-app-token pinned by sha, and checkout + gh use it. Parsed, not grepped.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.y*ml"))
APP_TOKEN = re.compile(r"actions/create-github-app-token@[0-9a-f]{40}")


def _pr_jobs():
    for wf in WORKFLOWS:
        for name, job in (yaml.safe_load(wf.read_text(encoding="utf-8")).get("jobs") or {}).items():
            steps = job.get("steps") or []
            if any("gh pr create" in str(s.get("run", "")) for s in steps):
                yield f"{wf.name}:{name}", steps


def test_bot_prs_use_an_app_token() -> None:
    for where, steps in _pr_jobs():
        mint = [s for s in steps if APP_TOKEN.fullmatch(str(s.get("uses", "")))]
        assert len(mint) == 1 and mint[0].get("id"), f"{where}: no sha-pinned app-token step with an id"
        ref = f"${{{{ steps.{mint[0]['id']}.outputs.token }}}}"
        for s in steps:
            if str(s.get("uses", "")).startswith("actions/checkout@"):
                assert (s.get("with") or {}).get("token") == ref, f"{where}: checkout pushes with GITHUB_TOKEN"
            if "gh pr create" in str(s.get("run", "")):
                assert (s.get("env") or {}).get("GH_TOKEN") == ref, f"{where}: gh pr create uses GITHUB_TOKEN"
