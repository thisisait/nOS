# NGI Zero Commons Fund — application draft

**Project name:** nOS — sovereign FOSS deployment automation for SMB and public sector

**Applicant:** This is AIT (Czech consultancy) — pazny.develop@gmail.com

**Website:** https://thisisait.eu • **Code:** https://github.com/thisisait/nOS

**Requested grant:** €50,000

**Cutoff target:** 2026-06-01 (NGI Zero Commons Fund)

---

## 1. Abstract (≤ 1200 chars)

nOS is an Ansible-driven self-hosted server suite that lets a 5–30 person organization replace Microsoft 365 / Google Workspace / Atlassian / GitHub-hosted services with ~50 FOSS components running on a single Apple Silicon Mac or Linux machine (Ubuntu LTS). Every service is wired into central Authentik SSO with an automatic OIDC provider+application setup, a four-tier RBAC, and end-to-end TLS via Let's Encrypt DNS-01. Telemetry events flow to a Wing dashboard; an upgrade engine applies versioned recipes with backup + rollback. The stack is currently macOS-only; this grant funds the Linux port plus integration of `cloud-gouv/securix` ANSSI hardening rules and La Suite numérique components (Docs, Meet) — directly aligning the project with French and Danish FOSS-first sovereignty plans, and giving Czech and EU SMBs a credible self-hosted alternative compliant with GDPR and the AI Act.

## 2. Problem

European SMBs and small public bodies are economically forced into US-hosted SaaS for office, identity, communications, and CI/CD. The cost is recurring, the data leaves the jurisdiction, and the AI Act's training-data provenance requirements are in tension with the SaaS data-flow model.

Self-hosted FOSS alternatives exist for every individual function (Nextcloud, Authentik, n8n, Mattermost, Gitea, …) but **deployment automation that integrates them coherently and stays current** does not. A 30-person company cannot maintain 50 individual upstreams. Without a maintained "FOSS-stack-as-a-service" layer, sovereignty stays theoretical.

## 3. Proposed solution

### 3.1 What exists today (state at 2026-04)

- **59 Ansible roles** under `pazny.*` namespace deploying 46 Docker services + 10 host services
- **Authentik SSO + auto-OIDC** for all services (native env-var or proxy_auth depending on app capability)
- **State + migration + upgrade + coexistence framework** with declarative YAML recipes, JSON Schema validation, and predicate engine (`module_utils/nos_migrate_*`)
- **Wing dashboard** + Bone FastAPI + `wing_telemetry` Ansible callback plugin pipeline (tested end-to-end, 1949 events from a single blank reset)
- **Mailpit dev SMTP sink** + outbound-mail roadmap via Stalwart smarthost
- **Watchtower** image-drift watcher with email alerts, label-gated for safety
- **ACME (Let's Encrypt) wildcard cert via Cloudflare DNS-01**
- **Anatomy naming** — Bone (state/dispatch), Wing (read model), OpenClaw (LLM agent runtime), Hermes (cross-channel messaging)
- **350+ Python tests** + 71 PHP tests covering the framework engines

### 3.2 What this grant funds (12 months)

| Workstream | Effort | Output |
|---|---|---|
| Linux port (Ubuntu 24.04 LTS, ARM64 + x86_64) | 3 months | `pazny.linux.{apt,systemd_user}` + cross-platform refactor of host roles + Linux integration CI |
| ANSSI hardening role (translated from `cloud-gouv/securix`) | 1 month | `pazny.hardening` — sysctl + auditd + PAM hardening, opt-in, citing securix as design reference |
| La Suite numérique integration | 2 months | `pazny.lasuite_docs` (collaborative editor, MIT, OIDC) + `pazny.lasuite_meet` (LiveKit videoconferencing, MIT) |
| EUDIW / ProConnect identity federation | 2 months | Authentik blueprint + `django-lasuite` integration, makes nOS deployments EUDIW-ready |
| Documentation + sovereignty case studies | 2 months | Public deployment guide, two pilot case studies (CZ accounting firm + EU NGO) |
| Project management + community engagement | 2 months | Public roadmap, monthly progress reports, Mastodon/X presence, conference talks (FOSDEM, OpenAlt, Akademy) |

### 3.3 Why now

Three EU initiatives create a window:
1. **France / Denmark FOSS-first plans** — DINUM publishes `cloud-gouv/securix` (2025), La Suite numérique is being adopted across French ministries (2024–2026)
2. **AI Act compliance pressure** — SMBs need to demonstrate where training data sits; self-hosted is the cleanest answer
3. **EUDIW Phase 3** — Q3 2026 expected calls require integrators with reference implementations

## 4. Comparable projects + differentiation

- **YunoHost** — Debian-only, less granular OIDC, less observability, no upgrade engine. Friendly to home users; less to SMBs.
- **Sandstorm.io** — different paradigm (per-user app sandboxes), low recent activity.
- **Cloudron** — proprietary parts, single-vendor risk, paid tier-gated features.
- **k3s + Helm charts (community)** — operationally heavier, requires cluster-ops literacy unsuitable for SMB IT.

nOS's differentiation: **single-host Ansible playbook** with full SSO + state + telemetry + upgrade engine, aimed at the operator who can read YAML but doesn't run a Kubernetes cluster.

## 5. Success metrics (12 months)

- ≥ 1000 GitHub stars (currently early-stage, public push 2026-04)
- ≥ 10 production deployments outside the maintainer's network
- Linux port: full infra + observability stack green on Ubuntu 24.04 LTS in CI
- ≥ 2 documented case studies (one SMB, one public body or NGO)
- Active contributor community: ≥ 5 non-maintainer commits/month sustained

## 6. Sustainability after the grant

The maintainer's consultancy provides paid setup + retainer support around the FOSS core. Free self-hosting stays unrestricted. Open-core temptation is explicitly rejected — paid tier is operational excellence (SLA, monitoring, hotfix priority), not feature flags. Post-grant the project survives on consultancy retainer revenue plus sustained NGI / TAČR follow-up grants tied to specific workstreams (e.g., EUDIW integrator certification).

## 7. License + governance

Apache 2.0. `MAINTAINERS.md` lists the maintainer; `CONTRIBUTING.md` defines PR review requirements (tests, lint, commit-message convention). Trademark (`nOS`, `This is AIT`) is held separately as defensive brand protection — kód zůstává freely forkable, brand respektuje upstream.

## 8. Asks beyond money

- Introductions to NGI alumni who have shipped similar deployment-automation projects
- Visibility on the NLnet showcase + NGI Forum (October)
- Optional: pairing with an EU-US partner for a follow-up NGI Sargasso application

---

**Two-page constraint:** this draft is ~3 pages — must trim to 2 before submission. Cut sections 4 (Comparable) and 8 (Asks) for the formal application; keep 1–3, 5–7. Total budget breakdown attached separately as `budget.xlsx`.
