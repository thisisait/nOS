<!-- Generated 2026-06-01 by the sso-autologin-research-plan workflow (13 agents, deep upstream research + 3 adversarial-verify lenses; 28 accuracy issues caught and folded in). Apply-ready input for the implementation workflow. -->

# Plán: Globální autologin SSO + custom preloader (nOS)

## Cíl a cílová UX

Operátor (a tenant) se přihlásí do Authentiku **jednou** za session. Poté je každá služba na `*.<tld>` přístupná na **nula až jeden klik**: buď je vstup čistě průchozí (forward_auth s existující session), nebo služba sama při dopadu na svou login-page okamžitě přesměruje na Authentik, kde už session existuje → uživatel skončí přihlášený ve službě, aniž by viděl login-formulář. Cílová věta: *"It feels like one app."*

"Done" znamená:

- **native_oidc služby (20):** ty, kde to upstream **ověřeně** umí, mají vynucené OIDC-only přihlášení (lokální formulář skrytý nebo auto-redirect na IdP). Ty, kde to upstream neumí, ponechávají tlačítko "Sign in with Authentik" — to je čestně dokumentováno a **gate-vynuceno** (`supports: no` nelze flipnout na `enabled: true`), ne falešně slíbeno.
- **header_oidc služba (1):** firefly — Authentik proxy outpost injektuje `REMOTE_USER`/`REMOTE_EMAIL` → auto-login na proxy-vrstvě. **Není** native_oidc (nemá vlastní OIDC klienta); zde auto-redirect řeší outpost, ne env-var ve službě.
- **forward_auth služby (17):** 6 je `passthrough_clean` (Authentik gate = úplný autologin, hotovo). 11 má "second login"; z toho 6 řešitelných header-provisionem/configem (+ wing už hotový), 3 čekají na upstream, snappymail je by-design (IMAP je zdroj identity).
- **Celkový součet napříč repem: 20 native_oidc + 1 header_oidc + 17 forward_auth = 38 služeb.**
- **Globální mechanismus, ne 20 ručních editů:** jediný config var `sso_autologin` (+ per-service override) propíše force-OIDC env do každé compose-extension přes plugin loader. Žádné per-role copy-paste.
- **Custom preloader:** Wing `/hub` jako sjednocený launcher s brandovaným splash + tichým session pre-warmem. Maskuje redirect-latenci **jen pro uživatele s existující Authentik session** (repeat login, ~100–200 ms); first-login latenci (~500 ms) neskryje — viz čestnou analýzu níže.
- **Break-glass:** SSO-down nikdy trvale nezamkne adminy ven. Per-service break-glass query param, per-service `ALLOW_LOCAL_LOGIN` fallback, Authentik recovery key (CLI-provisioned), restart fallback. **Wing `/api/unlock` je volitelný greenfield doplněk, ne load-bearing vrstva** (viz níže).
- **Bezpečný default:** `sso_autologin: false` na blank-run; opt-in; plně reverzibilní bez restartu kontejnerů (kromě env-driven služeb, které potřebují recreate).

Hard-honest baseline z výzkumu: **n8n CE** force-OIDC nativně neumí (login screen nelze skrýt; SSO je Business/Enterprise feature) → ponechat tlačítko, `supports: no`. **Metabase / InfluxDB OSS** OIDC nemají vůbec (Pro/Enterprise/Cloud-only) → forward_auth gate + sdílený operator účet, čeká na upstream/licenci. **HedgeDoc / Open-WebUI / ERPNext / Jellyfin (official) / Firefly (native)** nemají nativní auto-redirect; držet button nebo proxy-header path, `supports: no`.

---

## Globální mechanismus (ne 20 ručních editů)

Páteř: **rozšířit authentik manifest kontrakt o `autologin` blok** a nechat plugin loader / aggregator vykreslit per-service force-OIDC env do každé `compose_extension`. Mechanismus se opírá o tři už existující fakta v repu, ověřená kódem:

1. **`render_compose_extension`** (`files/anatomy/module_utils/load_plugins.py:916–932`) renderuje existující `templates/<svc>-base.compose.yml.j2` přes plný var-scope operátora (`ctx`) do `{{ stacks_dir }}/<stack>/overrides/<plugin-name>.yml`. → Nový `{% if sso_autologin %}` blok uvnitř už existujících compose-extension šablon stačí; **žádný nový per-file loader kód** — jen proměnná musí být v `ctx` (a tedy definovaná v `default.config.yml`).
2. **Aggregator** (`load_plugins.py:257–372`) harvestuje `authentik:` bloky všech plugin manifestů do `authentik-base.inputs.clients`, pre-renderuje Jinju (`_deep_render`, ř.232–253) a filtruje podle `requires.feature_flag`. → Nové pole `authentik.autologin` se automaticky veze v harvestovaném bloku.
3. **Blueprint** `10-oidc-apps.yaml.j2` iteruje `inputs.clients` (`authorization_flow` na ř.60 a ř.102 je dnes `default-provider-authorization-implicit-consent`). → Pro `autologin: true` klienty lze switchnout `authorization_flow` na dedikovaný `nos-autologin-flow` (viz §preloader / Authentik branding) místo implicit-consent.

### Kontrakt — tvar `autologin` bloku v `files/anatomy/plugins/<svc>-base/plugin.yml`

> **Pozn.: `sso_autologin*` proměnné NEEXISTUJÍ v dnešním repu.** Grep `default.config.yml`, `default.credentials.yml`, tasks i playbooků je nenajde. Tato sekce je **greenfield zavedení** — proměnné se MUSÍ nově přidat do `default.config.yml` v Batch 0. Níže je cílový tvar, který Batch 0 zavádí, ne stávající stav.

```yaml
authentik:
  mode: native_oidc          # GATE: autologin only legal for native_oidc
  client_id: nos-grafana
  client_secret: "{{ global_password_prefix }}_pw_oidc_grafana"
  slug: grafana
  tier: 1
  # ── NEW (Batch 0): autologin contract ───────────────────────────────
  autologin:
    # force-OIDC capability honestly carried from research:
    supports: yes            # yes | partial | no  (upstream truth, not aspiration)
    # resolves to bool via loader's _deep_render against operator var scope.
    # Precedence chain baked into the Jinja default — NOTE the | bool coercion:
    enabled: "{{ (sso_autologin_grafana | default(sso_autologin_min_tier_1 | default(sso_autologin | default(false)))) | bool }}"
    hides_local_form: true   # informational: does enabling it remove the local form?
    break_glass: "?disableAutoLogin=true"   # documented escape, per-service
    # local-login fallback (break-glass), rendered into compose env when on:
    local_login_fallback: "{{ enable_grafana_local_login | default(false) | bool }}"
```

Pravidla kontraktu:
- **`autologin` je legální jen pro `mode: native_oidc`.** Pin testem (`test_autologin_only_for_native_oidc_services`). forward_auth/header_oidc autologin nedeklarují (anti-pattern double-protection; firefly = header_oidc → auto-login řeší outpost, ne tento blok).
- **`supports`** nese upstream pravdu (`yes`/`partial`/`no`) z výzkumu — nikdy se nepřeklápí to, co upstream neumí. **`supports: no` plugin MUSÍ vždy rezolvovat `enabled` na false** — gate `test_autologin_no_means_no` projde celou matici a fail-fastne, pokud by jakákoli operátorská override (svc/tier/global) dokázala flipnout `supports: no` službu na `enabled: true`. To je tvrdá pojistka proti falešnému slibu (n8n/hedgedoc/open-webui/firefly/jellyfin/erpnext).
- **`enabled`** je vždy Jinja string s precedencí `sso_autologin_<svc>` → `sso_autologin_min_tier_<N>` → `sso_autologin` → `false`, **zakončený `| bool`**. Důvod `| bool`: `_deep_render` vrací string; bez explicitní koerce by `"false"` (neprázdný string) Jinja vyhodnotila jako truthy → tiché selhání. `| bool` převede `"true"/"false"/"yes"/"no"` na pravý bool před blueprint renderem. Gate `test_autologin_config_var_resolves` ověří, že každý `enabled` string končí `| bool` a rezolvuje na valid bool-ish.

### Loader touch-pointy (přesně)

| Touch-point | Soubor | Změna |
|---|---|---|
| Schema | `state/schema/plugin.schema.json` | přidat `authentik.autologin` objekt (`supports` enum yes/partial/no, `enabled` string, `hides_local_form` bool, `break_glass` string, `local_login_fallback` string). **Dnes v repu žádné `autologin` pole ani test neexistuje — toto je nová definice.** |
| Var do ctx | `default.config.yml` (definice) + ověření `tasks/stacks/core-up.yml` ř.38/385/594 + `stack-up.yml` ř.368 | **Ověřeno kódem:** orchestrátory volají `nos_plugin_loader` s `template_vars: "{{ vars }}"` — tj. předávají **celý** play-var scope přes Ansible magic `vars`. `default.config.yml` JE ve `vars_files`. Proto stačí proměnné *definovat* v `default.config.yml`; `{{ vars }}` je do `template_vars` (a odtud do `ctx` v `_render_template`, ř.807) automaticky veze. **Žádná změna kódu loaderu ani ruční konstrukce dict per-var.** Jediná povinnost: proměnné musí existovat v `default.config.yml`, jinak v `{{ vars }}` nebudou a `default(...)` v Jinje je dosadí na `false`. |
| Compose env render | každá `<svc>-base.compose.yml.j2` | nový `{% if (authentik_autologin_<svc> \| default(false) \| bool) %}` resp. přímo `{% if (sso_autologin... \| bool) %}` blok s force-OIDC env. Renderuje se existující cestou (`render_compose_extension`). |
| Blueprint flow switch | `files/anatomy/plugins/authentik-base/blueprints/10-oidc-apps.yaml.j2` (ř.60 a ř.102, `authorization_flow`) | pro `c.autologin.enabled` true → `nos-autologin-flow`, jinak ponechat `default-provider-authorization-implicit-consent`. |

**Klíčová úspora:** force-OIDC je u většiny služeb pouhý env-var toggle (Grafana, BookStack, WordPress, FreeScout) — compose-extension render je už hotová pipeline. Mechanismus = jeden var + per-plugin `{% if %}` blok, ne 20 nezávislých editů orchestrátoru. (Výjimky vyžadující API/config hook — Portainer, Nextcloud, Superset, HomeAssistant — viz matice.)

---

## Per-service matice (native_oidc, 20 služeb)

### (a) Clean autologin wins — env/config toggle skryje formulář nebo auto-redirect

| Service | force-OIDC | exact env/config | hides form | break-glass | ent-gated | effort | conf |
|---|---|---|---|---|---|---|---|
| grafana | yes | `GF_AUTH_OAUTH_AUTO_LOGIN=true` **(sekce `[auth]`, NE `[auth.generic_oauth]`)** + `GF_AUTH_DISABLE_LOGIN_FORM=true` (sekce `[auth]`) → `grafana-base.compose.yml.j2` | yes | `?disableAutoLogin=true` (ekvivalent `/login`) | no | S | 0.95 |
| bookstack | yes | `AUTH_AUTO_INITIATE=true` (AUTH_METHOD=oidc už set) → `bookstack-base.compose.yml.j2` | yes | `?prevent_auto_init=true` | no | S | 0.92 |
| portainer | yes (hybrid env+API) | OIDC env přes compose-extension **a** `OAuthSettings.HideInternalAuth=true` přes `PUT /api/settings` v `portainer-base/plugin.yml` `api_calls` post-compose hooku. **Hide-internal-auth je stateful API call, ne env** — apply playbook musí spustit post_compose task. | yes | `/#!/internal-auth` | no | M | 0.90 |
| Nextcloud | yes (config hook, ne env) | `user_oidc` app: single default provider → 302; auto-redirect **nelze nastavit env-var** — vyžaduje `occ config:app:set user_oidc allow_multiple_user_backends` resp. `oidc_login_auto_redirect` přes `occ`/`config.php`. Render přes `nextcloud-base` **post_setup lifecycle hook** (occ), NE compose env. | yes | `?direct=1` | no | M | 0.90 |
| superset | yes | `OAUTH_SKIP_PROVIDER_SELECTION=True` v `superset_config.py` → `roles/pazny.superset/templates/superset_config.py.j2`. **Přesná min-verze NEPOTVRZENA** (feature přibyla po 6.0.0; konkrétní 6.0.1/6.1.0 z výzkumu neověřena) — verifikovat proti instalované verzi před zapnutím. | yes | flag=False | no | M | 0.78 |
| freescout | viz pozn. | `FREESCOUT_OIDC_*` + Force OAuth Login toggle (`OAUTHLOGIN_FORCE_OAUTH_LOGIN`). **OAuth-Login modul je placený/enterprise-gated u upstreamu — v čistém CE bez modulu force-toggle NEEXISTUJE.** Proto: pokud operator modul má → clean win; pokud ne → viz sekce (d), `supports: no`. **Nelze být zároveň "win" i ent-gated.** | yes (s modulem) | `/login?disable_oauth=1` | **závisí na modulu** | S | 0.70 |
| homeassistant | yes | `auth_oidc` HACS plugin, YAML `features.default_redirect=true` → `roles/pazny.homeassistant` configuration.yaml (config hook, ne env) | yes | `?skip_oidc_redirect=true` | no | M | 0.80 |

### (b) Partial / needs care — formulář se neskryje sám, nebo nutná proxy-vrstva

| Service | force-OIDC | exact env/config | hides form | break-glass | ent-gated | effort | conf |
|---|---|---|---|---|---|---|---|
| gitlab | partial | `GITLAB_OMNIBUS_CONFIG: gitlab_rails['omniauth_auto_sign_in_with_provider']='openid_connect'` (+ opt. `..disable_password_authentication_for_web=true`). **Auto-redirect přes tento klíč NENÍ jednoznačně potvrzen v oficiálních GitLab docs pro OIDC omnibus** — `disable_password_authentication_for_web=true` skryje form spolehlivě; auto-sign-in klíč může a nemusí fungovat dle verze. Downgradováno z "clean win" na partial. | yes (form via disable_pw), auto-redirect nejistý | `?auto_sign_in=false` | no | M | 0.78 |
| gitea | yes (form), no (auto-redirect) | `GITEA__SERVICE__ENABLE_PASSWORD_SIGNIN_FORM=false` + `..ENABLE_BASIC_AUTHENTICATION=false` (žádný auto-redirect; jen OIDC button). **Admin musí existovat PŘED zamčením formuláře** | yes (form), no (no auto-redirect) | API token / re-enable form | no | M | 0.85 |
| outline | partial | **NEZAhrnovat** `OIDC_DISABLE_REDIRECT` → absence env = auto-redirect na OIDC. Pravý forced redirect bez návratu na form nutí proxy/source mod | no | set `OIDC_DISABLE_REDIRECT=true` | no | S | 0.75 |
| miniflux | partial | `DISABLE_LOCAL_AUTH=1` skryje formulář, ale **bez auto-redirectu** → nutný Traefik middleware redirect `/login`→OIDC, jinak blank page. **Lokální form pak NENÍ dosažitelný** (jen `DISABLE_LOCAL_AUTH` skrývá vše) → break-glass je unset var, ne UI param. | yes (form, no UI fallback) | unset var / proxy bypass | no | M | 0.80 |
| nodered | partial | settings.js `adminAuth.strategy` s `autoLogin=true` (passport-openidconnect). Redirect jen bez session; neskryje formulář natvrdo → `roles/pazny.nodered` settings.js + `AUTHENTIK_NODERED_AUTOLOGIN` env | no | local admin user v adminAuth.users array (fallback) | no | M | 0.70 |
| WordPress | partial | `WP_OIDC_LOGIN_TYPE=auto-sso` (z `button`) → `wordpress-base.compose.yml.j2`. `wp-login.php` zůstává dostupný | no | `/wp-login.php` přímo | no | S | 0.85 |
| Vaultwarden | partial / fork-gated | `SSO_ONLY=true` skryje master-password tak, že nechá jen SSO button — **ale plné SSO_ONLY chování spolehlivě poskytuje až community fork OIDCWarden (`SSO_FRONTEND=override`)**; oficiální build má OIDC podporu **omezenou/experimentální** a většina nasazení spoléhá na fork nebo external proxy. Bez auto-redirectu i tak. Označit `supports: partial` jen pokud operator běží fork/má ověřeno; jinak `supports: no` + forward_auth gate. | no (button only, fork) | `SSO_ONLY=false` / `/admin` | no (fork-conditional) | M | 0.60 |
| infisical | partial (enforce ent-gated) | `OIDC_*` env seed dá **OIDC button**, ale "Enforce OIDC" (force-only) je **enterprise-gated** — v OSS není user-facing enforce ani auto-redirect. UX v OSS: OIDC button + manuální org-admin aktivace post-first-login, NE pre-login auto-redirect. Marknout `supports: partial`, `enabled` se reálně chová jen jako "seed button", enforce deferován. | no | `/login/admin` (org-admin bypass) | **yes (enforce)** | M | 0.75 |

### (c) Cannot — upstream neumí force/auto; `supports: no`; **ponechat tlačítko / proxy-vrstvu** (čestně)

| Service | mode | force-OIDC | stav | break-glass | effort | conf |
|---|---|---|---|---|---|---|
| hedgedoc | native_oidc | **no** | žádný auto-redirect env (GH issue #5833, neimplementováno). Jen manuální klik na OAuth2 button. `supports: no`. | N/A | L | 0.90 |
| Open-WebUI | native_oidc | **no** | `OAUTH_*` enable button; žádný auto-login. True autologin jen přes oauth2-proxy sidecar (external infra) nebo upstream feature (disc. #7337). `supports: no`. | local login vždy | L | 0.90 |
| erpnext | native_oidc | **no** (native button only) | mode je **správně native_oidc** (Frappe Social Login Key), ale upstream **nemá auto-redirect/force-OIDC** — jen click-based button. Fork frappe-oidc-extended nestačí; force = bench hook override (greenfield). Proto `autologin.supports: no` → gate `test_autologin_no_means_no` zaručí, že `enabled` nikdy nerezolvuje na true. | `/app/login` vždy | L | 0.78 |
| jellyfin | native_oidc | **no** (native, no autologin) | SSO-Auth plugin má redirect endpoint `/sso/OID/start/Authentik`, ale **žádný native autologin** — nutný custom login HTML / API config (greenfield). `autologin.supports: no`. | native login na root vždy | L | 0.72 |

> **Pozn. k (b) vs (c):** erpnext a jellyfin figurují **právě v jedné sekci** — zde v (c), protože upstream auto-redirect **neumí** (`supports: no`). Nejsou v (b) "partial". Mode `native_oidc` je korektní (mají vlastního OIDC klienta), ale autologin-capability je `no`. Distinkce: (b) = "form lze skrýt/redirect lze přiblížit s prací", (c) = "upstream force/auto je nedostupné, button zůstává".

### (d) Enterprise-gated / upstream-blocked — výslovně (`supports: no`)

| Service | mode | stav | dopad |
|---|---|---|---|
| **n8n** | native_oidc | `supports: no`, **enterprise-gated**. `N8N_SSO_OIDC_LOGIN_ENABLED` přidá button (vyžaduje Business/Enterprise plan), "No supported way to disable the login screen exists" (oficiální docs). `N8N_DISABLE_UI_AUTHENTICATION` deprecated. Community `n8n-oidc` (hooks) není upstream. | **Ponechat tlačítko.** `enabled` gate-locked na false. CE nemá ani button bez workaroundu. |
| **freescout** | native_oidc | OAuth-Login modul **placený/enterprise-gated** u upstreamu. V CE bez modulu = `supports: no`. **S modulem** = clean win (a). Status je tedy podmíněn licencí modulu — viz (a) pozn. | Bez modulu: button neexistuje, `supports: no`. S modulem: force-toggle funguje. Operator musí potvrdit přítomnost modulu. |
| **metabase** | forward_auth | OSS bez OIDC (Pro/Enterprise-only). | forward_auth gate + sdílený operator účet; čeká na licenci/upstream. Žádný autologin blok. |
| **infisical** | native_oidc | OIDC enforce je enterprise-gated; OSS bez auto-redirectu. | partial seed (viz (b)); enforce deferován. Gate `test_infisical_no_enforce_in_oss` ověří, že plugin nerenderuje enterprise-only enforce volání v OSS módu. |

---

## forward_auth (17 služeb)

Doktrína: forward_auth gateuje **přístup k route (WHO)**, ne identitu služby (WHAT). Sdílená session cookie `.<tld>` (`AUTHENTIK_COOKIE_DOMAIN` v `roles/pazny.authentik/templates/compose.yml.j2` ř.53) + embedded outpost (bound na všechny proxy providery v `10-oidc-apps.yaml.j2` ř.120-148) → jakmile existuje Authentik session, outpost vrací X-Authentik-* hlavičky tiše, bez login UI.

### passthrough_clean (6) — už plný autologin, žádná práce

`kiwix`, `ntfy`, `onlyoffice`, `qdrant`, `spacetimedb`, `mailpit`. Stateless / žádná service-side auth → Authentik gate = úplné přihlášení. **Hotovo.**

### second-login offenders (11) — druhý login + cesta k eliminaci

| Service | druhý login | eliminovatelné | cesta |
|---|---|---|---|
| **wing** | X-Authentik-* (už auto-provisioned) | **yes ✓** | hotovo — `BasePresenter::startup()` čte X-authentik-* z forward_auth. passthrough_clean v praxi. |
| code-server | password (`HASHED_PASSWORD`) | **yes** | code-server `REMOTE_USER` trusted-proxy mód; Traefik už posílá `X-authentik-username`. Patch http.ts / oauth2-proxy wrapper. |
| paperclip | session (better-auth) | header-provision | better-auth adapter mapping X-authentik-username → user record (config customization). |
| openclaw | gateway token (launchd) | header-provision | patch OpenClaw na X-Authentik-* auto-provision / wrapper token-injection. |
| puter | Puter user dir | header-provision | patch Puter trusted-proxy mód na X-Authentik-* / OIDC client upstream / Pomerium wrapper. |
| woodpecker | Gitea OAuth2 (transitivně Authentik) | header-provision | login chain UŽ je Authentik (Gitea native-OIDC), ale user vidí Gitea form. Eliminace: `WOODPECKER_OIDC_*` jako primary, nebo trusted-proxy. |
| calibre-web | username/password | header-provision | bez native OIDC (req #2965 zamítnut). LDAP→header translation, nebo disable auth + spolehnout na forward_auth gate. |
| **influxdb** | local user DB | **needs-upstream** | 2.x OSS bez OIDC (jen Cloud Dedicated/Clustered). Sdílený operator credential v env, nebo fork. |
| **metabase** | Metabase user dir | **needs-upstream** | OIDC Pro/Enterprise-only. Sdílený operator účet za forward_auth gate. |
| **uptime-kuma** | local Kuma account | **needs-upstream** | bez native OIDC (req open). Fork/patch, nebo disable login env + forward_auth gate. |
| **snappymail** | IMAP/SMTP (Stalwart) | **no (by-design)** | webmail frontend, identita je IMAP-determined, ne Authentik. SSO pro IMAP neexistuje. Creds 1× do nastavení, šifrovaně v data volume. **Správně by-design.** |

Souhrn: 6 clean + wing(✓) = 7 hotových. 6 řešitelných header-provision/config (code-server, paperclip, openclaw, puter, woodpecker, calibre-web — quick wins). 3 čekají na upstream (influxdb, metabase, uptime-kuma). 1 by-design (snappymail). **Žádný autologin flag se forward_auth službám nedává** (gate `test_no_autologin_for_pure_proxy_services`).

---

## Custom preloader

**Doporučení: Option B — Wing `/hub` jako sjednocený launcher + brandovaný splash pre-warmer (PRIMARY), s Option A — Authentik branded flow (FALLBACK).** Fit pro nOS 0.75 (B) / 0.6 (A).

### Proč B — a čestná analýza, co preloader (ne)maskuje

Wing `/hub` **už je** dashboard: forward_auth-gated, harvestuje hub_cards (150+ služeb), má dark responzivní theme, RBAC tier filtrování, health/kategorie/search. Reuse ~80 % kódu. Pokrývá **všech 38 služeb**: forward_auth uživatelé jsou už u Wing gate (session warm), native_oidc dostanou pre-warmed session → klik na tile je instantní. Splash JE záměrná preloader UX, plně brandovatelná (logo, barvy, copy). Žádná nová infra (Traefik Go plugin Option D má fit jen 0.5 a vyžaduje Go toolchain; Option E outpost template fit 0.55 a nevidí Wing service registry).

**Čestně k latenci — kde session warmer pomáhá a kde NE:**

- **Repeat login (existující Authentik session):** `prompt=none` na `/authorize/` vrátí 302 rychle (~100–200 ms cookie-exchange). Splash maskuje tuto krátkou latenci → tile-klik se jeví instantní. **Toto je reálný přínos.**
- **First login (žádná Authentik session):** `prompt=none` selže (uživatel není přihlášen) → musí proběhnout plný OIDC flow (login formulář + consent + code-exchange, ~500 ms a víc s uživatelskou interakcí). **Splash zde latenci NEskryje** — uživatel stejně čeká na celý flow. Preloader není řešení first-login frikce.
- **Závěr:** preloader je **UX polish pro repeat logins** (maskuje ~100–200 ms), NE řešení first-login latence. Pro first-login UX je správná páka **Authentik branded flow** (Option A / FALLBACK) — brandovaný login/consent background dělá nutné čekání alespoň polished a on-brand.

### Implementační povrch (apply-ready)

| Co | Soubor | Detail |
|---|---|---|
| Splash route | `files/anatomy/wing/app/Presenters/HubPresenter.php` | nová metoda `renderSplash()` vracející brandovaný interstitial; `?skip_splash=1` bypass. |
| Splash šablona | `files/anatomy/wing/app/Templates/Hub/splash.latte` (nový) | nOS logo, "Warming session…" text, CSS animace; reuse dark theme. |
| Session warmer | `files/anatomy/wing/www/assets/hub-session-warmer.js` (nový) | na load redirect na `/application/o/authorize/?client_id=wing&redirect_uri=…&prompt=none` (OIDC cookie dance); po 302 auto-redirect na `/hub` nebo `?service=` param. **Při `prompt=none` selhání (žádná session) NEcyklit** — fallback na normální flow. **Timeout 10 s** → fallback message + "Retry" button. |
| Entry config | `default.config.yml` | `sso_enable_custom_preloader: false` (opt-in); volitelně `LAUNCHER_ENTRY_POINT` marker. |
| Style | `files/anatomy/wing/www/assets/style.css` | `.hub-splash`, logo animace (reuse `.hub-grid`/`.sys-card` patterny ř.221+). |

### Vazba na Authentik branding (FALLBACK + společný gate)

- Authentik **Brands** (System > Brands): custom logo/favicon, flow background, Custom CSS (≥2025.4.0) — branduje login/consent flow, který je preloaderem pro native_oidc služby, jejichž session ještě neexistuje (a tudíž pro first-login páka, viz výše).
- **`nos-autologin-flow`**: nový flow (blueprint), assigned jako `authorization_flow` pro `autologin: true` klienty místo implicit-consent. **POZOR — implicit-consent silent-skip není zaručený:** Authentik má dokumentované regrese, kdy implicit consent přesto zobrazí prompt (GH #15814 open/reviewing, #13068, #8660 — zvláště s `offline_access` scope nebo při first loginu). **Před implementací flow OVĚŘIT chování implicit-consent na cílové verzi Authentiku end-to-end.** Pokud silent-skip nefunguje spolehlivě, použít **explicit consent flow s expression policy**, která UI přeskočí jen při existující session, a upravit messaging preloaderu, aby nastavil správná očekávání. Doporučená varianta preloader-stage: **Dummy stage + per-flow background + custom CSS** (žádný custom stage class, žádný image bloat).
- Branding sám **nepokryje** redirect-latenci pro už-přihlášené (ti flow přeskočí) a forward_auth uživatele (nikdy nevidí Authentik UI). Proto je B primary, A fallback pro first-login polish.

---

## Bezpečnost: break-glass + lockout

Sjednocený únik — **SSO-down nikdy trvale nezamkne adminy ven.** Vrstvy (load-bearing první tři; čtvrtá volitelná):

1. **Per-service break-glass query / `?skip_autologin=1`.** Autologin **nikdy neskrývá ani nedisabluje** lokální formulář tam, kde fyzicky existuje a je dosažitelný — jen zkusí OIDC první. Každá služba nese svůj dokumentovaný escape v `authentik.autologin.break_glass`. **Truth-table dosažitelnosti fallbacku** (ne všechny escapes vedou na reálné UI):

   | Service | break-glass param | dosažitelný lokální form? |
   |---|---|---|
   | grafana | `?disableAutoLogin=true` (→ `/login`) | **ano** (form se vrátí, pokud `DISABLE_LOGIN_FORM=false`) |
   | bookstack | `?prevent_auto_init=true` | ano |
   | gitlab | `?auto_sign_in=false` | ano jen pokud `disable_password_authentication_for_web` ≠ true; jinak NE → použít recovery |
   | gitea | re-enable `ENABLE_PASSWORD_SIGNIN_FORM` env + recreate | **ne za běhu** — form je env-skryt; nutný re-render |
   | miniflux | unset `DISABLE_LOCAL_AUTH` + recreate | **ne za běhu** — žádné UI escape; jen env unset |
   | wordpress | `/wp-login.php` přímo | ano |
   | vaultwarden | `SSO_ONLY=false` + recreate | **ne za běhu** (button-only) |
   | portainer | `/#!/internal-auth` | ano (pokud HideInternalAuth nebyl set, jinak API revert) |
   | nextcloud | `?direct=1` | ano |

   **Pro služby bez za-běhu dosažitelného fallbacku (gitea, miniflux, vaultwarden) je break-glass = env unset + recreate, ne UI param** — toto je explicitně zdokumentováno v runbooku.

2. **Per-service local-login toggle.** `enable_<svc>_local_login: true` v `default.config.yml` → compose-extension renderuje `ALLOW_LOCAL_LOGIN`/ekvivalent. Default `false` (pure-SSO). Pinnut `test_local_login_fallback_renders_when_enabled`. **Pozn.:** toggle je smysluplný jen pro služby, které lokální fallback UI mají (viz tabulka výše); pro gitea/miniflux/vaultwarden je "fallback" = re-render bez force-OIDC, ne živé UI.

3. **Authentik recovery key (offline escape) — CLI-provisioned, NE blueprint.** `authentik_core.recoverytoken` model **NEEXISTUJE v Authentik blueprint schématu** (ověřeno proti goauthentik.io/blueprints/schema.json; blueprint má `authentik_core.token`, ne `recoverytoken`). Recovery tokens lze vytvořit **výhradně CLI příkazem** `docker compose run --rm server create_recovery_key <username>` (resp. `create_admin_group`/`create_recovery_key` management command). **Pokus o blueprint-provision = kritické riziko lockoutu** (blueprint by tiše selhal nebo seed neexistoval).
   - **Doktrína:** recovery-key break-glass zůstává **operátorský manuální zásah přes CLI**, ne nOS-config persistence.
   - **Co nOS udělá:** vygeneruje `authentik_recovery_key` jako náhodné bajty na first blank-run, **uloží do `~/.nos/secrets.yml`** (ověřeno: `~/.nos/secrets.yml` je reálný persistentní secrets store, čtený idempotentně např. `tasks/authentik-migrate.yml`), a **dokumentuje CLI postup** v runbooku. Klíč slouží jako **vstup do CLI příkazu**, ne jako blueprint seed.
   - **Durabilita/backup:** klíč je idempotentně čten ze `secrets.yml` napříč re-runy (gate `test_recovery_key_persists_across_reruns`). Runbook výslovně instruuje: *"`~/.nos/secrets.yml` zazálohovat mimo nOS — je to jediný offline vstup pro CLI recovery, pokud je Authentik nedostupný."*
   - **Gate:** `test_recovery_key_persists_across_reruns` (stabilita klíče napříč re-runy). **Žádný `test_recovery_key_in_secrets` testující blueprint seed — ten by byl nesplnitelný.** Žádný test ověřující `recoverytoken` v blueprintu.

4. **Wing `/api/unlock` (admin recovery portal) — VOLITELNÝ greenfield doplněk, NE load-bearing.** **V dnešním repu NEEXISTUJE** žádný `/api/unlock` endpoint ani odpovídající presenter (ověřeno: `app/Presenters/Api/` obsahuje Advisories/AgentSessions/Agents/Audit/…/Upgrades, ale žádný Unlock). Break-glass model **stojí na vrstvách 1–3** (per-service param/recreate + `ALLOW_LOCAL_LOGIN` + CLI recovery key + container restart) — ty jsou kompletní bez Wing. `/api/unlock` lze **přidat později** jako pohodlnější portál:
   - Pokud se implementuje: nový `files/anatomy/wing/app/Presenters/Api/UnlockPresenter.php` (extends `BaseApiPresenter`), **bez závislosti na neexistujícím Authentik recovery tokenu v DB** — validace proti **IP whitelist (`$operator_ip_whitelist`) + sdílený break-glass secret z `~/.nos/secrets.yml`** + rate-limit (max 3 / 5 min / IP). Na success razí dočasnou Wing admin session (15 min TTL) → Emergency Panel (bounce service, view logs, link na runbook). Gate (jen pokud implementováno) `test_wing_unlock_endpoint_exists`.
   - **Rozhodnutí pro tento plán:** rollout **NEvyžaduje** `/api/unlock`. Vrstvy 1–3 jsou postačující a ověřitelné. `/api/unlock` je post-rollout nice-to-have, nezdržuje zapnutí autologinu.

**Runbook:** `docs/break-glass-runbook.md` (nový) — sekce: Authentik down/check, container restart, **CLI recovery-key usage** (`docker compose run --rm server create_recovery_key`), per-service fallback truth-table (`ALLOW_LOCAL_LOGIN` vs env-unset+recreate), secrets.yml backup, last-resort nuke-and-reroll. Pinnut `test_break_glass_runbook_present`.

**Open-redirect / CSRF / session-fixation:** autologin dědí Authentik OAuth2 ochrany — `redirect_uris` whitelist per-provider, **Authorization Code flow + PKCE** (ne Implicit), `state` validace, httpOnly cookies. Preloader JS nese per-service `ALLOWED_REDIRECT_HOSTS` whitelist (jen `<svc>.<tld>` + `auth.<tld>`).

**Pre-existující riziko, ne nové:** pure-SSO bez local fallback = lockout při Authentik-down platí už dnes pro každou native_oidc službu. Autologin to nezhoršuje. Doporučení: Authentik HA (2+ replicas) nebo akceptovat downtime risk; komentář v configu odkazuje runbook.

---

## Feature flag + rollout

```yaml
# ── SSO Autologin (β) ──────────────────────────────────────────────
# Global flag: auto-redirect/force-OIDC for native_oidc services that
# SUPPORT it (autologin.supports: yes). supports:no services stay
# button-only and CANNOT be flipped (gate test_autologin_no_means_no).
# RISK: misconfig + no local fallback = lockout if Authentik down.
# READ docs/break-glass-runbook.md before enabling.
sso_autologin: false                  # SAFE DEFAULT (opt-in)
sso_enable_custom_preloader: false    # Wing /hub splash (optional)
sso_autologin_local_fallback_enabled: false
sso_autologin_timeout_ms: 5000
# Per-tier / per-service overrides (precedence: svc > min_tier > global > false).
# NOTE: tier var is named sso_autologin_min_tier_<N> to avoid collision/confusion
# with the unrelated authentik_app_tiers / authentik_rbac_tiers structures.
# sso_autologin_min_tier_1: true
# sso_autologin_gitea: "{{ sso_autologin | default(false) }}"
# sso_autologin_n8n: false            # upstream CANNOT force-OIDC (supports:no, gate-locked)
```

- **Default `false`** — autologin mění UX a riskuje lockout; opt-in po manuálním testu každé login flow.
- **Granularita / precedence:** `sso_autologin_<svc>` > `sso_autologin_min_tier_<N>` > `sso_autologin` > `false`. **Tier var přejmenován na `sso_autologin_min_tier_<N>`** (původní `sso_autologin_tier_<N>` kolidoval významově s `authentik_app_tiers`/`authentik_rbac_tiers`). Loader pre-renderuje na bool přes `| bool` před blueprintem.
- **Blank-run:** autologin OFF. First-admin přes Wing invite-onboarding (A15, `?itoken=`). Po vytvoření prvního admina lze zapnout. Disabled service (`install_<svc>: false`) plugin neloadne → žádná autologin config, žádné state pollution.
- **Plná reverzibilita:** OFF→ON i ON→OFF je re-run playbooku; **žádná persistentní autologin state** (žádná DB tabulka kromě volitelného `nos-autologin-flow`, žádný token cache). Compose-extension re-render odebere/přidá env. Pozn.: env-driven force-OIDC (Grafana/WordPress) potřebuje recreate kontejneru (`--tags <svc>` auto-fire to udělá); config-hook služby (Nextcloud/Superset/HomeAssistant) potřebují re-run lifecycle hooku; preloader JS je request-time, bez restartu. Rollback při lockoutu: `sso_autologin: false` + re-run + per-service break-glass.

---

## Testy / gates

Všechny pod `tests/anatomy/`, vzor existujících `test_plugin_wiring_contract.py` / `test_sso_doctrine.py`. **Žádný z těchto gates dnes v repu neexistuje — Batch 0 je zavádí jako novou test-suite. Bez nich projdou nevalidní konfigurace (forward_auth s autologinem, supports:no flipnuté na enabled).**

| Gate | Pinuje |
|---|---|
| `test_autologin_only_for_native_oidc_services` | každý plugin s `autologin.enabled`≠false má `mode: native_oidc` (ne forward_auth/header_oidc; firefly=header_oidc autologin nedeklaruje). |
| `test_autologin_no_means_no` | **TVRDÁ POJISTKA:** plugin s `autologin.supports: no` nesmí mít `enabled` rezolvující na true při ŽÁDNÉ kombinaci svc/min_tier/global override. Projde n8n/hedgedoc/open-webui/firefly/erpnext/jellyfin/freescout(bez modulu) a fail-fastne na jakémkoli flipu. |
| `test_autologin_block_has_required_fields` | je-li `autologin` přítomen, blok má `client_id`, `client_secret`, `slug`, `mode`, `tier`, `supports`. |
| `test_autologin_config_var_resolves` | každý `{{ sso_autologin* }}` v authentik blocích končí `\| bool` a rezolvuje na valid bool (ne typo, ne loose-string truthiness). |
| `test_no_autologin_for_pure_proxy_services` | code-server/calibre-web/influxdb/… (forward_auth) NEMAJÍ autologin pole. |
| `test_infisical_no_enforce_in_oss` | infisical plugin nerenderuje enterprise-only "enforce OIDC" volání v OSS módu (jen button seed). |
| `test_local_login_fallback_renders_when_enabled` | pro `autologin:true` službu s `enable_<svc>_local_login:true` compose-extension podmíněně renderuje `ALLOW_LOCAL_LOGIN`. |
| `test_autologin_blueprint_binding_present` | `10-oidc-apps.yaml.j2`: `autologin.enabled` true → `authorization_flow` = `nos-autologin-flow`, jinak byte-identický s dneškem. |
| `test_each_autologin_plugin_renders_correct_env` | loader pre_compose render každého autologin pluginu obsahuje force-OIDC env (env reálně dorazí do kontejneru). |
| `test_recovery_key_persists_across_reruns` | `authentik_recovery_key` v `~/.nos/secrets.yml` je stabilní napříč re-runy (idempotentní read). **NEtestuje blueprint seed (nesplnitelné).** |
| `test_break_glass_runbook_present` | `docs/break-glass-runbook.md` existuje, čitelný, má sekce CLI recovery-key/restart/per-service fallback-truth-table. |
| `test_autologin_preloader_skippable` | `sso_enable_custom_preloader:true` → warmer JS má `?skip_splash=1` check + `prompt=none`-failure NEcyklí. |
| `test_preloader_does_not_block_fallback_login` | i s preloaderem on je local-login fallback dosažitelný. |
| `test_wing_unlock_endpoint_exists` | **JEN pokud se Batch 4 rozhodne `/api/unlock` implementovat** — endpoint s IP whitelist + shared-secret + rate-limit, BEZ závislosti na Authentik recovery tokenu. Skip/xfail dokud není implementováno. |
| `test_plugin_wiring_capabilities.md` update | doplnit autologin do `files/anatomy/docs/plugin-wiring-capabilities.md` + `tools/plugin-wiring-report.py`. |
| `docs/native-sso-survey.md` per-service break-glass matrix | každá z 20 native_oidc + 1 header_oidc služeb má zdokumentovaný break-glass param NEBO alternativu (env-unset+recreate / restart+ALLOW_LOCAL_LOGIN / manuální config), ověřeno na blank instanci. |

---

## Plán pro Workflow 2 (implementace)

Uspořádané, batchované. Každý batch = soudržný shippable kus.

### Batch 0 — Schema + global flag + gate scaffold (backbone)
- **Files:** `state/schema/plugin.schema.json` (NOVÝ autologin objekt), `default.config.yml` (NOVÉ `sso_autologin` + `sso_autologin_min_tier_<N>` + companions + komentář — tyto vars dnes neexistují), `tests/anatomy/test_autologin_config_var_resolves.py`, `test_autologin_only_for_native_oidc_services.py`, `test_autologin_no_means_no.py`, `test_no_autologin_for_pure_proxy_services.py`, `test_autologin_block_has_required_fields.py`, `test_infisical_no_enforce_in_oss.py`.
- **Effort:** S (0.5–1 den).
- **Unblocks:** kontrakt, na kterém stojí všechny per-service editty; gaty fail-fast na chybný plugin (zvláště `test_autologin_no_means_no` — bez něj lze nevalidně flipnout n8n/erpnext/jellyfin).
- **Verify:** `python3 -m pytest tests/anatomy/test_autologin_*.py`; `ansible-playbook main.yml --syntax-check`; ověřit, že `default.config.yml` definuje všechny `sso_autologin*` (jinak v `{{ vars }}` chybí).

### Batch 1 — Pilot: Grafana (nejvyšší confidence 0.95)
- **Files:** `files/anatomy/plugins/grafana-base/plugin.yml` (autologin blok, `supports: yes`), `grafana-base/templates/grafana-base.compose.yml.j2` (`{% if (...| bool) %}` → `GF_AUTH_OAUTH_AUTO_LOGIN=true` pod `[auth]` + `GF_AUTH_DISABLE_LOGIN_FORM=true` pod `[auth]` — **NE `_GENERIC_OAUTH_AUTO_LOGIN`/`_ENABLE_LOGIN_FORM`, ty v Grafaně neexistují**), `tests/anatomy/test_each_autologin_plugin_renders_correct_env.py`.
- **Effort:** S.
- **Unblocks:** dokazuje celou pipeline (manifest → aggregator → compose-extension render → recreate) na jedné službě end-to-end.
- **Verify:** `tools/nos-stacks.sh observability` s `-e sso_autologin=true`; `docker inspect grafana | grep -i AUTO_LOGIN` (musí být `GF_AUTH_OAUTH_AUTO_LOGIN`); browser na `grafana.<tld>` → redirect na Authentik bez formuláře; `?disableAutoLogin=true` → formulář se vrátí.

### Batch 2 — Fan-out clean wins (a)
- **Files:** plugin.yml + compose-extension pro: `bookstack-base`, `wordpress-base` (compose env, partial — viz pozn.); `freescout-base` (compose env — **jen pokud OAuth-Login modul přítomen; jinak `supports: no`**); `portainer-base/plugin.yml` (**hybrid: OIDC env + api_calls post-compose HideInternalAuth**); `nextcloud-base` **post_setup lifecycle hook (occ, NE compose env)**; `roles/pazny.superset/templates/superset_config.py.j2` (`OAUTH_SKIP_PROVIDER_SELECTION`, **verifikovat min-verzi**); `roles/pazny.homeassistant` configuration.yaml (config hook).
- **Effort:** M (2–3 dny).
- **Unblocks:** většina hodnoty — služby s hides_local_form=true.
- **Verify:** per-service blank/reconverge s `sso_autologin=true`; ověřit redirect + break-glass param; `test_autologin_blueprint_binding_present`; pro Portainer ověřit, že post_compose API call běží (ne jen env); pro Nextcloud ověřit, že occ hook proběhl (auto-redirect NEjde env-var).

### Batch 3 — Partial / needs-care (b) + honest "cannot" (c)/(d)
- **Files:** gitlab (`disable_password_authentication_for_web` — `supports: partial`, auto-redirect klíč neověřen), gitea (`gitea-base` SERVICE env + bootstrap-admin pořadí), outline (vynechat OIDC_DISABLE_REDIRECT), miniflux (`DISABLE_LOCAL_AUTH=1` + Traefik redirect middleware v `roles/pazny.traefik`), nodered (settings.js autoLogin + fallback admin), vaultwarden (`SSO_ONLY` — `supports: partial` jen s fork; jinak `no`), infisical (`supports: partial`, defer enforce + `test_infisical_no_enforce_in_oss`). Pro (c)/(d) — **žádná force flip, `autologin.supports: no` + komentář:** n8n, hedgedoc, open-webui, firefly(header_oidc → bez autologin bloku), jellyfin, erpnext, freescout(bez modulu).
- **Effort:** M–L (3–4 dny; gitea admin-pořadí a miniflux middleware jsou nejcitlivější).
- **Unblocks:** úplnost matice; čestná dokumentace upstream limitů gate-vynucená.
- **Verify:** gate `test_autologin_no_means_no` (n8n/erpnext/jellyfin/hedgedoc/open-webui musí mít `enabled`=false neflipnutelné); gitea: ověřit admin existuje před zamčením formuláře (jinak lockout); miniflux: middleware redirect `/login`→OIDC nedělá blank page + zdokumentovat, že break-glass je env-unset, ne UI.

### Batch 4 — Break-glass + lockout safety (PŘED širokým zapnutím)
- **Files:** secrets gen (`authentik_recovery_key` → `~/.nos/secrets.yml`, **NE blueprint**), `docs/break-glass-runbook.md` (CLI recovery `create_recovery_key` + per-service fallback truth-table), gaty `test_recovery_key_persists_across_reruns`, `test_break_glass_runbook_present`, `test_local_login_fallback_renders_when_enabled`. **`/api/unlock` je VOLITELNÝ** — pokud se implementuje, `files/anatomy/wing/app/Presenters/Api/UnlockPresenter.php` (IP whitelist + shared-secret + rate-limit, BEZ Authentik-token závislosti) + `test_wing_unlock_endpoint_exists`; jinak skip.
- **Effort:** M (1–2 dny bez `/api/unlock`; +1 den s ním).
- **Unblocks:** bezpečné default-on per-tier; bez tohoto se autologin nedoporučuje zapnout plošně.
- **Verify:** simulovat Authentik-down (`docker stop authentik-server`) → CLI `docker compose run --rm server create_recovery_key admin` mintne recovery URL; per-service break-glass (param NEBO env-unset+recreate dle truth-table) dosáhne lokálního přístupu; ověřit `~/.nos/secrets.yml` přežije re-run.

### Batch 5 — Custom preloader (Wing /hub + Authentik branding)
- **Files:** `files/anatomy/wing/app/Presenters/HubPresenter.php` (`renderSplash()`), `app/Templates/Hub/splash.latte`, `www/assets/hub-session-warmer.js` (s `prompt=none`-failure handling, **bez cyklení**), `www/assets/style.css`, `default.config.yml` (`sso_enable_custom_preloader`); Authentik `nos-autologin-flow` blueprint (Dummy stage + background + Custom CSS) + binding v `10-oidc-apps.yaml.j2`; gaty `test_autologin_preloader_skippable`, `test_preloader_does_not_block_fallback_login`.
- **Effort:** M (5–7 dní — splash + session pre-warm + cookie-domain negotiation testing + **end-to-end ověření implicit-consent silent-skip na cílové verzi Authentiku**, GH #15814/#13068/#8660; pokud nefunguje → explicit-consent + expression policy).
- **Unblocks:** "feels like one app" UX **pro repeat logins** (~100–200 ms mask); first-login latenci NEskryje — Authentik branding dělá first-login polished.
- **Verify:** mkcert (local TLD) + public TLD (LE), cross-subdomain redirect, `prompt=none` cookie dance s existující session (302 ~100 ms) **i bez session (graceful fallback na full flow, ne loop)**, 10 s timeout fallback; **dodržet Wing live-verify recipe** (port 9000, edge token + forward-auth headers, clear Latte cache).

### Batch 6 — Forward_auth second-login quick wins + docs/report
- **Files:** code-server (REMOTE_USER trusted-proxy), paperclip/openclaw/puter/woodpecker (header-provision config/patch), calibre-web (LDAP-header / no-auth+gate); `files/anatomy/docs/plugin-wiring-capabilities.md` + `tools/plugin-wiring-report.py` (autologin sloupec); `docs/native-sso-survey.md` (**per-service break-glass matrix pro všech 20 native_oidc + 1 header_oidc — tested param NEBO dokumentovaná alternativa**); `docs/upstream-pr-opportunities.md` (influxdb/metabase/uptime-kuma upstream waits).
- **Effort:** M (rozprostřené; header-provisiony jsou per-service patche).
- **Unblocks:** eliminace 6 z 11 forward_auth second-loginů; čestné zaznamenání 3 upstream-blocked + 1 by-design (snappymail).
- **Verify:** `test_plugin_wiring_contract.py`; per-service: po Authentik loginu žádný druhý login na `code-server.<tld>` apod.; `tools/plugin-wiring-report.py` zobrazí autologin pokrytí; `docs/native-sso-survey.md` má break-glass řádek pro každou native_oidc službu, ověřeno na blank instanci.
