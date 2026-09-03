# 46 — An apply that always succeeds

**Found** 2026-09-02 (external audit); **half-closed** the same week, half OPEN.

## What it looks like

`main.yml`'s blueprint reapply: `ak apply_blueprint … || true` inside
`failed_when: false` — best-effort twice over, output discarded. It failed
SILENTLY on Linux for three months (SEC-1 0600 bind, fee 08 §Closed) before
run 33660558975 measured `applications == []`.

## What closed, what did not

CLOSED: `-u root` on the exec (2026-09-03) + `tasks/verify-authentik-apps.yml`
— a reader that queries Applications back and refuses a forward-auth route
with none. Both retro-verified.

OPEN: the reader covers ONE surface of ONE engine. `20-rbac-policies`,
`30-agent-clients`, `40-enrollment-flow`, `46-brand-auth-flow` still apply
under `|| true` with no live-state read-back — and those four apply under BOTH
engines (tofu does not own them). Every existing test for them checks the
TEMPLATE renders, not that the apply landed.

## The close, when someone pays it

Extend the same reader: one GET per blueprint's authoritative endpoint
(policy bindings count, oauth2 providers vs the declared agent roster, the
enrollment flow instance, the brand row), one assert each, same file, same
engine guard relaxed to cover the six tofu never owns. Roadmap row
`authentik-blueprint-readers`.
