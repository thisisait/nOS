#!/usr/bin/env python3
"""KEAP self-model generator — nOS architecture as a KEAP knowledge tree.

TWO SCHEMAS live in this file. `--schema` picks one; the default is `anchors`
so flipping to the new tree is a config change in the keap role, not a rewrite.

`anchors` (LEGACY, pre-contract-v1)
    One markdown card per service, anchored at KEAP *seed* taxonomy nodes
    ([[02.02]] and friends), written into a class-2 shared fs-sync tree:

        <out-root>/nOS/<stack>/<service>.md
        <out-root>/nOS/<stack>/_stack.md
        <out-root>/nOS/_platform.md

    Kept verbatim so an estate on the old pin keeps rendering. Everything below
    the `── legacy` banner belongs to it and is frozen.

`slug` (CONTRACT v1 — nOS <-> KEAP self-model)
    Two products under a single `--out` root:

      <out>/canonical/nos/nos.json          the platform root
      <out>/canonical/nos/nos.<stack>.json  that stack + its systems + credentials
      <out>/cards/<top>/<stack>/<Display>.md            per-system card
      <out>/cards/<top>/<stack>/<slug>/<skill>.md       per-skill card

    canonical/ is install-INVARIANT — every service nOS *can* run, regardless of
    install_* flags — because the taxonomy is the platform's shape, not this
    estate's inventory. It is consumed by KEAP's knowledge/ingest.mjs.

    cards/ is install-SPECIFIC — only ENABLED services, carrying live deployment
    state — and is consumed by KEAP's fs-sync mirror. A card anchors into the
    taxonomy with a bare [[nos.<stack>.<system>]] wikilink; anchors[0] decides
    where it lands, and a card with no anchor is invisible in the constellation.

WHY THE OLD TREE FAILED (and what this file must not repeat)
    Nine files named `_stack.md`, each carrying one near-identical sentence,
    became nine near-identical vectors and were measured as top recall hits for
    unrelated physics queries. Stacks are NODES now, not documents; and the `en`
    prose below is hand-written per node to be *discriminable* — what a thing IS
    and how it differs from its neighbours. A 20-char length floor is not
    quality, and a credential described in its consumer's vocabulary ("skills
    that touch files need it") steals its consumer's queries. Both are measured
    by KEAP's recall gate (e2e/fixtures/selfmodel-recall.json).

Determinism (both schemas): everything is sorted, nothing carries a timestamp or
a hash of runtime state, and writes are compare-and-skip — so an unchanged
manifest rewrites zero bytes and fs-sync does not re-embed.

python3 stdlib only, except PyYAML (already a hard playbook dependency).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

# ── contract v1: slugs ───────────────────────────────────────────────────────────
# KEAP's slug rule wins: /^[a-z][a-z0-9-]*$/ per dot-separated segment, first
# char a LETTER. The transform is a straight port of the nOS canonical slugifier
# (files/anatomy/face/src/lib/security/uid.ts :: slugifyUid) — it MUST stay
# byte-identical to it, so a segment derived here and a segment derived in the
# face agree. Underscored manifest ids (bluesky_pds) therefore become
# bluesky-pds; a leading digit (2fauth) is REJECTED loudly rather than silently
# never rendering.
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_COMBINING = re.compile(r"[̀-ͯ]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    """Port of uid.ts slugifyUid: NFKD, drop combining marks, lower, collapse."""
    s = unicodedata.normalize("NFKD", s or "")
    s = _COMBINING.sub("", s)          # Pázny → Pazny (accents DROPPED, not split)
    s = s.lower()
    s = _NON_ALNUM.sub("-", s)         # spaces, dots, '_', '@', leftovers → one '-'
    s = s.strip("-")[:64]
    return s.rstrip("-")


def slug_or_die(raw: str, what: str) -> str:
    """Slugify and enforce the KEAP segment rule, naming the offender on failure."""
    out = slugify(raw)
    if not SLUG_RE.match(out):
        raise SystemExit(
            f"keap_selfmodel_gen: {what} {raw!r} slugifies to {out!r}, which violates "
            "the KEAP segment rule /^[a-z][a-z0-9-]*$/ (first char must be a LETTER). "
            "Give it an explicit slug in SLUG_OVERRIDES before it silently disappears "
            "from the taxonomy."
        )
    return out


# Explicit slugs for ids the mechanical transform cannot rescue (leading digit,
# collision). Empty today; the guard above is what makes it discoverable.
SLUG_OVERRIDES: dict[str, str] = {}

ROOT_ID = "nos"
HOST_STACK = "host"  # bucket for manifest services with stack: null (host-native)

# Stack render order → the `ordinal` field. Substrate first, then what a person
# opens, then the specialist stacks; unknown stacks sort alphabetically after.
STACK_ORDER = [
    "infra", "observability", "iiab", "devops", "b2b", "data",
    "engineering", "voip", "host",
]

# fs-sync mirrors a markdown file's TITLE from its FILENAME basename — there is
# no H1 fallback. So these strings ARE the map labels. Card filenames only; the
# canonical node `name` stays the slug (matching KEAP's reference fixtures).
SYSTEM_NAME = {
    "postgresql": "PostgreSQL", "mariadb": "MariaDB", "redis": "Redis",
    "authentik": "Authentik", "infisical": "Infisical", "portainer": "Portainer",
    "traefik": "Traefik", "bluesky-pds": "Bluesky PDS", "smtp-stalwart": "Stalwart Mail",
    "grafana": "Grafana", "prometheus": "Prometheus", "loki": "Loki", "tempo": "Tempo",
    "wordpress": "WordPress", "nextcloud": "Nextcloud", "n8n": "n8n",
    "nodered": "Node-RED", "kiwix": "Kiwix", "offline-maps": "Offline Maps",
    "jellyfin": "Jellyfin", "open-webui": "Open WebUI", "uptime-kuma": "Uptime Kuma",
    "calibre-web": "Calibre-Web", "homeassistant": "Home Assistant", "rustfs": "RustFS",
    "face": "nOS face", "keap": "KEAP", "vaultwarden": "Vaultwarden", "ntfy": "ntfy",
    "miniflux": "Miniflux", "mailpit": "Mailpit", "watchtower": "Watchtower",
    "snappymail": "SnappyMail", "mcp-gateway": "MCP Gateway",
    "gitea": "Gitea", "gitlab": "GitLab", "woodpecker": "Woodpecker CI",
    "paperclip": "Paperclip", "code-server": "code-server",
    "erpnext": "ERPNext", "freescout": "FreeScout", "outline": "Outline",
    "hedgedoc": "HedgeDoc", "bookstack": "BookStack", "firefly": "Firefly III",
    "onlyoffice": "ONLYOFFICE",
    "metabase": "Metabase", "superset": "Superset", "influxdb": "InfluxDB",
    "freepbx": "FreePBX", "qgis-server": "QGIS Server",
    "alloy": "Grafana Alloy", "openclaw": "OpenClaw", "hermes": "Hermes",
    "opencode": "OpenCode", "wing": "Wing", "bone": "Bone",
    "iiab-terminal": "IIAB Terminal", "backup": "Backup", "backrest": "Backrest",
    "tailscale": "Tailscale",
}

ROOT_EN = (
    "The nOS platform's model of its own architecture: a navigable tree of compose "
    "stacks and the systems inside them. This root only organises — the substance "
    "lives on the deeper nodes. A node's presence means nOS can run it, not that "
    "this estate has it enabled."
)

# Stack prose. Each says what the stack is FOR and what it deliberately is not,
# so a stack node never wins a query that names a system inside it.
STACK_EN = {
    "infra": (
        "The infra compose stack: the substrate every other stack leans on — the edge "
        "proxy, the identity provider, the secret vault, and the shared relational and "
        "key-value stores. Nothing here is a destination in its own right; the things "
        "here are what make the rest possible."
    ),
    "observability": (
        "The observability compose stack: where the estate's own telemetry lands. "
        "Metrics, logs and traces each go to a purpose-built backend, and one dashboard "
        "surface queries all three."
    ),
    "iiab": (
        "The iiab compose stack: what a person on the tenant actually opens — knowledge "
        "archives, media, files, notifications, automation and the web desktop that "
        "fronts them."
    ),
    "devops": (
        "The devops compose stack: source code and the machinery around it — Git forges, "
        "continuous-integration runners and browser-based editors."
    ),
    "b2b": (
        "The b2b compose stack: the business applications — accounting, helpdesk, "
        "personal finance, document editing and the wikis a team writes into."
    ),
    "data": (
        "The data compose stack: analytics over data that already exists elsewhere — "
        "dashboard and query tools, plus a time-series store for measurements written "
        "by the estate's own instrumentation."
    ),
    # ── Single-member stacks ────────────────────────────────────────────────
    # These have no sibling to define themselves against, so they must NOT
    # restate what their one member does — that yields two near-identical
    # vectors and both lose the member's own queries. Each is written about its
    # PLACE in the estate: why it is a separate compose project at all.
    "engineering": (
        "The engineering compose stack: a deliberately isolated project for heavy "
        "domain tooling that is off by default and carries no dependency on the rest "
        "of the estate. It is separate so that specialist workloads can be enabled on "
        "one tenant without adding weight, or attack surface, to any other."
    ),
    "voip": (
        "The voip compose stack: the real-time boundary of the estate. It is the only "
        "project holding services that speak to the outside telephone network on their "
        "own protocols and ports, which is why it is isolated from everything routed "
        "through the ordinary web edge."
    ),
    "host": (
        "Host-native systems: the parts of nOS that run directly on the machine under "
        "launchd or systemd rather than in a container, because they need the host's own "
        "filesystem, devices or network stack."
    ),
}

# Per-system prose. Hand-written, not templated: each one says what the service IS
# and how it differs from its stack-mates. This is what the recall gate measures.
SYSTEM_EN = {
    # ── infra ──
    "postgresql": (
        "PostgreSQL, the estate's shared relational OLTP store. Services that need "
        "transactions, joins and a SQL schema keep their durable rows here — as opposed "
        "to the in-memory cache beside it, which keeps nothing."
    ),
    "mariadb": (
        "MariaDB, the second relational engine, kept because several PHP applications "
        "ship MySQL-dialect schemas and migrations that PostgreSQL will not accept. It "
        "is a compatibility store, not the preferred one."
    ),
    "redis": (
        "Redis, the shared in-memory key-value store. It holds sessions, locks, hot "
        "lookups and worker queues; everything in it is expendable and nothing is "
        "expected to survive a restart."
    ),
    "authentik": (
        "Authentik, the identity provider that decides who a request belongs to. It "
        "issues OIDC tokens and proxy headers for every other system, holds the group "
        "memberships that drive access tiers, and is the only place a person actually "
        "types a password."
    ),
    "infisical": (
        "Infisical, the machine-facing secret vault. Infrastructure credentials are "
        "stored, versioned and fetched here by the playbook and by agents over an API — "
        "distinct from the personal password manager, which is for humans."
    ),
    "portainer": (
        "Portainer, the browser console over the Docker daemon. It inspects containers, "
        "images, volumes and logs across every compose stack without an SSH session."
    ),
    "traefik": (
        "Traefik, the edge proxy. It terminates TLS and maps each hostname to a "
        "container; every request from outside the estate enters here first, and this is "
        "where the forward-auth identity check is attached."
    ),
    "bluesky-pds": (
        "The Bluesky Personal Data Server, an AT Protocol repository host. It owns social "
        "handles and their signed record repositories, which is a different kind of "
        "account from the OIDC login used everywhere else on the estate."
    ),
    "smtp-stalwart": (
        "Stalwart, the estate's real mail server: SMTP submission and delivery plus IMAP "
        "and JMAP mailboxes. Outbound notifications and per-user mailboxes both terminate "
        "here, unlike the capture-only development trap."
    ),
    # ── observability ──
    "grafana": (
        "Grafana, the query surface over every telemetry store: dashboards and ad-hoc "
        "exploration across metrics, logs and traces. It stores no telemetry of its own — "
        "it reads from the three backends beside it."
    ),
    "prometheus": (
        "Prometheus, the metrics time-series database. It scrapes numeric samples on an "
        "interval and answers PromQL range queries; it holds no log lines and no spans."
    ),
    "loki": (
        "Loki, the log store. It indexes only labels and keeps raw log text compressed, so "
        "a query filters by stream first and greps second — the counterpart to the metrics "
        "database, for text rather than numbers."
    ),
    "tempo": (
        "Tempo, the distributed-trace store. It keeps spans keyed by trace id so one "
        "request can be reassembled across services; instrumented code sends them here "
        "over OTLP."
    ),
    # ── iiab ──
    "wordpress": (
        "WordPress, the estate's public-facing website and blog. It is the one system "
        "meant to be read by anonymous visitors, in contrast with the wikis that sit "
        "behind the login."
    ),
    "nextcloud": (
        "Nextcloud, the tenant file cloud: WebDAV storage with sharing, calendars and "
        "contacts on top. The canonical home for user documents, as opposed to the S3 "
        "object bucket that machines write to."
    ),
    "n8n": (
        "n8n, the workflow automation engine. Operators wire HTTP triggers, schedules and "
        "third-party nodes into flows on a browser canvas; it is the general-purpose "
        "integration runner rather than a device-oriented one."
    ),
    "nodered": (
        "Node-RED, the flow runtime aimed at devices and message buses — MQTT, serial, "
        "GPIO and timers. It overlaps with the general automation engine but is chosen "
        "when the wires carry sensor traffic."
    ),
    "kiwix": (
        "Kiwix, the offline archive reader. It serves whole compressed snapshots of sites "
        "such as Wikipedia from local ZIM files, so reference material stays readable with "
        "no internet connection at all."
    ),
    "offline-maps": (
        "The offline map tile server. It serves vector and raster tiles out of local "
        "MBTiles archives, so a map renders without calling any hosted tile provider."
    ),
    "jellyfin": (
        "Jellyfin, the media library server. It catalogues film, television and music "
        "files, transcodes on demand and streams to client apps — a viewer for media, not "
        "a general file store."
    ),
    "open-webui": (
        "Open WebUI, the chat front end for locally hosted language models. Conversations, "
        "prompts and model selection live here; the weights and the inference run in the "
        "agent daemon it talks to."
    ),
    "uptime-kuma": (
        "Uptime Kuma, the availability prober. It repeatedly asks each endpoint whether it "
        "still answers and alerts when it stops — a black-box liveness check, unlike the "
        "metrics pipeline that reads a service's internals."
    ),
    "calibre-web": (
        "Calibre-Web, the ebook library. It browses a Calibre database of books, converts "
        "between formats and serves an OPDS feed to reader apps; video and audio belong to "
        "the media server instead."
    ),
    "homeassistant": (
        "Home Assistant, the home automation hub. It speaks to physical devices over "
        "Zigbee, Z-Wave, Matter and local IP, keeps their entity state, and runs the "
        "automations that act on it."
    ),
    "rustfs": (
        "RustFS, the S3-compatible object store. Machines write buckets and objects here "
        "over the S3 API — backups, artifacts and agent blobs — as opposed to the "
        "human-facing file cloud."
    ),
    "face": (
        "nOS face, the web desktop. It is the single window onto the estate: a dock of "
        "every enabled service, a file browser and control panels, rendered as one "
        "application rather than a list of links."
    ),
    "keap": (
        "KEAP, the knowledge cortex. It holds the curated taxonomy, resolves entries to "
        "the content services that actually store the material, and exposes the knowledge "
        "API that agents query."
    ),
    "vaultwarden": (
        "Vaultwarden, the personal password vault. Individual people keep their own logins "
        "here, unlocked with a master password — a different trust model from the "
        "machine-facing secret vault in infra."
    ),
    "ntfy": (
        "ntfy, the push notification broker. Anything on the estate can POST to a topic and "
        "reach a phone or desktop immediately; it is the fast path, where mail is the "
        "durable one."
    ),
    "miniflux": (
        "Miniflux, the feed reader. It polls RSS and Atom sources, keeps read state and "
        "presents articles as plain text; it consumes other people's publishing rather than "
        "publishing anything."
    ),
    "mailpit": (
        "Mailpit, the development mail trap. It accepts SMTP and never delivers anything, so "
        "a service's outgoing messages can be read and debugged without reaching a real "
        "recipient."
    ),
    "watchtower": (
        "Watchtower, the container image drift watcher. It compares each running container "
        "against its upstream tag and reports when the image it was started from has moved "
        "on."
    ),
    "snappymail": (
        "SnappyMail, the webmail client. It is a browser front end that connects to "
        "mailboxes over IMAP and sends over SMTP; it stores no mail itself — the mail "
        "server does."
    ),
    "mcp-gateway": (
        "The MCP gateway, which republishes Model Context Protocol tool servers as ordinary "
        "OpenAPI endpoints. It is an adapter, so chat front ends can call tools they do not "
        "natively understand."
    ),
    # ── devops ──
    "gitea": (
        "Gitea, the lightweight Git forge. It hosts repositories, issues and pull requests, "
        "and it is the account source the CI runner authenticates against — chosen where the "
        "heavyweight forge would be overkill."
    ),
    "gitlab": (
        "GitLab, the full DevOps forge: repositories plus its own pipelines, container "
        "registry and merge-request review surface. The heavyweight counterpart to the "
        "lightweight forge beside it."
    ),
    "woodpecker": (
        "Woodpecker, the CI engine. It watches the lightweight forge for pushes and runs "
        "pipeline steps in throwaway containers; it stores no repositories of its own."
    ),
    "paperclip": (
        "Paperclip, the multi-agent orchestration console. It fans one task out across "
        "several agent runs and collects the results, sitting above the individual agent "
        "daemons rather than replacing them."
    ),
    "code-server": (
        "code-server, a full VS Code editor served over HTTP. It gives a browser-only device "
        "a real editing and terminal session against the estate's filesystem."
    ),
    # ── b2b ──
    "erpnext": (
        "ERPNext, the enterprise resource planner: accounting ledgers, inventory, sales and "
        "HR in one Frappe application. It is the system of record for money and stock."
    ),
    "freescout": (
        "FreeScout, the shared-inbox helpdesk. Inbound customer mail becomes assignable "
        "conversations with history and internal notes — support workflow, not personal "
        "mail."
    ),
    "outline": (
        "Outline, the team wiki. Structured collections of long-lived documents with search "
        "and permissions; it targets curated internal knowledge rather than ad-hoc drafting."
    ),
    "hedgedoc": (
        "HedgeDoc, the real-time collaborative markdown pad. Several people type into the "
        "same document at once; it favours quick shared drafting over the wikis' structure."
    ),
    "bookstack": (
        "BookStack, documentation organised as shelves, books and pages. Its deliberately "
        "rigid hierarchy suits manuals and runbooks that need a fixed table of contents."
    ),
    "firefly": (
        "Firefly III, the personal finance ledger. It tracks accounts, budgets and "
        "transactions for a household — a smaller and different problem from the business "
        "resource planner in the same stack."
    ),
    "onlyoffice": (
        "ONLYOFFICE Document Server, the embedded editing engine. Other applications open a "
        "live, mutable document or spreadsheet in an iframe backed by this service; it edits, "
        "it never signs."
    ),
    # ── data ──
    "metabase": (
        "Metabase, the question-first analytics tool. Non-technical people build charts by "
        "clicking through a schema, with SQL kept as an escape hatch rather than the entry "
        "point."
    ),
    "superset": (
        "Superset, the analyst's exploration and dashboard platform. It assumes SQL fluency "
        "and offers deeper chart composition than the click-first tool beside it."
    ),
    "influxdb": (
        "InfluxDB, the time-series database for high-frequency measurements pushed by the "
        "estate's own instrumentation. It is a write target, distinct from the scrape-driven "
        "metrics store in observability."
    ),
    # ── voip / engineering ──
    "freepbx": (
        "FreePBX, the telephony control surface over Asterisk. It configures extensions, "
        "trunks, dial plans and call detail records — real phone calls, not chat."
    ),
    "qgis-server": (
        "QGIS Server, the OGC geospatial map service. It publishes WMS, WFS and WCS layers "
        "rendered from QGIS project files, for clients that speak the standard mapping "
        "protocols."
    ),
    # ── host ──
    "alloy": (
        "Grafana Alloy, the telemetry collector running on the host itself. It scrapes "
        "machine metrics, tails log files and receives OTLP spans, then forwards each to its "
        "matching backend; it stores nothing."
    ),
    "openclaw": (
        "OpenClaw, the autonomous DevOps agent daemon on the host. It runs long-lived agent "
        "loops against local language models and holds the tool permissions those loops act "
        "with."
    ),
    "hermes": (
        "Hermes, the cross-channel agent gateway. It bridges outside chat channels such as "
        "Telegram and Discord into the estate's agent runtime, so a conversation elsewhere "
        "reaches the same tools."
    ),
    "opencode": (
        "OpenCode, the agentic coding helper on the host. It works inside a checked-out "
        "repository, editing files and running commands, rather than serving a browser "
        "session."
    ),
    "wing": (
        "Wing, the operator dashboard and state-framework UI. It reads the estate's own "
        "event, migration, upgrade and agent-session tables, and it is where a human "
        "supervises what the automation did."
    ),
    "bone": (
        "Bone, the local HTTP bridge between playbook runs and the estate's own state store. "
        "Ansible callbacks, agents and scripts post events here; it is the write path for the "
        "platform's self-knowledge."
    ),
    "iiab-terminal": (
        "The IIAB terminal, a text user interface set as the forced shell for the kiosk "
        "account over SSH. It hands a console-only user a menu instead of a bare prompt."
    ),
    "backup": (
        "The nightly backup job on the host. It snapshots data directories and databases, "
        "encrypts them and ships them to the object store; it is the recovery path, not a "
        "synchronisation service."
    ),
    "backrest": (
        "A restic backup UI and scheduler, run as a host daemon. Where the backup job (its "
        "stack-mate) takes app-consistent logical dumps to the object store as the on-host "
        "copy, backrest orchestrates the off-site restic repository — the second copy — and "
        "adds a browse-and-restore web UI plus scheduled integrity checks. It complements the "
        "backup job, it does not replace it, and it does not itself dump databases."
    ),
    "tailscale": (
        "Tailscale, the mesh VPN. It gives the host a stable private address reachable from "
        "the operator's other devices without opening a port on the router."
    ),
}

# Credential prose — level-3 nodes hanging under the system that ISSUES them.
# Deliberately written about the SECRET (what kind it is, how it is minted, what
# rotating it does), never about what its consumers do with it: a credential that
# borrows its consumer's vocabulary steals its consumer's queries. A system with
# no issued secret (public, or reachable only via a container-local command line)
# gets NO credential node — absent is honest, a stub is noise.
CREDENTIAL_EN = {
    "authentik": (
        "The Authentik API token. An issued administrative secret scoped to the identity "
        "provider itself: it authorises reads and writes of users, groups, providers and "
        "flows, and rotating it changes nothing about who can log in."
    ),
    "bluesky-pds": (
        "The AT Protocol session token held for a repository account. A short-lived bearer "
        "credential minted by a handle-and-password exchange, unlike the long-lived API "
        "tokens issued elsewhere on the estate."
    ),
    "erpnext": (
        "The ERPNext API key and secret pair. Two halves of one issued machine identity, "
        "sent together on every request; either half alone is useless, and both rotate at "
        "once."
    ),
    "freescout": (
        "The FreeScout API key. A single issued string identifying a machine caller; it "
        "carries no person's identity, so anything done with it is attributed to the "
        "integration rather than to a user."
    ),
    "gitea": (
        "The Gitea personal access token. An issued secret bound to one forge account and a "
        "chosen scope set, standing in for a password on both Git transport and API calls."
    ),
    "grafana": (
        "The Grafana service-account token. An issued secret that belongs to a non-human "
        "account rather than to a person, so it survives any individual leaving."
    ),
    "homeassistant": (
        "The Home Assistant long-lived access token. An issued bearer secret with no expiry, "
        "minted from a user profile so an unattended integration keeps working."
    ),
    "infisical": (
        "The Infisical service token. An issued secret whose only purpose is to fetch other "
        "secrets, scoped to one project path; it sits at the root of the estate's secret "
        "chain."
    ),
    "jellyfin": (
        "The Jellyfin API key. An issued server-level secret that bypasses the per-viewer "
        "login, held by integrations rather than by a playback client."
    ),
    "metabase": (
        "The Metabase session token. A time-limited secret obtained by exchanging a username "
        "and password, carried in a dedicated session header rather than as a bearer token."
    ),
    "n8n": (
        "The n8n API key. An issued secret presented in a dedicated header to reach the "
        "automation engine's own management API — separate from any credential a workflow "
        "stores for a third party."
    ),
    "nextcloud": (
        "The Nextcloud app password issued to a machine account. An issued secret, nothing "
        "more: it stands in for the account's real password over basic auth, and it can be "
        "rotated without changing what any skill does."
    ),
    "open-webui": (
        "The Open WebUI bearer token. A signed token obtained by a sign-in exchange and valid "
        "for a bounded window; it represents a chat account, not a service identity."
    ),
    "outline": (
        "The Outline API token. An issued secret tied to one wiki member, so documents "
        "created with it carry that member's authorship and permissions."
    ),
    "portainer": (
        "The Portainer bearer token. A short-lived secret minted by an authentication call, "
        "granting whatever the container console itself can do — which is broad, because that "
        "console reaches the Docker daemon."
    ),
    "rustfs": (
        "The access key and secret used to sign RustFS requests. Not a bearer token: each "
        "request is signed under AWS Signature V4, so the secret itself never crosses the "
        "wire."
    ),
    "superset": (
        "The Superset bearer token. An issued token from a login exchange, refreshed on "
        "expiry, and separate from the CSRF token that write calls additionally demand."
    ),
    "uptime-kuma": (
        "The Uptime Kuma API key. An issued secret for the prober's HTTP surface only; its "
        "live control channel is a socket, so this credential reaches a narrow slice of the "
        "service."
    ),
    "vaultwarden": (
        "The Vaultwarden API token. An issued secret that reaches the vault server's API "
        "only — the vault items themselves stay encrypted under a separate master key this "
        "token cannot unlock."
    ),
    "wordpress": (
        "The WordPress application password. An issued per-application secret used with basic "
        "auth, revocable on its own so withdrawing one integration never disturbs the site "
        "owner's own login."
    ),
}

# docs/systems/<dir>/SKILLS.md — the directory name is the slugified service id
# for every system except this one, whose manifest id carries no separator to
# slugify. Explicit, because a silent miss loses a whole system's skill cards.
DOCS_DIR_ALIASES = {"homeassistant": "home-assistant"}

# Live deployment facts rendered onto a system card, in order. Keys are what
# tasks/selfmodel.yml resolves from the manifest's own *_var declarations.
FACT_LABELS = [
    ("image", "Image"),
    ("version", "Version"),
    ("domain", "Domain"),
    ("port", "Port"),
    ("data_path", "Data path"),
    ("mem_limit", "Memory limit"),
    ("cpus", "CPU limit"),
]


# ── contract v1: model ───────────────────────────────────────────────────────────

def _stack_ordinal(stack: str) -> tuple[int, str]:
    """Sort key for stacks: curated order first, then alphabetical for newcomers."""
    return (STACK_ORDER.index(stack) if stack in STACK_ORDER else len(STACK_ORDER), stack)


def _skills_path(docs_root: str, sslug: str) -> str | None:
    d = DOCS_DIR_ALIASES.get(sslug, sslug)
    p = os.path.join(docs_root, d, "SKILLS.md")
    return p if os.path.isfile(p) else None


def parse_skills(path: str) -> tuple[dict, list[dict]]:
    """Split a docs/systems/<svc>/SKILLS.md into (auth, [skill, ...]).

    A `## <heading>` section is a SKILL iff its body carries a `**Trigger:**`
    line — that is what separates the callable actions from the file's single
    `## Authentication` preamble. Returns the auth section's `**Method:**` value
    so the caller can decide whether the system issues a credential at all.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    sections: list[tuple[str, list[str]]] = []
    head, body = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if head is not None:
                sections.append((head, body))
            head, body = line[3:].strip(), []
        elif head is not None:
            body.append(line)
    if head is not None:
        sections.append((head, body))

    auth: dict = {}
    skills: list[dict] = []
    for name, lines in sections:
        joined = "\n".join(lines)
        if "**Trigger:**" not in joined:
            if name.lower().startswith("auth"):
                m = re.search(r"^\-\s+\*\*Method:\*\*\s*(.+?)\s*$", joined, re.M)
                auth["method"] = m.group(1) if m else ""
            continue
        trigger = ""
        facts: list[str] = []
        for ln in lines:
            s = ln.strip()
            if not s or s == "---":
                continue
            if s.startswith("**Trigger:**"):
                trigger = s[len("**Trigger:**"):].strip()
            elif s.startswith("**"):
                facts.append(s)
        skills.append({"name": name, "trigger": trigger, "facts": facts})
    return auth, skills


def _issues_credential(auth: dict) -> bool:
    """True when the system hands out a secret at all.

    `N/A` / `None (public…)` in the SKILLS.md Method line means access is decided
    at the edge proxy or by a container-local command — there is nothing to store
    or rotate, so no credential node is minted.
    """
    m = (auth.get("method") or "").strip().lower()
    return bool(m) and not (m.startswith("n/a") or m.startswith("none"))


def build_slug_model(manifest_path: str, docs_root: str) -> dict:
    """Derive the install-INVARIANT taxonomy from state/manifest.yml.

    install_* flags are deliberately ignored: the taxonomy is the shape of the
    PLATFORM, and a node's presence means nOS can run that system, not that this
    estate enabled it. Returns {'stacks': {stack: {...}}, 'systems': {id: {...}}}.
    """
    import yaml

    with open(manifest_path, encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh) or {}

    systems: dict[str, dict] = {}
    for s in manifest.get("services", []):
        sid = s["id"]
        sslug = SLUG_OVERRIDES.get(sid) or slug_or_die(sid, "service id")
        stack_raw = s.get("stack") or HOST_STACK
        stack = SLUG_OVERRIDES.get(stack_raw) or slug_or_die(stack_raw, "stack")

        en = SYSTEM_EN.get(sslug)
        if not en:
            # A new service without hand-written prose would land as a generic
            # vector and pollute recall. Fail loudly rather than ship filler.
            raise SystemExit(
                f"keap_selfmodel_gen: no SYSTEM_EN entry for {sslug!r} (manifest id "
                f"{sid!r}). Write a discriminable description — what it IS and how it "
                "differs from its stack-mates — before it enters the taxonomy."
            )

        skills: list[dict] = []
        credential = False
        sp = _skills_path(docs_root, sslug)
        if sp:
            auth, skills = parse_skills(sp)
            credential = _issues_credential(auth)
            if credential and sslug not in CREDENTIAL_EN:
                # Hard error, deliberately. Degrading to "no credential" would
                # drop the node AND the `**Requires:**` line from every skill
                # card of this system — and the contract reads an absent
                # Requires line as "NO precondition", never as "unknown". A
                # real precondition would silently become a declared absence,
                # with counts that still look plausible.
                raise SystemExit(
                    f"keap_selfmodel_gen: {sid} declares auth ({auth!r}) but has no "
                    f"CREDENTIAL_EN[{sslug!r}] prose. Write it — a generic or missing "
                    f"credential description is the failure this generator exists to avoid."
                )

        systems[sid] = {
            "manifest_id": sid,
            "slug": sslug,
            "stack": stack,
            "node_id": f"{ROOT_ID}.{stack}.{sslug}",
            "display": SYSTEM_NAME.get(sslug, sslug),
            "en": en,
            "credential": credential,
            "skills": skills,
        }

    stacks: dict[str, dict] = {}
    for sv in systems.values():
        st = sv["stack"]
        if st not in stacks:
            en = STACK_EN.get(st)
            if not en:
                raise SystemExit(
                    f"keap_selfmodel_gen: no STACK_EN entry for stack {st!r}. Write one "
                    "before it enters the taxonomy — a stack node with filler prose is "
                    "the _stack.md attractor all over again."
                )
            stacks[st] = {"slug": st, "node_id": f"{ROOT_ID}.{st}", "en": en, "members": []}
        stacks[st]["members"].append(sv["slug"])
    for st in stacks:
        stacks[st]["members"].sort()

    return {"stacks": stacks, "systems": systems}


# ── contract v1: canonical/ ──────────────────────────────────────────────────────

def _node(node_id: str, name: str, en: str, ordinal: int, parent: str | None) -> dict:
    """One ext node in KEAP's canonical shape. `level` == dot count; parentId is
    OMITTED on the root (not an empty string); `kind` is always "ext" — the
    "seed-override" kind is FORBIDDEN on a slug id."""
    out: dict = {
        "id": node_id,
        "level": node_id.count("."),
        "kind": "ext",
    }
    if parent is not None:
        out["parentId"] = parent
    out["name"] = name
    out["zone"] = "free"
    out["ordinal"] = ordinal
    out["en"] = en
    return out


def _domain_doc(domain: str, nodes: list[dict]) -> str:
    """Serialize one canonical domain file. Sorted, 1-space indent, trailing NL."""
    doc = {"domain": domain, "nodes": nodes, "relations": []}
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def render_canonical(model: dict) -> dict[str, str]:
    """Return {relative path under canonical/: file body}.

    One file per domain. The ROOT is its own domain file, and the lint rule is
    that every node must fall inside its file's domain scope — so nos.json holds
    only "nos", and nos.infra.json holds nos.infra plus everything beneath it.
    """
    files: dict[str, str] = {}

    files[f"{ROOT_ID}/{ROOT_ID}.json"] = _domain_doc(
        ROOT_ID, [_node(ROOT_ID, "nOS", ROOT_EN, 0, None)]
    )

    for ordinal, st in enumerate(sorted(model["stacks"], key=_stack_ordinal)):
        stack = model["stacks"][st]
        nodes = [_node(stack["node_id"], st, stack["en"], ordinal, ROOT_ID)]
        members = [sv for sv in model["systems"].values() if sv["stack"] == st]
        for i, sv in enumerate(sorted(members, key=lambda x: x["slug"])):
            nodes.append(
                _node(sv["node_id"], sv["slug"], sv["en"], i, stack["node_id"])
            )
            if sv["credential"]:
                # Credential ids are bare (`…​.credential`); the display NAME is
                # disambiguated, because a map full of nodes called "credential"
                # is unreadable. Ids are not names.
                nodes.append(
                    _node(
                        f"{sv['node_id']}.credential",
                        f"{sv['slug']}-credential",
                        CREDENTIAL_EN[sv["slug"]],
                        0,
                        sv["node_id"],
                    )
                )
        files[f"{ROOT_ID}/{stack['node_id']}.json"] = _domain_doc(stack["node_id"], nodes)

    return files


# ── contract v1: cards/ ──────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """A card's TITLE is its filename basename — fs-sync has no H1 fallback — so
    only path-hostile characters are stripped; the human wording is preserved."""
    return re.sub(r"[\\/\x00]+", "-", name).strip() or "untitled"


def render_system_card(sv: dict, facts: dict) -> str:
    """Install-SPECIFIC card: taxonomy anchor first, prose, then live state.

    No H1 (the filename is the title), no [[object:fs:…]] hashes and no
    "part-of / contains" prose: KEAP does not parse a relation TYPE, so that text
    is pure noise inside the embedded body.
    """
    lines = [f"[[{sv['node_id']}]]", "", sv["en"], ""]
    state = [(label, facts[k]) for k, label in FACT_LABELS if facts.get(k)]
    if state:
        lines.append("## Deployed state")
        lines += [f"- **{label}:** {val}" for label, val in state]
        lines.append("")
    if sv["skills"]:
        names = ", ".join(sorted(s["name"] for s in sv["skills"]))
        lines += [f"Callable skills: {names}.", ""]
    return "\n".join(lines)


def render_skill_card(sv: dict, skill: dict) -> str:
    """One skill card. The frontmatter block MUST lead the file or the router
    never sees it as a skill; it stays flat scalars only, because a single
    non-key line makes KEAP treat the whole block as body."""
    lines = [
        "---",
        "type: skill",
        f"title: {skill['name']}",
        "---",
        "",
        f"[[{sv['node_id']}]]",
        "",
        f"A callable action on {sv['display']}.",
        "",
    ]
    if skill["trigger"]:
        lines += [f"**Trigger:** {skill['trigger']}", ""]
    if sv["credential"]:
        # Precondition line: BODY, one line, full node ids, comma separated.
        # Absent means NO precondition — never a stub reading "unknown".
        lines += [f"**Requires:** `{sv['node_id']}.credential`", ""]
    if skill["facts"]:
        lines += skill["facts"] + [""]
    return "\n".join(lines)


def render_cards(model: dict, top: str, enabled: set[str] | None,
                 facts: dict) -> dict[str, str]:
    """Return {relative path under cards/: body} for ENABLED services only."""
    files: dict[str, str] = {}
    for sid in sorted(model["systems"]):
        sv = model["systems"][sid]
        if enabled is not None and sid not in enabled:
            continue
        sfacts = {
            k: str(v).strip()
            for k, v in (facts.get(sid) or {}).items()
            if v not in (None, "", "None") and str(v).strip()
        }
        base = f"{top}/{sv['stack']}"
        card = f"{base}/{_safe_filename(sv['display'])}.md"
        if card in files:
            raise SystemExit(
                f"keap_selfmodel_gen: two systems in stack {sv['stack']!r} both render to "
                f"{card!r}. Card filenames are TITLES and must be unique — fix SYSTEM_NAME."
            )
        files[card] = render_system_card(sv, sfacts)
        # Skills live one level down, keyed by the system slug, so two systems can
        # each own a `list-files` skill without colliding on a filename.
        for skill in sorted(sv["skills"], key=lambda s: s["name"]):
            fn = f"{base}/{sv['slug']}/{_safe_filename(skill['name'])}.md"
            files[fn] = render_skill_card(sv, skill)
    return files


# ── contract v1: write ───────────────────────────────────────────────────────────

def _write_tree(root: str, files: dict[str, str], suffixes: tuple[str, ...],
                result: dict) -> None:
    """Write `files` under `root`, compare-and-skip, then prune stale leftovers.

    A removed service's file must disappear so KEAP prunes its object; the prune
    only ever touches our own suffixes under our own root.
    """
    wanted: set[str] = set()
    for rel in sorted(files):
        path = os.path.join(root, rel)
        _write_if_changed(path, files[rel], result)
        wanted.add(os.path.realpath(path))
    if not os.path.isdir(root):
        return
    for dirpath, _dirs, names in os.walk(root):
        for n in sorted(names):
            if not n.endswith(suffixes):
                continue
            full = os.path.join(dirpath, n)
            if os.path.realpath(full) not in wanted:
                os.remove(full)
                result["removed"] += 1


def generate_slug(model: dict, out: str, top: str, enabled: set[str] | None,
                  facts: dict) -> dict:
    """Write <out>/canonical and <out>/cards. Returns counts."""
    result = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    _write_tree(os.path.join(out, "canonical"), render_canonical(model), (".json",), result)
    _write_tree(
        os.path.join(out, "cards"),
        render_cards(model, top, enabled, facts),
        (".md",),
        result,
    )
    return result


# ── legacy (schema=anchors) — frozen, do not extend ──────────────────────────────
# Everything below serves the pre-contract tree whose cards anchor at KEAP seed
# taxonomy nodes ([[02.02]]). It is kept byte-for-byte so an estate that has not
# flipped keap_selfmodel_schema keeps rendering exactly what it rendered before.

# ── taxonomy anchors (KEAP src/game/data/taxonomy.ts, Computer Science branch) ──
# Every card anchors to the CS root (whole-constellation ray) plus one category ray.
# Ids are dotted 2-digit — server/objects.ts classifyRef promotes [[NN.NN]] to a
# taxonomy-node anchor iff getNode(id) exists (all ids below are real v1.7.0 nodes).
CS_ROOT = "02.02"  # Computer Science
ANCHOR_BY_CATEGORY = {
    "database": "02.02.05",          # Databases
    "cache": "02.02.05.02",          # NoSQL Databases
    "identity": "02.02.08",          # Computer Security
    "secrets": "02.02.08",           # Computer Security
    "proxy": "02.02.07",             # Computer Networks
    "vpn": "02.02.07",               # Computer Networks
    "observability": "02.04",        # Information Theory (metrics/telemetry)
    "monitoring": "02.04",           # Information Theory
    "ci": "02.02.04",                # Software Engineering
    "devops": "02.02.04",            # Software Engineering
    "git": "02.02.04",               # Software Engineering
    "ai": "02.02.09",                # Artificial Intelligence
    "automation": "02.02.09",        # Artificial Intelligence
    "web": "02.02.07.04",            # Web Technologies
    "cms": "02.02.07.04",            # Web Technologies
    "content": "02.02.07.04",        # Web Technologies
    "storage": "02.02.06",           # Operating Systems (filesystems)
}
# Per-stack fallback anchor when the manifest category doesn't map above.
ANCHOR_BY_STACK = {
    "infra": "02.02.06",             # Operating Systems (platform substrate)
    "observability": "02.04",        # Information Theory
    "devops": "02.02.04",            # Software Engineering
    "b2b": "02.02.07.04",            # Web Technologies
    "data": "02.02.05",              # Databases
    "iiab": "02.02.07.04",           # Web Technologies
    "engineering": "02.02",          # Computer Science (generic)
    "voip": "02.02.07",              # Computer Networks
    "host": "02.02.06",              # Operating Systems
}

GEN_MARKER = "<!-- nOS self-model — generated by keap_selfmodel_gen.py from state/manifest.yml (spine) + per-plugin manifests (prose) + Ansible-resolved role vars (real state). Deterministic; edit the source, not this file. -->"


def _norm(s: str) -> str:
    return re.sub(r"[_-]", "", (s or "").lower())


def load_plugins(plugins_dir: str) -> dict:
    """Map normalized service id → {name, description} from *-base plugin.yml."""
    import yaml

    out: dict[str, dict] = {}
    if not os.path.isdir(plugins_dir):
        return out
    for entry in sorted(os.listdir(plugins_dir)):
        if not entry.endswith("-base"):
            continue
        p = os.path.join(plugins_dir, entry, "plugin.yml")
        if not os.path.isfile(p):
            continue
        try:
            with open(p) as fh:
                y = yaml.safe_load(fh) or {}
        except Exception:
            continue
        ui = (y.get("ui-extension") or y.get("ui_extension") or {})
        hub = (ui.get("hub_card") or {})
        authentik = (y.get("authentik") or {})
        name = (hub.get("title") or authentik.get("name") or "").strip()
        desc = (hub.get("description") or "").strip()
        if not desc:
            # top-level description is a paragraph — take the first sentence/line.
            top = (y.get("description") or "").strip()
            desc = re.split(r"(?<=[.!?])\s|\n", top)[0].strip() if top else ""
        out[_norm(entry[:-5])] = {"name": name, "description": desc}
    return out


def build_model(manifest_path: str, plugins_dir: str, deps: dict, anchors: dict,
                facts: dict | None = None) -> dict:
    """Return {'platform':..., 'stacks': {...}, 'services': {id: {...}}}.

    `facts` (from tasks/selfmodel.yml, keyed by service id) carries the REAL
    Ansible-resolved deployment values (version/image/port/domain/data_path/…).
    """
    import yaml

    facts = facts or {}
    with open(manifest_path) as fh:
        manifest = yaml.safe_load(fh) or {}
    plugins = load_plugins(plugins_dir)

    services: dict[str, dict] = {}
    for s in manifest.get("services", []):
        sid = s["id"]
        stack = s.get("stack") or HOST_STACK
        pj = plugins.get(_norm(sid), {})
        display = pj.get("name") or sid.replace("_", " ").replace("-", " ").title()
        # REAL facts for this service (empty strings/None dropped).
        sfacts = {k: str(v).strip() for k, v in (facts.get(sid) or {}).items()
                  if v not in (None, "", "None") and str(v).strip()}
        # Description = the plugin prose, appended with a real-state sentence so the
        # ACTUAL deployment (image:version, domain) lands in the embedded body.
        base_desc = pj.get("description") or (
            f"{display} — a {s.get('category') or 'platform'} service in the "
            f"nOS {stack} stack."
        )
        state_bits = []
        if sfacts.get("image"):
            iv = sfacts["image"] + (f":{sfacts['version']}" if sfacts.get("version") else "")
            state_bits.append(iv)
        elif sfacts.get("version"):
            state_bits.append(f"v{sfacts['version']}")
        if sfacts.get("domain"):
            state_bits.append(f"https://{sfacts['domain']}")
        description = base_desc + (
            f" Deployed as {', '.join(state_bits)}." if state_bits else ""
        )
        # Category anchor → stack anchor → CS root.
        cat = (s.get("category") or "").lower()
        anchor = (
            anchors.get(sid)
            or ANCHOR_BY_CATEGORY.get(cat)
            or ANCHOR_BY_STACK.get(stack)
            or CS_ROOT
        )
        # Dependencies: authentik for any SSO consumer, plus curated overrides.
        dep_set = set(deps.get(sid, []))
        if s.get("oidc") in ("native", "proxy") and sid != "authentik":
            dep_set.add("authentik")
        services[sid] = {
            "id": sid,
            "stack": stack,
            "display": display,
            "description": description,
            "category": s.get("category"),
            "tier": s.get("rbac_tier"),
            "oidc": s.get("oidc"),
            "domain_var": s.get("domain_var"),
            "anchor": anchor,
            "deps": sorted(dep_set),
            "facts": sfacts,
        }

    stacks: dict[str, list] = {}
    for sid, sv in services.items():
        stacks.setdefault(sv["stack"], []).append(sid)
    for st in stacks:
        stacks[st] = sorted(stacks[st])

    return {"stacks": stacks, "services": services}


# relPath is uid-relative (what KEAP fs-sync hashes into the object id) — the
# top-class dir IS `nOS`, so the shape is <top>/<stack>/<service>.md.
def _relpath_service(top: str, stack: str, sid: str) -> str:
    return f"{top}/{stack}/{sid}.md"


def _relpath_stack(top: str, stack: str) -> str:
    return f"{top}/{stack}/_stack.md"


def _relpath_platform(top: str) -> str:
    return f"{top}/_platform.md"


def _obj_id(uid: str, relpath: str) -> str:
    import hashlib

    return f"fs:{uid}:{hashlib.sha1(relpath.encode('utf-8')).hexdigest()[:16]}"


def _wikilink(uid: str, relpath: str) -> str:
    return f"[[object:{_obj_id(uid, relpath)}]]"


def render_service(model: dict, sid: str, uid: str, top: str) -> str:
    sv = model["services"][sid]
    stack = sv["stack"]
    lines = [f"# {sv['display']}", "", sv["description"], ""]
    lines.append(f"- **Stack:** {stack}")
    if sv["tier"] is not None:
        lines.append(f"- **RBAC tier:** {sv['tier']}")
    if sv["category"]:
        lines.append(f"- **Category:** {sv['category']}")
    if sv["oidc"]:
        lines.append(f"- **SSO:** {sv['oidc']}")
    lines.append(f"- **nOS role:** pazny.{sid}")
    # REAL deployed state (Ansible-resolved facts) — only the ones present.
    state = [(label, sv["facts"][k]) for k, label in FACT_LABELS if sv["facts"].get(k)]
    if state:
        lines.append("")
        lines.append("## State")
        for label, val in state:
            lines.append(f"- **{label}:** {val}")
    lines.append("")
    lines.append("## Relations")
    # Taxonomy anchors (render as rays): whole-map CS root + a category node.
    anchors = [CS_ROOT]
    if sv["anchor"] != CS_ROOT:
        anchors.append(sv["anchor"])
    lines.append(
        "- topic anchors: " + " ".join(f"[[{a}]]" for a in anchors)
    )
    # belongs-to → its stack card (object cross-link, embeddable + forward-compat).
    lines.append(
        f"- belongs-to {_wikilink(uid, _relpath_stack(top, stack))} — "
        f"the **{stack}** stack"
    )
    for dep in sv["deps"]:
        if dep in model["services"]:
            dstack = model["services"][dep]["stack"]
            lines.append(
                f"- depends-on {_wikilink(uid, _relpath_service(top, dstack, dep))} "
                f"— {model['services'][dep]['display']}"
            )
    lines += ["", GEN_MARKER, ""]
    return "\n".join(lines)


def render_stack(model: dict, stack: str, uid: str, top: str) -> str:
    members = model["stacks"][stack]
    lines = [
        f"# nOS stack: {stack}",
        "",
        f"The **{stack}** compose stack of the nOS platform — "
        f"{len(members)} service(s): {', '.join(members)}.",
        "",
        "## Relations",
        f"- topic anchor: [[{CS_ROOT}]]",
        f"- part-of {_wikilink(uid, _relpath_platform(top))} — the nOS platform",
    ]
    for sid in members:
        lines.append(
            f"- contains {_wikilink(uid, _relpath_service(top, stack, sid))} "
            f"— {model['services'][sid]['display']}"
        )
    lines += ["", GEN_MARKER, ""]
    return "\n".join(lines)


def render_platform(model: dict, uid: str, top: str) -> str:
    stacks = sorted(model["stacks"])
    n_svc = len(model["services"])
    lines = [
        "# nOS — platform self-model",
        "",
        "nOS is an Ansible-provisioned self-hosted Agentic Home Lab: "
        f"{n_svc} services across {len(stacks)} stacks, all FOSS, all local. "
        "This constellation is the platform's model of its own architecture, "
        "generated from state/manifest.yml.",
        "",
        "## Relations",
        f"- topic anchor: [[{CS_ROOT}]]",
    ]
    for st in stacks:
        lines.append(
            f"- stack {_wikilink(uid, _relpath_stack(top, st))} — "
            f"**{st}** ({len(model['stacks'][st])} services)"
        )
    lines += ["", GEN_MARKER, ""]
    return "\n".join(lines)


def generate(model: dict, out_root: str, uid: str, top: str) -> dict:
    """Write the whole tree under <out_root>/nOS/, prune stale .md. Returns counts."""
    result = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    nos_root = os.path.join(out_root, top)
    wanted: set[str] = set()

    plat_path = os.path.join(out_root, _relpath_platform(top))
    _write_if_changed(plat_path, render_platform(model, uid, top), result)
    wanted.add(os.path.realpath(plat_path))

    for stack in sorted(model["stacks"]):
        sp = os.path.join(out_root, _relpath_stack(top, stack))
        _write_if_changed(sp, render_stack(model, stack, uid, top), result)
        wanted.add(os.path.realpath(sp))
        for sid in model["stacks"][stack]:
            fp = os.path.join(out_root, _relpath_service(top, stack, sid))
            _write_if_changed(fp, render_service(model, sid, uid, top), result)
            wanted.add(os.path.realpath(fp))

    # Prune stale generated cards (a removed service's card must disappear so
    # fs-sync prunes its object). Only touch .md under our own nOS/ subtree.
    for dirpath, _dirs, files in os.walk(nos_root):
        for f in files:
            if not f.endswith(".md"):
                continue
            full = os.path.join(dirpath, f)
            if os.path.realpath(full) not in wanted:
                os.remove(full)
                result["removed"] += 1

    return result


# ── shared: write with compare-and-skip ──────────────────────────────────────────

def _write_if_changed(path: str, content: str, result: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = content.encode("utf-8")
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            if fh.read() == data:
                result["unchanged"] += 1
                return
        with open(path, "wb") as fh:
            fh.write(data)
        result["updated"] += 1
        return
    with open(path, "wb") as fh:
        fh.write(data)
    result["created"] += 1


# ── cli ──────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the KEAP nOS self-model tree.")
    ap.add_argument("--schema", choices=["anchors", "slug"], default="anchors",
                    help="'anchors' = the legacy seed-anchored card tree (DEFAULT, "
                         "keeps today's behaviour); 'slug' = the contract-v1 canonical "
                         "taxonomy + install-specific cards")
    ap.add_argument("--manifest", required=True, help="path to state/manifest.yml")
    ap.add_argument("--plugins-dir", default="", help="files/anatomy/plugins (schema=anchors)")
    ap.add_argument("--docs-root", default="docs/systems",
                    help="docs/systems root holding <svc>/SKILLS.md (schema=slug)")
    ap.add_argument("--out", default="",
                    help="schema=slug output root; gets canonical/ and cards/")
    ap.add_argument("--out-root", default="",
                    help="schema=anchors output root, e.g. .../shared/nos-docs")
    ap.add_argument("--uid", default="nos-docs",
                    help="KEAP fs-sync owner uid the tree mounts as (default nos-docs)")
    ap.add_argument("--top", default="nOS",
                    help="fs-sync top class dir under the uid (default nOS)")
    ap.add_argument("--deps-json", default="{}",
                    help="JSON map {service:[dep,...]} of extra dependency edges "
                         "(schema=anchors)")
    ap.add_argument("--anchors-json", default="{}",
                    help="JSON map {service: 'NN.NN'} of per-service taxonomy anchors "
                         "(schema=anchors)")
    ap.add_argument("--enabled-json", default="",
                    help="JSON list of ENABLED manifest service ids — cards are written "
                         "only for these. Omit to write a card for every service "
                         "(schema=slug). canonical/ ignores this by contract.")
    ap.add_argument("--facts-json", default="{}",
                    help="JSON map {service: {version,image,port,domain,...}} of REAL "
                         "Ansible-resolved deployment facts (from tasks/selfmodel.yml)")
    args = ap.parse_args(argv)

    facts = json.loads(args.facts_json or "{}")

    if args.schema == "slug":
        # NOT `args.out or args.out_root`: the two roots mean different shapes
        # (slug writes <out>/canonical + <out>/cards, anchors writes
        # <out-root>/<top>). Accepting the legacy flag here would quietly write
        # a contract-v1 tree into the legacy card root and look like it worked.
        out = args.out
        if not out:
            ap.error("--schema slug requires --out (not --out-root)")
        enabled = None
        if args.enabled_json.strip():
            enabled = set(json.loads(args.enabled_json))
        model = build_slug_model(args.manifest, args.docs_root)
        result = generate_slug(model, out, args.top, enabled, facts)
        result["schema"] = "slug"
        result["systems"] = len(model["systems"])
        result["stacks"] = len(model["stacks"])
        result["credentials"] = sum(
            1 for sv in model["systems"].values() if sv["credential"]
        )
        result["skills"] = sum(len(sv["skills"]) for sv in model["systems"].values())
        print(json.dumps(result, sort_keys=True))
        return 0

    if not args.out_root:
        ap.error("--out-root is required with --schema anchors")
    if not args.plugins_dir:
        ap.error("--plugins-dir is required with --schema anchors")
    deps = json.loads(args.deps_json or "{}")
    anchors = json.loads(args.anchors_json or "{}")
    model = build_model(args.manifest, args.plugins_dir, deps, anchors, facts)
    result = generate(model, args.out_root, args.uid, args.top)
    result["services"] = len(model["services"])
    result["stacks"] = len(model["stacks"])
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
