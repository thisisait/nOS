"""`contract-search` may find an endpoint; it may never reach one.

Measured 2026-08-30: qwen3:14b, asked how many security findings are open,
invented GET /api/v1/security/findings/open/count and 404'd. The answer —
GET /api/v1/remediation, with its query parameters — was already written in
files/anatomy/skills/contracts/wing.openapi.yml, which nothing read.

The tool that closes that gap is handed out with NO data scope, and that is
only safe while it stays incapable of data. Three things are pinned here:

  1. requiredScopes() names mcp.tool_use and nothing else — no wing.read, no
     bone.read, no keap.*. The scope list is the machine-readable half of the
     line the class docblock states in prose.
  2. The class cannot transport: no HTTP client, no PDO/Nette database, no
     socket call, and a constructor that takes a path and nothing else. Read
     out of the source, not out of the comment that describes it.
  3. Every path it returns EXISTS in the committed contract, byte for byte.
     That is the check that cannot be satisfied by editing this file: it
     compares the tool's output against the artifact, so a version that
     started synthesising plausible paths would fail it while every prose
     claim stayed true.

Plus the bug itself: the Czech sentence that produced the 404 must surface
`/api/v1/remediation` in the top five.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
TOOL = WING / "app/AgentKit/Tools/ContractSearchTool.php"
INDEX = WING / "app/AgentKit/StaticIndex.php"
AUTOLOAD = WING / "vendor/autoload.php"
CONTRACTS = REPO / "files/anatomy/skills/contracts"


def test_the_scope_list_names_no_data_scope() -> None:
    src = TOOL.read_text(encoding="utf-8")
    body = re.search(r"function requiredScopes\(\): array\s*\{(.+?)\}", src, re.S)
    assert body, "requiredScopes() not found — the tool must declare its scopes"
    granted = set(re.findall(r"'([a-z0-9_.\-]+)'", body.group(1)))
    assert granted == {"mcp.tool_use"}, (
        f"contract-search grants {sorted(granted)}. It reads two static files; "
        "any scope that gates live data means the tool grew a reach the whole "
        "design depends on it not having."
    )


def test_the_class_cannot_transport() -> None:
    src = TOOL.read_text(encoding="utf-8") + INDEX.read_text(encoding="utf-8")
    # Comments describe; code acts. Strip the prose before looking for reach.
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
    for banned in (
        "HttpClient", "GuzzleHttp", "curl_", "fsockopen", "stream_socket",
        "PDO", "Nette\\Database", "Explorer", "shell_exec", "proc_open",
        "exec(", "system(", "file_put_contents", "http://", "https://",
    ):
        assert banned not in code, (
            f"ContractSearchTool/StaticIndex mention `{banned}` in code. This tool "
            "returns static strings from committed files; a transport of any "
            "kind here is the feature the scope list says it does not have."
        )
    ctor = re.search(r"public function __construct\((.*?)\)", src, re.S)
    assert ctor and "repoRoot" in ctor.group(1) and "," not in ctor.group(1), (
        "the constructor takes exactly one argument, a repo path — anything "
        "else injected is something to call."
    )


PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\ContractSearchTool;
use App\AgentKit\Tools\ToolContext;

$tool = new ContractSearchTool(getenv('NOS_TEST_REPO_ROOT'));
$ctx = new ToolContext('sess-1', 'th', 'tr', 'sp', 'agent:jeff', 'tu');

$out = ['id' => $tool->id(), 'scopes' => $tool->requiredScopes()];
foreach ([
    'cz' => 'kolik je otevřených bezpečnostních nálezů',
    'en' => 'list open security findings',
    'miss' => 'xyzzy quux flibberty',
] as $k => $q) {
    $r = $tool->execute(['query' => $q], $ctx);
    $out[$k] = ['error' => $r->isError, 'content' => $r->content, 'meta' => $r->metadata];
}
$out['input_keys'] = array_keys($tool->schema()->inputSchema['properties'] ?? []);
echo json_encode($out);
"""


@pytest.fixture(scope="module")
def probe() -> dict:
    if not AUTOLOAD.is_file():
        pytest.skip("wing vendor/autoload.php missing — run `composer install` in files/anatomy/wing")
    p = WING / "contract-search-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", p.name], cwd=WING, capture_output=True, text=True, timeout=120,
            env={**__import__("os").environ, "NOS_TEST_REPO_ROOT": str(REPO)},
        )
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_query_that_404d_finds_the_endpoint_that_exists(probe: dict) -> None:
    for lang in ("cz", "en"):
        assert probe[lang]["error"] is False
        assert "/api/v1/remediation" in probe[lang]["content"], (
            f"the {lang} phrasing of the measured question does not surface "
            "/api/v1/remediation; the tool answers a question nobody asked"
        )
        assert probe[lang]["meta"]["hits"] <= 5


def test_every_path_returned_exists_in_the_committed_contract(probe: dict) -> None:
    published = (CONTRACTS / "wing.openapi.yml").read_text(encoding="utf-8") \
        + (CONTRACTS / "bone.openapi.yml").read_text(encoding="utf-8")
    for lang in ("cz", "en"):
        paths = re.findall(r"\s(/api/\S+)", probe[lang]["content"])
        assert paths, "no path in the answer"
        for path in paths:
            # Quoted when it carries a {placeholder}, bare otherwise.
            assert re.search(rf"^\s+'?{re.escape(path)}'?:", published, re.M), (
                f"contract_search returned {path}, which is not a path in the "
                "committed contract — it is synthesising, which is the exact "
                "failure it exists to stop."
            )


def test_a_miss_is_a_refusal_and_names_no_alternatives(probe: dict) -> None:
    miss = probe["miss"]["content"]
    assert "no confident match" in miss
    assert "/api/" not in miss, (
        "the no-match answer lists paths. An error may not enumerate what "
        "would have worked — that is the oracle this estate refuses."
    )


def test_it_takes_one_argument(probe: dict) -> None:
    """A `surface` enum shipped in the first cut and nobody had asked for it:
    two contracts, one index, and a model that must now choose between them
    before it can ask a question. Deleted 2026-09-01. This pins the absence,
    because an option is easier to add back than to notice."""
    assert probe["input_keys"] == ["query"], (
        f"contract_search takes {probe['input_keys']}. Every extra argument is a "
        "decision the caller has to make before it can ask."
    )


def test_it_is_registered_where_tools_are_registered() -> None:
    neon = (WING / "app/config/common.neon").read_text(encoding="utf-8")
    assert "register(@App\\AgentKit\\Tools\\ContractSearchTool)" in neon, (
        "a tool the registry never registers throws at session start for "
        "every agent that declares it"
    )
    assert "ContractSearchTool(%nosRepoRoot%)" in neon
    schema = (REPO / "state/schema/agent.schema.yaml").read_text(encoding="utf-8")
    assert "- contract-search" in schema, "no agent.yml can declare an id the schema rejects"
    for agent in ("jeff", "jeff-cloud"):
        roster = (REPO / f"files/anatomy/agents/{agent}/agent.yml").read_text(encoding="utf-8")
        assert "id: contract-search" in roster, f"{agent} is the agent that 404'd"
