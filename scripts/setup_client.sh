#!/usr/bin/env bash
# DevFlow client onboarding (Option A — dedicated cloud root).
#
# Idempotent: first run clones viniciuscffreitas/devflow into
# $DEVFLOW_CLOUD_ROOT (default ~/.claude/devflow-cloud); subsequent runs
# fetch + reset --hard origin/main inside that path. Destructive scope is
# confined to the dedicated install root — never touches dotfiles or any
# other repo.
#
# Usage:
#   scripts/setup_client.sh [--endpoint URL] [--cloud-root PATH]
#                           [--repo URL] [--no-hooks] [--skip-healthz]
set -euo pipefail

ENDPOINT="${DEVFLOW_CLOUD_ENDPOINT:-https://cloud.vinicius.xyz/v1/evaluate}"
CRED_FILE="${HOME}/.devflow/cloud-credentials.json"
CLOUD_ROOT="${DEVFLOW_CLOUD_ROOT:-${HOME}/.claude/devflow-cloud}"
REPO_URL="${DEVFLOW_SETUP_REPO:-https://github.com/viniciuscffreitas/devflow.git}"
INSTALL_HOOKS=1
SKIP_HEALTHZ=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --endpoint)     ENDPOINT="$2"; shift 2 ;;
        --cloud-root)   CLOUD_ROOT="$2"; shift 2 ;;
        --repo)         REPO_URL="$2"; shift 2 ;;
        --no-hooks)     INSTALL_HOOKS=0; shift ;;
        --skip-healthz) SKIP_HEALTHZ=1; shift ;;
        *) echo "Unknown flag: $1" >&2; exit 2 ;;
    esac
done

HEALTHZ_URL="${ENDPOINT%/v1/evaluate}/v1/healthz"

step() { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
fail() { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; exit 1; }

# 1. Credentials
step "Verifying credentials at ${CRED_FILE}"
if [[ ! -f "$CRED_FILE" ]]; then
    fail "missing credentials file at ${CRED_FILE} — create it with {\"endpoint\":\"...\",\"api_key\":\"...\",\"client_id\":\"...\"}"
fi
CRED_FILE="$CRED_FILE" python3 -c "
import json, os, sys
with open(os.environ['CRED_FILE']) as f:
    d = json.load(f)
required = ('endpoint', 'api_key', 'client_id')
missing = [k for k in required if k not in d]
if missing:
    sys.exit(f'incomplete credentials — missing keys: {missing}')
" || fail "credentials malformed (missing endpoint/api_key/client_id)"
ok "credentials present"

# 2. Healthz
if [[ "$SKIP_HEALTHZ" == "0" ]]; then
    step "Pinging ${HEALTHZ_URL}"
    if curl -fsS --max-time 5 "$HEALTHZ_URL" >/dev/null; then
        ok "endpoint reachable"
    else
        fail "endpoint unreachable — check VPN / firewall / endpoint URL"
    fi
fi

# 3. Install or repair the cloud root
step "Resolving cloud root at ${CLOUD_ROOT}"
if [[ -d "${CLOUD_ROOT}/.git" ]]; then
    EXISTING_ORIGIN="$(git -C "$CLOUD_ROOT" remote get-url origin 2>/dev/null || true)"
    if [[ -z "$EXISTING_ORIGIN" ]]; then
        fail "${CLOUD_ROOT} is a git repo without origin — refusing to repair (foreign state)"
    fi
    norm() { echo "$1" | sed -E 's#(.+/|.+:)([^/:]+/[^/]+?)(\.git)?$#\2#'; }
    if [[ "$(norm "$EXISTING_ORIGIN")" != "$(norm "$REPO_URL")" ]]; then
        fail "foreign origin at ${CLOUD_ROOT} (${EXISTING_ORIGIN}) — refusing to overwrite. Move it aside or pass --cloud-root to a different path."
    fi
    step "Repairing existing clone (fetch + reset --hard origin/main)"
    git -C "$CLOUD_ROOT" fetch -q origin main
    git -C "$CLOUD_ROOT" reset -q --hard origin/main
    git -C "$CLOUD_ROOT" clean -qfd
    ok "repaired to origin/main at $(git -C "$CLOUD_ROOT" rev-parse --short HEAD)"
elif [[ -e "$CLOUD_ROOT" ]]; then
    fail "${CLOUD_ROOT} exists but is not a git repo — refusing to overwrite"
else
    step "Cloning ${REPO_URL} into ${CLOUD_ROOT}"
    mkdir -p "$(dirname "$CLOUD_ROOT")"
    git clone -q --branch main "$REPO_URL" "$CLOUD_ROOT"
    ok "cloned to $(git -C "$CLOUD_ROOT" rev-parse --short HEAD)"
fi

# 4. Optional hook re-registration
if [[ "$INSTALL_HOOKS" == "1" ]]; then
    if [[ -x "${CLOUD_ROOT}/install.sh" ]]; then
        step "Installing devflow hooks via ${CLOUD_ROOT}/install.sh"
        bash "${CLOUD_ROOT}/install.sh"
        ok "hooks installed"
    else
        ok "install.sh not present — skipping hook registration"
    fi
fi

printf "\n\033[1;32mSetup complete.\033[0m\n"
printf "Add this to your shell rc to make the dedicated root the source of truth:\n"
printf "  export DEVFLOW_ROOT=%s\n" "$CLOUD_ROOT"
printf "Then run a project with \`devflow --cloud --heal\` to verify.\n"
