"""A scrape target is a claim that something exists and answers.

FIVE ALERTS HAD BEEN FIRING SINCE 2026-07-26, all `NosWarningServiceDegraded`,
all against healthy containers, none an incident. Measured 2026-08-06 against
the live estate:

  * `qdrant`  localhost:6333/metrics → **401**. The Alloy block's own comment
    said "/metrics is unauthenticated by design ... metrics are exempt".
  * `gitea`   localhost:3003/metrics → **401**. That comment said
    "unauthenticated unless GITEA__metrics__TOKEN is set (it isn't)". It was
    set — and `roles/pazny.gitea/templates/compose.yml.j2` said, in the other
    direction, "the scrape block carries the matching gitea_metrics_token".
    Two files describing each other's behaviour, neither correct.
  * `firefly` localhost:3014/metrics → **404**. Firefly III ships no
    Prometheus endpoint; the target had never returned a metric.
  * `nginx-exporter` / `phpfpm-exporter` — declared unconditionally while
    `install_nginx: false` has been the default since Traefik became the
    primary proxy. Two targets for services a stock estate never installs.

None of this was noticed because the alerts fired into a void: nothing carried
Prometheus's alerts to a human until the Bone relay landed on 2026-08-06. The
morning a channel is unmuted is the worst possible morning to inherit five
standing false alarms — the first thing they teach is to skim.

THE RULE HELD HERE: a scrape target must be conditional on the thing it
scrapes existing, and must carry whatever credential that thing requires. This
gate renders the templates and inspects the result, because the defect was
never in what the file said — it was in what it sent.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PROM = REPO / "files/anatomy/plugins/prometheus-base/provisioning/prometheus.yml.j2"
ALLOY = REPO / "files/observability/alloy/config.alloy.j2"


def _env() -> jinja2.Environment:
    # ChainableUndefined mirrors Ansible's tolerance for absent facts; the
    # point of this render is the scrape blocks, not the host facts around them.
    return jinja2.Environment(
        trim_blocks=True, undefined=jinja2.ChainableUndefined, keep_trailing_newline=True
    )


def _prom_jobs(install_nginx: bool) -> list[str]:
    out = _env().from_string(PROM.read_text(encoding="utf-8")).render(
        install_nginx=install_nginx,
        observability_hostname="h", ansible_facts={"hostname": "h"},
        prometheus_port=9090, grafana_port=3000, loki_port=3100,
        tempo_http_port=3200, alloy_ui_port=12345,
        nginx_exporter_port=9113, phpfpm_exporter_port=9253,
    )
    doc = yaml.safe_load(out)
    assert isinstance(doc, dict) and doc.get("scrape_configs"), (
        "the rendered prometheus.yml has no scrape_configs — the template broke"
    )
    return [j["job_name"] for j in doc["scrape_configs"]]


def _alloy(**overrides) -> str:
    base = dict(
        install_gitea=True, alloy_scrape_qdrant=True, install_firefly=True,
        install_influxdb=True, gitea_port=3003, qdrant_port=6333,
        firefly_port=3014, influxdb_port=8086,
        gitea_metrics_token="GITEA-TOKEN", qdrant_api_key_ro="QDRANT-RO",
        global_password_prefix="p",
    )
    base.update(overrides)
    return _env().from_string(ALLOY.read_text(encoding="utf-8")).render(**base)


def test_the_host_exporters_follow_install_nginx():
    """They scrape a host nginx and its php-fpm. With `install_nginx: false`
    — the default — neither process exists."""
    with_nginx = _prom_jobs(True)
    without = _prom_jobs(False)

    for job in ("nginx-exporter", "phpfpm-exporter"):
        assert job in with_nginx, f"{job} vanished even with install_nginx=true"
        assert job not in without, (
            f"{job} is scraped with install_nginx=false. It is a standing "
            f"false positive on every stock estate, and since 2026-08-06 the "
            f"Bone relay delivers it."
        )
    # Guard the guard: the gating must not have swallowed the rest of the file.
    assert len(without) >= 5, f"only {len(without)} jobs survive the gate: {without}"


def test_both_scrape_paths_agree_that_the_exporters_are_optional():
    """Two collectors, one decision — and only one of them knew it.

    Alloy already derived `alloy_scrape_nginx` / `alloy_scrape_phpfpm` from
    `install_nginx` in default.config.yml. `prometheus.yml.j2` scraped the same
    two exporters unconditionally. The estate therefore held one fact twice and
    disagreed with itself for months; the half that was wrong is the half that
    alerted. This keeps them in step.
    """
    config = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8"))
    for var in ("alloy_scrape_nginx", "alloy_scrape_phpfpm"):
        expr = str(config.get(var, ""))
        assert "install_nginx" in expr, (
            f"{var} no longer derives from install_nginx ({expr!r}). Alloy and "
            f"Prometheus would then disagree about whether the host exporters "
            f"exist, and whichever is wrong becomes a permanent alert."
        )


@pytest.mark.parametrize(
    "job, var, value",
    [
        ("gitea", "gitea_metrics_token", "GITEA-TOKEN"),
        ("qdrant", "qdrant_api_key_ro", "QDRANT-RO"),
    ],
)
def test_the_authenticated_endpoints_are_scraped_with_a_credential(job, var, value):
    """Both answer 401 without one — measured, not assumed. A scrape with no
    credential against an endpoint that needs one is a target guaranteed to
    fail, and the alert it raises says 'degraded' about a healthy service."""
    rendered = _alloy()
    block = rendered[rendered.find(f'prometheus.scrape "{job}"'):]
    block = block[: block.find("\n}") + 2]
    assert block, f"no prometheus.scrape block for {job}"
    assert "bearer_token" in block, (
        f"the {job} scrape sends no credential. Measured 2026-08-06: "
        f"/metrics answers 401 without one."
    )
    assert value in block, (
        f"the {job} scrape's bearer_token does not come from {var} — it "
        f"rendered to something else, so the credential is not the one the "
        f"service was configured with"
    )


def test_qdrant_is_scraped_with_the_read_only_key():
    """A scraper reads. Handing it the full API key would give the metrics
    path write authority it has no use for."""
    rendered = _alloy(qdrant_api_key="FULL-KEY", qdrant_api_key_ro="RO-KEY")
    block = rendered[rendered.find('prometheus.scrape "qdrant"'):]
    block = block[: block.find("\n}") + 2]
    assert "RO-KEY" in block and "FULL-KEY" not in block, (
        "the qdrant scrape carries the full API key instead of the read-only one"
    )


def test_firefly_has_no_scrape_at_all():
    """Not gated — GONE. Firefly III has no /metrics; the endpoint answered 404
    for as long as it was scraped. A gate would imply the target works when
    the flag is on."""
    assert 'prometheus.scrape "firefly"' not in _alloy(), (
        "the firefly scrape is back. Firefly III publishes no Prometheus "
        "endpoint — measured 404 against the running container. Metrics would "
        "need a sidecar exporter, not a path."
    )
