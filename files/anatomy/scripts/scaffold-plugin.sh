#!/usr/bin/env bash
# =============================================================================
# scaffold-plugin.sh — bootstrap a new plugin under files/anatomy/plugins/
#
# Anatomy P0.5 (2026-05-04). Generates a starting plugin manifest +
# manifest fragment + README so Phase 1 multi-agent workers don't each
# invent their own shape (10+ workers producing slightly different
# manifests would blow up Phase 2 C2 manifest merge).
#
# Usage:
#   files/anatomy/scripts/scaffold-plugin.sh --name <slug> [options]
#
# Required:
#   --name <slug>          Plugin slug (lowercase, hyphen-separated).
#                          The plugin lands at files/anatomy/plugins/<slug>/.
#
# Options:
#   --shape <s>            service | composition | skill (default: service)
#   --sso <s>              oauth2 | forward_auth | none  (default: none)
#   --tier <n>             RBAC tier 1-4 when --sso != none (default: 3)
#   --role <name>          Tier-1 role this plugin requires (default: pazny.<slug>)
#   --feature-flag <name>  Ansible var gating activation (default: install_<slug>)
#   --target-stack <name>  infra | observability | iiab | devops | b2b | ...
#                          (used when shape=service for compose_extension; default: iiab)
#   --legal-basis <s>      consent | contract | legal_obligation | vital_interests |
#                          public_task | legitimate_interests (default: contract)
#   --help                 Show usage.
#
# Output (relative to repo root):
#   files/anatomy/plugins/<slug>/plugin.yml          — manifest skeleton
#   files/anatomy/plugins/<slug>/manifest.fragment.yml — Phase 2 C2 merge target
#   files/anatomy/plugins/<slug>/README.md           — placeholder docs
#
# IMPORTANT for parallel workers:
#   Workers MUST emit their state/manifest.yml entry as
#   plugins/<slug>/manifest.fragment.yml — never edit the shared
#   state/manifest.yml directly. Phase 2 C2 (operator-serial) merges
#   all fragments into the canonical manifest in one ordered commit.
#   See files/anatomy/docs/role-thinning-recipe.md §"Manifest fragment
#   pattern".
# =============================================================================

set -euo pipefail

SLUG=""
SHAPE="service"
SSO="none"
TIER="3"
ROLE=""
FEATURE_FLAG=""
TARGET_STACK="iiab"
LEGAL_BASIS="contract"

usage() {
	awk '/^#$/ {exit} /^#/ {sub(/^# ?/, ""); print}' "$0" | head -40
	exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--name)         SLUG="$2";          shift 2 ;;
		--shape)        SHAPE="$2";         shift 2 ;;
		--sso)          SSO="$2";           shift 2 ;;
		--tier)         TIER="$2";          shift 2 ;;
		--role)         ROLE="$2";          shift 2 ;;
		--feature-flag) FEATURE_FLAG="$2";  shift 2 ;;
		--target-stack) TARGET_STACK="$2";  shift 2 ;;
		--legal-basis)  LEGAL_BASIS="$2";   shift 2 ;;
		--help|-h)      usage 0 ;;
		*)              echo "Unknown flag: $1" >&2; usage 1 ;;
	esac
done

if [[ -z "$SLUG" ]]; then
	echo "ERROR: --name is required." >&2
	usage 1
fi

if [[ ! "$SLUG" =~ ^[a-z][a-z0-9-]{1,63}$ ]]; then
	echo "ERROR: --name must match ^[a-z][a-z0-9-]{1,63}$ (lowercase, hyphens, 2-64 chars)." >&2
	exit 1
fi

case "$SHAPE" in service|composition|skill) ;; *)
	echo "ERROR: --shape must be one of: service composition skill" >&2; exit 1
	;;
esac

case "$SSO" in oauth2|forward_auth|none) ;; *)
	echo "ERROR: --sso must be one of: oauth2 forward_auth none" >&2; exit 1
	;;
esac

case "$LEGAL_BASIS" in
	consent|contract|legal_obligation|vital_interests|public_task|legitimate_interests) ;;
	*) echo "ERROR: --legal-basis must be a GDPR Article 6 enum value (see plugin.schema.json)" >&2; exit 1 ;;
esac

# Resolve repo root (scripts/ -> anatomy/ -> files/ -> repo)
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
TARGET_DIR="$REPO_ROOT/files/anatomy/plugins/$SLUG"

if [[ -e "$TARGET_DIR" ]]; then
	echo "ERROR: $TARGET_DIR already exists. Refuse to overwrite." >&2
	exit 1
fi

# Defaults derived from --name. Strip ``-base`` suffix when present
# (most service plugins follow the ``<svc>-base`` convention; the
# corresponding role / feature flag uses the bare ``<svc>``).
SLUG_BARE="${SLUG%-base}"
# Convert hyphens to underscores for Ansible var conventions.
SLUG_UNDERSCORE="${SLUG_BARE//-/_}"
[[ -z "$ROLE" ]] && ROLE="pazny.${SLUG_UNDERSCORE}"
[[ -z "$FEATURE_FLAG" ]] && FEATURE_FLAG="install_${SLUG_UNDERSCORE}"

mkdir -p "$TARGET_DIR"

# -- plugin.yml ---------------------------------------------------------------
cat > "$TARGET_DIR/plugin.yml" <<MANIFEST
---
# =============================================================================
# ${SLUG} — plugin manifest (scaffolded by scaffold-plugin.sh on $(date +%Y-%m-%d))
#
# TODO: replace this header with a real description of what this plugin
# does + its position in the bones-and-wings doctrine.
# =============================================================================

name: ${SLUG}
version: 0.1.0
description: |
  TODO: 1-3 sentences describing the wiring this plugin owns.
upstream: https://example.invalid/TODO
license: TODO

type:
  - ${SHAPE}

requires:
  role: ${ROLE}
  feature_flag: ${FEATURE_FLAG}
  variables: []
MANIFEST

if [[ "$SHAPE" == "service" ]]; then
	cat >> "$TARGET_DIR/plugin.yml" <<EXTENSION

compose_extension:
  template: ${SLUG}.compose.yml.j2
  target_stack: ${TARGET_STACK}
  target_service: ${SLUG_UNDERSCORE}     # MUST match role's compose service name

lifecycle:
  pre_compose:
    - render_compose_extension: compose_extension
  # post_compose: []   # add wait_health / api_calls if needed
  # post_blank:   []   # add cleanup actions if needed
EXTENSION
fi

if [[ "$SHAPE" == "composition" ]]; then
	cat >> "$TARGET_DIR/plugin.yml" <<COMP

# Composition plugin: cross-wires two existing service plugins. Declare
# the upstream plugin dependencies via requires.plugin so the loader's
# DAG resolver runs them first.
#   requires:
#     plugin:
#       - <upstream-1>
#       - <upstream-2>

provisioning:
  config:
    template: provisioning/wiring.yml.j2
    target: "{{ stacks_dir }}/<stack>/<service>/wiring.yml"

lifecycle:
  pre_compose:
    - render: provisioning.config
COMP
fi

if [[ "$SHAPE" == "skill" ]]; then
	cat >> "$TARGET_DIR/plugin.yml" <<SKILL

# Skill plugin: registers a Pulse scheduled-job. Loader's plugin
# registration phase populates pulse_jobs from this block.
scheduled-job:
  id: ${SLUG_UNDERSCORE}_default
  command: ./skills/run-${SLUG%-base}.sh
  schedule: "0 3 * * 0"     # TODO: pick the right cron
  jitter_min: 5
  max_runtime_s: 1800
  max_concurrent: 1

skill:
  entrypoint: skills/run-${SLUG%-base}.sh
SKILL
fi

if [[ "$SSO" == "oauth2" ]]; then
	cat >> "$TARGET_DIR/plugin.yml" <<AUTHOAUTH

authentik:
  client_id: "{{ ${SLUG_UNDERSCORE}_oidc_client_id | default('${SLUG_UNDERSCORE}') }}"
  client_secret: "{{ global_password_prefix }}_pw_oidc_${SLUG_UNDERSCORE}"
  slug: ${SLUG%-base}
  tier: ${TIER}
  provider_type: oauth2
  scopes: [openid, email, profile]
  redirect_uris:
    - "https://${SLUG%-base}.{{ tenant_domain | default('dev.local') }}/auth/oidc/callback"
  launch_url: "https://${SLUG%-base}.{{ tenant_domain | default('dev.local') }}"
AUTHOAUTH
elif [[ "$SSO" == "forward_auth" ]]; then
	cat >> "$TARGET_DIR/plugin.yml" <<AUTHPROXY

authentik:
  client_id: "${SLUG_UNDERSCORE}-fwdauth"
  client_secret: "{{ global_password_prefix }}_pw_oidc_${SLUG_UNDERSCORE}"
  slug: ${SLUG%-base}
  tier: ${TIER}
  provider_type: forward_auth
  launch_url: "https://${SLUG%-base}.{{ tenant_domain | default('dev.local') }}"
AUTHPROXY
fi

cat >> "$TARGET_DIR/plugin.yml" <<GDPR

gdpr:
  data_categories:
    - TODO_data_category
  data_subjects:
    - TODO_data_subject       # operators | end_users | automated_systems
  legal_basis: ${LEGAL_BASIS}
  retention_days: 365         # -1 = indefinite (active accounts)
  processors:
    - ${SLUG%-base}
  eu_residency: true

# ui-extension:
#   hub_card:
#     title: "TODO"
#     icon: TODO
#     url: "https://${SLUG%-base}.{{ tenant_domain | default('dev.local') }}"
#     tier: ${TIER}
GDPR

# -- manifest.fragment.yml ----------------------------------------------------
# This is the entry that gets merged into state/manifest.yml in Phase 2 C2.
# Workers NEVER edit state/manifest.yml directly — operator merges fragments.
cat > "$TARGET_DIR/manifest.fragment.yml" <<FRAGMENT
# state/manifest.yml fragment — operator merges in Phase 2 C2.
# Workers NEVER edit state/manifest.yml directly. See
# files/anatomy/docs/role-thinning-recipe.md "Manifest fragment pattern".
- id: ${SLUG%-base}
  tier: ${TIER}
  feature_flag: ${FEATURE_FLAG}
  domain_var: ${SLUG_UNDERSCORE}_domain   # rename if role uses different var
  port_var: ${SLUG_UNDERSCORE}_port       # rename if role uses different var
FRAGMENT

# -- README.md ----------------------------------------------------------------
TODAY="$(date +%Y-%m-%d)"
EXTRA_FILE_LINE=""
if [[ "$SHAPE" == "service" ]]; then
	EXTRA_FILE_LINE="└── ${SLUG}.compose.yml.j2     # compose-extension Jinja (TODO: create)"
fi

# Use a quoted heredoc so $-substitution is disabled, then substitute
# placeholders with sed at the end (avoids backtick + brace escape pain).
cat > "$TARGET_DIR/README.md" <<'README'
# __SLUG__

> **Status:** scaffolded __TODAY__, not yet validated. Replace this
> banner once the plugin is live in a blank-green run.

TODO: 1-2 paragraph summary of what this plugin does + its position
in the bones-and-wings doctrine.

## What lives here

```
files/anatomy/plugins/__SLUG__/
├── plugin.yml                  # manifest
├── manifest.fragment.yml       # Phase 2 C2 merge target
├── README.md                   # this file
__EXTRA_FILE_LINE__
```

TODO: describe templates / provisioning artifacts you add.

## Required operator vars

TODO: enumerate every `{{ var }}` referenced in templates here so the
operator can confirm `default.config.yml` covers them.

## GDPR

| Field | Value |
|---|---|
| Data categories | TODO |
| Data subjects | TODO |
| Legal basis | __LEGAL_BASIS__ |
| Retention | 365 days (TODO: confirm) |
| Processors | __SLUG_BARE__ |
| EU residency | true (TODO: confirm) |
README

# Substitute placeholders. Using | as sed delimiter to avoid clash with
# template content. ANY user-supplied input here is from CLI args
# already validated against tight regex — no shell-injection surface.
sed -i.bak \
	-e "s|__SLUG__|${SLUG}|g" \
	-e "s|__SLUG_BARE__|${SLUG_BARE}|g" \
	-e "s|__TODAY__|${TODAY}|g" \
	-e "s|__LEGAL_BASIS__|${LEGAL_BASIS}|g" \
	-e "s|__EXTRA_FILE_LINE__|${EXTRA_FILE_LINE}|g" \
	"$TARGET_DIR/README.md"
rm -f "$TARGET_DIR/README.md.bak"
# Strip the EXTRA_FILE_LINE placeholder line if it was empty (composition/skill).
if [[ -z "$EXTRA_FILE_LINE" ]]; then
	# Remove blank lines left from the empty substitution.
	sed -i.bak '/^[[:space:]]*$/N;/^[[:space:]]*\n[[:space:]]*```$/D' "$TARGET_DIR/README.md" 2>/dev/null || true
	rm -f "$TARGET_DIR/README.md.bak"
fi

echo "Scaffolded plugin at $TARGET_DIR"
echo
echo "Next steps:"
echo "  1. Edit plugin.yml — replace TODOs (description, license, variables, gdpr.data_categories)"
echo "  2. Add templates/provisioning artifacts (compose extension, blueprint snippets, etc.)"
echo "  3. Validate: python3 -c \"from module_utils import load_plugins; ...\" or run tests/anatomy"
echo "  4. Add operator vars to default.config.yml if any are missing"
echo "  5. Commit; do NOT edit state/manifest.yml directly — your manifest.fragment.yml is merged in Phase 2 C2"
