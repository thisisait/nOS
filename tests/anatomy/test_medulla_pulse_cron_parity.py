"""The medulla's cron says what Wing's cron says, for every schedule the catalog declares.

WHY (row medulla-scheduler, increment a). Today Wing's PHP owns the schedule
(PulseRepository::computeNextFireAt, dragonmantank/cron-expression 3.6, UTC). The
medulla will fire the schedule itself, so it parses cron in Rust
(medulla/src/pulse/cron.rs). One file of vectors binds the two: PHP must still
produce every vector (here), and the Rust unit test reads the same file. A schedule a
plugin adds without a vector fails here, with PHP's answer in the message.

Regenerate after adding a schedule: python3 tests/anatomy/test_medulla_pulse_cron_parity.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
VECTORS = REPO / "tests/fixtures/pulse_cron.json"

# Month end, year end, a leap February, an exact minute boundary, mid-minute seconds.
NOWS = [1792060397, 1798761540, 1835352030, 1793489400, 1799020800]
# Beyond the catalog: day-of-month OR day-of-week, Sunday as 7, steps on ranges, Feb 29.
# Not a list holding a range: PHP's 3.6 skips its first value (`5,10-12 * * * *` at 10:33
# gives 11:10, not 11:05; measured 2026-10-25). No job writes one; cron.rs pins the right answer.
EDGES = ["0 0 1-7 * 1", "0 12 * * 7", "5,10 1-3 * * *", "0 */6 1 */3 *", "59 23 31 12 *",
         "0 0 29 2 *", "*/7 * * * *", "0 0 * * 1-5", "15 14 1 * 0", "0 9-17/2 * * 1-5"]

PROBE = r"""
require getcwd() . '/vendor/autoload.php';
date_default_timezone_set('UTC');  // Wing's php runs UTC; next_fire_at carries +00:00
$out = [];
foreach (json_decode(stream_get_contents(STDIN), true) as [$e, $now]) {
    try { $out[] = (new Cron\CronExpression($e))->getNextRunDate('@' . $now)->format('c'); }
    catch (\Throwable) { $out[] = null; }
}
echo json_encode($out);
"""


def _php(pairs: list[list]) -> list[str | None]:
    if not shutil.which("php") or not (WING / "vendor/autoload.php").is_file():
        pytest.skip("php or files/anatomy/wing/vendor missing — composer install there")
    r = subprocess.run(["php", "-r", PROBE], cwd=WING, input=json.dumps(pairs),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _declared() -> set[str]:
    """Every schedule the catalog registers; a token schedule gets its default.config.yml value."""
    import os
    sys.path[:0] = [str(Path(__file__).parent), str(REPO / "tools")]
    import nos_identity  # noqa: PLC0415
    from test_pulse_command_allowlist import _declared_jobs  # noqa: PLC0415 — the catalog, as it registers
    had = os.environ.get("NOS_MAIL_DIGEST_CRON")
    os.environ["NOS_MAIL_DIGEST_CRON"] = had or nos_identity.default_config()["mail_digest_cron"]
    try:
        return {j["job"]["schedule"] for j in _declared_jobs("")}
    finally:
        os.environ.pop("NOS_MAIL_DIGEST_CRON") if had is None else None


def _vectors() -> list[dict]:
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def test_every_declared_schedule_has_vectors():
    have = {v["expr"] for v in _vectors()}
    missing = sorted(_declared() - have)
    assert not missing, (f"schedules with no parity vector: {missing}; PHP says "
                         f"{dict(zip(missing, _php([[e, NOWS[0]] for e in missing])))}. "
                         "Regenerate: python3 tests/anatomy/test_medulla_pulse_cron_parity.py")


def test_php_still_produces_every_vector():
    vs = _vectors()
    got = _php([[v["expr"], v["now"]] for v in vs])
    wrong = [(v["expr"], v["now"], v["next"], g) for v, g in zip(vs, got) if g != v["next"]]
    assert not wrong, f"(expr, now, vector, php) — PHP's cron moved: {wrong[:5]}"
    assert all(v["next"] for v in vs), "a vector PHP cannot schedule is no parity vector"


if __name__ == "__main__":
    exprs = sorted(_declared() | set(EDGES))
    pairs = [[e, n] for e in exprs for n in NOWS]
    VECTORS.write_text(json.dumps([{"expr": e, "now": n, "next": x} for (e, n), x in zip(pairs, _php(pairs))],
                                  indent=0) + "\n", encoding="utf-8")
    print(f"{len(pairs)} vectors -> {VECTORS.relative_to(REPO)}")
