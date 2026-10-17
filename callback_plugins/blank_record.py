# -*- coding: utf-8 -*-
# (c) 2026, This is AIT / nOS project
# GNU GPL v3.0 — distributed with the nOS Ansible playbook.
"""Close the blank-run record with the PLAY's outcome, after the last task.

main.yml opens ~/.nos/blank-runs.jsonl; post-smoke adds the smoke result. A
task can fail anywhere after that, so only v2_playbook_on_stats (Ansible's last
word, also on failure) may write finished. Gate: test_blank_run_leaves_a_record.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
    name: blank_record
    type: notification
    short_description: Close the nOS blank-run record with the play's outcome.
    description:
      - "No-op unless the play set_fact'd nos_blank_started and nos_blank_record."
    requirements:
      - "enabled in ansible.cfg (callback_plugins path + callbacks_enabled)"
"""

import json
from datetime import datetime, timezone

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "blank_record"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self._started = self._path = self._failed_task = None

    def v2_runner_on_ok(self, result):
        facts = result._result.get("ansible_facts") or {}
        if "nos_blank_started" in facts and "nos_blank_record" in facts:
            self._started, self._path = facts["nos_blank_started"], facts["nos_blank_record"]

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if not ignore_errors:
            self._failed_task = result._task.get_name()

    def v2_playbook_on_stats(self, stats):
        if not self._started:
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                rows = [json.loads(x) for x in fh if x.strip()]
            row = [r for r in rows if r.get("started") == self._started][-1]
        except (OSError, ValueError, IndexError, AttributeError):
            row = {"started": self._started, "smoke_strict": None}  # the reader still sees FAILED/finished
        failed = any(stats.failures.values()) or any(stats.dark.values())
        row.update(finished=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   failed=bool(failed),
                   failed_task=self._failed_task if failed else None)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
