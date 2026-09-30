"""Gate: pytest's ansible runs log to a temp file, never ~/.nos/ansible.log."""
import os
import subprocess
import sys


def test_the_log_path_is_redirected():
    assert ".nos" not in os.environ.get("ANSIBLE_LOG_PATH", "~/.nos/ansible.log")


def test_ansible_sees_the_redirect():
    out = subprocess.run(["ansible-config", "dump", "--only-changed"], capture_output=True, text=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("DEFAULT_LOG_PATH")]
    assert line and ".nos" not in line[0], line
