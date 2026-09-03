# 58 — A fix list that still teaches the old probe

**Found** 2026-09-02; **closed** 2026-09-03.

`test_healthcheck_coverage.py`'s FIXED entry for hedgedoc still described the
bash TCP :3000 probe that fee 02 replaced with the node `/status` DB-aware one
— and the companion assertion only checked that a `healthcheck:` block EXISTS,
so reverting hedgedoc to bare TCP would have passed. The allowlist taught its
own stale answer (fee 22's shape, in a gate file).

Close: the FIXED string describes the current probe; the uptime-kuma entry
gained the pointer to the converge-time wizard check it silently relied on;
and fee 02 gained the TCP-connect-only sub-class section (stalwart, mcpo,
qgis) the sweep surfaced. The per-service probe-string pin for hedgedoc rides
the existing miniflux pattern when someone touches that file next.
