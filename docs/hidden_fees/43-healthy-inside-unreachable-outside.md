# 43 — Healthy inside, unreachable from the host

**Paid:** twice in one day — 2026-09-01 evening and 2026-09-02 morning, ~40
minutes each, both spent proving the estate was fine.

## What it looks like

`nos-smoke` reads 3/16. Twelve services answer `000`, `Connection reset by
peer`, or `SSL: UNEXPECTED_EOF_WHILE_READING`. The three that pass are the only
three that are **not** Docker: bone, wing and openclaw are host launchd
services.

Every service is healthy. Measured from inside:

    prometheus  /-/healthy              "Prometheus Server is Healthy."
    traefik     :8080/ping              OK
    peer -> prometheus:9090/-/healthy   200
    peer -> traefik:443 (Host header)   200

The container↔container fabric is untouched. Traefik's own access log shows it
serving requests every minute throughout.

## Why it wastes time

Three separate lies, each of which reads as a different fault:

**`nc` says the port is open.** Docker's proxy holds a host-side listener
(`lsof` shows `com.docker` LISTEN on 127.0.0.1:8082) and accepts the TCP
connection before discovering it cannot forward. So a port check passes and
every request fails.

**`openssl s_client` says `no peer certificate available`.** That sends you to
the certificate, which is fine — files present, readable in-container, `tls.yml`
store correct, traefik's log clean. TLS is not involved. The connection dies
before the handshake.

**It is PARTIAL, so the pattern looks meaningful and is not.** Same host, same
minute, identical publish specs:

    observability-loki-1        3100/tcp -> 127.0.0.1:3100     200
    iiab-keap-1                 8080/tcp -> 127.0.0.1:8091     401
    observability-prometheus-1  9090/tcp -> 127.0.0.1:9090     000
    infra-traefik-1             8080/tcp -> 127.0.0.1:8082     000

Not the bind address, not loopback-vs-`0.0.0.0`, not the stack, not health.

## What does not fix it

A Docker restart. It cleared the fault on 2026-09-01 and did not on 2026-09-02
— same symptom, restart, still 3/16.

## The rule

**Ask the container before believing the host.** A smoke run from the host
measures Docker's port forwarder as much as it measures the estate, and cannot
tell them apart. `docker exec <c> wget -qO- 127.0.0.1:<port>/<health>` and a
peer-container request separate the two in one command each.

Environment when observed: macOS 26.6.1 (25G76), Docker 29.4.2, VM cap
17920 MiB / 12 CPU, VM RSS 10.6 GiB.

## What is owed

`tests/anatomy/test_hub_url_audit.py` treats `000` as a hard 404 and lists a
reachable service as drift. Unreachable and 404 are different facts; the smoke
makes the same conflation. Neither should report an estate fault for a
transport failure they can distinguish with one extra call.
