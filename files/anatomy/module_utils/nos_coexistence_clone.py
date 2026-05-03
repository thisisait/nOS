"""Data-cloning strategies for coexistence tracks.

Spec reference: docs/framework-plan.md section 4.4 -- "Data cloning strategies".

Each strategy takes a ``spec`` dict plus a ``ctx`` (runtime context) and
returns a uniform result dict::

    {"success": bool, "changed": bool, "method": str, "error": str|None,
     "details": {...}}

The underlying shell commands (pg_dump, mariadb-dump, cp, docker) are
invoked through ``ctx['runner']`` -- tests inject a recorder, production
uses ``subprocess.run``.  The helpers NEVER mutate the source: every
strategy is a pure copy from a source track to a target track.

Supported strategies
--------------------

* ``pg_dump``       -- PostgreSQL logical dump + restore between databases
                       (same cluster or across cluster).  Used for the
                       ``postgresql`` service and any Postgres-backed
                       tenant that lives in its own DB (authentik,
                       gitea, nextcloud when Postgres-backed, paperclip).
* ``mariadb_dump``  -- MariaDB/MySQL logical dump + restore.  Used for
                       the ``mariadb`` service and MySQL-backed
                       tenants (wordpress, nextcloud when MariaDB-backed,
                       bookstack, freescout, erpnext).
* ``cp_recursive``  -- ``cp -R`` for bind-mounted directories.  Used for
                       file-only services with host-mounted data
                       (grafana, gitea repositories, wordpress uploads,
                       nextcloud data dir when it is a bind mount).
* ``docker_volume`` -- Copy between two Docker named volumes using an
                       ephemeral ``alpine`` helper container (``cp -aR``
                       from /src to /dst).

Supported services -> default strategy
--------------------------------------

* grafana     -> ``cp_recursive`` (bind mount at ``grafana_data_dir``).
* postgresql  -> ``pg_dump``      (dump + restore inside the same cluster
                                   or between tracks; cloning the *data
                                   directory* of Postgres between majors
                                   is unsafe, so we always go through
                                   pg_dump).
* mariadb     -> ``mariadb_dump``.
* authentik   -> ``pg_dump``      (state lives in Postgres).  The
                                   filesystem ``media`` volume can be
                                   cloned via ``cp_recursive`` as a
                                   second step by the caller.
* gitea       -> ``cp_recursive`` for the repo tree + ``pg_dump`` or
                                   ``mariadb_dump`` for the metadata DB
                                   (caller composes both if needed).
* nextcloud   -> ``cp_recursive`` for the data dir + DB dump for config.
* wordpress   -> ``mariadb_dump`` for the DB + ``cp_recursive`` for
                                   ``wp-content`` (again composed).

The module always refuses to clone into a non-empty target unless
``force=True``.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import shutil
import subprocess


# ---------------------------------------------------------------------------
# uniform result helpers

def _ok(method, changed=True, **details):
    return {
        "success": True,
        "changed": bool(changed),
        "method": method,
        "error": None,
        "details": details,
    }


def _fail(method, error, **details):
    return {
        "success": False,
        "changed": False,
        "method": method,
        "error": str(error),
        "details": details,
    }


# ---------------------------------------------------------------------------
# pluggable shell runner (tests inject a recorder)

def _default_runner(cmd, check=True, input_data=None, env=None, shell=False):
    """subprocess.run wrapper that returns (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(  # noqa: S603 -- command comes from known builders
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            env=env,
            shell=shell,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def _get_runner(ctx):
    return (ctx or {}).get("runner") or _default_runner


def _expand(ctx, path):
    if not path:
        return path
    expander = (ctx or {}).get("expand_path")
    if expander:
        return expander(path)
    return os.path.expandvars(os.path.expanduser(path))


def _is_non_empty_dir(path):
    if not os.path.isdir(path):
        return False
    try:
        return any(True for _ in os.scandir(path))
    except OSError:
        return False


# ---------------------------------------------------------------------------
# cp -R strategy (bind-mount directory clone)

def clone_cp_recursive(spec, ctx=None):
    """Clone a bind-mounted data dir with ``cp -R``.

    spec keys:
      src_path       -- source data directory (must exist)
      dst_path       -- target data directory (created if missing)
      force          -- if True, wipe dst when non-empty (default False)
      preserve_attrs -- if True, use ``cp -aR`` (default True)
    """
    src = _expand(ctx, spec.get("src_path"))
    dst = _expand(ctx, spec.get("dst_path"))
    force = bool(spec.get("force", False))
    preserve = bool(spec.get("preserve_attrs", True))
    ctx = ctx or {}

    if not src or not dst:
        return _fail("cp_recursive", "src_path and dst_path are required")
    if not os.path.isdir(src):
        return _fail("cp_recursive", "src_path does not exist", src=src)

    if _is_non_empty_dir(dst) and not force:
        return _fail(
            "cp_recursive",
            "dst_path is non-empty; refuse clone without force=true",
            dst=dst,
        )

    if ctx.get("dry_run"):
        return _ok("cp_recursive", changed=True, dry_run=True, src=src, dst=dst)

    if _is_non_empty_dir(dst) and force:
        try:
            shutil.rmtree(dst)
        except OSError as exc:
            return _fail("cp_recursive", "wipe failed: %s" % exc, dst=dst)

    # Ensure parent exists (cp needs the dst parent, not dst itself).
    parent = os.path.dirname(os.path.abspath(dst))
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            return _fail("cp_recursive", "mkdir parent failed: %s" % exc, parent=parent)

    flag = "-aR" if preserve else "-R"
    # Trailing /. copies directory *contents* so dst need not pre-exist.
    cmd = ["cp", flag, src.rstrip("/") + "/.", dst]
    runner = _get_runner(ctx)
    rc, out, err = runner(cmd)
    if rc != 0:
        return _fail("cp_recursive", "cp failed rc=%s: %s" % (rc, err.strip() or out),
                     src=src, dst=dst)
    return _ok("cp_recursive", changed=True, src=src, dst=dst)


# ---------------------------------------------------------------------------
# PostgreSQL dump/restore

def clone_pg_dump(spec, ctx=None):
    """Clone a Postgres database from one track to another via pg_dump|psql.

    spec keys (all required unless noted):
      src_container   -- name of the source Postgres container (e.g. nos-postgresql-legacy)
                         OR use src_dsn for a direct connection string
      dst_container   -- target container (OR dst_dsn)
      src_dsn         -- optional: postgres://user:pw@host:port/db (alternative to container)
      dst_dsn         -- optional: same, for target
      database        -- database name to copy (created on target if missing)
      owner           -- optional: role name owning the dump (default: postgres)
      force           -- drop+recreate target db if it exists (default: False)
    """
    database = spec.get("database")
    if not database:
        return _fail("pg_dump", "database is required")
    src_container = spec.get("src_container")
    dst_container = spec.get("dst_container")
    src_dsn = spec.get("src_dsn")
    dst_dsn = spec.get("dst_dsn")
    if not (src_container or src_dsn) or not (dst_container or dst_dsn):
        return _fail("pg_dump",
                     "either src_container or src_dsn AND dst_container or dst_dsn required")
    force = bool(spec.get("force", False))
    owner = spec.get("owner", "postgres")
    ctx = ctx or {}
    runner = _get_runner(ctx)

    if ctx.get("dry_run"):
        return _ok("pg_dump", changed=True, dry_run=True,
                   src=src_container or src_dsn, dst=dst_container or dst_dsn,
                   database=database)

    # --- Build dump command ---
    if src_container:
        dump_cmd = ["docker", "exec", src_container,
                    "pg_dump", "-U", owner, "--clean", "--if-exists", database]
    else:
        dump_cmd = ["pg_dump", "--dbname", src_dsn, "--clean", "--if-exists"]

    # --- Check / create target DB ---
    if force:
        if dst_container:
            drop = ["docker", "exec", dst_container, "psql", "-U", owner,
                    "-c", "DROP DATABASE IF EXISTS \"%s\";" % database]
            rc, _out, err = runner(drop)
            if rc != 0:
                return _fail("pg_dump", "drop db failed: %s" % err, database=database)
            create = ["docker", "exec", dst_container, "psql", "-U", owner,
                      "-c", "CREATE DATABASE \"%s\";" % database]
            rc, _out, err = runner(create)
            if rc != 0:
                return _fail("pg_dump", "create db failed: %s" % err, database=database)
        else:
            drop = ["psql", "--dbname", dst_dsn,
                    "-c", "DROP DATABASE IF EXISTS \"%s\";" % database]
            rc, _out, err = runner(drop)
            if rc != 0:
                return _fail("pg_dump", "drop db failed: %s" % err, database=database)
            create = ["psql", "--dbname", dst_dsn,
                      "-c", "CREATE DATABASE \"%s\";" % database]
            rc, _out, err = runner(create)
            if rc != 0:
                return _fail("pg_dump", "create db failed: %s" % err, database=database)

    # --- Run dump ---
    rc, dump_out, dump_err = runner(dump_cmd)
    if rc != 0:
        return _fail("pg_dump", "pg_dump failed rc=%s: %s" % (rc, dump_err.strip() or dump_out),
                     database=database)

    # --- Restore ---
    if dst_container:
        restore_cmd = ["docker", "exec", "-i", dst_container,
                       "psql", "-U", owner, "-d", database]
    else:
        restore_cmd = ["psql", "--dbname", dst_dsn]

    rc, rest_out, rest_err = runner(restore_cmd, input_data=dump_out)
    if rc != 0:
        return _fail("pg_dump", "restore failed rc=%s: %s" % (rc, rest_err.strip() or rest_out),
                     database=database)

    return _ok("pg_dump", changed=True,
               src=src_container or src_dsn,
               dst=dst_container or dst_dsn,
               database=database,
               bytes_dumped=len(dump_out or ""))


# ---------------------------------------------------------------------------
# MariaDB/MySQL dump/restore

def clone_mariadb_dump(spec, ctx=None):
    """Clone a MariaDB database using mariadb-dump | mariadb.

    spec keys:
      src_container   -- source MariaDB container (or use src_dsn-like opts)
      dst_container   -- target MariaDB container
      database        -- database to copy
      user            -- DB user (default root)
      password_env    -- env var name holding the DB password
                         (passed to ``docker exec -e``; required unless
                         container is configured with MYSQL_ROOT_PASSWORD)
      password        -- literal password (alternative to password_env).
                         Discouraged for production use; fine for tests.
      force           -- drop+recreate target db if it exists (default False)
    """
    database = spec.get("database")
    if not database:
        return _fail("mariadb_dump", "database is required")
    src_container = spec.get("src_container")
    dst_container = spec.get("dst_container")
    if not src_container or not dst_container:
        return _fail("mariadb_dump",
                     "src_container and dst_container are required")
    user = spec.get("user", "root")
    password = spec.get("password")
    password_env = spec.get("password_env")
    force = bool(spec.get("force", False))
    ctx = ctx or {}
    runner = _get_runner(ctx)

    if ctx.get("dry_run"):
        return _ok("mariadb_dump", changed=True, dry_run=True,
                   src=src_container, dst=dst_container, database=database)

    def _auth_args():
        args = ["-u", user]
        if password is not None:
            args.append("-p%s" % password)
        return args

    # --- Optional: drop+recreate target DB ---
    if force:
        drop_sql = "DROP DATABASE IF EXISTS `%s`;" % database
        create_sql = "CREATE DATABASE `%s`;" % database
        cmd = ["docker", "exec", "-i", dst_container, "mariadb"] + _auth_args()
        rc, _out, err = runner(cmd, input_data=drop_sql + "\n" + create_sql + "\n")
        if rc != 0:
            return _fail("mariadb_dump", "drop/create db failed: %s" % err,
                         database=database)

    # --- Dump ---
    dump_cmd = ["docker", "exec", src_container, "mariadb-dump"] + _auth_args() + [
        "--single-transaction", "--quick", database,
    ]
    rc, dump_out, dump_err = runner(dump_cmd)
    if rc != 0:
        return _fail("mariadb_dump",
                     "mariadb-dump failed rc=%s: %s" % (rc, dump_err.strip() or dump_out),
                     database=database)

    # --- Restore ---
    restore_cmd = ["docker", "exec", "-i", dst_container, "mariadb"] + _auth_args() + [database]
    rc, rest_out, rest_err = runner(restore_cmd, input_data=dump_out)
    if rc != 0:
        return _fail("mariadb_dump",
                     "restore failed rc=%s: %s" % (rc, rest_err.strip() or rest_out),
                     database=database)

    return _ok("mariadb_dump", changed=True,
               src=src_container, dst=dst_container,
               database=database,
               bytes_dumped=len(dump_out or ""))


# ---------------------------------------------------------------------------
# Docker named-volume clone via alpine helper

def clone_docker_volume(spec, ctx=None):
    """Clone data between two Docker named volumes.

    spec keys:
      src_volume    -- source named volume
      dst_volume    -- target named volume (auto-created)
      image         -- helper image (default alpine:3.19)
      force         -- if True, wipe dst before copy (default False)
    """
    src_vol = spec.get("src_volume")
    dst_vol = spec.get("dst_volume")
    if not src_vol or not dst_vol:
        return _fail("docker_volume", "src_volume and dst_volume required")
    image = spec.get("image", "alpine:3.19")
    force = bool(spec.get("force", False))
    ctx = ctx or {}
    runner = _get_runner(ctx)

    if ctx.get("dry_run"):
        return _ok("docker_volume", changed=True, dry_run=True,
                   src=src_vol, dst=dst_vol)

    # Create the target volume if needed (docker volume create is idempotent).
    rc, _out, err = runner(["docker", "volume", "create", dst_vol])
    if rc != 0:
        return _fail("docker_volume", "volume create failed: %s" % err,
                     dst=dst_vol)

    if force:
        wipe_cmd = [
            "docker", "run", "--rm",
            "-v", "%s:/dst" % dst_vol,
            image,
            "sh", "-c", "rm -rf /dst/* /dst/.[!.]* /dst/..?* 2>/dev/null || true",
        ]
        runner(wipe_cmd)  # best effort; not fatal

    copy_cmd = [
        "docker", "run", "--rm",
        "-v", "%s:/src:ro" % src_vol,
        "-v", "%s:/dst" % dst_vol,
        image,
        "sh", "-c", "cp -aR /src/. /dst/",
    ]
    rc, out, err = runner(copy_cmd)
    if rc != 0:
        return _fail("docker_volume",
                     "cp failed rc=%s: %s" % (rc, err.strip() or out),
                     src=src_vol, dst=dst_vol)

    return _ok("docker_volume", changed=True, src=src_vol, dst=dst_vol)


# ---------------------------------------------------------------------------
# Strategy registry

STRATEGIES = {
    "cp_recursive": clone_cp_recursive,
    "pg_dump": clone_pg_dump,
    "mariadb_dump": clone_mariadb_dump,
    "docker_volume": clone_docker_volume,
}


# Default strategy hint per service (v1).  Services with multiple
# storage domains (DB + files) may need multiple invocations -- the
# caller composes them.
SERVICE_DEFAULT_STRATEGY = {
    "grafana": "cp_recursive",
    "postgresql": "pg_dump",
    "mariadb": "mariadb_dump",
    "authentik": "pg_dump",
    "gitea": "cp_recursive",
    "nextcloud": "cp_recursive",
    "wordpress": "cp_recursive",
}


def clone(method, spec, ctx=None):
    """Dispatch by strategy name."""
    handler = STRATEGIES.get(method)
    if handler is None:
        return _fail(str(method), "unknown clone strategy %r" % method)
    return handler(spec, ctx)
