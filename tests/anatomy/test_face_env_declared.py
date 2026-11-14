"""Every env var the face server reads is declared in src/env.ts.

SvelteKit 3 hands the server only variables DECLARED in `src/env.ts`; an undeclared `env.X` reads as undefined
whatever the container sets. Measured 2026-11-14 on the kit-3 branch: FACE_EDGE_TOKEN undeclared, so
hooks.server.ts took its "no token configured: trust is implicit" branch, a caller without the edge token got
200 and its forged X-Authentik-Username was rendered into the page. Build, check and vitest were all green.
This reads the source, not prose: every `env.NAME` / `env['NAME']` in a file that imports SvelteKit's env
module must have a key in env.ts. `process.env.X` (node, not gated by kit) and `import.meta.env.X` are not reads
of that module and are skipped.
"""
from __future__ import annotations

import re
from pathlib import Path

FACE = Path(__file__).resolve().parents[2] / "files" / "anatomy" / "face"
ENV_TS = FACE / "src" / "env.ts"
IMPORTS_ENV = re.compile(r"""from\s+['"](\$env/[^'"]+|\$app/env[^'"]*)['"]""")
READ = re.compile(r"""(?<![\w.])env(?:\.([A-Z][A-Z0-9_]*)|\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\])""")


def declared() -> set[str]:
    text = ENV_TS.read_text(encoding="utf-8")
    block = text[text.index("defineEnvVars(") :]
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*:", block, re.M))


def reads() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in sorted((FACE / "src").rglob("*")):
        if f.suffix not in (".ts", ".js", ".svelte") or f.name.endswith((".test.ts", ".spec.ts")) or f == ENV_TS:
            continue
        text = f.read_text(encoding="utf-8")
        if not IMPORTS_ENV.search(text):
            continue
        for m in READ.finditer(text):
            name = m.group(1) or m.group(2)
            out.setdefault(name, []).append(str(f.relative_to(FACE)))
    return out


def test_env_ts_exists_and_declares_the_edge_token():
    assert ENV_TS.is_file(), "src/env.ts is gone: kit 3 would hand the server no variable at all"
    assert "FACE_EDGE_TOKEN" in declared(), "FACE_EDGE_TOKEN undeclared: hooks.server.ts would trust every caller"


def test_every_server_env_read_is_declared():
    found = reads()
    assert found, "no env reads found: the scan is broken, not the face"
    missing = {k: v for k, v in found.items() if k not in declared()}
    assert not missing, (
        f"read but not declared in src/env.ts (kit 3 hands the server undefined for these): {missing}. "
        "Add each name to defineEnvVars in files/anatomy/face/src/env.ts."
    )
