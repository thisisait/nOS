# Plan — Jellyfin SSO: pin the order-sensitive SSO-Auth.xml schema (v4.0.0.4)

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Item: `v0.7 / sso / jellyfin-sso-plugin-xml-order-vuln`
Author context: nOS, AIT. SSO is mandatory (memory `sso-mandatory-never-local-form`).

---

## 1. Problem / why

Jellyfin native SSO is wired through the **server-side** `jellyfin-plugin-sso`
(9p4, pinned to `4.0.0.4`), configured by an XML file the role renders to
`{{ jellyfin_config_dir }}/plugins/configurations/SSO-Auth.xml`
(template: `roles/pazny.jellyfin/templates/SSO-Auth.xml.j2`). The plugin
deserializes this file with the **.NET `XmlSerializer`**, which is **strict on
element order** when `[XmlElement]` attributes are implicit (the default in
`PluginConfiguration.cs` / `OidConfig`).

The failure mode is silent and total:

> If the plugin can't deserialize, it **silently falls back to an empty dict and
> overwrites the file** on the next save — every login attempt then 400s with
> "Provider does not exist".

This already bit the install once live (2026-06-02): the `<PortOverride/>` field,
which v4.0.0.4 inserts **between `SchemeOverride` and `NewPath`**, was missing →
the deserializer wiped `<OidConfigs>` to empty → `/sso/OID/start/<provider>` 400'd.
The template header and the `post.yml` "DEFERRED" comment both document this trap
in prose, and the SSO **login button** is consequently NOT injected (a broken
button is worse than none).

The structural vulnerability is that **the exact field order is encoded only in a
hand-maintained Jinja template and two prose comments**. There is no gate. Any of
the following silently re-breaks SSO with zero test failure:

1. A field re-ordered, added, or removed during a future edit (e.g. a copy-paste
   that moves `<PortOverride/>` back below `<NewPath>`, or alphabetizes the block).
2. A plugin-version bump (`jellyfin_sso_plugin_version`) whose `OidConfig`
   declaration order drifts from the rendered XML — the version pin and the
   template order are coupled but nothing enforces the coupling.
3. The `SerializableDictionary` wire shape (`<item><key><string/></key><value>
   <OidConfig/></value></item>`) regressing — a subtle mis-nest here also yields
   an empty-dict fallback.

Because the plugin **rewrites the file on bad parse**, a regression is
self-erasing: by the time an operator inspects the live file it already looks
"empty but valid", masking the root cause. The role then re-renders the (still
order-wrong) template on the next run, the plugin wipes it again — an infinite
silent loop. This is exactly the saga class the v0.7 `verify-ok`/`-vuln` sweep
exists to close: behaviour is believed correct **today**, but it is **ungated**
and one careless edit from a silent SSO outage.

Per the overnight rules — "if you cannot gate it, it is a plan not a fix" — the
deliverable is a **structural gate** that pins the rendered XML against the
v4.0.0.4 `OidConfig` schema order, plus a small render-hardening so the gate has
a stable artifact to assert against.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `roles/pazny.jellyfin/defaults/main.yml` | **ADD** `jellyfin_sso_oidconfig_field_order` — the canonical ordered list of `OidConfig` child element names for the pinned `jellyfin_sso_plugin_version`. Single source of truth shared by render + gate. Uses stock Jinja only (a literal list — no filters), real default. NB: lives in a **role default**, not `default.config.yml`, so it must NOT be referenced before core-up (it is not — jellyfin renders during stack-up). |
| `roles/pazny.jellyfin/templates/SSO-Auth.xml.j2` | **OPTIONAL refactor (preferred):** keep the explicit per-field markup (readability) but add an inline comment cross-referencing `jellyfin_sso_oidconfig_field_order` as the authority, OR drive the `<OidConfig>` body from a `{% for field in jellyfin_sso_oidconfig_field_order %}` loop with a value map. **Decision:** keep the explicit markup (less churn, less risk) and treat the var as the assertion oracle — the gate compares rendered order against the var. Add a one-line header note pointing at the gate. |
| `tests/anatomy/test_jellyfin_sso_xml_order.py` | **NEW** anatomy gate. Renders `SSO-Auth.xml.j2` with a minimal test var context (mirroring `tests/config.yml` style), parses it, and asserts: (a) well-formed XML; (b) `OidConfig` child element order **exactly equals** `jellyfin_sso_oidconfig_field_order`; (c) the `SerializableDictionary` wire shape (`item > key > string`, `item > value > OidConfig`); (d) the version pin is the one the field-order list claims authority for (guard against a bump that forgets to re-verify order). |
| `roles/pazny.jellyfin/defaults/main.yml` (comment) | Strengthen the existing `jellyfin_sso_plugin_version` comment to state: "bumping this version REQUIRES re-deriving `jellyfin_sso_oidconfig_field_order` from the matching `PluginConfiguration.cs` tag and the gate `test_jellyfin_sso_xml_order.py` will fail until they agree." |

No live-system writes. No plugin re-download. Render + parse only, all offline.

---

## 3. Approach

### 3.1 Canonical order var (single source of truth)

Add to `roles/pazny.jellyfin/defaults/main.yml`:

```yaml
# Canonical OidConfig child-element order for jellyfin-plugin-sso v4.0.0.4,
# transcribed from OidConfig in PluginConfiguration.cs@v4.0.0.4. .NET
# XmlSerializer is order-strict; a drift here silently wipes OidConfigs and
# every SSO login 400s "Provider does not exist". Gate: test_jellyfin_sso_xml_order.py.
jellyfin_sso_oidconfig_field_order:
  - OidEndpoint
  - OidClientId
  - OidSecret
  - Enabled
  - EnableAuthorization
  - EnableAllFolders
  - EnabledFolders
  - AdminRoles
  - Roles
  - EnableFolderRoles
  - EnableLiveTvRoles
  - EnableLiveTv
  - EnableLiveTvManagement
  - LiveTvRoles
  - LiveTvManagementRoles
  - FolderRoleMappings
  - RoleClaim
  - OidScopes
  - DefaultProvider
  - SchemeOverride
  - PortOverride
  - NewPath
  - CanonicalLinks
  - DefaultUsernameClaim
  - DisableHttps
  - DoNotValidateEndpoints
  - DoNotValidateIssuerName
```

> **Authority caveat — do this first, before writing the list:** the order above
> is transcribed from the CURRENT `SSO-Auth.xml.j2` (which was live-corrected on
> 2026-06-02 and is believed correct). The plan REQUIRES confirming it against
> the upstream `PluginConfiguration.cs` at tag `v4.0.0.4`
> (`https://github.com/9p4/jellyfin-plugin-sso/blob/v4.0.0.4/SSO-Auth/Config/PluginConfiguration.cs`).
> If the implementer cannot reach the archived 9p4 repo offline, derive the
> oracle from the live, known-good `SSO-Auth.xml` on the running Jellyfin
> instance (READ-ONLY: `docker exec`/`cat` the deployed
> `plugins/configurations/SSO-Auth.xml` — that is the file the plugin itself
> re-serialized and accepted, i.e. ground truth). Do NOT invent the order.

### 3.2 Gate

`tests/anatomy/test_jellyfin_sso_xml_order.py` (Python, stdlib only):

1. Load `jellyfin_sso_oidconfig_field_order` and `jellyfin_sso_plugin_version`
   from `roles/pazny.jellyfin/defaults/main.yml` (PyYAML, already a test dep).
2. Render `SSO-Auth.xml.j2` with Jinja2 (the test harness already renders
   templates elsewhere — reuse the pattern from `test_hub_render_smoke.py` /
   the notification-template tests) against a minimal var dict:
   provider name, endpoint, client id/secret, the two role lists. The template
   uses only stock filters/loops, so a bare `jinja2.Environment` suffices.
3. `xml.etree.ElementTree.fromstring(rendered)` → assert well-formed.
4. Walk `OidConfigs/item/value/OidConfig` and collect child tag names in document
   order; assert `== jellyfin_sso_oidconfig_field_order` (exact, length + order).
5. Assert the dictionary wire shape: `OidConfigs/item/key/string` exists and
   `OidConfigs/item/value/OidConfig` exists (guards the
   `SerializableDictionary<TKey,TValue>` nesting).
6. Assert `<SamlConfigs />` is present and empty (self-closing → no children),
   matching the empty-list contract.
7. Version-coupling guard: assert `jellyfin_sso_plugin_version == "4.0.0.4"` (the
   version the field-order list is authored against). A version bump deliberately
   trips this so the bumper re-derives the order — the test message points at the
   upstream `PluginConfiguration.cs` URL and §3.1.

This makes the gate fail on ANY of the three regression vectors in §1.

### 3.3 Template note (no behavioural change)

Add a single comment line in `SSO-Auth.xml.j2` header pointing at the var + gate,
so the next editor sees the contract without reading this plan. The explicit
markup stays (loop-driving the body is higher-risk for no real benefit and would
obscure the literal field names a reviewer wants to see).

---

## 4. Risks

- **Oracle correctness is load-bearing.** A wrong order list would pin the bug,
  not the fix. Mitigation: §3.1 mandates deriving the order from upstream
  `PluginConfiguration.cs@v4.0.0.4` OR the live re-serialized `SSO-Auth.xml`
  (ground truth), never by guessing. This is the one step that must not be rushed.
- **Render context drift.** The gate must render the template with a var set that
  exercises the role-loops (`AdminRoles`, `Roles`, `OidScopes`). If the test
  passes empty role lists, the `{% for %}` blocks emit nothing and the gate still
  validates order (the wrapping `<AdminRoles>`/`<Roles>` tags render regardless) —
  acceptable, but prefer non-empty lists to also exercise the `<string>` children.
- **False coupling on version bump.** The version-pin assertion (§3.2 step 7) is
  intentionally strict; it will go red on a legitimate plugin bump. That is the
  point — it forces a human to re-verify the schema. Documented in the failure
  message + the defaults comment so it reads as a checklist item, not a mystery.
- **9p4 repo is archived read-only.** v4.0.0.4 is end-of-line; a future Jellyfin
  10.12 needs a successor plugin (already noted in defaults). This gate covers the
  current pin only; the successor will need its own order oracle. Out of scope.
- **No live mutation.** Gate is pure render+parse, offline. Zero risk to the
  running instance. The role's existing `notify: Restart jellyfin` on the XML
  render is unchanged — we touch defaults + template comment + a new test only.

---

## 5. Gates it needs

- **NEW:** `tests/anatomy/test_jellyfin_sso_xml_order.py` (the gate above).
- **Existing suite stays green:** `python3 -m pytest tests/anatomy/` (no other
  test references the jellyfin XML, so no collateral).
- **Syntax:** `ansible-playbook main.yml --syntax-check` clean (adding a role
  default + a template comment cannot break syntax, but verify).
- **Stock-Jinja trap N/A but checked:** the new var is a role default (loaded at
  stack-up, after core-up) and is a literal list with no filters, so
  `test_config_stock_jinja_only.py` does not apply — but run it anyway to confirm
  nothing regressed.

---

## 6. Verification recipe

All steps are READ-ONLY / offline. Run from repo root on `feat/v0.7-overnight`.

```bash
# 1. The new gate passes against the corrected template + var.
python3 -m pytest tests/anatomy/test_jellyfin_sso_xml_order.py -v

# 2. Prove the gate BITES: temporarily swap <PortOverride/> back below <NewPath>
#    in SSO-Auth.xml.j2 (the exact 2026-06-02 regression) and confirm RED, then revert.
#    (Manual one-line edit → rerun step 1 → expect failure on the order assert → git restore.)

# 3. Prove the version-coupling guard bites: bump jellyfin_sso_plugin_version to a
#    fake "4.0.0.5" in defaults → rerun → expect the version-pin assert RED → revert.

# 4. Full anatomy suite stays green.
python3 -m pytest tests/anatomy/ -q

# 5. Stock-Jinja gate unaffected.
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 6. Playbook syntax clean.
ansible-playbook main.yml --syntax-check
```

**Live cross-check (READ-ONLY, optional, confirms the oracle):**

```bash
# Compare the rendered template's OidConfig field order against the live,
# plugin-re-serialized SSO-Auth.xml — they MUST match field-for-field.
docker exec iiab-jellyfin-1 cat \
  /config/plugins/configurations/SSO-Auth.xml 2>/dev/null | \
  grep -oE '<[A-Za-z]+' | sed 's/<//' | head -40
# Eyeball against jellyfin_sso_oidconfig_field_order. Any divergence = oracle wrong.
# (Container name per CLAUDE.md A19: <stack>-<service>-1 → iiab-jellyfin-1.)
```

**Expected outcome:** the gate is green on the current (corrected) template,
goes red the instant the `<PortOverride/>` order regresses or the version pin
moves without a schema re-derive, and the live SSO-Auth.xml field order matches
the oracle. SSO login button injection remains deferred (separate item) — this
plan only pins the config schema so the OidConfig stops silently self-erasing.

---

## 7. Out of scope (explicit)

- **Injecting the SSO login button** (the `post.yml` "DEFERRED" block). That is a
  separate item; it depends on the OidConfig provisioning reliably, which THIS
  plan secures the precondition for but does not itself enable.
- **API-driven plugin config** (POST to the plugin instead of XML). A larger
  refactor; the XML path is the live one and worth pinning as-is.
- **A successor plugin for Jellyfin 10.12** (9p4 archived). Future track.
