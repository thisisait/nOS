"""A task never hands a command's unbounded output to another through an environment variable.

Integration (ubuntu-24.04) failed 2026-10-16/17 on 'Upsert Tier-1 GDPR processing rows':
[Errno 7] Argument list too long - NOS_GDPR_JSON carried gdpr-records.py's whole output
(142724 bytes) and Linux caps one env string at 131072 (MAX_ARG_STRLEN). macOS passed, so only
the Linux lane saw it, and that job is continue-on-error. Output that grows with the estate goes on
stdin or in a file. The env values below that read a `.stdout` are bounded, each with its reason.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
BOUNDED = {
    "NOS_GDPR_VARS": "a dict of the choice-var NAMES gdpr-records --choice-vars lists, not records",
    "CAROOT": "one directory path from mkcert -CAROOT",
    "NOS_BODY": "one canonical app event body, signed per event",
}


def _env_stdout():
    files = [REPO / "main.yml", *map(Path, glob.glob(str(REPO / "tasks/**/*.yml"), recursive=True)),
             *map(Path, glob.glob(str(REPO / "roles/*/tasks/**/*.yml"), recursive=True))]
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue

        def walk(n):
            if isinstance(n, list):
                for x in n:
                    yield from walk(x)
            elif isinstance(n, dict):
                env = n.get("environment")
                if isinstance(env, dict):
                    for k, v in env.items():
                        if isinstance(v, str) and re.search(r"\.stdout\b", v):
                            yield f, n.get("name"), k
                for key in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
                    yield from walk(n.get(key))
        yield from walk(doc)


def test_only_bounded_output_rides_the_env():
    bad = [f"{f.relative_to(REPO)}: {name!r} sets {k} from a command's stdout"
           for f, name, k in _env_stdout() if k not in BOUNDED]
    assert not bad, "unbounded output in an env var dies past 131072 bytes on Linux; use stdin:\n" + "\n".join(bad)
