"""A host-side tool runs Wing's PHP through the resolved CLI, never a bare `php`.

On macOS `php` is Homebrew's; on Linux there is no `php` at all: Wing's PHP is
`frankenphp php-cli`, reached through the `nos-php` shim pazny.wing installs (and
`wing_php_cli` in default.config.yml). spark1 (2026-10-22): every e2e tester
provisioning died on "No such file or directory: 'php'" in wing_token_admin.py,
so all four RBAC tiers skipped.

The order everywhere: WING_PHP_CLI, else `php` on PATH, else `nos-php`. A shell script may keep
its `php ...` lines when it defines that resolution as a `php()` function first.
PHP run INSIDE a container (docker exec <svc> php ...) is that image's PHP and out of scope.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [*ROOT.glob("tools/*.sh"), *ROOT.glob("tools/*.py"), *ROOT.glob("tests/e2e/lib/*.py")]
# Container PHP: the argv goes to `docker exec`, not to the host.
CONTAINER = {"tools/tls-uptake.py": "occ / php -r run in the service container via _exec(container, argv)"}
SH_BARE = re.compile(r"^\s*(?:[A-Z_]+=\S+\s+)*php\s")       # a shell command whose word is php
SH_SHIM = re.compile(r"^\s*php\(\)\s*\{")                    # php() { WING_PHP_CLI / nos-php ... }
PY_BARE = re.compile(r"""(?:[\[(]|^)\s*["']php["']\s*,""")    # an argv list starting with "php" (or its first line)


def test_no_host_tool_runs_a_bare_php():
    hits = []
    for f in SOURCES:
        rel = str(f.relative_to(ROOT))
        if rel in CONTAINER:
            continue
        pat = SH_BARE if f.suffix == ".sh" else PY_BARE
        lines = f.read_text(encoding="utf-8").splitlines()
        shim = next((i for i, x in enumerate(lines) if SH_SHIM.search(x) and "nos-php" in x and "WING_PHP_CLI" in x), None)
        for n, line in enumerate(lines, 1):
            if f.suffix == ".sh" and shim is not None and n - 1 > shim:
                continue
            if not line.lstrip().startswith("#") and pat.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:90]}")
    assert not hits, "bare `php` on the host (Linux has none; resolve WING_PHP_CLI/php/nos-php):\n" + "\n".join(hits)


def test_the_exemptions_still_exist():
    gone = [p for p in CONTAINER if not (ROOT / p).exists()]
    assert not gone, f"exempted files no longer exist: {gone}"
