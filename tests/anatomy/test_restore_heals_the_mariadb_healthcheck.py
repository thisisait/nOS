"""A replayed `mariadb-dump --all-databases` carries mysql.user and clobbers the
image's `healthcheck` login; the container then stays unhealthy and core-up's
STRICT wait aborts before post.yml runs (measured 2026-09-28, the morning after
the first real restore). One task file heals it; this pins that BOTH the
restore path (right after the replay) and the pre-wait render path include it,
and that the task changes only on a real resync — a reader's verdict, not the
attempt's."""
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "roles/pazny.mariadb/tasks/healthcheck-user.yml"


def _includes(path: Path, key: str) -> list[dict]:
    out = []
    def walk(node):
        if isinstance(node, dict):
            if any(k in node for k in ("include_tasks", "ansible.builtin.include_tasks",
                                        "include_role", "ansible.builtin.include_role")):
                out.append(node)
            for v in node.values(): walk(v)
        elif isinstance(node, list):
            for v in node: walk(v)
    walk(yaml.safe_load(path.read_text()))
    return [n for n in out if key in yaml.safe_dump(n)]


def test_restore_resyncs_right_after_the_replay():
    text = (REPO / "tasks/restore.yml").read_text()
    replay = text.index("Pipe gunzip'd dump into mariadb client")
    heal = text.index("tasks_from: healthcheck-user.yml")
    assert replay < heal < text.index("[Restore] Replay PostgreSQL role post.yml")


def test_render_path_includes_it_before_the_health_wait():
    assert _includes(REPO / "roles/pazny.mariadb/tasks/main.yml", "healthcheck-user.yml")


def test_the_task_reports_change_from_the_probe_not_the_attempt():
    task = yaml.safe_load(TASK.read_text())[0]
    assert "resynced" in task["changed_when"]
    script = task["ansible.builtin.shell"]
    assert "healthcheck.sh --connect --innodb_initialized && echo \"resynced\"" in script, (
        "'resynced' must be printed only after healthcheck.sh itself logs in again")
    assert task.get("no_log") is True
