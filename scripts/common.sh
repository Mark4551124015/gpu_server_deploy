#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -f ${GPU_CONFIG:-$ROOT_DIR/config.env} ]]; then
  # A config file is trusted shell code, maintained by the administrator.
  source "${GPU_CONFIG:-$ROOT_DIR/config.env}"
fi
: "${USERS:=admin user1 user2 user3 user4}" "${ADMIN_USER:=admin}" "${SET_PASSWORDS:=0}"
: "${DRIVER_BRANCH:=580}" "${CONDA_ROOT:=/opt/conda}" "${NVM_ROOT:=/opt/nvm}"
: "${NVM_VERSION:=v0.40.3}" "${NODE_VERSION:=--lts}" "${PYTHON_VERSION:=3.11}"
: "${AGENTS_ROOT:=/opt/gpu-agents}" "${CODEX_VERSION:=latest}"
: "${PI_PACKAGE:=@earendil-works/pi-coding-agent}" "${PI_VERSION:=latest}"
: "${TORCH_VERSION:=2.10.0}" "${TORCH_INDEX_URL:=https://download.pytorch.org/whl/cu128}"
: "${APT_SOURCE:=keep}" "${RESTORE_APT_SOURCE:=1}"
: "${APT_DIRECT_HOSTS:=}" "${NO_PROXY_EXTRA:=}"
# Some cloud images ship Python linked to a custom OpenSSL with no CA file.
if [[ -z ${SSL_CERT_FILE:-} && -s /etc/ssl/certs/ca-certificates.crt ]]; then
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
fi
export USERS ADMIN_USER SET_PASSWORDS DRIVER_BRANCH CONDA_ROOT NVM_ROOT NVM_VERSION NODE_VERSION
export PYTHON_VERSION TORCH_VERSION TORCH_INDEX_URL APT_SOURCE RESTORE_APT_SOURCE
export AGENTS_ROOT CODEX_VERSION PI_PACKAGE PI_VERSION
export APT_DIRECT_HOSTS NO_PROXY_EXTRA
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
require_root() { [[ $EUID -eq 0 ]] || fail 'Run this command with sudo or as root.'; }
require_platform() {
  [[ -f /etc/os-release ]] || fail 'Ubuntu 22.04 is required.'
  source /etc/os-release
  [[ $ID == ubuntu && $VERSION_ID == 22.04 && $(uname -m) == x86_64 ]] || fail 'Expected Ubuntu 22.04 x86_64.'
}
