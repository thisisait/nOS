# Agent-Operable nOS — strategie a roadmapa

> Cílový stav: **autonomní LLM agenti najdou bezpečnostní díry, navrhnou
> patch, otestují ho přes preview, počkají na lidský souhlas u rizikových
> operací, aplikují, ověří, a v případě problému rollbacknou — to vše
> přes deklarativní artefakty, které engine umí zvalidovat _před_
> spuštěním.** Tento dokument je destilát aktuálních bolístek a navrhuje
> architekturu, která je odpaluje.

## 1. Kde jsme dnes (čestný snímek)

**Funguje a je solidní:**
- Ansible playbook, plně idempotentní, blank reset replikovatelný
- 60+ služeb, 8 stacků, Authentik SSO + auto-OIDC
- State framework: `state/manifest.yml` + migrations + upgrades + coexistence
- Predicate engine + JSON Schema validace (chytl jeden druh regresí, viz `tests/state_manager/test_schema_handler_consistency.py`)
- Wing telemetry pipeline: Ansible callback → Bone HMAC → `wing.db.events` ✓ ověřeno end-to-end
- 1 949 events z posledního blank runu, 0 ve fallback queue
- Mailpit dev SMTP sink + Bone API + ACME role (čeká jen na CF token + Wedos NS delegation)

**Je co vylepšit (=bolístky, co nás celý týden trápí):**

| # | Bolístka | Frekvence | Cena pro agenta |
|---|---|---|---|
| 1 | Ručně zaregistrovat službu do **5 různých míst** (`authentik_oidc_apps`, `health-probes.yml`, `state/manifest.yml`, `nginx_sites_auto`, `RBAC tiers`) | Každá nová služba | Vysoká — agent zapomene jeden seznam → broken |
| 2 | `failed_when: false` skrývá reálné chyby (FreeScout module clone, WordPress install, Bluesky bridge) | Často | Vysoká — agent vidí "ok" v logu, realita prázdná |
| 3 | Authentik blueprints jsou **write-once** v PostgreSQL — flip TLD = stale OIDC discovery URL | Při změně TLD | Střední — agent musí vědět že re-apply je nutný |
| 4 | Schema/handler drift se objeví až **at runtime** (typeerror v migration engine) | Občas | Vysoká — pre-emptivní validace by ušetřila debug |
| 5 | First-run race conditions: PG user ještě neexistuje, container restart-loopy, Wing.db schema not ready | Při blank | Střední — fixed v 503-retry, ale architektura by tomu měla bránit |
| 6 | Telemetrie zachytí "co se stalo" ale **ne "kdo to spustil a proč"** | Vždy | Vysoká — agent nevidí svůj vlastní řetězec kauzality |
| 7 | Wing dashboard je **read-only** — agent najde problém, ale operator musí klikat manuálně | Vždy | Vysoká — žádný "approve patch" workflow |
| 8 | Patches/upgrades jsou opt-in, agent je nemůže iniciovat | Vždy | Kritická — celá AI-driven smyčka chybí |
| 9 | Žádné CVE / dependency feed | Pasivní | Kritická — agent nemá co skenovat |
| 10 | Service descriptor je **rozdrobený** (info o službě se píše do role defaults, do default.config.yml, do health-probes, do manifestu) | Vždy | Kritická — single source of truth chybí |

## 2. Vize: jak vypadá "agent-operable" nOS

Krátce: **každá změna prochází stejným pipeline** — declarative artifact → engine validace → preview → human-or-policy approval → apply → verify → telemetry. Agent píše YAML, engine ho zkontroluje, lidský operátor (nebo autonomous policy) schválí, engine aplikuje. Nikdy agent nemá raw `kubectl`/`docker exec`/`ansible-playbook --tags risky`.

```
┌─────────────────────────────────────────────────────────────────────┐
│  EYE        Vulnerability scanner (CVE feeds, dep audit)            │
│              ↓ findings → events                                    │
│  EAR        Signal triage (probe failures, alerts, scan_cycles)     │
│              ↓ classified → events                                  │
│  BRAIN      LLM agent reads events + state, drafts patches          │
│              ↓ patch.yml (declarative artifact)                     │
│  SPINE      Schema validation, predicate eval, dry-run preview      │
│              ↓ preview JSON → Wing UI                               │
│  HAND       Operator approves (or policy auto-approves low-risk)    │
│              ↓ approval token                                       │
│  BONE       Action dispatcher: applies via existing engines          │
│              (nos_migrate, upgrade, patch, coexistence)             │
│              ↓ events                                               │
│  WING       Read model + dashboard + audit trail                    │
└─────────────────────────────────────────────────────────────────────┘
```

Klíčové vlastnosti:
- **Žádný free-form action.** Agent neumí provést nic, co není schémou popsáno. To zabraňuje halucinacím a sniženému blast-radius.
- **Capability-based authz.** API token "patch:draft" ≠ "patch:apply". Agent dostane draft, lidský/policy souhlas vystaví apply token.
- **Causality chain v telemetrii.** Každý event má `trigger.type` (`manual` | `scheduled` | `agent:openclaw` | `policy`) + `parent_event_id`. Audit kdo udělal co a proč.
- **Dry-run je first-class.** Žádná operace není "spusti a uvidíme" — vše má `preview` endpoint, který vrací co by se stalo.

## 3. Rozšíření anatomie: Spine, Ear, Eye, Hand

Ve stávající anatomii máme **Bone** (state/dispatcher) + **Wing** (read model) + **OpenClaw** (agent runtime) + **Hermes** (messaging). Pro agent operability potřebujeme tři nové orgány a Bone se trochu rozdělí:

### **Spine** — kontraktový spec (single source of truth)
Co: jeden katalog služeb (`state/services.yml`) ze kterého se DERIVUJÍ:
- `authentik_oidc_apps`
- `health-probes.yml`
- `state/manifest.yml`
- `nginx_sites_auto` whitelist
- `authentik_app_tiers` RBAC mapování
- compose-override port + domain pro role

**Dnes:** 5 míst pro každou službu, agent zapomene některé.
**Zítra:** 1 záznam v `state/services.yml`, generátor (`pazny.spine` role) emituje zbylé. Bolístka #1 a #10 zmizí.

### **Eye** — vulnerability scanner
Co: launchd agent, který:
- Pravidelně tahá NVD / OSV.dev feed
- Cross-referencuje s `state.yml.services[*].installed` (verze, image digesty, dependency hashes)
- Emituje high-severity findings jako events
- Wing dashboard má `/cve` view

**Dnes:** žádné (Wing hlásí "16 CRITICAL Cycle 14" z legacy scan-state.json).
**Zítra:** real CVE feed → real telemetry → agent material to work with.

### **Ear** — signal triage
Co: konsoliduje **všechny** signály do unified stream:
- HTTP probe failures
- Authentik outpost / login failures
- Container restart-loops (nos_state introspect)
- Backup failures
- CVE findings (z Eye)
- Drift detekce (desired vs observed)

Klasifikuje (`network` | `auth` | `disk` | `dependency` | `config` | `unknown`) + emituje structured event s remediation pointer.

**Dnes:** každý signál si žije zvlášť (probe → ansible log; CVE → nikam; drift → nikde).
**Zítra:** jeden stream, agent jeden adresát.

### **Hand** — capability-gated executor
Co: oddělit "I/O dispatcher" (Bone) od "actuator" (Hand). Bone dělá routing + auth, Hand provádí.

Hand má registry actions:
- `patch.apply(patch_id, approval_token)` 
- `service.restart(svc, reason)` — bezpečné, idempotent
- `migration.apply(id, approval_token)`
- ...

Každá akce má `safety_level` (`readonly` | `idempotent` | `mutating` | `irreversible`). Agent může vyvolat readonly+idempotent volně, mutating vyžaduje approval token, irreversible vyžaduje human-in-the-loop.

**Dnes:** Bone vystavuje POST endpoints chráněné jediným BONE_SECRET. Agent který má klíč může vše.
**Zítra:** capability tokens, audit trail, blast radius bounded.

## 4. Konkrétní vylepšení — co lze přinést kdy

### **Quick wins (možno PŘED domain flip, ~1 sezení každá)**

#### W1. Telemetry enrichment (event schema v2)
Přidat do event schema: `trigger`, `parent_event_id`, `safety_level`, `error_class` (pro task_failed).
- Callback plugin populuje `trigger` z env / play vars (`agent` | `manual` | `cron`)
- `parent_event_id` z `--extra-vars run_parent_event_id=…` chain
- `safety_level` z task tag annotations (`@safety:idempotent` v `name:`)
- `error_class` z exit code / stderr patterns (zjednodušený dispatcher)

**Benefit:** příští blank má již enriched events. Wing UI může zobrazit kauzalitu a klasifikaci. Agent dostává čitelnější vstup.

**Cena:** 50 řádků v `wing_telemetry.py` + sloupcový migrace v `wing.db.events`. Schema test ujistí že staré payloady stále projdou.

#### W2. Service descriptor — zárodek Spine (1 stack)
Vyrobit `state/services.yml` ALE jen pro 1 stack na začátek (např. observability). Generator role `pazny.spine` který ze services.yml emituje rozdíly do existujících struktur. 

**Cena:** generator je ~200 řádků Jinja, services.yml ~30 záznamů. Existující struktura zůstává — Spine pouze GENERUJE její podsekce, nemění lifecycle.

**Benefit:** první real test patternu. Nová služba (mailpit, bone) by se přidávala jen do services.yml.

#### W3. Zničit `failed_when: false` na critical-path tasks
Audit + opravit. Hlavní hříšníci:
- `roles/pazny.freescout/tasks/post.yml` — module clone failed silently
- `roles/pazny.bluesky_pds/tasks/post.yml` — `-invite-code` flag bug zamlčen
- Various OIDC post-setup tasks

**Cena:** ~1 hodina grep + audit + decision per task (drop-the-failed_when vs add-real-recovery). Risk regrese — ale lépe failnout znovu než tichá broken instance.

#### W4. Drift detection — first pass
Nová role `pazny.drift_check` která po každém runu:
- Načte `state/manifest.yml` (desired)
- Načte `~/.nos/state.yml` (observed — generated by introspect)
- Diffuje
- Emituje `drift_detected` event s diff payload

**Benefit:** agent má strukturovaný "what's wrong" vstup. Wing dostane `/drift` view.

#### W5. CI guard for failed_when:false
Test: `python3 -m pytest tests/ci/test_no_silent_failures.py` — projede `roles/**/*.yml` a flagne `failed_when: false` mimo whitelisted patterns. Zabrání regresi po W3.

### **Medium-term (po flipu, ~1 týden)**

#### M1. Patch authoring API + UI
- `/api/patches/draft` — agent submituje YAML draft  
- `/api/patches/<id>/preview` — dry-run (engine už existuje)
- `/api/patches/<id>/apply` — vyžaduje approval token
- Wing UI `/recommendations` — pending list, approve/deny tlačítka

#### M2. CVE Eye — minimal
- `pazny.cve_watcher` role: launchd plist, daily fetch OSV.dev, cross-ref s state, emit events
- Wing UI `/cve` view

#### M3. Capability tokens (Hand → Bone)
Refaktorovat Bone authentik na capability-based:
- BONE_SECRET odeznívá → tokens vystavované Hand orgánem
- Tokeny mají scope + expirační čas + audit trail

### **Strategic (po stabilizaci, měsíce)**

- **Spine plně rolled out** — všech 60+ služeb v `services.yml`, generator emituje vše ostatní. Nová služba = jeden YAML soubor.
- **Autonomous policy engine** — některé akce (patch s low CVE severity, restart non-prod containers) povolit bez human approval. Vyžaduje policy DSL + důvěryhodný OpenClaw.
- **Cross-instance fleet mode** — Bone na centrálním uzlu agreguje state z mnoha hostitelů, agent vidí celou flotilu, koordinované patche napříč fleetem.

## 5. Doporučená sekvence pro **PŘÍŠTÍCH 7 DNÍ**

```
DNES (před TLD flipem)            ETA       Risk
─────────────────────────────────────────────────────
1. W1: telemetry enrichment       2-3h      low
2. W3: failed_when audit          1-2h      medium (regrese)
3. W5: CI guard for #2            30 min    nope
4. Push 14+1+W1+W3+W5 commitů     5 min     none

—————— WEDOS DELEGATION 5 min, propagace 1-24h ————

PAK (hybrid flip)                 ETA       Risk
─────────────────────────────────────────────────────
5. Wedos NS delegation → CF       5 min     none
6. CF API token + DNS records     10 min    none
7. config.yml: instance_tld+hybr  30 sec    none
8. blank=true                     ~25 min   medium (CF first contact)
9. Playwright UI sweep            30 min    none

—————— TÝDEN PO FLIPU ————

10. W2: services.yml + Spine      4h        low
11. W4: drift detection           2h        low
12. M1: patch UI                  1 den     medium (Wing changes)
```

## 6. Co tímhle dokumentem ŘEŠÍME

Ten "out-of-the-box pohled" který jsi chtěl: **přestaneme řešit jednotlivé bolístky reaktivně**, místo toho:

1. **Connectovat dosud fragmenty** (Spine pattern → 5 míst se redukuje na 1)
2. **Strukturovat telemetrii pro AI agenta** (W1: trigger + causality + safety_level + error_class — to LLM dokáže klasifikovat)
3. **Otevřít smyčku člověk-stroj** (M1: agent navrhuje, člověk schvaluje, engine aplikuje)
4. **Aktivně skenovat zranitelnosti** (M2: bez Eye nemá agent co dělat)
5. **Eliminovat tiché chyby** (W3+W5: pokud něco selhalo, ať to víme)

Pomalé budování. Ale každá z těch 12 položek má jasný entry/exit kritérium a *žádná z nich blokuje TLD flip*. Quick wins (W1/W3/W5) by chtělo doručit ještě před flipem; zbytek je post-flip krmení.
