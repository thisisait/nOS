# postgresql-base

Wiring layer for the pazny.postgresql role. Headless OLTP substrate in the
infra compose stack — backs Authentik, Outline, HedgeDoc, Miniflux, BookStack
and any other Postgres-backed consumer. No app-level OIDC, no Wing /hub card
(TCP service, not a UI). Activates whenever `install_postgresql: true` (the
playbook auto-flips this on when a consuming service is enabled). Q3 batch.
