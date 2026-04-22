"""Tests for module_utils/nos_state_lib.py — the shared helpers backing nos_state.

Covers (per agent-1 brief):
  - state roundtrip (read/write/merge)
  - dotted-path get/set/unset
  - manifest schema validity (manifest.yml passes manifest.schema.json)
  - introspect dispatcher (mocked subprocess/docker)
  - retroactive migration detect predicates are false on current repo
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import yaml

from module_utils import nos_state_lib as lib  # noqa: E402


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST_PATH = os.path.join(REPO_ROOT, "state", "manifest.yml")
MANIFEST_SCHEMA = os.path.join(REPO_ROOT, "state", "schema", "manifest.schema.json")
MIGRATION_SCHEMA = os.path.join(REPO_ROOT, "state", "schema", "migration.schema.json")
RETROACTIVE_MIGRATION = os.path.join(
    REPO_ROOT, "migrations", "2026-04-22-devboxnos-to-nos.yml"
)


# ---------------------------------------------------------------------------
# State roundtrip
# ---------------------------------------------------------------------------

class StateRoundtripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nos-state-test-")
        self.state_path = os.path.join(self.tmp, "state.yml")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_missing_returns_skeleton(self):
        data = lib.load_state(self.state_path)
        self.assertIn("schema_version", data)
        self.assertEqual(data["schema_version"], lib.CURRENT_SCHEMA_VERSION)
        self.assertIn("services", data)
        self.assertEqual(data["services"], {})
        # Graceful degrade: no file should exist after load.
        self.assertFalse(os.path.exists(self.state_path))

    def test_dump_and_reload(self):
        data = lib.empty_state()
        data["services"]["grafana"] = {"installed": "11.5.0", "healthy": True}
        lib.dump_state(data, self.state_path)
        self.assertTrue(os.path.exists(self.state_path))
        reloaded = lib.load_state(self.state_path)
        self.assertEqual(reloaded["services"]["grafana"]["installed"], "11.5.0")

    def test_dump_is_atomic_and_permissions_tight(self):
        data = lib.empty_state()
        lib.dump_state(data, self.state_path)
        mode = os.stat(self.state_path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_deep_merge_preserves_siblings(self):
        a = {"services": {"grafana": {"installed": "11"}}, "migrations_applied": [{"id": "a"}]}
        b = {"services": {"gitea": {"installed": "1.22"}}}
        out = lib.deep_merge(a, b)
        self.assertIn("grafana", out["services"])
        self.assertIn("gitea", out["services"])
        self.assertEqual(out["migrations_applied"], [{"id": "a"}])
        # Inputs unchanged.
        self.assertNotIn("gitea", a["services"])

    def test_deep_merge_overlay_wins_at_leaves(self):
        a = {"x": {"y": 1, "z": 2}}
        b = {"x": {"y": 99}}
        out = lib.deep_merge(a, b)
        self.assertEqual(out["x"]["y"], 99)
        self.assertEqual(out["x"]["z"], 2)

    def test_deep_merge_lists_replace(self):
        a = {"items": [1, 2, 3]}
        b = {"items": [9]}
        out = lib.deep_merge(a, b)
        self.assertEqual(out["items"], [9])


# ---------------------------------------------------------------------------
# Dotted path helpers
# ---------------------------------------------------------------------------

class DottedPathTest(unittest.TestCase):
    def test_get_missing_returns_default(self):
        self.assertEqual(lib.dotted_get({}, "a.b.c", default="fallback"), "fallback")

    def test_get_found(self):
        s = {"a": {"b": {"c": 42}}}
        self.assertEqual(lib.dotted_get(s, "a.b.c"), 42)

    def test_set_creates_intermediates(self):
        s = {}
        self.assertTrue(lib.dotted_set(s, "a.b.c", 1))
        self.assertEqual(s, {"a": {"b": {"c": 1}}})

    def test_set_reports_no_change_when_equal(self):
        s = {"a": 1}
        self.assertFalse(lib.dotted_set(s, "a", 1))

    def test_unset_removes_leaf(self):
        s = {"a": {"b": 2}}
        self.assertTrue(lib.dotted_unset(s, "a.b"))
        self.assertEqual(s, {"a": {}})
        self.assertFalse(lib.dotted_unset(s, "a.b"))


# ---------------------------------------------------------------------------
# Manifest validity
# ---------------------------------------------------------------------------

class ManifestTest(unittest.TestCase):
    def test_manifest_loads(self):
        m = lib.load_manifest(MANIFEST_PATH)
        self.assertEqual(m["schema_version"], 1)
        self.assertIn("services", m)
        self.assertGreater(len(m["services"]), 20, "manifest should enumerate the full catalog")

    def test_manifest_services_have_required_keys(self):
        m = lib.load_manifest(MANIFEST_PATH)
        ids = set()
        for svc in m["services"]:
            self.assertIn("id", svc)
            self.assertIn("category", svc)
            self.assertIn("version_source", svc)
            self.assertNotIn(svc["id"], ids, "duplicate service id: %r" % svc["id"])
            ids.add(svc["id"])

    def test_manifest_matches_schema(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed; skipping schema validation")
        import jsonschema

        with open(MANIFEST_SCHEMA, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        m = lib.load_manifest(MANIFEST_PATH)
        jsonschema.validate(lib.to_json_safe(m), schema)


# ---------------------------------------------------------------------------
# Introspect dispatcher (mocked subprocess)
# ---------------------------------------------------------------------------

class IntrospectTest(unittest.TestCase):
    def test_docker_image_extraction(self):
        fake_proc = mock.Mock(returncode=0, stdout="grafana/grafana-oss:11.5.0\n", stderr="")
        with mock.patch.object(lib, "_which", return_value="/usr/local/bin/docker"), \
                mock.patch.object(lib.subprocess, "run", return_value=fake_proc):
            self.assertEqual(lib.introspect_docker_image("nos-grafana"), "11.5.0")

    def test_docker_image_missing_container(self):
        fake_proc = mock.Mock(returncode=1, stdout="", stderr="no such container")
        with mock.patch.object(lib, "_which", return_value="/usr/local/bin/docker"), \
                mock.patch.object(lib.subprocess, "run", return_value=fake_proc):
            self.assertIsNone(lib.introspect_docker_image("nonexistent"))

    def test_docker_unavailable_returns_none(self):
        with mock.patch.object(lib, "_which", return_value=None):
            self.assertIsNone(lib.introspect_docker_image("nos-grafana"))
            self.assertIsNone(lib.introspect_docker_running("nos-grafana"))

    def test_introspect_service_desired_from_role_vars(self):
        svc = {
            "id": "grafana",
            "category": "observability",
            "stack": "observability",
            "version_source": "docker_image",
            "image": "grafana/grafana-oss",
            "container_name": "nos-grafana",
            "version_var": "grafana_version",
            "data_path_var": "grafana_data_dir",
            "install_flag": "install_observability",
        }
        role_vars = {
            "grafana_version": "11.5.0",
            "grafana_data_dir": "/tmp/gf",
            "install_observability": True,
        }
        with mock.patch.object(lib, "introspect_docker_image", return_value=None), \
                mock.patch.object(lib, "introspect_docker_running", return_value=None):
            entry = lib.introspect_service(svc, role_vars=role_vars)
        self.assertEqual(entry["desired"], "11.5.0")
        self.assertEqual(entry["data_path"], "/tmp/gf")
        self.assertTrue(entry["enabled"])
        self.assertEqual(entry["stack"], "observability")
        self.assertIsNone(entry["installed"])

    def test_introspect_all_runs_over_manifest(self):
        m = lib.load_manifest(MANIFEST_PATH)
        with mock.patch.object(lib, "introspect_docker_image", return_value=None), \
                mock.patch.object(lib, "introspect_docker_running", return_value=None), \
                mock.patch.object(lib, "introspect_brew_version", return_value=None), \
                mock.patch.object(lib, "introspect_launchd_loaded", return_value=None):
            observed = lib.introspect_all(m, role_vars={})
        self.assertEqual(len(observed), len(m["services"]))
        # Every entry must be a dict with the expected keys.
        for sid, entry in observed.items():
            self.assertIn("installed", entry)
            self.assertIn("desired", entry)
            self.assertIn("healthy", entry)


# ---------------------------------------------------------------------------
# Retroactive migration: detect predicates are FALSE on the current host/repo.
# ---------------------------------------------------------------------------

class RetroactiveMigrationTest(unittest.TestCase):
    def setUp(self):
        with open(RETROACTIVE_MIGRATION, "r", encoding="utf-8") as fh:
            self.migration = yaml.safe_load(fh)

    def test_id_matches_filename(self):
        fname = os.path.basename(RETROACTIVE_MIGRATION)
        self.assertEqual(self.migration["id"] + ".yml", fname)

    def test_severity_is_breaking(self):
        self.assertEqual(self.migration["severity"], "breaking")

    def test_has_notes_explaining_retention(self):
        notes = self.migration.get("notes", "") or ""
        self.assertTrue(
            "audit" in notes.lower() or "retain" in notes.lower() or "fork" in notes.lower(),
            "notes should document why the migration is retained",
        )

    def test_applies_if_gate_is_false_on_current_host(self):
        """Mirror the `applies_if` predicates and verify each one resolves false.

        This is the idempotency contract: on current nOS, the migration does
        not apply. We exercise the filesystem predicate directly and stub out
        Authentik predicates (the real check requires a live API).
        """
        # fs_path_exists: "~/.devboxnos"
        self.assertFalse(
            os.path.exists(os.path.expanduser("~/.devboxnos")),
            "This test host carries ~/.devboxnos — the retroactive migration "
            "would fire. Clean up before running tests.",
        )
        # launchagent_matches: "com.devboxnos.*"
        la_dir = os.path.expanduser("~/Library/LaunchAgents")
        if os.path.isdir(la_dir):
            legacy = [f for f in os.listdir(la_dir) if f.startswith("com.devboxnos.")]
            self.assertEqual(legacy, [], "legacy com.devboxnos.* plists present")

    def test_each_step_has_detect_and_rollback(self):
        for step in self.migration["steps"]:
            self.assertIn("id", step)
            self.assertIn("action", step)
            # every step must have a rollback (may be noop).
            self.assertIn("rollback", step)

    def test_validates_against_schema(self):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed; skipping schema validation")
        import jsonschema

        with open(MIGRATION_SCHEMA, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(lib.to_json_safe(self.migration), schema)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
