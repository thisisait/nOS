#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Ansible module wrapper around files/anatomy/module_utils/load_plugins.py.

NB on shebang: `#!/usr/bin/python` is the canonical Ansible Ansiballz
placeholder — Ansible rewrites it on assembly to the host's resolved
`ansible_python_interpreter`. Using `#!/usr/bin/env python3` here
breaks Ansiballz detection on Ansible 2.20 + Python 3.14 and the
loader gets executed as a "binary script" with the literal shebang,
which fails on hosts where /usr/bin/env's PATH doesn't have python3.

Exposes structured `changed`/`failed` results so the playbook gets proper
PLAY RECAP accounting + clean per-plugin error attribution rather than
parsing shell stdout.

Usage from a task:

    - name: "Plugin loader — pre_render hook"
      nos_plugin_loader:
        hook: pre_render
        plugins_root: "{{ playbook_dir }}/files/anatomy/plugins"
"""

from __future__ import annotations

import os
import pathlib

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils import load_plugins  # type: ignore[attr-defined]

DOCUMENTATION = r"""
---
module: nos_plugin_loader
short_description: Run a plugin-loader lifecycle hook over files/anatomy/plugins/.
description:
  - Discovers plugin manifests, runs schema validation, builds the
    plugin DAG, executes aggregators, and runs the named lifecycle hook.
  - Empty plugin set is a clean no-op (the common case during A6 PoC
    bootstrap before any real plugins land).
  - See `files/anatomy/docs/plugin-loader-spec.md` for the full contract.
options:
  hook:
    description: Lifecycle hook to execute.
    required: true
    type: str
    choices: ['pre_render', 'pre_compose', 'post_compose', 'post_blank']
  plugins_root:
    description: Directory to scan for `<name>/plugin.yml`.
    required: false
    type: path
    default: "{{ playbook_dir }}/files/anatomy/plugins"
  agent_profiles_root:
    description: Optional directory of agent profile YAMLs (for aggregator).
    required: false
    type: path
    default: ""
"""

RETURN = r"""
plugins_loaded:
  description: Names of all plugins discovered + validated.
  type: list
  returned: always
plugins_skipped:
  description: Names of plugins skipped (requirement not met).
  type: list
  returned: always
hook_results:
  description: Per-plugin hook outcome (status + note).
  type: list
  returned: always
"""


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "hook": {"type": "str", "required": True,
                     "choices": ["pre_render", "pre_compose",
                                 "post_compose", "post_blank"]},
            "plugins_root": {"type": "path", "required": False, "default": ""},
            "agent_profiles_root": {"type": "path", "required": False,
                                    "default": ""},
        },
        supports_check_mode=True,
    )
    hook = module.params["hook"]
    plugins_root = pathlib.Path(module.params["plugins_root"]
                                or os.path.join(os.getcwd(),
                                                "files/anatomy/plugins"))
    agent_root = module.params["agent_profiles_root"]
    plugins = load_plugins.discover(plugins_root)
    # Optional agent profile harvest
    agent_profiles: list[dict] = []
    if agent_root and pathlib.Path(agent_root).is_dir():
        import yaml
        for ap_dir in sorted(pathlib.Path(agent_root).iterdir()):
            ap_yml = ap_dir / "profile.yml"
            if ap_yml.is_file():
                with open(ap_yml) as fh:
                    agent_profiles.append(yaml.safe_load(fh) or {})
    load_plugins.run_aggregators(plugins, agent_profiles=agent_profiles)
    if module.check_mode:
        module.exit_json(
            changed=False,
            plugins_loaded=[p.name for p in plugins],
            plugins_skipped=[],
            hook_results=[],
            msg=f"check mode: would run hook {hook!r} over {len(plugins)} plugin(s)",
        )
        return
    try:
        results = load_plugins.run_hook(hook, plugins)
    except load_plugins.ValidationError as e:
        module.fail_json(msg=f"validation: {e}")
        return
    except Exception as e:                                # noqa: BLE001
        module.fail_json(msg=f"hook {hook!r} aborted: {e}")
        return
    changed = any(r["status"] == "ok" and r["note"] != "no-op" for r in results)
    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        module.fail_json(
            msg=f"{len(failed)} plugin(s) failed in hook {hook!r}",
            hook_results=results,
            plugins_loaded=[p.name for p in plugins],
            plugins_skipped=[],
        )
        return
    module.exit_json(
        changed=changed,
        plugins_loaded=[p.name for p in plugins],
        plugins_skipped=[p.name for p in plugins if p.status == "skipped"],
        hook_results=results,
        msg=f"hook {hook!r}: {len(plugins)} plugin(s), {sum(1 for r in results if r['status'] == 'ok')} ok",
    )


if __name__ == "__main__":
    main()
