"""compose.set_image_tag / compose.restart_service — docker compose actions.

Both handlers operate on the rendered override files under
``~/stacks/<stack>/overrides/<service>.yml``.  The override is the file the
service role wrote during the last ``stack-up.yml`` run; the upgrade engine
edits it IN PLACE rather than re-running the role.

Why in-place edit?  It's faster, it avoids a role-rerun dependency, and
(most importantly) it produces a diff the operator can see in
``git status`` / Wing.  The caveat is documented in upgrades/README.md:
if a later playbook run re-renders the override, the manual tag gets
overwritten.  The upgrade engine mitigates this by also recording the new
version in ``~/.nos/state.yml`` under ``services.<svc>.desired`` so any
future render picks it up.

Image-tag manipulation is line-oriented (regex-based) rather than a full
YAML round-trip.  Reason: preserves comments, jinja expressions, and other
rendered artifacts that PyYAML would normalize away.  The pattern we
rewrite is ``<indent>image: <image>:<tag>`` — the only line we touch.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import os.path
import re
import subprocess


DEFAULT_STACKS_DIR = "~/stacks"


def _expand(ctx, path):
    if not path:
        return path
    expander = ctx.get("expand_path") if ctx else None
    if expander is not None:
        return expander(path)
    return os.path.expandvars(os.path.expanduser(path))


def _ok(changed, **extra):
    out = {"success": True, "changed": bool(changed)}
    if extra:
        out["result"] = extra
    return out


def _fail(error, **extra):
    out = {"success": False, "changed": False, "error": str(error)}
    if extra:
        out["result"] = extra
    return out


def _stacks_dir(ctx):
    d = ctx.get("stacks_dir") if ctx else None
    return _expand(ctx, d or DEFAULT_STACKS_DIR)


def _override_path(ctx, stack, service):
    return os.path.join(_stacks_dir(ctx), stack, "overrides", "%s.yml" % service)


def _run(cmd, ctx, cwd=None):
    injected = ctx.get("run_cmd") if ctx else None
    if injected is not None:
        return injected(cmd, cwd=cwd)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# compose.set_image_tag

_IMAGE_RE = re.compile(r"^(?P<prefix>\s*image:\s*)(?P<image>[^:\s]+)(?::(?P<tag>\S+))?\s*$")


def handle_set_image_tag(action, ctx):
    """Rewrite the ``image: <repo>:<tag>`` line in one or more override files.

    action keys:
      stack   (required) — e.g. 'infra', 'observability'
      service (optional) — single override filename stem
      services (optional list[str]) — multiple overrides (authentik-server+worker)
      tag     (required)
      wait    (bool, default true) — run ``docker compose up <stack> --wait``
      compose_project (optional str) — project name; defaults to stack
    """
    stack = action.get("stack")
    tag = action.get("tag")
    if not stack or not tag:
        return _fail("compose.set_image_tag requires 'stack' and 'tag'")

    services = action.get("services")
    if services is None:
        svc = action.get("service")
        if not svc:
            return _fail("compose.set_image_tag requires 'service' or 'services'")
        services = [svc]
    if not isinstance(services, list) or not services:
        return _fail("compose.set_image_tag 'services' must be a non-empty list")

    changed_files = []
    prior = {}
    # `override` decouples the file to rewrite from the compose service names.
    # Some services share one override file (authentik.yml holds both
    # authentik-server + authentik-worker, same image) — per-service file
    # lookup would 404 on authentik-server.yml. When given, we rewrite EVERY
    # image: line in that file whose repo matches the first one.
    override_stem = action.get("override")
    if override_stem:
        path = _override_path(ctx, stack, override_stem)
        if not os.path.lexists(path):
            return _fail("compose.set_image_tag: override %r not found" % path,
                         path=path, override=override_stem)
        before = _read_image_line(path)
        if before is None:
            return _fail("compose.set_image_tag: no image: line in %r" % path,
                         path=path, override=override_stem)
        prior[override_stem] = before
        if before["tag"] != tag:
            if not ctx.get("dry_run"):
                _rewrite_all_image_tags(path, tag)
            changed_files.append(path)
    else:
        for service in services:
            path = _override_path(ctx, stack, service)
            if not os.path.lexists(path):
                return _fail("compose.set_image_tag: override %r not found" % path,
                             path=path, service=service)
            before = _read_image_line(path)
            if before is None:
                return _fail("compose.set_image_tag: no image: line in %r" % path,
                             path=path, service=service)
            prior[service] = before

            if before["tag"] == tag:
                continue

            if ctx.get("dry_run"):
                changed_files.append(path)
                continue

            _rewrite_image_tag(path, tag)
            changed_files.append(path)

    if not changed_files:
        return _ok(False, reason="tags_already_set", tag=tag, services=services)

    wait = bool(action.get("wait", True))
    if wait and not ctx.get("dry_run"):
        project = action.get("compose_project") or stack
        stack_dir = os.path.join(_stacks_dir(ctx), stack)
        # Invoke docker compose via the project's base file(s); the engine
        # is expected to have the overrides glob discovered elsewhere, but
        # for a standalone upgrade we rely on `-p <project>` resolution.
        cmd = ["docker", "compose", "-p", project, "-f",
               os.path.join(stack_dir, "docker-compose.yml")]
        # Include every override under the stack's overrides dir.
        ov_dir = os.path.join(stack_dir, "overrides")
        if os.path.isdir(ov_dir):
            for entry in sorted(os.listdir(ov_dir)):
                if entry.endswith(".yml"):
                    cmd.extend(["-f", os.path.join(ov_dir, entry)])
        # --force-recreate + --pull always: a bare `up -d` sometimes leaves a
        # healthy container untouched even after the override's image tag
        # changed (observed: bookstack override bumped to v26.04.0 but the
        # v26.03.3 container stayed Up, "ok" with drift). Be explicit.
        cmd.extend(["up", "-d", "--force-recreate", "--pull", "always",
                    "--wait"] + list(services))
        proc = _run(cmd, ctx, cwd=stack_dir)
        if proc.returncode != 0:
            return _fail("docker compose up failed: %s" % (proc.stderr or proc.stdout).strip(),
                         cmd=cmd, rc=proc.returncode)

        # Post-condition: the running container actually adopted the new tag.
        # Best-effort (real runs only — skipped when a test injects run_cmd)
        # so silent drift becomes a loud failure instead of a false success.
        if ctx.get("run_cmd") is None:
            drift = _verify_running_tags(project, stack_dir, services, tag, ctx)
            if drift:
                return _fail("compose.set_image_tag: %s still not on tag %r after "
                             "up --force-recreate" % (", ".join(drift), tag),
                             drift=drift, tag=tag)

    return _ok(True, tag=tag, services=services, prior=prior, paths=changed_files)


def _read_image_line(path):
    with open(path, "r") as fh:
        for line in fh:
            m = _IMAGE_RE.match(line.rstrip("\n"))
            if m:
                return {"image": m.group("image"), "tag": m.group("tag") or ""}
    return None


def _rewrite_image_tag(path, new_tag):
    with open(path, "r") as fh:
        lines = fh.readlines()
    out = []
    rewrote = False
    for line in lines:
        if not rewrote:
            m = _IMAGE_RE.match(line.rstrip("\n"))
            if m:
                prefix = m.group("prefix")
                image = m.group("image")
                out.append("%s%s:%s\n" % (prefix, image, new_tag))
                rewrote = True
                continue
        out.append(line)
    tmp = path + ".upgrade-tmp"
    with open(tmp, "w") as fh:
        fh.writelines(out)
    os.replace(tmp, path)


def _rewrite_all_image_tags(path, new_tag):
    """Rewrite EVERY ``image:`` line in ``path`` whose repo matches the first
    one (e.g. authentik.yml's server + worker both on goauthentik/server).
    Returns the count of lines rewritten."""
    with open(path, "r") as fh:
        lines = fh.readlines()
    target_repo = None
    out = []
    n = 0
    for line in lines:
        m = _IMAGE_RE.match(line.rstrip("\n"))
        if m:
            repo = m.group("image")
            if target_repo is None:
                target_repo = repo
            if repo == target_repo:
                out.append("%s%s:%s\n" % (m.group("prefix"), repo, new_tag))
                n += 1
                continue
        out.append(line)
    tmp = path + ".upgrade-tmp"
    with open(tmp, "w") as fh:
        fh.writelines(out)
    os.replace(tmp, path)
    return n


def _verify_running_tags(project, stack_dir, services, tag, ctx):
    """Return the list of services whose running container image does NOT end
    with ``:<tag>``. Best-effort — any probe error yields no drift (we don't
    want a flaky `docker ps` to fail a successful upgrade)."""
    drift = []
    for svc in services:
        try:
            ps = _run(["docker", "compose", "-p", project, "ps", "-q", svc],
                      ctx, cwd=stack_dir)
            cid = (getattr(ps, "stdout", "") or "").strip().splitlines()
            if not cid:
                continue
            insp = _run(["docker", "inspect", "-f", "{{.Config.Image}}", cid[0]],
                        ctx, cwd=stack_dir)
            image = (getattr(insp, "stdout", "") or "").strip()
            if image and not image.endswith(":" + str(tag)):
                drift.append(svc)
        except Exception:
            continue
    return drift


# ---------------------------------------------------------------------------
# compose.restart_service

def handle_restart_service(action, ctx):
    """Restart / stop / up a compose service.

    action keys:
      stack   (required)
      service (required)
      action  ('restart' | 'stop' | 'up'), default 'restart'
      wait    (bool, default true for 'up') — pass --wait to docker compose up
      compose_project (optional) — defaults to stack
    """
    stack = action.get("stack")
    service = action.get("service")
    verb = action.get("action", "restart")
    if not stack or not service:
        return _fail("compose.restart_service requires 'stack' and 'service'")
    if verb not in ("restart", "stop", "up"):
        return _fail("compose.restart_service: unknown action %r" % verb)

    project = action.get("compose_project") or stack
    stack_dir = os.path.join(_stacks_dir(ctx), stack)

    if ctx.get("dry_run"):
        return _ok(True, would_run=True, verb=verb, stack=stack, service=service)

    cmd = ["docker", "compose", "-p", project]
    base = os.path.join(stack_dir, "docker-compose.yml")
    if os.path.lexists(base):
        cmd.extend(["-f", base])
    ov_dir = os.path.join(stack_dir, "overrides")
    if os.path.isdir(ov_dir):
        for entry in sorted(os.listdir(ov_dir)):
            if entry.endswith(".yml"):
                cmd.extend(["-f", os.path.join(ov_dir, entry)])
    if verb == "up":
        cmd.extend(["up", "-d"])
        if bool(action.get("wait", True)):
            cmd.append("--wait")
        cmd.append(service)
    else:
        cmd.extend([verb, service])

    proc = _run(cmd, ctx, cwd=stack_dir)
    if proc.returncode != 0:
        return _fail("docker compose %s failed: %s" % (verb, (proc.stderr or proc.stdout).strip()),
                     cmd=cmd, rc=proc.returncode)
    return _ok(True, verb=verb, stack=stack, service=service)


# ---------------------------------------------------------------------------
# compose.recreate

def handle_recreate(action, ctx):
    """Pull the service's image and force-recreate the container, in place.

    For rolling same-tag updates (e.g. Bluesky PDS ghcr.io/.../pds:0.4) where
    compose.set_image_tag is a no-op (the tag string is unchanged) but we still
    want the latest digest. Runs through the project's full -f override chain
    so the service is actually defined — a bare `docker compose -p <p> up` has
    no compose file in the engine's exec cwd.

    action keys:
      stack   (required)
      service (required)
      wait    (bool, default true) — pass --wait
      compose_project (optional) — defaults to stack
    """
    stack = action.get("stack")
    service = action.get("service")
    if not stack or not service:
        return _fail("compose.recreate requires 'stack' and 'service'")
    project = action.get("compose_project") or stack
    stack_dir = os.path.join(_stacks_dir(ctx), stack)

    if ctx.get("dry_run"):
        return _ok(True, would_recreate=True, stack=stack, service=service)

    base_cmd = ["docker", "compose", "-p", project]
    base = os.path.join(stack_dir, "docker-compose.yml")
    if os.path.lexists(base):
        base_cmd.extend(["-f", base])
    ov_dir = os.path.join(stack_dir, "overrides")
    if os.path.isdir(ov_dir):
        for entry in sorted(os.listdir(ov_dir)):
            if entry.endswith(".yml"):
                base_cmd.extend(["-f", os.path.join(ov_dir, entry)])

    pull = base_cmd + ["pull", service]
    pproc = _run(pull, ctx, cwd=stack_dir)
    if pproc.returncode != 0:
        return _fail("docker compose pull failed: %s" % (pproc.stderr or pproc.stdout).strip(),
                     cmd=pull, rc=pproc.returncode)

    up = base_cmd + ["up", "-d", "--force-recreate", "--no-deps"]
    if bool(action.get("wait", True)):
        up.append("--wait")
    up.append(service)
    uproc = _run(up, ctx, cwd=stack_dir)
    if uproc.returncode != 0:
        return _fail("docker compose up failed: %s" % (uproc.stderr or uproc.stdout).strip(),
                     cmd=up, rc=uproc.returncode)
    return _ok(True, stack=stack, service=service, recreated=True)
