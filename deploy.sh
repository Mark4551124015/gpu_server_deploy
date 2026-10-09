#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/scripts/common.sh"
usage() {
  cat <<'HELP'
Usage: bash deploy.sh [auto|DIGITS] [--dry-run] [--keys-dir DIR]
                      [--proxy-url URL | --proxy-server HOST --proxy-client-ip IP]
Without arguments, show the menu. Every module can be selected separately.
  1  Users and sudo membership
  2  NVIDIA driver and Fabric Manager
  3  Shared Miniconda / NVM / Node.js / npm
  4  Shared CUDA PyTorch environment
  5  Import user SSH public keys (optional, requires --keys-dir or config.env)
  6  Install Node 1 proxy + local tunnel, or use an existing HTTP proxy (optional)
  7  Prepare Clash source code (optional; does not install/start Clash)
  8  Shared Codex + pi; private config, login and sessions per Unix user
  9  Only NVM + Node.js LTS + bundled npm (without Miniconda)
auto = 1234; 13 = only users and shared tools; 12345 = core + public keys.
On Node 2: deploy.sh 6 --proxy-server NODE1_IP --proxy-client-ip NODE2_IP
From admin computer: python3 scripts/node_proxy.py bootstrap --help
HELP
}
selection= dry_run=0
while (($#)); do
  case $1 in
    --help|-h) usage; exit 0 ;;
    --dry-run) dry_run=1; shift ;;
    --keys-dir) [[ $# -ge 2 ]] || fail 'Missing --keys-dir value'; SSH_KEYS_DIR=$2; shift 2 ;;
    --proxy-url) [[ $# -ge 2 ]] || fail 'Missing --proxy-url value'; PROXY_URL=$2; shift 2 ;;
    --proxy-server) [[ $# -ge 2 ]] || fail 'Missing --proxy-server value'; PROXY_SERVER=$2; shift 2 ;;
    --proxy-client-ip) [[ $# -ge 2 ]] || fail 'Missing --proxy-client-ip value'; PROXY_CLIENT_IP=$2; shift 2 ;;
    auto|[1-9]*) [[ -z $selection ]] || fail 'Specify one selection'; selection=$1; shift ;;
    *) fail "Unknown argument: $1" ;;
  esac
done
if [[ -z $selection ]]; then
  usage
  [[ -t 0 ]] || fail 'Specify auto or a digit selection in non-interactive mode.'
  read -r -p 'Select modules (auto / 12345 / 6 / ...), or q to quit: ' selection
  [[ $selection != q ]] || exit 0
fi
[[ $selection != auto ]] || selection=1234
[[ $selection =~ ^[1-9]+$ ]] || fail 'Selection must contain only digits 1 through 9.'
has() { [[ $selection == *"$1"* ]]; }
if has 5; then
  if [[ -z ${SSH_KEYS_DIR:-} && -t 0 ]]; then read -r -p 'Public-key directory: ' SSH_KEYS_DIR; fi
  [[ -n ${SSH_KEYS_DIR:-} ]] || fail 'Module 5 needs --keys-dir DIR or SSH_KEYS_DIR in config.env.'
  [[ -d $SSH_KEYS_DIR ]] || fail "Missing public-key directory: $SSH_KEYS_DIR"
fi
if has 6; then
  if [[ -z ${PROXY_SERVER:-} && -z ${PROXY_URL:-} && -t 0 ]]; then
    read -r -p 'Proxy mode: 1 = install Node 1 proxy and local tunnel; 2 = existing URL: ' proxy_mode
    case $proxy_mode in
      1) read -r -p 'Node 1 IP or SSH host: ' PROXY_SERVER ;;
      2) read -r -p 'HTTP proxy URL: ' PROXY_URL ;;
      *) fail 'Choose proxy mode 1 or 2.' ;;
    esac
  fi
  if [[ -n ${PROXY_SERVER:-} ]]; then
    [[ $PROXY_SERVER =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail 'Invalid --proxy-server host.'
    [[ -n ${PROXY_CLIENT_IP:-} ]] || fail 'Set --proxy-client-ip IP or PROXY_CLIENT_IP in config.env.'
  else
    [[ ${PROXY_URL:-} =~ ^http://[^[:space:]]+$ ]] || fail 'Module 6 needs --proxy-url URL or --proxy-server HOST.'
  fi
fi
run() {
  printf 'RUN'; printf ' %q' "$@"; printf '\n'
  ((dry_run)) || "$@"
}
printf 'Selected modules: %s (execution follows dependency order)\n' "$selection"
if (( ! dry_run )); then
  require_root; require_platform
  mkdir -p /var/log/gpu-deploy
  exec > >(tee -a "/var/log/gpu-deploy/deploy-$(date +%Y%m%d-%H%M%S).log") 2>&1
fi
# Proxy is a pre-install option; it never implies user-key import.
if has 6; then
  if [[ -n ${PROXY_SERVER:-} ]]; then
    run python3 "$ROOT_DIR/scripts/node_proxy.py" setup --server "$PROXY_SERVER" \
      --server-address "${PROXY_SERVER_ADDRESS:-$PROXY_SERVER}" --client-ip "$PROXY_CLIENT_IP" \
      --port "${PROXY_PORT:-18888}" --local-port "${PROXY_LOCAL_PORT:-18888}"
  else
    run python3 "$ROOT_DIR/scripts/node_proxy.py" configure --url "$PROXY_URL"
  fi
  if (( ! dry_run )); then source /etc/profile.d/gpu-node-proxy.sh; fi
fi
needs_network=0
for item in 2 3 4 7 8 9; do if has "$item"; then needs_network=1; fi; done
if ((needs_network)); then
  [[ $APT_SOURCE == ustc || $APT_SOURCE == keep ]] || fail 'APT_SOURCE must be ustc or keep.'
  if [[ $APT_SOURCE == ustc ]]; then run bash "$ROOT_DIR/scripts/switch_apt_source.sh" ustc
  else run apt-get update; fi
fi
has 1 && run bash "$ROOT_DIR/scripts/setup_users.sh"
has 2 && run bash "$ROOT_DIR/scripts/install_driver.sh"
has 3 && run bash "$ROOT_DIR/scripts/install_tools.sh"
if has 9 && ! has 3; then run bash "$ROOT_DIR/scripts/install_node.sh"; fi
has 4 && run bash "$ROOT_DIR/scripts/install_pytorch.sh"
has 8 && run bash "$ROOT_DIR/scripts/install_agents.sh"
has 5 && run bash "$ROOT_DIR/scripts/import_ssh_keys.sh" "$SSH_KEYS_DIR"
has 7 && run bash "$ROOT_DIR/scripts/prepare_clash.sh"
if ((needs_network)) && [[ $APT_SOURCE == ustc && $RESTORE_APT_SOURCE == 1 ]]; then
  run bash "$ROOT_DIR/scripts/switch_apt_source.sh" restore
fi
printf 'Finished. No automatic reboot. Driver changes may require a maintenance reboot.\n'
