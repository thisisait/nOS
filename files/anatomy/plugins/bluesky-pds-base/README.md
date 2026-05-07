# bluesky-pds-base

Wiring layer for the pazny.bluesky_pds role. AT Protocol Personal Data Server
— identity, repository, and blob substrate for AT-native handles like
`@user.bsky.<tld>`. No `authentik:` OIDC block in this manifest: AT identity
is DID-backed, not OIDC; the Authentik → PDS account-provision bridge lives
out-of-plugin in `tasks/stacks/bluesky_pds_bridge.yml` and stays there until
a follow-up Q-batch harvests it. Wing /hub card points at the AT-native
OAuth login URL. Activates when `install_bluesky_pds: true`. Q3 batch.
