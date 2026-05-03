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
    list_tracks / provision_track / cutover / cleanup_track.
options:
  action:
    description: Sub-command.
    required: true
    choices: [list_tracks, provision_track, cutover, cleanup_track]
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


def render_compose_override(params):
    image_map = {
        "grafana": ("grafana/grafana", 3000, "/var/lib/grafana"),
        "postgresql": ("postgres", 5432, "/var/lib/postgresql/data"),
        "mariadb": ("mariadb", 3306, "/var/lib/mysql"),
        "authentik": ("ghcr.io/goauthentik/server", 9000, "/media"),
        "gitea": ("gitea/gitea", 3000, "/data"),
        "nextcloud": ("nextcloud", 80, "/var/www/html/data"),
        "wordpress": ("wordpress", 80, "/var/www/html"),
    }
    service = params["service"]
    image, internal_port, container_data_path = image_map.get(
        service, (service, params.get("internal_port", 80), "/data"))
    return _COMPOSE_TEMPLATE.format(
        service=service,
        tag=params["tag"],
        version=params["version"],
        port=params["port"],
        internal_port=internal_port,
        image=params.get("image", image),
        data_path=params["data_path"],
        container_data_path=params.get("container_data_path", container_data_path),
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
    }
    # First track becomes active automatically.
    svc_state["tracks"] = list(svc_state.get("tracks", [])) + [new_track]
    if not svc_state.get("active_track"):
        svc_state["active_track"] = tag

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


def action_cutover(params, state, ctx=None):
    service = params["service"]
    target_tag = params["target_tag"]
    dry_run = bool(params.get("dry_run", False))
    ttl_seconds = params.get("ttl_seconds")

    svc_state = _get_svc_state(state, service)
    if _find_track(svc_state, target_tag) is None:
        return _err("cutover target %r does not exist for %r" % (target_tag, service))

    previous = svc_state.get("active_track")
    if previous == target_tag:
        return {"changed": False, "result": {
            "previous_active": previous, "new_active": target_tag,
            "noop": True,
        }}

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
                                   "cutover", "cleanup_track"]},
            "service": {"type": "str"},
            "tag": {"type": "str"},
            "target_tag": {"type": "str"},
            "version": {"type": "str"},
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
