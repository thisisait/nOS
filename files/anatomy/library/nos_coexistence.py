#!/usr/bin/python
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position
"""Ansible module: ``nos_coexistence`` -- dual-version track controller.

Spec reference: ``docs/framework-plan.md`` section 4.4.

This module lets nOS run an old and a new version of the same service
side-by-side, each on its own port and data directory, while nginx
routes live traffic to whichever track is flagged ``active``.  It is
the executor behind ``tasks/coexistence-provision.yml``,
``tasks/coexistence-cutover.yml`` and ``tasks/coexistence-cleanup.yml``.

Actions
-------

``list_tracks``
    Return every track currently recorded in ``~/.nos/state.yml`` under
    ``coexistence.<service>``.  Optional ``service`` arg narrows the
    result.

``provision_track``
    Register a new track for ``service`` with a unique ``tag`` and
    ``version``.  Automatically allocates a port if none is provided
    (``base_port + track_index * coexistence_port_offset``) and refuses
    if the computed port is already bound by a non-coexistence process.
    Renders a Docker-Compose override at
    ``<stacks_dir>/<stack>/overrides/<service>-<tag>.yml`` and a
    per-service nginx routing vhost at
    ``<nginx_sites_dir>/<service>-coexist.conf``.  When
    ``data_source=clone_from:<existing_tag>`` the module also invokes
    the correct data-clone strategy (see
    ``module_utils.nos_coexistence_clone``).  Refuses to overwrite a
    non-empty target data path unless ``force=true``.

``cutover``
    Flip the ``active_track`` pointer for ``service``.  Idempotent: a
    cutover to the already-active tag is a no-op.  The previously
    active track is left running -- stateful tracks are marked
    ``read_only: true`` so the operator can observe them for a cooling-
    off period before running ``cleanup_track``.  The per-service
    nginx vhost is regenerated so the primary upstream now points to
    the new track.

    **Pointer flip ONLY (A4 / Q3, 2026-06-16):** cutover is a dumb,
    instantaneous pointer flip — it runs NO migration data-transform.  The B5
    auto-at-cutover hook was reverted: the data move (``pg_dumpall`` →
    restore into the secondary's cluster) is now an explicit, re-runnable
    ``copy_data`` verb the operator fires on demand BEFORE promoting.  The
    cutover echoes the target's ``source_migration_id`` in ``result`` for
    visibility but never applies it.  Flow: ``provision(empty)`` →
    ``[copy_data]`` → ``[cutover/promote]``.

``copy_data``
    Run the track's recorded migration (``source_migration_id``) data-
    transform against the SECONDARY's (empty) cluster — idempotently, on
    operator demand, re-runnable right before a promote so the secondary
    captures the latest data.  This is the relocated B5 data move: the
    ``nos_migrate action=apply`` engine path that used to fire implicitly
    inside cutover/promote now lives here and ONLY here.  Stamps
    ``data_copied_at`` on the track; does NO pointer flip / vhost regen /
    nginx reload.  Guards: ``G-COPY-HAS-MIGRATION`` (refuse a track with no
    ``source_migration_id``), ``G-COPY-NOT-PRIMARY`` (refuse copying INTO
    the active primary serving live traffic), ``G-COPY-ENGINE`` (fail closed
    if no migration engine is reachable).  ``migration_applied=true`` (set by
    the live task after it ran the ``nos_migrate`` apply itself) short-
    circuits the in-module apply and just stamps ``data_copied_at``.

``promote_track``
    Toggle-as-primary: the reversible operator-facing cutover.  Reuses
    every ``cutover`` mechanic (flip ``active_track`` + regenerate the
    vhost) and additionally stamps the human-facing reversible state
    machine: the promoted track becomes ``role=primary`` /
    ``lifecycle=primary`` / ``read_only=False`` / ``promoted_at`` while
    the prior primary is demoted to ``role=secondary`` /
    ``lifecycle=secondary`` / ``read_only=True`` (with the cooling-off
    ``ttl_until``) -- all in the SAME state write, so the single-primary
    invariant (``role='primary' ⟺ active=1``) never has two primaries.
    Symmetric: re-promoting the other track reverts the toggle.  Refuses
    a draft/cleaned/deactivated target (G-PROMOTE-LIFECYCLE), is a no-op
    on the already-primary (G-PROMOTE-NOOP), and (when a ``port_probe``
    is supplied) refuses a port-down target unless ``force`` (G-PROMOTE-
    HEALTH).

``deactivate_track``
    Take a non-primary track out of rotation WITHOUT destroying it:
    stamps ``role=deactivated`` / ``lifecycle=deactivated`` /
    ``deactivated_at``, drops the track's upstream from the vhost, and
    signals the caller to ``docker compose stop`` (NOT ``down`` -- the
    container, its data dir and its compose override are all kept so the
    track can be re-promoted within the TTL).  Refuses the current
    primary unless ``force`` AND another track exists to fail over to
    (G-DEACTIVATE-NOT-PRIMARY); refuses the only remaining track
    (G-DEACTIVATE-LAST).

``cleanup_track``
    Remove a track.  Refuses to remove the currently active tag unless
    ``force=true``.  By default honors the track's ``ttl_until`` -- if
    the TTL has not yet expired, the module declines.  Pass
    ``respect_ttl=false`` to bypass.  Deletes the compose override
    file and the track's data directory (after taking a timestamped
    ``.backup`` sibling when the data path is a bind mount).

State format (``~/.nos/state.yml``)
-----------------------------------

::

    coexistence:
      grafana:
        active_track: "new"
        tracks:
          - tag: "legacy"
            version: "11.5.0"
            port: 3000
            data_path: "/Volumes/SSD1TB/observability/grafana-legacy"
            stack: "observability"
            started_at: "2026-04-20T10:00:00Z"
            ttl_until: "2026-04-29T00:00:00Z"
            read_only: true
          - tag: "new"
            version: "12.0.0"
            port: 3010
            data_path: "/Volumes/SSD1TB/observability/grafana"
            stack: "observability"
            started_at: "2026-04-24T09:00:00Z"
            cutover_at: "2026-04-24T10:00:00Z"

Supported services (v1) and their default clone strategies
----------------------------------------------------------

* ``grafana``    -- ``cp_recursive`` (bind-mounted data dir).
* ``postgresql`` -- ``pg_dump`` (dump + restore between containers).
* ``mariadb``    -- ``mariadb_dump``.
* ``authentik``  -- ``pg_dump`` (DB-backed state).
* ``gitea``      -- ``cp_recursive`` (repo tree on disk).
* ``nextcloud``  -- ``cp_recursive`` (data dir).
* ``wordpress``  -- ``cp_recursive`` (wp-content); DB clone composed by caller.

Multi-domain services (wordpress + DB, gitea + DB, etc.) may need a
second ``provision_track`` invocation with ``clone_strategy`` set
explicitly.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: nos_coexistence
short_description: Manage nOS dual-version (coexistence) tracks.
description:
  - See module docstring for the full contract.  Implements
    list_tracks / provision_track / cutover / cleanup_track /
    promote_track / deactivate_track / copy_data.
options:
  action:
    description: Sub-command.
    required: true
    choices: [list_tracks, provision_track, cutover, cleanup_track,
              promote_track, deactivate_track, copy_data]
    type: str
  service:
    description: Service id (e.g. grafana, postgresql).
    type: str
  tag:
    description: Track tag (used for provision / cleanup).
    type: str
  target_tag:
    description: Target track for cutover.
    type: str
  version:
    description: Service version this track pins.
    type: str
  source_migration_id:
    description: The migrations_authored.migration_id this track is built
      ON (recorded at provision; CONSUMED by the copy_data action -- the
      migration's apply[] data-transform runs against the secondary track's
      cluster on operator demand, re-runnable). cutover/promote echo it for
      visibility but never apply it (A4 / Q3: the data move left the pointer
      flip).
    type: str
  migration_applied:
    description: Consumed by the copy_data action, IGNORED by cutover/promote
      (A4 / Q3, 2026-06-16). Set true by tasks/coexistence-copy-data.yml when
      the migration's data-transform was already run by a preceding
      nos_migrate action=apply task; copy_data then just stamps data_copied_at
      WITHOUT re-running the in-module engine apply (no double-apply). When
      false and the target carries a source_migration_id, copy_data runs the
      migration in-process (or refuses, failing closed). cutover and promote
      are dumb pointer flips and never read this flag.
    type: bool
    default: false
  port:
    description: Explicit port.  When omitted, computed from base_port
      + track_index * coexistence_port_offset.
    type: int
  base_port:
    description: The baseline port from which offsets are measured.
    type: int
  coexistence_port_offset:
    description: Port delta between consecutive tracks.
    type: int
    default: 10
  data_path:
    description: Target data directory for the new track.
    type: path
  data_source:
    description: One of `empty`, `clone_from:<existing_tag>` or a dict
      describing the underlying clone spec.
    type: raw
  stack:
    description: Docker Compose stack name (e.g. observability).
    type: str
  stacks_dir:
    description: Path to ~/stacks (used to write the compose override).
    type: path
    required: true
  nginx_sites_dir:
    description: Directory that Nginx loads vhosts from.  The module
      writes `<service>-coexist.conf` there.
    type: path
    required: true
  state_path:
    description: Path to ~/.nos/state.yml.
    type: path
    default: ~/.nos/state.yml
  ttl_seconds:
    description: TTL (seconds from now) for the *previous* active
      track during cutover.
    type: int
  force:
    description: Override safety checks (active-track cleanup, non-empty
      data dir, port collision with existing tracks).
    type: bool
    default: false
  respect_ttl:
    description: If true (default), cleanup refuses to delete a track
      whose ttl_until has not yet elapsed.
    type: bool
    default: true
  web_service:
    description: Whether this service is HTTP-reachable and needs an
      nginx routing vhost.
    type: bool
    default: true
  domain:
    description: Public domain for the service (used in nginx template).
    type: str
  clone_strategy:
    description: Override the default clone strategy for the service.
    type: str
    choices: [cp_recursive, pg_dump, mariadb_dump, docker_volume]
  clone_spec:
    description: Extra keyword arguments forwarded to the clone
      strategy (e.g. database, src_container, dst_container).
    type: dict
  dry_run:
    description: Plan without writing files.
    type: bool
    default: false
author:
  - "nOS Agent 5"
"""

RETURN = r"""
changed:
  description: Whether the action mutated state.
  type: bool
  returned: always
result:
  description: Action-specific payload.
  type: dict
  returned: always
"""

import copy
import datetime
import os
import os.path
import socket
import sys

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised in deployed env
    yaml = None  # type: ignore

try:
    from ansible.module_utils.basic import AnsibleModule  # type: ignore
except ImportError:  # pragma: no cover - allow import from tests w/o ansible
    AnsibleModule = None  # type: ignore

# Support two import paths: when invoked by ansible, the package is
# ``ansible.module_utils.nos_coexistence_clone``; when the tests import
# the library file directly, the repo-root ``module_utils/`` is on
# sys.path.
_clone_module = None
try:  # pragma: no cover - ansible context
    from ansible.module_utils import nos_coexistence_clone as _clone_module  # type: ignore
except Exception:  # noqa: BLE001  -- fall through to plain path
    try:
        # Make sure the repo-root module_utils is importable.
        _here = os.path.dirname(os.path.abspath(__file__))
        _repo_root = os.path.dirname(_here)
        if _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)
        import module_utils.nos_coexistence_clone as _clone_module  # type: ignore
    except Exception as _exc:  # pragma: no cover
        _clone_module = None


SUPPORTED_SERVICES = {
    "grafana",
    "postgresql",
    "mariadb",
    "authentik",
    "gitea",
    "nextcloud",
    "wordpress",
    "paperclip",   # PostgreSQL-backed; /paperclip instance dir is bind-mounted (copy_recursive)
}


# Coexistence cooling-TTL default (the one-click-rollback window). When a track
# is promoted the prior primary becomes a read-only secondary with this cooling
# window. The operator-configurable value (``coexistence_secondary_ttl_days``)
# is VALIDATED to the inclusive range [3, 60] days by
# ``tasks/coexistence-ttl-validate.yml`` (the clamp lives in a TASK, not here:
# a vars-file value must stay a bare literal per the {{ vars }} eager-resolve
# trap, and the derived seconds reach this module via the ``ttl_seconds`` param).
# This last-ditch fallback (7 days) only fires if the demotion runs with no
# ttl_seconds threaded at all — e.g. an offline unit test or a skipped validate.
_FALLBACK_TTL_SECONDS = 7 * 24 * 3600   # default 7 days, as seconds


# ---------------------------------------------------------------------------
# state.yml helpers

def _now_iso():
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state(path):
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def _save_state(path, data):
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
    os.replace(tmp, path)


def _get_svc_state(state, service):
    coex = state.setdefault("coexistence", {})
    return coex.setdefault(service, {"active_track": None, "tracks": []})


def _find_track(svc_state, tag):
    for t in svc_state.get("tracks", []):
        if t.get("tag") == tag:
            return t
    return None


# ---------------------------------------------------------------------------
# port helpers

def _port_in_use(port, host="127.0.0.1", probe=None):
    """Return True if a TCP listener is bound to (host, port).

    Tests override via ``probe`` -- a callable that takes (host, port)
    and returns a bool.  Default uses a non-blocking connect.
    """
    if probe is not None:
        return bool(probe(host, port))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def _compute_port(svc_state, base_port, offset):
    """Deterministic port for the next new track.

    The first track (index 0) owns ``base_port``.  Each subsequent
    track is ``base_port + index * offset``.  When an existing track
    already holds the candidate port, skip to the next index until a
    free slot is found.
    """
    existing = {int(t.get("port")) for t in svc_state.get("tracks", []) if t.get("port")}
    idx = len(svc_state.get("tracks", []))
    while True:
        candidate = int(base_port) + idx * int(offset)
        if candidate not in existing:
            return candidate
        idx += 1


# ---------------------------------------------------------------------------
# template rendering

_COMPOSE_TEMPLATE = """# Auto-generated by nos_coexistence -- do not edit by hand.
# service: {service}   tag: {tag}   version: {version}   port: {port}
services:
  {service}-{tag}:
    image: {image}:{version}
    container_name: nos-{service}-{tag}
    restart: unless-stopped
    ports:
      - "127.0.0.1:{port}:{internal_port}"
    volumes:
      - {data_path}:{container_data_path}
    labels:
      - "nos.coexistence.service={service}"
      - "nos.coexistence.tag={tag}"
      - "nos.coexistence.version={version}"
{read_only_block}
"""

_READ_ONLY_BLOCK = "    read_only: true\n"


# Per-service (image-repo, internal-port, container-data-path) used for the
# minimal-template fallback and to locate the data volume in the legacy block.
_IMAGE_MAP = {
    "grafana": ("grafana/grafana", 3000, "/var/lib/grafana"),
    "postgresql": ("postgres", 5432, "/var/lib/postgresql/data"),
    "mariadb": ("mariadb", 3306, "/var/lib/mysql"),
    "authentik": ("ghcr.io/goauthentik/server", 9000, "/media"),
    "gitea": ("gitea/gitea", 3000, "/data"),
    "nextcloud": ("nextcloud", 80, "/var/www/html/data"),
    "wordpress": ("wordpress", 80, "/var/www/html"),
}


def _read_legacy_service(stacks_dir, stack, service):
    """The legacy service's on-disk compose override (rendered by its role) at
    {stacks_dir}/{stack}/overrides/{service}.yml. Returns the service block dict
    or None (missing file / no PyYAML / unparseable) → caller falls back to the
    minimal template."""
    if not stacks_dir or not stack or yaml is None:
        return None
    path = os.path.join(stacks_dir, stack, "overrides", "%s.yml" % service)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001 - any parse error → fallback
        return None
    return (doc.get("services") or {}).get(service)


def _render_from_legacy(legacy, service, tag, version, port,
                        internal_port, data_path, container_data_path, image_fallback):
    """Derive the track from the legacy service block: inherit environment /
    networks / healthcheck / command / limits, swap image tag + container_name +
    hostname + port + the data volume, and tag with coexistence labels. This is
    what lets stateful tracks (postgres needs POSTGRES_PASSWORD) actually boot —
    the minimal template carried none of that."""
    svc = copy.deepcopy(legacy)
    legacy_image = svc.get("image") or image_fallback
    repo = legacy_image.rsplit(":", 1)[0] if ":" in str(legacy_image) else legacy_image
    svc["image"] = "%s:%s" % (repo, version)
    svc["container_name"] = "nos-%s-%s" % (service, tag)
    if svc.get("hostname"):
        svc["hostname"] = "%s-%s" % (service, tag)
    svc.setdefault("restart", "unless-stopped")
    svc["ports"] = ["127.0.0.1:%s:%s" % (port, internal_port)]

    # Replace the volume mounting container_data_path with the track's data dir;
    # keep every other volume (mkcert CA mounts, config binds, …).
    new_vols, replaced = [], False
    for vol in (svc.get("volumes") or []):
        if isinstance(vol, str) and vol.split(":")[1:2] == [container_data_path]:
            new_vols.append("%s:%s" % (data_path, container_data_path))
            replaced = True
        else:
            new_vols.append(vol)
    if not replaced:
        new_vols.append("%s:%s" % (data_path, container_data_path))
    svc["volumes"] = new_vols

    labels = svc.get("labels") or []
    if isinstance(labels, dict):
        labels = ["%s=%s" % (k, v) for k, v in labels.items()]
    svc["labels"] = list(labels) + [
        "nos.coexistence.service=%s" % service,
        "nos.coexistence.tag=%s" % tag,
        "nos.coexistence.version=%s" % version,
    ]

    doc = {"services": {"%s-%s" % (service, tag): svc}}
    header = (
        "# Auto-generated by nos_coexistence -- do not edit by hand.\n"
        "# service: %s   tag: %s   version: %s   port: %s\n"
        "# Derived from the legacy %s override (env / networks / healthcheck inherited).\n"
        % (service, tag, version, port, service)
    )
    return header + yaml.safe_dump(doc, default_flow_style=False, sort_keys=False)


def render_compose_override(params):
    """Render the track's compose override. Prefer DERIVING from the legacy
    service's on-disk override so the track inherits environment / networks /
    healthcheck — a bare template omitted those, so stateful tracks couldn't
    boot (postgres restart-looped: 'POSTGRES_PASSWORD not specified'). Fall back
    to the minimal template when no legacy override is on disk."""
    service = params["service"]
    image, internal_port, container_data_path = _IMAGE_MAP.get(
        service, (service, params.get("internal_port", 80), "/data"))
    container_data_path = params.get("container_data_path", container_data_path)

    legacy = _read_legacy_service(params.get("stacks_dir"), params.get("stack"), service)
    if legacy is not None:
        return _render_from_legacy(
            legacy, service, params["tag"], params["version"], params["port"],
            internal_port, params["data_path"], container_data_path, image,
        )

    # Fallback: minimal self-contained template (no legacy override on disk).
    return _COMPOSE_TEMPLATE.format(
        service=service,
        tag=params["tag"],
        version=params["version"],
        port=params["port"],
        internal_port=internal_port,
        image=params.get("image", image),
        data_path=params["data_path"],
        container_data_path=container_data_path,
        read_only_block=_READ_ONLY_BLOCK if params.get("read_only") else "",
    )


_NGINX_TEMPLATE = """# Auto-generated by nos_coexistence -- do not edit by hand.
# service: {service}   active track: {active_tag}
# Regenerated on every provision / cutover / cleanup.

{upstream_blocks}

server {{
    listen      80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen      443 ssl http2;
    server_name {domain};

    access_log  {nginx_log_dir}/{service}-coexist.access.log main;
    error_log   {nginx_log_dir}/{service}-coexist.error.log warn;

    # Track selection: ?nos_track=<tag> cookie OR query string overrides
    # the active track so operators can side-by-side compare without
    # flipping the pointer.
    set $nos_upstream {active_upstream};
{track_switches}

    location / {{
        proxy_pass         http://$nos_upstream;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-nOS-Track       $nos_track_label;
        add_header         X-nOS-Track       $nos_track_label always;
    }}
}}
"""


def render_nginx_vhost(service, svc_state, params):
    domain = params.get("domain") or "%s.dev.local" % service
    nginx_log_dir = params.get("nginx_log_dir", "/opt/homebrew/var/log/nginx")

    tracks = svc_state.get("tracks", [])
    active = svc_state.get("active_track")

    # Upstream blocks -- one per track.
    upstreams = []
    track_switches_lines = []
    for t in tracks:
        tag = t.get("tag")
        port = t.get("port")
        name = "%s_%s" % (service.replace("-", "_"), tag.replace("-", "_"))
        upstreams.append("upstream %s {\n    server 127.0.0.1:%s;\n}" % (name, port))
        track_switches_lines.append(
            '    if ($arg_nos_track = "%s") { set $nos_upstream %s; set $nos_track_label "%s"; }'
            % (tag, name, tag))
        track_switches_lines.append(
            '    if ($http_cookie ~* "nos_track=%s") { set $nos_upstream %s; set $nos_track_label "%s"; }'
            % (tag, name, tag))

    active_upstream = "127.0.0.1:%s" % (next(
        (t.get("port") for t in tracks if t.get("tag") == active), "80"))
    active_label = active or "unknown"
    # When active matches an upstream block, prefer the symbolic name.
    for t in tracks:
        if t.get("tag") == active:
            active_upstream = "%s_%s" % (service.replace("-", "_"),
                                         t.get("tag").replace("-", "_"))
            break

    header = "    set $nos_track_label \"%s\";" % active_label
    return _NGINX_TEMPLATE.format(
        service=service,
        active_tag=active or "none",
        upstream_blocks="\n".join(upstreams),
        domain=domain,
        nginx_log_dir=nginx_log_dir,
        active_upstream=active_upstream,
        track_switches="\n".join([header] + track_switches_lines),
    )


def _compose_override_path(stacks_dir, stack, service, tag):
    return os.path.join(stacks_dir, stack, "overrides", "%s-%s.yml" % (service, tag))


def _nginx_vhost_path(nginx_sites_dir, service):
    return os.path.join(nginx_sites_dir, "%s-coexist.conf" % service)


# ---------------------------------------------------------------------------
# action handlers

def action_list_tracks(params, state):
    service = params.get("service")
    coex = state.get("coexistence", {}) or {}
    if service:
        return {"changed": False, "result": {"tracks": {service: coex.get(service, {})}}}
    return {"changed": False, "result": {"tracks": coex}}


def action_provision_track(params, state, ctx=None):
    service = params["service"]
    tag = params["tag"]
    version = params["version"]
    stacks_dir = params["stacks_dir"]
    nginx_sites_dir = params["nginx_sites_dir"]
    stack = params.get("stack") or "observability"
    data_path = params.get("data_path")
    force = bool(params.get("force", False))
    web_service = params.get("web_service", True)
    dry_run = bool(params.get("dry_run", False))
    ctx = ctx or {}

    if service not in SUPPORTED_SERVICES:
        return _err("service %r is not in SUPPORTED_SERVICES %r" %
                    (service, sorted(SUPPORTED_SERVICES)))

    svc_state = _get_svc_state(state, service)

    # Reject duplicate tag.
    if _find_track(svc_state, tag) is not None:
        return _err("track %r already exists for service %r" % (tag, service))

    # Port allocation.
    base_port = params.get("base_port")
    offset = params.get("coexistence_port_offset") or 10
    port = params.get("port")
    if port is None:
        if base_port is None:
            return _err("either port or base_port must be provided")
        port = _compute_port(svc_state, base_port, offset)

    # Refuse if this port is already bound to a non-coexistence process.
    existing_ports = {int(t.get("port")) for t in svc_state.get("tracks", []) if t.get("port")}
    if int(port) not in existing_ports:
        if _port_in_use(int(port), probe=ctx.get("port_probe")):
            if not force:
                return _err("port %s is already bound to a non-coexistence process"
                            % port)

    # Refuse if data_path exists and non-empty.
    if data_path and os.path.isdir(data_path) and _is_non_empty_dir(data_path) and not force:
        return _err("data_path %r exists and is non-empty; pass force=true to reuse"
                    % data_path)

    # Data clone (optional).
    clone_result = None
    data_source = params.get("data_source") or "empty"
    if isinstance(data_source, str) and data_source.startswith("clone_from:"):
        src_tag = data_source.split(":", 1)[1]
        src_track = _find_track(svc_state, src_tag)
        if src_track is None:
            return _err("data_source clone_from:%s -- no such track" % src_tag)
        strategy = params.get("clone_strategy") or _clone_strategy_for(service)
        spec = dict(params.get("clone_spec") or {})
        spec.setdefault("src_path", src_track.get("data_path"))
        spec.setdefault("dst_path", data_path)
        spec.setdefault("force", force)
        if not dry_run and _clone_module is not None:
            clone_result = _clone_module.clone(strategy, spec, ctx)
            if not clone_result["success"]:
                return _err("data clone failed: %s" % clone_result["error"],
                            clone=clone_result)
        else:
            clone_result = {"success": True, "changed": True, "dry_run": True,
                            "method": strategy, "details": {"src": spec.get("src_path"),
                                                             "dst": spec.get("dst_path")}}
    elif isinstance(data_source, dict):
        strategy = data_source.get("strategy") or params.get("clone_strategy") \
                   or _clone_strategy_for(service)
        spec = {k: v for k, v in data_source.items() if k != "strategy"}
        if not dry_run and _clone_module is not None:
            clone_result = _clone_module.clone(strategy, spec, ctx)
            if not clone_result["success"]:
                return _err("data clone failed: %s" % clone_result["error"],
                            clone=clone_result)
    # else: empty -- caller provisions a blank data dir separately.

    # Render compose override.
    compose_path = _compose_override_path(stacks_dir, stack, service, tag)
    compose_body = render_compose_override({
        "service": service, "tag": tag, "version": version,
        "port": port, "data_path": data_path,
        "read_only": False,
        "stacks_dir": stacks_dir, "stack": stack,
    })
    vhost_path = _nginx_vhost_path(nginx_sites_dir, service)

    # Build the new state so the vhost can include the new track.
    new_track = {
        "tag": tag,
        "version": version,
        "port": int(port),
        "data_path": data_path,
        "stack": stack,
        "started_at": _now_iso(),
        "read_only": False,
        # Human-facing reversible state machine. The legacy active_track pointer
        # stays the live-routing truth (active=1 ⟺ role='primary'); these mirror
        # it so /coexistence can render a primary/secondary pair. A freshly
        # provisioned (non-active) track is 'provisioned' until promoted.
        "role": "provisioned",
        "lifecycle": "provisioned",
    }
    # The migration this track is built ON (consumed at cutover).
    source_migration_id = params.get("source_migration_id")
    if source_migration_id:
        new_track["source_migration_id"] = source_migration_id
    # First track becomes active automatically — and active ⟺ primary.
    svc_state["tracks"] = list(svc_state.get("tracks", [])) + [new_track]
    if not svc_state.get("active_track"):
        svc_state["active_track"] = tag
        new_track["role"] = "primary"
        new_track["lifecycle"] = "primary"

    vhost_body = render_nginx_vhost(service, svc_state, params) if web_service else None

    if not dry_run:
        _ensure_parent(compose_path)
        with open(compose_path, "w", encoding="utf-8") as fh:
            fh.write(compose_body)
        if vhost_body is not None:
            _ensure_parent(vhost_path)
            with open(vhost_path, "w", encoding="utf-8") as fh:
                fh.write(vhost_body)
        _save_state(params["state_path"], state)

    return {
        "changed": True,
        "result": {
            "track": new_track,
            "port": int(port),
            "compose_override": compose_path,
            "nginx_vhost": vhost_path if web_service else None,
            "clone": clone_result,
            "dry_run": dry_run,
        },
    }


def _resolve_migrate_apply(ctx):
    """Locate the migration-engine apply path the cutover hook consumes.

    Priority:
      1. ``ctx["migrate_apply"]`` -- an injected callable
         ``(migration_id, tokens, dry_run) -> {"success": bool, "error"?}``.
         The live task passes a real one; unit tests stub it. This mirrors the
         existing ``ctx["port_probe"]`` injection idiom exactly.
      2. The in-process ``nos_migrate`` engine (``engine_apply`` resolving by
         ``migration_id`` against ``ctx["migrations_dir"]``) when importable.
      3. None -- the caller must fail the cutover closed (never flip the pointer
         without the data move having run).
    """
    if ctx and ctx.get("migrate_apply") is not None:
        return ctx["migrate_apply"]

    migrations_dir = (ctx or {}).get("migrations_dir")
    if not migrations_dir:
        return None

    # Import the live migration engine the same dual-path way nos_migrate.py
    # does (ansible.module_utils first, repo-root module_utils fallback). The
    # engine resolves the record by id and runs its detect/action/verify/rollback
    # steps -- the SAME action=apply path --tags upgrade/migrate uses.
    _eng = None
    try:  # pragma: no cover - ansible context
        from ansible.module_utils import nos_migrate_engine as _eng  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
            _repo_root = os.path.dirname(_here)
            if _repo_root not in sys.path:
                sys.path.insert(0, _repo_root)
            import module_utils.nos_migrate_engine as _eng  # type: ignore
        except Exception:  # pragma: no cover
            _eng = None
    if _eng is None:
        return None

    def _engine_apply(migration_id, tokens, dry_run):
        # Locate the record by id in migrations_dir (engine_apply consumes a
        # record dict, not an id -- resolve it the way nos_migrate._resolve_record
        # does: scan, then fall back to <dir>/<id>.yml).
        record = None
        for rec_id, _path, loaded in _eng.list_migrations(migrations_dir):
            if rec_id == migration_id:
                record = loaded
                break
        if record is None:
            direct = os.path.join(migrations_dir, "%s.yml" % migration_id)
            if os.path.isfile(direct):
                record = _eng.load_record(direct)
        if record is None:
            return {"success": False,
                    "error": "migration %r not found in %s" % (migration_id, migrations_dir)}
        m_ctx = dict((ctx or {}).get("migrate_ctx") or {})
        m_ctx.setdefault("dry_run", bool(dry_run))
        # Thread the new track's runtime tokens (port / data_path / tag) so the
        # migration's data-transform targets the NEW cluster, not the live one.
        m_ctx.setdefault("tokens", {})
        m_ctx["tokens"].update(tokens or {})
        return _eng.apply(record, ctx=m_ctx, dry_run=bool(dry_run))

    return _engine_apply


def action_cutover(params, state, ctx=None):
    service = params["service"]
    target_tag = params["target_tag"]
    dry_run = bool(params.get("dry_run", False))
    ttl_seconds = params.get("ttl_seconds")
    ctx = ctx or {}

    svc_state = _get_svc_state(state, service)
    target = _find_track(svc_state, target_tag)
    if target is None:
        return _err("cutover target %r does not exist for %r" % (target_tag, service))

    previous = svc_state.get("active_track")
    if previous == target_tag:
        return {"changed": False, "result": {
            "previous_active": previous, "new_active": target_tag,
            "noop": True,
        }}

    # A4 / Q3 (2026-06-16): cutover is a POINTER FLIP ONLY. The B5 auto-at-
    # cutover hook (run the target's migration data-transform here before the
    # flip) was REVERTED -- the data move (pg_dumpall -> restore into the
    # secondary's cluster) is now the explicit, re-runnable `copy_data` verb the
    # operator fires on demand. We read source_migration_id ONLY to echo it in
    # result for visibility; cutover never applies it (and never reads
    # migration_applied). Freshness is the operator's call: re-run copy_data
    # right before this flip.
    source_migration_id = target.get("source_migration_id")

    svc_state["active_track"] = target_tag
    now = _now_iso()
    for t in svc_state.get("tracks", []):
        if t.get("tag") == target_tag:
            t["cutover_at"] = now
            t["read_only"] = False
        elif t.get("tag") == previous:
            t["read_only"] = True
            if ttl_seconds:
                until = datetime.datetime.now(tz=datetime.timezone.utc) + \
                        datetime.timedelta(seconds=int(ttl_seconds))
                t["ttl_until"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")

    vhost_path = _nginx_vhost_path(params["nginx_sites_dir"], service)
    vhost_body = render_nginx_vhost(service, svc_state, params)

    if not dry_run:
        _ensure_parent(vhost_path)
        with open(vhost_path, "w", encoding="utf-8") as fh:
            fh.write(vhost_body)
        _save_state(params["state_path"], state)

    return {
        "changed": True,
        "result": {
            "previous_active": previous,
            "new_active": target_tag,
            "nginx_vhost": vhost_path,
            "cutover_at": now,
            "source_migration_id": source_migration_id,
            # A4 / Q3: cutover runs no migration -> always None (the data move
            # is the copy_data verb). Kept for result-shape stability.
            "migration": None,
        },
    }


def _is_primary(track, active_track):
    """role=primary ⟺ legacy active=1. The legacy ``active_track`` pointer is
    the single source of truth; ``role`` is the human-facing mirror. A track is
    primary iff it is the active track."""
    return track is not None and track.get("tag") == active_track


def action_promote_track(params, state, ctx=None):
    """Toggle-as-primary -- the reversible operator cutover.

    Reuses ``action_cutover`` mechanics (flip ``active_track`` + regenerate the
    vhost) and additionally stamps the reversible primary/secondary state in the
    SAME write so the single-primary invariant never sees two primaries:
    promoted track -> role=primary/read_only=False/promoted_at, the prior
    primary -> role=secondary/read_only=True/ttl_until.
    """
    service = params["service"]
    target_tag = params.get("target_tag") or params.get("tag")
    dry_run = bool(params.get("dry_run", True))   # dry_run defaults TRUE
    force = bool(params.get("force", False))
    ttl_seconds = params.get("ttl_seconds")

    svc_state = _get_svc_state(state, service)
    target = _find_track(svc_state, target_tag)

    # G-PROMOTE-EXISTS: the target track must be provisioned.
    if target is None:
        return _err("promote target %r does not exist for %r" % (target_tag, service))

    # G-PROMOTE-LIFECYCLE: a draft/cleaned/deactivated track is not promotable.
    lifecycle = target.get("lifecycle") or target.get("role") or "provisioned"
    if lifecycle in ("draft", "provisioning", "cleaned", "deactivated"):
        return _err(
            "promote target %r is %s -- only a provisioned/secondary track may "
            "be promoted to primary" % (target_tag, lifecycle))

    previous = svc_state.get("active_track")

    # G-PROMOTE-NOOP: promoting the already-primary is a no-op.
    if previous == target_tag:
        return {"changed": False, "result": {
            "previous_primary": previous, "new_primary": target_tag,
            "noop": True,
        }}

    # G-PROMOTE-HEALTH: refuse a port-down target unless force. Only enforced
    # when a probe is supplied (live runs pass ctx["port_probe"]); offline tests
    # without a probe skip the network check, like provision.
    ctx = ctx or {}
    probe = ctx.get("port_probe")
    if probe is not None and not force:
        port = target.get("port")
        if port and not _port_in_use(int(port), probe=probe):
            return _err("promote target %r port %s is not answering; pass "
                        "force=true to promote a down track" % (target_tag, port))

    # A4 / Q3 (2026-06-16): promote (toggle-as-primary) is a POINTER FLIP ONLY,
    # the reversible sibling of cutover. The B5 auto-at-promote hook (run the
    # target's migration data-transform here before the flip) was REVERTED -- the
    # data move is the explicit, re-runnable `copy_data` verb the operator fires
    # on demand right before this toggle. We read source_migration_id ONLY to
    # echo it in result; promote never applies it (and never reads
    # migration_applied). This keeps promote non-destructive and instantaneous --
    # it never silently runs a 12-minute Postgres dump mid-toggle.
    source_migration_id = target.get("source_migration_id")

    now = _now_iso()
    svc_state["active_track"] = target_tag
    for t in svc_state.get("tracks", []):
        if t.get("tag") == target_tag:
            # New primary.
            t["role"] = "primary"
            t["lifecycle"] = "primary"
            t["read_only"] = False
            t["promoted_at"] = now
            t["cutover_at"] = now
            t.pop("ttl_until", None)
            t.pop("deactivated_at", None)
            # A5 (§6.5): the new primary is NOT a rollback target. Clear any stamp
            # left from a prior demotion so a re-promote drops the marker — this is
            # what guarantees "exactly one rollback target" across a toggle.
            t.pop("demoted_from_primary_at", None)
        elif t.get("tag") == previous:
            # Demote the prior primary in the SAME write (single-primary).
            t["role"] = "secondary"
            t["lifecycle"] = "secondary"
            t["read_only"] = True
            # A5 (§6.5): stamp the just-demoted known-good prior primary as THE
            # one-click-rollback target. Only the previous-primary branch matches
            # (exactly one active primary before the flip), so at most one track
            # ever carries this — the property the Wing rollback button relies on.
            t["demoted_from_primary_at"] = now
            until = datetime.datetime.now(tz=datetime.timezone.utc) + \
                datetime.timedelta(seconds=int(ttl_seconds or _FALLBACK_TTL_SECONDS))
            t["ttl_until"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")

    vhost_path = _nginx_vhost_path(params["nginx_sites_dir"], service)
    vhost_body = render_nginx_vhost(service, svc_state, params)

    if not dry_run:
        _ensure_parent(vhost_path)
        with open(vhost_path, "w", encoding="utf-8") as fh:
            fh.write(vhost_body)
        _save_state(params["state_path"], state)

    return {
        "changed": True,
        "result": {
            "previous_primary": previous,
            "new_primary": target_tag,
            "nginx_vhost": vhost_path,
            "promoted_at": now,
            "dry_run": dry_run,
            "source_migration_id": source_migration_id,
            # A4 / Q3: promote runs no migration -> always None (the data move is
            # the copy_data verb). Kept for result-shape stability.
            "migration": None,
        },
    }


def action_copy_data(params, state, ctx=None):
    """Manual, re-runnable "Copy data" — the relocated B5 data move (A4 / Q3).

    Runs the track's recorded migration (``source_migration_id``) apply[] data-
    transform against the SECONDARY's (empty) cluster, idempotently, on operator
    demand. This is the ONLY consumer of ``_resolve_migrate_apply`` now: the
    ``nos_migrate action=apply`` path that used to fire implicitly inside
    cutover/promote lives here and ONLY here. It does NO pointer flip, NO vhost
    regen, NO nginx reload -- it just moves data into the secondary and stamps
    ``data_copied_at`` so the operator can re-run it right before a promote.

    Guards:
      G-COPY-HAS-MIGRATION  refuse a track with no source_migration_id (an empty
                            provision has nothing to copy).
      G-COPY-NOT-PRIMARY    refuse copying INTO the active primary (never dump
                            into the cluster serving live traffic).
      G-COPY-ENGINE         fail closed if no migration engine is reachable
                            (same contract B5 enforced, re-used here).

    ``migration_applied=true`` short-circuits the in-module apply (the live task
    already ran the nos_migrate apply itself) -- copy_data then just stamps
    ``data_copied_at`` without re-running the engine (no double-apply).
    """
    service = params["service"]
    tag = params.get("tag") or params.get("target_tag")
    dry_run = bool(params.get("dry_run", True))   # dry_run defaults TRUE
    ctx = ctx or {}

    svc_state = _get_svc_state(state, service)
    target = _find_track(svc_state, tag)
    if target is None:
        return _err("copy_data target %r does not exist for %r" % (tag, service))

    # G-COPY-HAS-MIGRATION: an empty provision has no data move to run.
    source_migration_id = target.get("source_migration_id")
    if not source_migration_id:
        return _err(
            "copy_data target %r for %r has no source_migration_id -- an empty "
            "provision has nothing to copy (provision it ON a merged migration "
            "first)" % (tag, service))

    # G-COPY-NOT-PRIMARY: never dump INTO the cluster serving live traffic.
    active = svc_state.get("active_track")
    if _is_primary(target, active):
        return _err(
            "copy_data refuses to copy INTO the active primary %r for %r -- the "
            "data move targets the SECONDARY's empty cluster, never the live one"
            % (tag, service),
            source_migration_id=source_migration_id)

    # migration_applied=true: the live task ran nos_migrate apply itself -> skip
    # the in-module engine apply and just stamp data_copied_at (no double-apply).
    migration_result = None
    already_applied = bool(params.get("migration_applied", False))
    if not already_applied:
        # G-COPY-ENGINE: fail closed if no migration engine is reachable.
        migrate_apply = _resolve_migrate_apply(ctx)
        if migrate_apply is None:
            return _err(
                "copy_data target %r is built ON migration %r but no migration "
                "engine is reachable (set ctx['migrate_apply'] or "
                "ctx['migrations_dir']); refusing to claim a data copy that "
                "never ran" % (tag, source_migration_id),
                source_migration_id=source_migration_id)
        tokens = {
            "coexist_service": service,
            "coexist_tag": tag,
            "coexist_port": target.get("port"),
            "coexist_data_path": target.get("data_path"),
            "coexist_version": target.get("version"),
        }
        try:
            migration_result = migrate_apply(source_migration_id, tokens, dry_run)
        except Exception as exc:  # noqa: BLE001 - surface as a clean copy error
            return _err("copy_data migration %r raised: %s"
                        % (source_migration_id, exc),
                        source_migration_id=source_migration_id)
        if not (isinstance(migration_result, dict)
                and migration_result.get("success")):
            err = (migration_result.get("error")
                   if isinstance(migration_result, dict) else None) \
                or "migration did not report success"
            return _err(
                "copy_data migration %r failed: %s -- data NOT copied"
                % (source_migration_id, err),
                source_migration_id=source_migration_id,
                migration=migration_result)

    # Stamp the copy timestamp. On a dry_run we plan (return the timestamp) but
    # do not persist state -- mirrors promote/deactivate dry_run semantics.
    now = _now_iso()
    if not dry_run:
        for t in svc_state.get("tracks", []):
            if t.get("tag") == tag:
                t["data_copied_at"] = now
                break
        _save_state(params["state_path"], state)

    return {
        "changed": True,
        "result": {
            "service": service,
            "tag": tag,
            "source_migration_id": source_migration_id,
            "data_copied_at": now,
            "dry_run": dry_run,
            "migration": migration_result,
        },
    }


def action_deactivate_track(params, state, ctx=None):
    """Take a non-primary track out of rotation without destroying it.

    Stamps role=deactivated/lifecycle=deactivated/deactivated_at, drops the
    track's upstream from the vhost, and tells the caller to ``docker compose
    stop`` (NOT down -- container + data + override are kept so the track can be
    re-promoted within the TTL).
    """
    service = params["service"]
    tag = params.get("tag")
    force = bool(params.get("force", False))
    dry_run = bool(params.get("dry_run", True))   # dry_run defaults TRUE

    svc_state = _get_svc_state(state, service)
    target = _find_track(svc_state, tag)
    if target is None:
        return _err("deactivate target %r does not exist for %r" % (tag, service))

    tracks = svc_state.get("tracks", [])
    active = svc_state.get("active_track")

    # G-DEACTIVATE-LAST: refuse the only track (nothing to fail over to).
    if len([t for t in tracks if t.get("lifecycle") != "deactivated"]) <= 1:
        return _err("refusing to deactivate the only live track %r for %r "
                    "(nothing to fall back to)" % (tag, service))

    # G-DEACTIVATE-NOT-PRIMARY: refuse the active/primary track unless force
    # AND another live track exists to fail over to.
    if _is_primary(target, active):
        failover = next((t for t in tracks
                         if t.get("tag") != tag
                         and t.get("lifecycle") != "deactivated"), None)
        if not force:
            return _err("refusing to deactivate the primary track %r for %r; "
                        "promote another track first or pass force=true" % (tag, service))
        if failover is None:
            return _err("cannot deactivate primary %r -- no other live track to "
                        "fail over to (would 502)" % tag)
        # Force-deactivating the primary fails over to the next live track.
        svc_state["active_track"] = failover.get("tag")
        failover["role"] = "primary"
        failover["lifecycle"] = "primary"
        failover["read_only"] = False
        failover["promoted_at"] = _now_iso()

    now = _now_iso()
    target["role"] = "deactivated"
    target["lifecycle"] = "deactivated"
    target["deactivated_at"] = now
    target["read_only"] = True

    vhost_path = _nginx_vhost_path(params["nginx_sites_dir"], service)
    # Regenerated vhost no longer routes ?nos_track=<tag> to a stopped track:
    # render from a view of state that omits the deactivated track's upstream.
    vhost_state = {
        "active_track": svc_state.get("active_track"),
        "tracks": [t for t in tracks if t.get("tag") != tag],
    }
    vhost_body = render_nginx_vhost(service, vhost_state, params)

    if not dry_run:
        _ensure_parent(vhost_path)
        with open(vhost_path, "w", encoding="utf-8") as fh:
            fh.write(vhost_body)
        _save_state(params["state_path"], state)

    return {
        "changed": True,
        "result": {
            "service": service,
            "tag": tag,
            "role": "deactivated",
            "compose_action": "stop",   # caller does `docker compose stop`, NOT down
            "nginx_vhost": vhost_path,
            "deactivated_at": now,
            "dry_run": dry_run,
        },
    }


def action_cleanup_track(params, state, ctx=None):
    service = params["service"]
    tag = params["tag"]
    force = bool(params.get("force", False))
    respect_ttl = params.get("respect_ttl", True)
    dry_run = bool(params.get("dry_run", False))

    svc_state = _get_svc_state(state, service)
    target = _find_track(svc_state, tag)
    if target is None:
        return {"changed": False, "result": {"reason": "missing", "tag": tag}}

    if svc_state.get("active_track") == tag and not force:
        return _err("refusing to remove active track %r; pass force=true" % tag)

    # TTL check.
    ttl_until = target.get("ttl_until")
    if respect_ttl and ttl_until and not force:
        try:
            until = datetime.datetime.strptime(ttl_until, "%Y-%m-%dT%H:%M:%SZ")
            until = until.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            until = None
        if until and until > datetime.datetime.now(tz=datetime.timezone.utc):
            remaining = (until - datetime.datetime.now(tz=datetime.timezone.utc)).total_seconds()
            return _err(
                "ttl_until=%s has %ds remaining; pass respect_ttl=false or force=true"
                % (ttl_until, int(remaining)))

    # Determine paths to remove.
    stacks_dir = params["stacks_dir"]
    stack = target.get("stack") or params.get("stack") or "observability"
    compose_path = _compose_override_path(stacks_dir, stack, service, tag)
    data_path = target.get("data_path")

    removed = {
        "compose_override": compose_path,
        "data_path": data_path,
        "backed_up_to": None,
        "data_removed": False,
    }

    if not dry_run:
        if os.path.exists(compose_path):
            os.remove(compose_path)
        if data_path and os.path.isdir(data_path):
            backup = "%s.backup-%s" % (data_path.rstrip("/"),
                                       datetime.datetime.now(tz=datetime.timezone.utc)
                                       .strftime("%Y%m%d%H%M%S"))
            try:
                os.rename(data_path, backup)
                removed["backed_up_to"] = backup
                removed["data_removed"] = True
            except OSError as exc:
                return _err("failed to back up data_path: %s" % exc,
                            data_path=data_path)

        # Remove from state.
        svc_state["tracks"] = [t for t in svc_state.get("tracks", []) if t.get("tag") != tag]
        if svc_state.get("active_track") == tag:
            svc_state["active_track"] = None

        # Regenerate nginx vhost (or remove it if no tracks remain).
        vhost_path = _nginx_vhost_path(params["nginx_sites_dir"], service)
        if svc_state["tracks"]:
            if svc_state.get("active_track") is None:
                # pick first remaining as active
                svc_state["active_track"] = svc_state["tracks"][0].get("tag")
            _ensure_parent(vhost_path)
            with open(vhost_path, "w", encoding="utf-8") as fh:
                fh.write(render_nginx_vhost(service, svc_state, params))
            removed["nginx_vhost"] = vhost_path
        else:
            if os.path.exists(vhost_path):
                os.remove(vhost_path)
            # Also drop the service entry entirely.
            state.get("coexistence", {}).pop(service, None)
            removed["nginx_vhost"] = None

        _save_state(params["state_path"], state)

    return {"changed": True, "result": removed}


# ---------------------------------------------------------------------------
# small utilities

def _err(message, **extra):
    out = {"changed": False, "failed": True, "msg": message, "result": {"error": message}}
    if extra:
        out["result"].update(extra)
    return out


def _ensure_parent(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def _is_non_empty_dir(path):
    if not os.path.isdir(path):
        return False
    try:
        return any(True for _ in os.scandir(path))
    except OSError:
        return False


def _clone_strategy_for(service):
    if _clone_module is not None:
        return _clone_module.SERVICE_DEFAULT_STRATEGY.get(service, "cp_recursive")
    defaults = {
        "grafana": "cp_recursive",
        "postgresql": "pg_dump",
        "mariadb": "mariadb_dump",
        "authentik": "pg_dump",
        "gitea": "cp_recursive",
        "nextcloud": "cp_recursive",
        "wordpress": "cp_recursive",
    }
    return defaults.get(service, "cp_recursive")


# ---------------------------------------------------------------------------
# Dispatch entry point (usable from tests without ansible)

def run_action(params, ctx=None):
    """Pure-python dispatcher exposed for unit tests."""
    state_path = params.get("state_path") or os.path.expanduser("~/.nos/state.yml")
    params = dict(params)
    params["state_path"] = state_path

    state = _load_state(state_path) if os.path.exists(state_path) else {}
    state.setdefault("schema_version", 1)
    state.setdefault("coexistence", {})

    action = params.get("action")
    if action == "list_tracks":
        return action_list_tracks(params, state)
    if action == "provision_track":
        return action_provision_track(params, state, ctx=ctx)
    if action == "cutover":
        return action_cutover(params, state, ctx=ctx)
    if action == "promote_track":
        return action_promote_track(params, state, ctx=ctx)
    if action == "deactivate_track":
        return action_deactivate_track(params, state, ctx=ctx)
    if action == "copy_data":
        return action_copy_data(params, state, ctx=ctx)
    if action == "cleanup_track":
        return action_cleanup_track(params, state, ctx=ctx)
    return _err("unknown action %r" % action)


# ---------------------------------------------------------------------------
# Ansible entry point

def main():  # pragma: no cover - exercised only inside ansible
    if AnsibleModule is None:
        raise SystemExit("ansible is required to run this module directly")

    module = AnsibleModule(
        argument_spec={
            "action": {"type": "str", "required": True,
                       "choices": ["list_tracks", "provision_track",
                                   "cutover", "cleanup_track",
                                   "promote_track", "deactivate_track",
                                   "copy_data"]},
            "service": {"type": "str"},
            "tag": {"type": "str"},
            "target_tag": {"type": "str"},
            "version": {"type": "str"},
            "source_migration_id": {"type": "str"},
            "migration_applied": {"type": "bool", "default": False},
            "port": {"type": "int"},
            "base_port": {"type": "int"},
            "coexistence_port_offset": {"type": "int", "default": 10},
            "data_path": {"type": "path"},
            "data_source": {"type": "raw"},
            "stack": {"type": "str"},
            "stacks_dir": {"type": "path", "required": True},
            "nginx_sites_dir": {"type": "path", "required": True},
            "nginx_log_dir": {"type": "path"},
            "domain": {"type": "str"},
            "state_path": {"type": "path", "default": "~/.nos/state.yml"},
            "ttl_seconds": {"type": "int"},
            "force": {"type": "bool", "default": False},
            "respect_ttl": {"type": "bool", "default": True},
            "web_service": {"type": "bool", "default": True},
            "clone_strategy": {"type": "str",
                               "choices": ["cp_recursive", "pg_dump",
                                           "mariadb_dump", "docker_volume"]},
            "clone_spec": {"type": "dict"},
            "dry_run": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    params = dict(module.params)
    # Treat check mode as dry_run.
    if module.check_mode:
        params["dry_run"] = True
    # Expand ~ in paths.
    for key in ("stacks_dir", "nginx_sites_dir", "state_path", "data_path"):
        v = params.get(key)
        if v:
            params[key] = os.path.expanduser(v)
    result = run_action(params)
    if result.get("failed"):
        module.fail_json(**result)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
