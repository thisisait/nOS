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
               os.path.join(stack_dir, "compose.yml")]
        # Include every override under the stack's overrides dir.
        ov_dir = os.path.join(stack_dir, "overrides")
        if os.path.isdir(ov_dir):
            for entry in sorted(os.listdir(ov_dir)):
                if entry.endswith(".yml"):
                    cmd.extend(["-f", os.path.join(ov_dir, entry)])
        cmd.extend(["up", "-d", "--wait"] + list(services))
        proc = _run(cmd, ctx, cwd=stack_dir)
        if proc.returncode != 0:
            return _fail("docker compose up failed: %s" % (proc.stderr or proc.stdout).strip(),
                         cmd=cmd, rc=proc.returncode)

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
    base = os.path.join(stack_dir, "compose.yml")
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
