"""An agent that owes an artifact is told so in the TURN IT ANSWERS.

MEASURED 2026-08-29 across four surveyor runs and three librarian ones, on the
same runtime, the same day.

  * The librarian's `NOS_AGENT_TASK` ends with a numbered step: "POST your
    '## Librarian report' … via Wing /api/v1/events". It filed every time.
  * The surveyor's task was four lines of prose ending "follow your system
    prompt exactly". Its filing instruction lived at `system.md:175`, beneath
    ~170 lines about a read budget. It filed twice of four — once with an empty
    body, and once not at all, having been told by the grader's feedback, twice
    in the same session, exactly what it owed.

The harness was not at fault: the revision turn carries the feedback verbatim
(`Runner.php` — "WHY IT IS NOT DONE"), and the deliverable reader was correct by
then. The task is the turn the model answers, and an obligation buried in a long
system prompt is one the model reads once and spends its budget away from.

So: if a ceremony declares `outcomes.deliverable`, the pulse task that starts it
must NAME the filing step. This gate reads the manifests — the task text and the
declaration are in the same file, which is the only reason it can compare them.

What it cannot do, said plainly: it cannot make a model obey. It can only refuse
the configuration where nobody asked.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"

#: The filing step, however it is spelled. A task that says none of these is a
#: task that never mentions the artifact.
NAMES_THE_STEP = ("/api/v1/events", "api/v1/events")


def ceremonies() -> list[tuple[str, str, str]]:
    """(agent, job, task) for every scheduled job of an agent that owes an artifact."""
    out = []
    for d in sorted(AGENTS.iterdir()):
        f = d / "agent.yml"
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if not ((doc.get("outcomes") or {}).get("deliverable")):
            continue
        for job in ((doc.get("pulse") or {}).get("jobs") or []):
            # BOUND CEREMONIES ONLY. Three conductor jobs are plain scripts
            # (drift-watch.sh, scan-state-snapshot.py, scan-runner.sh) that
            # happen to hang off the conductor manifest; they run no model and
            # carry no task, and demanding one of them would be this gate
            # refusing a correct configuration.
            if not str(job.get("command", "")).endswith("/tools/run-agent.sh"):
                continue
            task = ((job.get("env") or {}).get("NOS_AGENT_TASK") or "")
            out.append((d.name, job.get("name", "?"), task))
    return out


def test_there_are_ceremonies_that_owe_an_artifact() -> None:
    """Positive control — an empty sweep would make this vacuous."""
    found = ceremonies()
    assert len(found) >= 3, (
        f"only {len(found)} scheduled jobs belong to an agent declaring "
        "outcomes.deliverable; this gate reasons over them"
    )


def test_every_such_task_names_the_filing_step() -> None:
    silent = [
        f"{agent}:{job}"
        for agent, job, task in ceremonies()
        if not any(n in task for n in NAMES_THE_STEP)
    ]
    assert not silent, (
        f"these tasks owe an artifact and never mention filing it: {silent}. "
        "The surveyor spent 222k input tokens on reads and posted nothing, "
        "twice in one session, with the obligation sitting in its system "
        "prompt. Name it in the task."
    )


# A SECOND ASSERTION WAS WRITTEN HERE AND DELETED, 2026-08-29. It required the
# task to phrase filing as an obligation ("must", "not done until", "did not
# happen"). It failed the librarian — which names the step plainly, phrases
# nothing as a duty, and filed on every run measured. A gate that refuses the
# configuration with the best evidence behind it is measuring the author's
# taste, not the estate. Naming the step is what the runs support; nothing
# observed says the wording beyond that matters.
