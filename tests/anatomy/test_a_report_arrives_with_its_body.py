"""A filed report that stored nothing is not a filed report.

MEASURED 2026-08-29, session `461db38c`. The surveyor POSTed a complete survey
— `result_json.report_markdown`, "## Surveyor report", ranked findings, the lot
— and the stored row came back `length(result_json) = 0`. The event existed, so
the deliverable check passed, so the run was satisfied. Every surface agreed and
the work was gone.

TWO SPELLINGS, ONE FIELD. `EventRepository::insert()` read the body from
`$payload['result']`; every agent PROMPT in this estate says
`result_json.report_markdown`, because that is what the column is called. Neither
side was wrong on its own and nothing compared them. The comment directly beneath
the fix records the same defect from 2026-05-05, one field along: "Bone POST
handler accepted `source` in JSON but the INSERT silently dropped it."

So this file pins both halves, by INSERTING through the real repository and
reading the row back:

  * either spelling arrives and is stored;
  * a body that is absent, or empty, does not satisfy a ceremony that owes one —
    an artifact nobody can read is the same as no artifact.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"

pytestmark = pytest.mark.skipif(
    not AUTOLOAD.is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\Model\EventRepository;
use Nette\Database\Connection;
use Nette\Database\Explorer;
use Nette\Database\Structure;
use Nette\Database\Conventions\DiscoveredConventions;
use Nette\Caching\Storages\MemoryStorage;

$db = sys_get_temp_dir() . '/nos-events-' . bin2hex(random_bytes(4)) . '.db';
$init = getenv('NOS_INIT_DB');
exec(sprintf('php %s --data-dir=%s 2>&1', escapeshellarg($init), escapeshellarg(dirname($db))), $o, $rc);
// init-db writes wing.db in the given dir; use that.
$db = dirname($db) . '/wing.db';

$conn = new Connection('sqlite:' . $db);
$storage = new MemoryStorage();
$structure = new Structure($conn, $storage);
$explorer = new Explorer($conn, $structure, new DiscoveredConventions($structure), $storage);
$repo = new EventRepository($explorer);

$out = [];
foreach ([
    'legacy_result'   => ['result'      => ['report_markdown' => '## from result']],
    'agent_spelling'  => ['result_json' => ['report_markdown' => '## from result_json']],
    'no_body'         => [],
] as $label => $extra) {
    $id = $repo->insert(array_merge([
        'ts' => gmdate('c'), 'type' => 'conductor_report', 'run_id' => 'r-' . $label,
        'actor_action_id' => 's-' . $label,
    ], $extra));
    $row = $conn->fetch('SELECT result_json FROM events WHERE id = ?', $id);
    $out[$label] = $row->result_json;
}

// THE READER ITSELF, against this real database — the predicate the Runner
// builds, transcribed. Stubbing it is how it shipped wrong twice.
$reader = static function (string $session) use ($repo): bool {
    $found = $repo->query(['type' => 'conductor_report', 'actor_action_id' => $session], 1)['items'] ?? [];
    $body = $found === [] ? null : ($found[0]['result_json'] ?? null);
    return is_string($body) && trim($body) !== '' && trim($body) !== '[]' && trim($body) !== '{}';
};
$out['reader'] = [
    'with_body'    => $reader('s-agent_spelling'),
    'without_body' => $reader('s-no_body'),
    'no_such_run'  => $reader('s-never-happened'),
];
echo json_encode($out);
"""


def _probe() -> dict:
    p = WING / "events-body-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", p.name], cwd=WING, capture_output=True, text=True, timeout=90,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                 "HOME": str(Path.home()),
                 "NOS_INIT_DB": str(WING / "bin/init-db.php")},
        )
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr or out.stdout
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_agent_spelling_is_stored() -> None:
    """`result_json` is what four agent prompts tell the model to send."""
    got = _probe()["agent_spelling"]
    assert got, "an agent's report body was dropped on insert — this is 461db38c"
    assert "from result_json" in got


def test_the_in_process_spelling_still_works() -> None:
    """AuditEmitter and Runner send `result`; the fix must not move the goalposts."""
    got = _probe()["legacy_result"]
    assert got and "from result" in got


def test_no_body_stores_null_rather_than_an_empty_object() -> None:
    """Absent and empty must stay tellable apart at the column."""
    assert _probe()["no_body"] in (None, "")


def test_the_deliverable_reader_answers_correctly_on_a_real_database() -> None:
    """The reader, RUN — not stubbed, not grepped.

    It shipped wrong twice in one morning and both times a gate was green,
    because the gate replaced this callable with a stub and then asserted about
    the stub. `query()` returns `['items' => rows, 'total' => n]`: `!== []` is
    therefore always true (461db38c: an empty report satisfied) and `$rows[0]`
    is always null (245cf5e9: a 4409-byte report was called missing).
    """
    got = _probe()["reader"]
    assert got["with_body"] is True, (
        "a report that IS in the table reads as absent — this is 245cf5e9, "
        "where the agent revised twice against work it had already filed"
    )
    assert got["without_body"] is False, "an empty artifact counts as filed — 461db38c"
    assert got["no_such_run"] is False, "a session with no report at all reads as satisfied"


def test_the_runner_uses_that_shape() -> None:
    """And the transcription above matches the code it stands in for."""
    src = (REPO / "files/anatomy/wing/app/AgentKit/Runner.php").read_text(encoding="utf-8")
    i = src.index("deliverableEvent === null")
    body = src[i:i + 1800]
    assert "['items']" in body, "the reader no longer unwraps query()'s envelope"
    for empty in ("'[]'", "'{}'"):
        assert empty in body, f"an artifact of {empty} counts as filed"
