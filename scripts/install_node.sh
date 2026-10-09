#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
[[ $NVM_ROOT =~ ^/[A-Za-z0-9_./-]+$ && $NVM_ROOT != / ]] || fail 'Invalid NVM_ROOT.'
[[ $NVM_VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'Expected a versioned NVM release tag.'
export DEBIAN_FRONTEND=noninteractive
apt-get install -y curl ca-certificates xz-utils
if [[ ! -f $NVM_ROOT/nvm.sh ]]; then
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  # Official release archive avoids github.com Git CONNECT failures.
  curl --connect-timeout 15 --max-time 180 --retry 3 -fL \
    "https://codeload.github.com/nvm-sh/nvm/tar.gz/refs/tags/$NVM_VERSION" -o "$t/nvm.tar.gz"
  mkdir "$t/nvm"
  tar -xzf "$t/nvm.tar.gz" --strip-components=1 -C "$t/nvm"
  [[ -f $t/nvm/nvm.sh ]] || fail 'NVM archive is incomplete.'
  mkdir -p "$NVM_ROOT"
  cp -a "$t/nvm/." "$NVM_ROOT/"
fi
export NVM_DIR=$NVM_ROOT
set +u
source "$NVM_ROOT/nvm.sh"
nvm install "$NODE_VERSION"
if [[ $NODE_VERSION == --lts ]]; then nvm alias default 'lts/*'
else nvm alias default "$NODE_VERSION"; fi
node_bin=$(dirname -- "$(nvm which default)")
set -u
chown -R root:root "$NVM_ROOT"; chmod -R a+rX,go-w "$NVM_ROOT"
mkdir -p /usr/local/bin
for command in node npm npx; do
  target=/usr/local/bin/$command
  if [[ -e $target || -L $target ]]; then
    [[ -L $target && $(readlink "$target") == "$NVM_ROOT"/* ]] || fail "Existing unmanaged command: $target"
  fi
  ln -sfn "$node_bin/$command" "$target"
done
cat >/etc/profile.d/gpu-nvm.sh <<PROFILE
export NVM_DIR="$NVM_ROOT"
[ ! -s "\$NVM_DIR/nvm.sh" ] || . "\$NVM_DIR/nvm.sh"
PROFILE
node --version; npm --version
printf 'Shared Node LTS/npm installed. NVM versions are maintained by root.\n'
