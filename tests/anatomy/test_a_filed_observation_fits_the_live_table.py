"""discovery-scan files a row the live table accepts, and a refused row is not a finding.

MEASURED 2026-10-27: discovery:contradiction-scan crashed on 5 of 5 runs since 10-23 with KEAP's
400 on the rows POST. The blanks re-created the roadmap table from its definition, where `refs` is
`kind: json`, and the scan still sent the `·`-joined string. The crash went uncaught, Python exited 1,
and 1 is the job's findings code, so Wing recorded every crash as "found something".

Executed: file_rows and main against a fake KEAP that validates `refs` the way
shared/contracts/table.ts does.
"""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import sys
import urllib.error

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("discovery_scan_filed", REPO / "tools/discovery-scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["discovery_scan_filed"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_keap(mod, monkeypatch, refs_kind):
    sent = []
    monkeypatch.setattr(mod, "_get_json", lambda url: (
        {"data": {"schema": {"columns": [{"key": "refs", "kind": refs_kind}]}}} if url == mod.BASE
        else {"data": {"rows": []}}))
    monkeypatch.setattr(mod, "paged", lambda get, url: {"data": {"rows": []}})

    def urlopen(req, timeout=None):
        body = json.loads(req.data)
        values = body.get("values", body)
        sent.append(values)
        if refs_kind == "json" and not isinstance(values["refs"], (list, dict)):
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                         io.BytesIO(b'{"error":"refs: expected object/array"}'))
        return io.BytesIO(b"{}")
    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    return sent


def _finding(mod):
    return mod.Finding(slug="obs-x", title="t", body="b", refs="remediation-queue.json REM-1 · docker ps x")


def test_refs_go_as_a_list_to_a_json_column(monkeypatch):
    mod = _load()
    sent = _fake_keap(mod, monkeypatch, "json")
    filed, refused = mod.file_rows([_finding(mod)])
    assert (filed, refused) == (1, []), refused
    assert sent[0]["refs"] == ["remediation-queue.json REM-1", "docker ps x"]


def test_refs_stay_text_for_a_text_column(monkeypatch):
    mod = _load()
    sent = _fake_keap(mod, monkeypatch, "text")
    assert mod.file_rows([_finding(mod)]) == (1, [])
    assert sent[0]["refs"] == "remediation-queue.json REM-1 · docker ps x"


def test_a_refused_row_is_not_a_finding(monkeypatch):
    mod = _load()
    _fake_keap(mod, monkeypatch, "json")
    monkeypatch.setattr(mod, "_refs_kind", lambda: "text")  # the scan's guess goes stale
    filed, refused = mod.file_rows([_finding(mod)])
    assert filed == 0 and "HTTP 400" in refused[0] and "refs" in refused[0]
    plugin = yaml.safe_load((REPO / "files/anatomy/plugins/discovery/plugin.yml").read_text())
    job = next(j for j in plugin["pulse"]["jobs"] if j["name"] == "contradiction-scan")
    assert mod.EXIT_NOT_FILED not in job.get("findings_exit_codes", []), \
        "a refused write would read as a finding again"
