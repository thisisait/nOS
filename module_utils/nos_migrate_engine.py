"""Migration engine — orchestrates a single migration record end to end.

Flow per spec (docs/framework-plan.md section 3.3 + 4.2):

  1. load record (or accept as dict) → validate (schema if available)
  2. gate: evaluate ``applies_if`` (default: true)
  3. preconditions: evaluate each, bail on first failure
  4. foreach step in order:
       a. evaluate step.detect — if false, mark skipped (already done) and
          record a ``step_applied`` entry with changed=false.
       b. dispatch action handler → if fail → begin rollback of completed
          steps (in reverse) and return
       c. evaluate verify predicates (all must pass) → if any fail →
          mark step failed, rollback, return
       d. record step result
  5. post_verify: evaluate each, on failure begin rollback.
  6. persist migration record to state.migrations_applied (via state client).

Rollback rules:

  - step order: reverse of the steps that successfully applied (including any
    that reported changed=false — we still run rollback because verify may
    have partially modified state).
  - each step's ``rollback.type`` is dispatched via the same handler table.
  - ``rollback.type: noop`` is allowed and recorded as "non-reversible".
  - A failure *inside rollback* is recorded but does not halt the loop; the
    engine attempts every remaining rollback and reports aggregate state.

The engine is library code — ``library/nos_migrate.py`` wires it into an
Ansible module.  Tests import the engine directly.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy
import datetime
import glob
import os
import os.path
import time
import uuid

from .nos_migrate_actions import get_handler
from .nos_migrate_detect import evaluate, PredicateError


# ---------------------------------------------------------------------------
# Public result shape

class MigrationResult(dict):
    """Dict subclass purely for type clarity; JSON-serialisable."""


# ---------------------------------------------------------------------------
# Loader + validator

def load_record(path):
    """Load a YAML migration file and return the parsed dict."""
    import yaml  # noqa: WPS433
    with open(path, "r") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("migration file %s must be a mapping" % path)
    return data


def list_migrations(migrations_dir):
    """Return [(id, path, record)] sorted by id."""
    if not os.path.isdir(migrations_dir):
        return []
    out = []
    for path in sorted(glob.glob(os.path.join(migrations_dir, "*.yml"))):
        base = os.path.basename(path)
        if base.startswith("_"):  # _template.yml etc.
            continue
        try:
            rec = load_record(path)
        except Exception:  # pragma: no cover
            continue
        rec_id = rec.get("id") or base[:-4]
        out.append((rec_id, path, rec))
    out.sort(key=lambda t: t[0])
    return out


def list_pending(migrations_dir, state):
    """Return migrations that are not in state.migrations_applied (successful)."""
    applied_ids = set()
    if isinstance(state, dict):
        for entry in state.get("migrations_applied") or []:
            if isinstance(entry, dict) and entry.get("success") and entry.get("id"):
                applied_ids.add(entry["id"])
    return [
        rec for (rec_id, _path, rec) in list_migrations(migrations_dir)
        if rec_id not in applied_ids
    ]


# Minimal structural validator (works without schema file).  When
# ``state/schema/migration.schema.json`` is present, we defer to jsonschema
# for a full check.
_REQUIRED_FIELDS = ("id", "title", "severity", "steps")
_SEVERITY_VALUES = {"patch", "minor", "breaking"}


def validate_record(record, schema_path=None):
    """Raise ValueError on malformed record.  Returns True on success."""
    if not isinstance(record, dict):
        raise ValueError("migration record must be a mapping")
    missing = [f for f in _REQUIRED_FIELDS if f not in record]
    if missing:
        raise ValueError("migration record missing required field(s): %s" %
                         ", ".join(missing))
    if record["severity"] not in _SEVERITY_VALUES:
        raise ValueError("migration.severity must be one of %s (got %r)" %
                         (sorted(_SEVERITY_VALUES), record["severity"]))
    steps = record.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("migration.steps must be a non-empty list")
    step_ids = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError("step[%d] is not a mapping" % i)
        sid = step.get("id")
        if not sid:
            raise ValueError("step[%d] missing 'id'" % i)
        if sid in step_ids:
            raise ValueError("duplicate step id: %r" % sid)
        step_ids.add(sid)
        action = step.get("action")
        if not isinstance(action, dict) or not action.get("type"):
            raise ValueError("step[%s] missing action.type" % sid)

    # Optional JSON-schema validation, if file + library are available.
    if schema_path and os.path.isfile(schema_path):
        try:
            import json
            import jsonschema  # type: ignore
        except ImportError:
            return True  # best-effort; spec validator absent is non-fatal
        try:
            with open(schema_path, "r") as fh:
                schema = json.load(fh)
            jsonschema.validate(record, schema)
        except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
            raise ValueError("migration record violates schema: %s" %
                             exc.message)
    return True


# ---------------------------------------------------------------------------
# Preconditions

def _check_precondition(pre, ctx):
    """Return (ok: bool, detail: dict)."""
    if not isinstance(pre, dict):
        return False, {"error": "precondition must be a mapping"}
    ptype = pre.get("type")
    if not ptype:
        return False, {"error": "precondition missing 'type'"}

    if ptype == "authentik_api_reachable":
        client = ctx.get("authentik_client") if ctx else None
        if client is None:
            factory = ctx.get("authentik_client_factory") if ctx else None
            if callable(factory):
                try:
                    client = factory()
                except Exception as exc:  # pragma: no cover
                    return False, {"error": "authentik factory: %s" % exc}
        if client is None:
            return False, {"error": "authentik client unavailable"}
        timeout = int(pre.get("timeout_sec") or 10)
        if hasattr(client, "wait_api_reachable"):
            try:
                ok = bool(client.wait_api_reachable(timeout_sec=timeout))
            except Exception as exc:
                return False, {"error": "authentik probe failed: %s" % exc}
            return ok, {"timeout_sec": timeout}
        # No probe method: best-effort — a client object exists, assume reachable.
        return True, {"assumed": True}

    if ptype == "no_active_coexistence":
        sc = ctx.get("state_client") if ctx else None
        if sc is None:
            return True, {"assumed": True}
        coexist = sc.get("coexistence", {}) or {}
        if not isinstance(coexist, dict):
            return True, {}
        active = [svc for svc, rec in coexist.items()
                  if isinstance(rec, dict) and rec.get("active_track")]
        return (len(active) == 0), {"active_services": active}

    # treat unknown precondition types as predicates (re-use evaluator).
    try:
        ok = evaluate({"type": ptype, **{k: v for k, v in pre.items() if k != "type"}}, ctx)
        return bool(ok), {}
    except PredicateError as exc:
        return False, {"error": str(exc)}


# ---------------------------------------------------------------------------
# Main engine

def _now_iso():
    # Timezone-aware UTC, second precision, trailing "Z" per ISO-8601.
    tz = getattr(datetime, "UTC", datetime.timezone.utc)
    return datetime.datetime.now(tz).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _state_record_step(ctx, migration_id, step_id, outcome):
    """Append a step event to state.migrations_in_progress.<id>.steps."""
    sc = ctx.get("state_client") if ctx else None
    if sc is None:
        return
    path = "migrations_in_progress.%s.steps" % migration_id
    try:
        steps = sc.get(path, []) or []
        if not isinstance(steps, list):
            steps = []
        steps.append({"id": step_id, "at": _now_iso(), **outcome})
        sc.set(path, steps)
    except Exception:  # pragma: no cover - state writes are best-effort
        pass


def _record_migration_applied(ctx, migration_id, record, result):
    sc = ctx.get("state_client") if ctx else None
    if sc is None:
        return
    try:
        current = sc.get("migrations_applied", []) or []
        if not isinstance(current, list):
            current = []
        entry = {
            "id": migration_id,
            "at": _now_iso(),
            "success": bool(result.get("success")),
            "duration_sec": int(result.get("duration_sec", 0) or 0),
            "steps_applied": int(result.get("steps_applied", 0) or 0),
            "rolled_back_from": result.get("failed_step"),
            "event_run_id": ctx.get("run_id"),
            "severity": record.get("severity"),
            "title": record.get("title"),
        }
        # dedupe by id — last write wins
        current = [e for e in current if not (isinstance(e, dict) and e.get("id") == migration_id)]
        current.append(entry)
        sc.set("migrations_applied", current)
        sc.set("migrations_in_progress.%s" % migration_id, None)
    except Exception:  # pragma: no cover
        pass


def preview(record, ctx=None):
    """Return a dry-run plan — which steps would run, and which would skip."""
    ctx = _normalise_ctx(ctx, dry_run=True, migration=record)
    validate_record(record, schema_path=ctx.get("schema_path"))
    plan = []
    for step in record.get("steps", []):
        detect_pred = step.get("detect")
        try:
            detect_true = evaluate(detect_pred, ctx) if detect_pred else True
        except PredicateError as exc:
            plan.append({"id": step["id"], "would_run": False,
                         "skipped": "detect_error", "error": str(exc)})
            continue
        plan.append({
            "id": step["id"],
            "description": step.get("description"),
            "action_type": (step.get("action") or {}).get("type"),
            "would_run": bool(detect_true),
            "skipped": None if detect_true else "detect_false",
        })
    would_change = any(p.get("would_run") for p in plan)
    return {"plan": plan, "would_change": would_change}


def apply(record, ctx=None, dry_run=False):
    """Apply a migration record.  Returns a structured result dict."""
    started = time.monotonic()
    ctx = _normalise_ctx(ctx, dry_run=dry_run, migration=record)
    migration_id = record.get("id", "<anonymous>")

    # 1. Validate.
    try:
        validate_record(record, schema_path=ctx.get("schema_path"))
    except ValueError as exc:
        return _final(False, migration_id, 0, error=str(exc),
                      phase="validate", started=started)

    # 2. Gate.
    applies = record.get("applies_if")
    try:
        gate_ok = evaluate(applies, ctx) if applies is not None else True
    except PredicateError as exc:
        return _final(False, migration_id, 0,
                      error="applies_if: %s" % exc, phase="gate", started=started)
    if not gate_ok:
        return _final(True, migration_id, 0, phase="gated_out",
                      skipped="applies_if_false", started=started)

    # 3. Preconditions.
    for pre in record.get("preconditions") or []:
        ok, detail = _check_precondition(pre, ctx)
        if not ok:
            return _final(False, migration_id, 0,
                          error="precondition failed: type=%s %s" %
                                (pre.get("type"), detail),
                          phase="precondition", started=started,
                          failed_step=None)

    # 4. Steps.
    applied_steps = []   # list of (step, result_dict) for rollback
    steps = record.get("steps") or []

    for step in steps:
        sid = step["id"]
        # 4a. detect
        detect_pred = step.get("detect")
        try:
            detect_true = evaluate(detect_pred, ctx) if detect_pred else True
        except PredicateError as exc:
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error="step %s detect error: %s" % (sid, exc),
                          phase="detect", failed_step=sid, started=started)
        if not detect_true:
            # Already-done: record and move on, but do NOT add to rollback list
            # because there's nothing to undo.
            _state_record_step(ctx, migration_id, sid,
                               {"status": "skipped", "reason": "detect_false",
                                "changed": False})
            continue

        # 4b. dispatch action
        action = step.get("action") or {}
        action_type = action.get("type")
        try:
            handler = get_handler(action_type)
        except KeyError as exc:
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error=str(exc), phase="dispatch",
                          failed_step=sid, started=started)
        try:
            res = handler(action, ctx)
        except Exception as exc:  # defensive
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error="step %s handler %s raised: %s" %
                                (sid, action_type, exc),
                          phase="action", failed_step=sid, started=started)
        if not isinstance(res, dict) or not res.get("success"):
            _state_record_step(ctx, migration_id, sid,
                               {"status": "failed", "action": action_type,
                                "error": (res or {}).get("error")})
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error=(res or {}).get("error") or
                                "step %s failed" % sid,
                          phase="action", failed_step=sid, started=started,
                          action_result=res)

        # 4c. verify
        verify = step.get("verify") or []
        verify_ok = True
        verify_err = None
        for v in verify:
            try:
                ok = evaluate(v, ctx)
            except PredicateError as exc:
                verify_ok = False
                verify_err = "verify predicate error: %s" % exc
                break
            if not ok:
                verify_ok = False
                verify_err = "verify predicate %r returned false" % v
                break
        if not verify_ok:
            # Record the step as applied so rollback runs too.
            applied_steps.append((step, res))
            _state_record_step(ctx, migration_id, sid,
                               {"status": "verify_failed", "action": action_type,
                                "error": verify_err})
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error=verify_err, phase="verify",
                          failed_step=sid, started=started)

        applied_steps.append((step, res))
        _state_record_step(ctx, migration_id, sid,
                           {"status": "ok", "action": action_type,
                            "changed": bool(res.get("changed"))})

    # 5. post_verify
    for pv in record.get("post_verify") or []:
        try:
            ok = evaluate(pv, ctx)
        except PredicateError as exc:
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error="post_verify error: %s" % exc,
                          phase="post_verify", started=started)
        if not ok:
            _rollback(applied_steps, ctx)
            return _final(False, migration_id, len(applied_steps),
                          error="post_verify predicate %r returned false" % pv,
                          phase="post_verify", started=started)

    # 6. persist applied entry
    result = _final(True, migration_id, len(applied_steps),
                    phase="complete", started=started,
                    steps_total=len(steps))
    _record_migration_applied(ctx, migration_id, record, result)
    return result


def rollback_by_id(migration_id, state, migrations_dir, ctx=None):
    """Roll back a previously-applied migration.

    We re-load the record from disk, walk its steps in reverse, and run each
    ``rollback`` action.  Unlike in-flight rollback (which knows which steps
    actually ran), this applies rollback to *every* step in the record — any
    whose detect-inverse says "already rolled back" can be skipped by the
    handler via idempotence.
    """
    ctx = _normalise_ctx(ctx)
    # Find the migration on disk.
    target = None
    for rec_id, _path, rec in list_migrations(migrations_dir):
        if rec_id == migration_id:
            target = rec
            break
    if target is None:
        return {
            "success": False,
            "error": "migration %r not found in %s" % (migration_id, migrations_dir),
            "steps_rolled_back": 0,
        }
    try:
        validate_record(target, schema_path=ctx.get("schema_path"))
    except ValueError as exc:
        return {"success": False, "error": str(exc), "steps_rolled_back": 0}
    fake_applied = [(step, {"success": True, "changed": True})
                    for step in target.get("steps", [])]
    summary = _rollback(fake_applied, ctx)
    # Update state: mark not-applied.
    sc = ctx.get("state_client")
    if sc is not None:
        try:
            lst = sc.get("migrations_applied", []) or []
            lst = [e for e in lst if not (isinstance(e, dict) and e.get("id") == migration_id)]
            sc.set("migrations_applied", lst)
        except Exception:  # pragma: no cover
            pass
    return {
        "success": summary["success"],
        "steps_rolled_back": summary["rolled_back"],
        "steps_non_reversible": summary["non_reversible"],
        "errors": summary["errors"],
    }


# ---------------------------------------------------------------------------
# internals

def _rollback(applied_steps, ctx):
    """Run rollback for each (step, result) in reverse order.

    Returns a summary dict.  Any single rollback failure is recorded but does
    not abort the loop — we want best-effort recovery.
    """
    errors = []
    rolled = 0
    non_reversible = 0
    for step, _res in reversed(applied_steps):
        rb = step.get("rollback") or {"type": "noop", "reason": "no rollback specified"}
        rb_type = rb.get("type")
        if rb_type == "noop":
            non_reversible += 1
            _state_record_step(ctx, ctx.get("migration_id", ""), step.get("id"),
                               {"status": "non_reversible",
                                "reason": rb.get("reason")})
            continue
        try:
            handler = get_handler(rb_type)
        except KeyError as exc:
            errors.append({"step": step.get("id"), "error": str(exc)})
            continue
        try:
            res = handler(rb, ctx)
        except Exception as exc:
            errors.append({"step": step.get("id"),
                           "error": "rollback handler %s raised: %s" % (rb_type, exc)})
            continue
        if not isinstance(res, dict) or not res.get("success"):
            errors.append({"step": step.get("id"),
                           "error": (res or {}).get("error") or "rollback failed"})
            continue
        rolled += 1
    return {
        "success": not errors,
        "rolled_back": rolled,
        "non_reversible": non_reversible,
        "errors": errors,
    }


def _final(success, migration_id, steps_applied, phase=None, error=None,
           failed_step=None, skipped=None, started=None, action_result=None,
           steps_total=None):
    out = MigrationResult({
        "success": bool(success),
        "migration_id": migration_id,
        "steps_applied": int(steps_applied or 0),
    })
    if steps_total is not None:
        out["steps_total"] = int(steps_total)
    if started is not None:
        out["duration_sec"] = max(0, int(round(time.monotonic() - started)))
    if phase:
        out["phase"] = phase
    if error:
        out["error"] = error
    if failed_step:
        out["failed_step"] = failed_step
    if skipped:
        out["skipped"] = skipped
    if action_result:
        out["last_action_result"] = action_result
    return out


def _normalise_ctx(ctx, dry_run=None, migration=None):
    """Ensure ctx has the keys the handlers rely on."""
    out = dict(ctx or {})
    if dry_run is not None:
        out["dry_run"] = bool(dry_run) or bool(out.get("dry_run"))
    if migration is not None:
        out["migration_id"] = migration.get("id")
        out["migration_allows_shell"] = bool(migration.get("allow_shell"))
    if "run_id" not in out:
        out["run_id"] = "run_%s" % uuid.uuid4().hex[:12]
    return out
