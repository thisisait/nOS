# Landing

> The estate's front door at the **root domain**, for its own people: one card per
> routed service and a short how-to (names, certificate, sign-in, ssh, Iris,
> notebooks, GPU). Static files, no application, no session.

| | |
|---|---|
| **URL** | `https://{tenant_domain}` (`landing_domain`) — the root domain itself |
| **Toggle** | `install_landing: false` (on in `profiles/workstation.yml`); not together with `install_apex` |
| **Role** | `roles/pazny.landing` — pinned nginx (`landing_version` = `apex_version`), read-only |
| **Cards** | the wing-base hub-card harvest (`~/wing/app/data/hub-cards.json`), i.e. every enabled plugin's `ui-extension.hub_card` |
| **Also serves** | `/hosts.txt` (the hosts line a client needs for a local TLD) and `/nos-root-ca.crt` (the PUBLIC half of the local root CA) |
| **Host text** | `landing_title`, `landing_host_note`, `landing_contact` in `config.yml` |
| **Edge** | `traefik_auth_modes.landing: none` (justified in `roles/pazny.traefik/vars/main.yml`) |

A bare host IP redirects here when the landing is installed (to the face otherwise).

**Landing vs apex.** Apex is the signed public projection for strangers; the landing is
a signpost for the people who use this estate. Both claim the root domain, so the role
refuses to run beside apex.
