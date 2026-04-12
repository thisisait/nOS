#!/usr/bin/env bash
# ansible-bridge.sh — Safe Ansible execution wrapper for OpenClaw
# Usage:
#   ansible-bridge.sh run-tag <tag>     — Run playbook with specific tag
#   ansible-bridge.sh status            — Show service status
#   ansible-bridge.sh verify            — Run stack verification
#   ansible-bridge.sh syntax-check      — Validate playbook syntax
#   ansible-bridge.sh list-tags         — List available tags
set -euo pipefail

PLAYBOOK_DIR="${PLAYBOOK_DIR:-$HOME/projects/mac-dev-playbook}"
PLAYBOOK="$PLAYBOOK_DIR/main.yml"
LOG_DIR="$HOME/agents/log"
mkdir -p "$LOG_DIR"

# Allowed tags (whitelist — prevent destructive operations)
ALLOWED_TAGS="nginx,stacks,verify,observability,iiab,service-registry,backup,export"
# Blocked tags (never allow)
BLOCKED_TAGS="blank"

log() {
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $*" | tee -a "$LOG_DIR/ansible-bridge.log"
}

case "${1:-help}" in
    run-tag)
        TAG="${2:?Usage: ansible-bridge.sh run-tag <tag>}"
        # Check blocked list
        if echo "$BLOCKED_TAGS" | tr ',' '\n' | grep -qx "$TAG"; then
            log "BLOCKED: Tag '$TAG' is not allowed via bridge"
            exit 1
        fi
        # Check whitelist
        if ! echo "$ALLOWED_TAGS" | tr ',' '\n' | grep -qx "$TAG"; then
            log "BLOCKED: Tag '$TAG' is not in allowed list"
            exit 1
        fi
        log "Running playbook with tag: $TAG"
        cd "$PLAYBOOK_DIR"
        ansible-playbook "$PLAYBOOK" --tags "$TAG" -e "blank=false" 2>&1 | tee -a "$LOG_DIR/ansible-bridge.log"
        ;;
    status)
        # Show running Docker containers across all stacks
        for stack in infra observability iiab devops b2b voip engineering data; do
            COMPOSE="$HOME/stacks/$stack/docker-compose.yml"
            if [ -f "$COMPOSE" ]; then
                echo "=== $stack ==="
                docker compose -f "$COMPOSE" -p "$stack" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || true
            fi
        done
        ;;
    verify)
        cd "$PLAYBOOK_DIR"
        ansible-playbook "$PLAYBOOK" --tags verify -e "blank=false" 2>&1
        ;;
    syntax-check)
        cd "$PLAYBOOK_DIR"
        ansible-playbook "$PLAYBOOK" --syntax-check
        ;;
    list-tags)
        cd "$PLAYBOOK_DIR"
        ansible-playbook "$PLAYBOOK" --list-tags 2>&1 | grep "TASK TAGS"
        ;;
    help|*)
        echo "Usage: ansible-bridge.sh <command>"
        echo "Commands:"
        echo "  run-tag <tag>   Run playbook with specific tag"
        echo "  status          Show Docker service status"
        echo "  verify          Run stack verification"
        echo "  syntax-check    Validate playbook syntax"
        echo "  list-tags       List available playbook tags"
        ;;
esac
