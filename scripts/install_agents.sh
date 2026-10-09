#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
[[ $AGENTS_ROOT =~ ^/[A-Za-z0-9_./-]+$ && $AGENTS_ROOT != / ]] || fail 'Invalid AGENTS_ROOT.'
[[ -s $NVM_ROOT/nvm.sh ]] || fail 'Shared Node is missing: select module 9 (or 3) before module 8.'
export NVM_DIR=$NVM_ROOT
set +u
source "$NVM_ROOT/nvm.sh"
nvm use default
node_bin=$(dirname -- "$(nvm which default)")
set -u
mkdir -p "$AGENTS_ROOT"
# Root installs the programs; no user authentication is copied or preconfigured.
npm install --global --prefix "$AGENTS_ROOT" "@openai/codex@$CODEX_VERSION"
npm install --global --ignore-scripts --prefix "$AGENTS_ROOT" "$PI_PACKAGE@$PI_VERSION"
chown -R root:root "$AGENTS_ROOT"; chmod -R a+rX,go-w "$AGENTS_ROOT"
for tool in codex pi; do
  target=/usr/local/bin/$tool
  if [[ -e $target || -L $target ]]; then
    [[ -f $target ]] && grep -q '^# Managed by gpu-deploy' "$target" || fail "Existing unmanaged command: $target"
  fi
  cat >"$target" <<WRAPPER
#!/usr/bin/env bash
# Managed by gpu-deploy: shared executable, private state for current Unix user.
set -euo pipefail
agent_user_home=\$(getent passwd "\$(id -u)" | cut -d: -f6)
[[ -n \$agent_user_home && -d \$agent_user_home ]] || { echo 'No account home directory' >&2; exit 1; }
export PATH="$node_bin:\$PATH"
export NODE_USE_ENV_PROXY="\${NODE_USE_ENV_PROXY:-1}"
WRAPPER
  if [[ $tool == codex ]]; then
    cat >>"$target" <<'WRAPPER'
export CODEX_HOME="$agent_user_home/.codex"
mkdir -p -m 700 "$CODEX_HOME"
WRAPPER
  else
    cat >>"$target" <<'WRAPPER'
export PI_CODING_AGENT_DIR="$agent_user_home/.pi/agent"
export PI_CODING_AGENT_SESSION_DIR="$PI_CODING_AGENT_DIR/sessions"
mkdir -p -m 700 "$agent_user_home/.pi" "$PI_CODING_AGENT_DIR" "$PI_CODING_AGENT_SESSION_DIR"
WRAPPER
  fi
  printf 'exec "%s/bin/%s" "$@"\n' "$AGENTS_ROOT" "$tool" >>"$target"
  chmod 755 "$target"
done
for u in $USERS; do
  id "$u" &>/dev/null || continue
  agent_home=$(getent passwd "$u" | cut -d: -f6); group=$(id -gn "$u")
  for state_dir in "$agent_home/.codex" "$agent_home/.pi" "$agent_home/.pi/agent"; do
    [[ ! -L $state_dir ]] || fail "Refusing to make a linked config directory private: $state_dir"
    install -d -m 700 -o "$u" -g "$group" "$state_dir"
  done
done
printf 'Shared Codex/pi installed. Each user logs in separately under their own Unix account.\n'
