"""`--tags pulse` must reach the tasks that register Pulse jobs in Wing.

2026-10-27: a manifest's jobs changed, `nos --tags pulse` deployed the scripts,
but Wing's pulse_jobs kept the old rows until `--tags wing`: the upsert sat
behind the wing post include tagged only wing,security. Walks the real include chain.
"""

from test_a_declared_tag_can_be_reached import _analyse

POST = "roles/pazny.wing/tasks/post.yml"
REGISTRATION = ("Wait for Wing API health", "Discover Pulse job catalog", "Parse Pulse job catalog",
                "Drop Pulse jobs of retired agents", "Drop Pulse jobs of services not installed",
                "Register discovered Pulse jobs")


def test_the_pulse_tag_selects_the_job_registration():
    alive = {name for where, name, tag in _analyse().alive if where == POST and tag == "pulse"}
    missing = [n for n in REGISTRATION if not any(n in a for a in alive)]
    assert not missing, f"--tags pulse never reaches {missing} in {POST}"
