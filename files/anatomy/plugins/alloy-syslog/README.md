# alloy-syslog — Phase 3 U13

Composition plugin. Tails host-side log files into Loki:

- nginx (when host nginx is enabled) — access + error
- Wing FrankenPHP/Caddy access log
- Bone, Pulse, OpenClaw launchd stdout/stderr
- Conductor per-run logs at `~/.nos/conductor/*.log` (auto-active once
  pulse-run-agent.sh writes per-run files — A8 follow-up).

## Status

**Structure landed. Activation pending Phase-3 alloy launch flag.**

Same gate as alloy-host-metrics + alloy-docker-metrics. River fragment
at `~/.config/alloy/conf.d/syslog.river` is dormant until Alloy reads
multi-file config.

## Verifying activation (post-Phase-3)

Loki labels:
```bash
curl -s "http://localhost:{{ loki_port }}/loki/api/v1/label/job/values" | jq
```

Expect: at least `nginx`, `wing`, `daemon` (the ones whose log paths
exist on the operator's host).

Tail a daemon stream:
```bash
curl -s -G "http://localhost:{{ loki_port }}/loki/api/v1/query_range" \
  --data-urlencode 'query={job="daemon",service="pulse"}' \
  --data-urlencode 'start='"$(date -u -v -5M +%s)"'000000000' \
  | jq '.data.result[].values | length'
```

Expect: > 0 if Pulse logged anything in the last 5 min.

## Caveats

- Path globs assume macOS Homebrew layout (`/opt/homebrew/var/log/nginx/`,
  `/Users/pazny/...`). Linux ports of nOS will need overrides; addressed
  in `docs/linux-port.md`.
- The `conductor_runs` source matches a path that doesn't exist yet.
  Once `pulse-run-agent.sh` is updated to write per-run log files (A8
  follow-up), the glob auto-tails them without manual config.
- High GDPR surface — see `gdpr:` block in plugin.yml. Especially nginx
  access logs (client IPs) require source-side redaction.
