"""The alloy-* fragment plugins must not render into Alloy's live config dir.

THIS GATE EXISTS TO PREVENT A PLAUSIBLE FIX. Four plugins — alloy-base,
alloy-docker-metrics, alloy-host-metrics, alloy-syslog — render into
`~/.config/alloy/`, which the running daemon does not read: brew starts
`alloy run` against `<homebrew_prefix>/etc/grafana-alloy`. The obvious repair
is to point them at the directory Alloy actually reads, and it would work on
the first try — `alloy run` merges every `*.alloy` in a directory, so no change
to the service is needed.

It would also be a mistake, and a quiet one. Measured 2026-08-31, the fragments
DUPLICATE what `files/observability/alloy/config.alloy.j2` already declares:

  * alloy-host-metrics   prometheus.exporter.unix "host"   vs live "local"
  * alloy-docker-metrics discovery.docker + loki.source.docker "containers"
                         vs live "docker_targets" / "docker_logs"
  * alloy-syslog         nginx / wing / daemons file matches vs live
                         nginx_access, nginx_error, organ_logs

The component LABELS differ, so Alloy would not complain — it would start
cleanly and then ship every container log to Loki twice and scrape every host
metric twice. Doubling ingest on an estate whose Loki retention is already the
open question is a worse outcome than the fragments doing nothing, and the
symptom (duplicate series, doubled bill on disk) is far from the cause.

The four are a superseded parallel implementation. Deleting them is the right
end state and is the operator's call, because it moves the Track Q plugin
tally. Until then, this holds the line.
"""

from __future__ import annotations

import pathlib
import yaml
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = ROOT / "files/anatomy/plugins"

#: The path Alloy is actually launched against, as a fragment of the rendered
#: target. Matching on the tail avoids depending on how homebrew_prefix is
#: spelled in a given manifest.
LIVE_CONFIG_DIR = "etc/grafana-alloy"

ALLOY_PLUGINS = ["alloy-base", "alloy-docker-metrics",
                 "alloy-host-metrics", "alloy-syslog"]


def _targets(plugin: str) -> list[str]:
    manifest = PLUGINS / plugin / "plugin.yml"
    if not manifest.is_file():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    out = []
    for entry in (data.get("provisioning") or {}).values():
        if isinstance(entry, dict):
            target = entry.get("target") or entry.get("target_dir")
            if target:
                out.append(str(target))
    return out


@pytest.mark.parametrize("plugin", ALLOY_PLUGINS)
def test_the_fragment_does_not_target_the_live_dir(plugin: str) -> None:
    manifest = PLUGINS / plugin / "plugin.yml"
    if not manifest.is_file():
        pytest.skip(f"{plugin} has been deleted — the superseded implementation is gone, "
                    "which is the intended end state")
    for target in _targets(plugin):
        assert LIVE_CONFIG_DIR not in target, (
            f"{plugin} now renders to {target}, inside the directory Alloy "
            "actually loads. It would merge cleanly and then DOUBLE the "
            "estate's container logs and host metrics, because "
            "files/observability/alloy/config.alloy.j2 already declares the "
            "same collectors under different labels. Reconcile the duplication "
            "first — or delete this plugin, which is the intended end state."
        )


def test_the_live_template_still_owns_the_collectors() -> None:
    """If the live template ever stops declaring these, the ban above is wrong."""
    body = (ROOT / "files/observability/alloy/config.alloy.j2").read_text(encoding="utf-8")
    for component in ('prometheus.exporter.unix "local"',
                      'discovery.docker "docker_targets"',
                      'loki.source.docker "docker_logs"'):
        assert component in body, (
            f'{component} is gone from the live Alloy template. This gate bans '
            "the fragment plugins BECAUSE the live template already does their "
            "job; if it no longer does, the ban is backwards and the fragments "
            "may be the right home after all.")
