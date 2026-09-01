# SpacetimeDB — Skills

## Authentication

- **Method:** Bearer JWT — either a server-issued token signed by the local ECDSA keypair (`spacetimedb_keys_dir`, used by the host `spacetime` CLI) or an Authentik OIDC ID token validated against JWKS. No username/password exists.

## Read the server's own state

**Trigger:** an agent needs to know whether SpacetimeDB is live and which databases exist before reasoning about a module.
**Method:** `GET http://127.0.0.1:3030/admin`
**Returns:** the control-plane response used as the liveness probe. An estate with zero published modules answers normally — that is not an error.

## Publish a module

**Trigger:** never autonomously. Publishing changes the running application, because in SpacetimeDB the module IS the application.
**Method:** `spacetime publish <module> {{ spacetimedb_dev_db }}` from the host CLI, requiring a built WASM artifact.
**Returns:** operator territory. An agent proposes the change through the playbook; it does not run this.
