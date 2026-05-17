"""Anatomy gates for per-plugin notification templates (2026-05-17).

A9 + A9.5 shipped the plugin-manifest `notification:` block with severity
routing + channel resolution sidecar. This batch promotes title/body
template strings into the same block so emitters can post
`{template: name, context: {...}}` instead of building literal title+body
strings per skill. Bone resolves the template via the routing sidecar
and renders with Python `string.Template` (`$var`/`${var}` syntax —
distinct from Latte/Jinja `{{ var }}` to prevent double-evaluation).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_routing_template_emits_templates_key():
    """The wing-base aggregator template must include `templates:` in
    the rendered routing sidecar so Bone's _lookup_template can find
    per-plugin title/body source strings."""
    src = (REPO / "files/anatomy/plugins/wing-base/templates/notification-routing.json.j2").read_text()
    assert '"templates"' in src
    assert "e.templates" in src


def test_bone_wing_client_resolves_templates():
    src = (REPO / "files/anatomy/bone/clients/wing.py").read_text()
    assert "_lookup_template" in src
    assert "_render_template_string" in src
    assert "string.Template" in src
    assert "safe_substitute" in src


def test_bone_validate_payload_accepts_template_or_title():
    src = (REPO / "files/anatomy/bone/notifications.py").read_text()
    # Validator must accept EITHER literal title OR template+context.
    assert "missing required field: title (or template+context)" in src
    # Template name shape pinned (lowercase + alnum + _-).
    assert "[a-z0-9][a-z0-9_-]" in src


def test_gitleaks_manifest_declares_template():
    """First live consumer: gitleaks plugin manifest exposes the
    `new_findings` template under `notification.templates`."""
    import yaml
    manifest = yaml.safe_load(
        (REPO / "files/anatomy/plugins/gitleaks/plugin.yml").read_text()
    )
    templates = (manifest.get("notification") or {}).get("templates") or {}
    assert "new_findings" in templates
    tpl = templates["new_findings"]
    assert "title" in tpl and "body" in tpl
    # string.Template placeholders (not Jinja).
    assert "$count" in tpl["title"]
    assert "$count" in tpl["body"]
    assert "$top_findings_md" in tpl["body"]
    # No Jinja {{ }} that would double-evaluate at routing-render time.
    assert "{{" not in tpl["title"] and "{{" not in tpl["body"]


def test_gitleaks_skill_uses_template_emit():
    """gitleaks skill posts `template: new_findings + context: {...}`
    instead of building literal title+body strings."""
    src = (REPO / "files/anatomy/plugins/gitleaks/skills/run-gitleaks.sh").read_text()
    assert '--arg tpl "new_findings"' in src
    assert "template: $tpl" in src
    assert "context: " in src
    # Literal title shouldn't be in the payload anymore (template wins).
    assert '"Gitleaks: $INSERTED' not in src
    # Context placeholders documented.
    for key in ("count", "scan_dir", "top_findings_md"):
        assert key in src, f"context key {key} missing in skill"


def test_end_to_end_template_resolution(tmp_path):
    """Drive the full chain: aggregator → routing JSON → Bone insert
    with template+context → DB row with rendered title+body."""
    sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))
    sys.path.insert(0, str(REPO / "files/anatomy/bone"))
    import importlib
    import load_plugins as lp
    importlib.reload(lp)
    plugins = lp.discover(REPO / "files/anatomy/plugins")
    lp.run_aggregators(plugins)
    wing_base = next(p for p in plugins if p.name == "wing-base")
    routing = wing_base.inputs.get("notification_routing") or []
    gitleaks_entry = next(
        (r for r in routing if r.get("plugin_name") == "gitleaks"), None
    )
    assert gitleaks_entry is not None
    assert "new_findings" in (gitleaks_entry.get("templates") or {})

    # Render routing into the file Bone reads.
    import jinja2
    env = jinja2.Environment()
    env.filters["to_json"] = lambda v: json.dumps(v)
    rendered = env.from_string(
        (REPO / "files/anatomy/plugins/wing-base/templates/notification-routing.json.j2").read_text()
    ).render(inputs={"notification_routing": routing},
             ansible_date_time={"iso8601": "2026-05-17T20:00:00Z"})
    data_dir = tmp_path / "app" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "notification-routing.json").write_text(rendered)
    subprocess.run(
        ["php", str(REPO / "files/anatomy/wing/bin/init-db.php"),
         f"--data-dir={data_dir}"],
        check=True, capture_output=True,
    )

    os.environ["WING_DB_PATH"] = str(data_dir / "wing.db")
    # Force re-import (env var read at module load).
    for mod in ("clients.wing", "clients"):
        if mod in sys.modules:
            del sys.modules[mod]
    from clients import wing
    rid, _ = wing.insert_notification({
        "severity": "high",
        "template": "new_findings",
        "context": {
            "count": "3",
            "scan_dir": "/some/repo",
            "top_findings_md": "- finding1\n- finding2",
        },
        "origin_plugin": "gitleaks",
        "actor_id": "plugin:gitleaks",
    })
    assert rid > 0
    rows = wing.query_notifications(unread_only=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Gitleaks: 3 new secret finding(s)"
    assert "**3 new finding(s)** in /some/repo" in row["body"]
    assert "- finding1" in row["body"]
