# The router as a declared estate fact

> Status: design, opened 2026-09-03. Scope: one small file + one reader. Not an
> idea/ entry (that surface is at its 20-document ceiling) and not a
> `docs/plans/` entry (that directory is explicitly retired — "do not add a
> plan here"). This is a `docs/` topic guide, the same shape as
> `docs/traefik-primary-proxy.md` or `docs/native-sso-survey.md`.

## 1. Why this exists

The estate's edge sits behind a **Mercusys MR27BE (marketed as BE3600
Dual-Band Wi-Fi 7)**, admin UI at `http://192.168.1.1/`. Everything nOS has
ever said about it lived as prose in an operator checklist: remote management
off, UPnP off, forwards limited to 80+443. Prose is exactly the shape this
estate keeps converting into declared config + a reader — see
`docs/doctrine/gates.md` and the security-queue precedent in CLAUDE.md
("this line no longer carries the numbers — ask instead"). The router is the
same shape one layer further out: a fact about the network the estate cannot
introspect, sitting only in someone's memory of a checklist.

## 2. What the router class actually exposes (researched 2026-09-03)

**No documented API.** Mercusys publishes no REST/JSON API reference for
consumer routers. The web UI at `192.168.1.1` is a login-walled single-page
app; community reverse-engineering (`tplinkrouterc6u`, assorted
`mcp-tplink-router` clients) shows TP-Link-family firmware — which Mercusys
shares, TP-Link being its parent brand — uses a `cgi-bin` endpoint with a
session token (`stok`) obtained only after authenticating with the admin
password. **This is unofficial, reverse-engineered, and not a contract**: it
has broken across firmware revisions before and nothing obligates Mercusys to
keep it stable.

**TR-069 is supported, but it is the wrong kind of API for this purpose.**
Mercusys markets TR-069 (CWMP) support for ISP-operated Auto Configuration
Servers — it is a protocol for the *ISP* to remotely manage the CPE, not a
local API for nOS to query. Standing up a private ACS to talk TR-069 to this
router would be a larger foreign-surface commitment than the operator asked
for, and TR-069 access is itself one of the things a security-conscious setup
usually wants OFF unless the ISP requires it.

**No SNMP, no local status API.** Nothing found indicates a plaintext,
unauthenticated (or even authenticated-but-standard) status query. Every
signal about the router's actual configuration is behind the login-walled
admin UI.

**Probed live (read-only, presence only):** `GET`/`HEAD` against
`http://192.168.1.1/` both return `200 OK` — a static login-page response
(`ETag`, `Content-Length: 272`, `X-Frame-Options: deny`,
`Content-Security-Policy: frame-ancestors 'none'`) with no server banner
naming firmware version or exact model. This confirms presence and nothing
else — it is consistent with any TP-Link-family login page.

**CVE history:** no BE3600/MR27BE-specific CVE found. The Wi-Fi 7 line is
recent (product pages dated 2024+), which is more plausibly "not yet
scrutinized" than "clean" — sibling Mercusys models (e.g. MW325R,
CVE-2023-52162, stack-based buffer overflow) have shipped memory-safety CVEs
in the same firmware family. Treat "no known CVE" as absence of evidence, per
the same rule this estate already applies to its own remediation queue
(`docs/doctrine/security-floor.md`: a GHSA with no CVE id is still a real
finding).

**Conclusion this design is built on:** login-walled web UI only, no stable
documented API, no safe unauthenticated status surface. That fact decides the
design below — declare, don't scrape.

## 3. What nOS should KNOW (declared)

Lives in `state/router.yml` (not `state/manifest.yml` — see that file's own
header for why: the manifest schema is `additionalProperties: false` and
shaped around services nOS deploys; the router is foreign hardware, not a
service). Fields: gateway IP, model, admin URL, the 80/443 port-forward list
(making the ADR-style operator checklist machine-readable), the operator's
intent for remote-management and UPnP (both `false`), and a dated
operator-entered firmware version — `TODO`/`TODO` until the operator fills it
in, because nOS has no way to read it off the device.

## 4. What nOS can MEASURE without credentials

**Gateway presence.** `tools/router-status.py` does one `HEAD` request to the
declared `admin_url` and reports `reachable`/`unreachable`. That is all — a
200 from a login page proves the router answers, not that any declared
setting matches reality.

**Whether the declared forwards actually reach the estate: not from here.**
A container behind the router cannot self-probe its own WAN-facing ports —
that packet would have to leave the network and come back in, which is not
what "read-only, LAN-side" means. The estate already has the right vantage
point for this: the edge/Traefik access log sees every inbound connection that
arrives on 80/443, including the router-RCE scan traffic already observed
hitting `/cgi-bin/luci` and dying at Traefik. That is a **different reader's**
job (an edge-log surface), not this one's — named here so nobody builds it
twice.

**UPnP IGD exposure: proposed, not built.** An SSDP `M-SEARCH` broadcast from
inside the LAN would reveal whether the router is still advertising an IGD
control point despite `upnp_enabled: false` being declared. This is left as a
**follow-up**, not shipped now, because it needs its own small reader with its
own honest UNKNOWN semantics and is out of scope for this pass — the ask was
metadata + a mention, not a network-scanning tool. If built, it belongs beside
`router-status.py` as a second, clearly-labeled probe (`router-upnp-scan.py`),
never folded silently into the presence check.

## 5. Where it lives

- **`state/router.yml`** — the declared block. Small, separate from the
  manifest schema on purpose (see file header).
- **`tools/router-status.py`** — the reader. Reports the declared facts,
  probes gateway presence, and returns `UNKNOWN` (never a guessed `OK`) when
  `state/router.yml` is missing. Never `OK`s a forward or a toggle it did not
  measure — `measured_config` is always `null` until a credentialed or
  external-vantage measurement path exists. Gate:
  `tests/anatomy/test_router_status_is_honest.py`.

## 6. Doctrine

One line added to `docs/doctrine/foreign-properties.md` (§6): the router is a
foreign property with no API — declared facts + a presence probe, never an
assumed configuration. Not duplicated into `operator-model.md`; this is a
narrower, single-topic fact and foreign-properties.md is exactly the file
whose rule (§1: "a property of an artifact we do not build... getting it
wrong produces a confident wrong reading") already covers it.

## 7. What is deliberately excluded

- **No config automation against the router's admin UI.** It is a
  login-walled, undocumented, reverse-engineering-only surface — the kind of
  foreign property `docs/doctrine/foreign-properties.md` §1 says to route
  around, not own. A firmware bump could silently break a scraper with no
  warning and no changelog entry naming the break.
- **No credential storage for the router.** Nothing in this design asks for
  or stores the router admin password. Adding that later would be a
  `config.yml`-tier decision (`docs/doctrine/operator-model.md` §2 — "operator,
  always") and its own, separate proposal.
- **No TR-069/ACS integration.** Disproportionate to the ask, and TR-069
  access is itself a thing worth having OFF, not a channel worth opening.
- **No UPnP scan shipped in this pass** — named above as a scoped follow-up,
  not silently rolled into `router-status.py`.
