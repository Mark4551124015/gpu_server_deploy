#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
[[ $CONDA_ROOT =~ ^/[A-Za-z0-9_./-]+$ && $CONDA_ROOT != / ]] || fail 'Invalid CONDA_ROOT.'
[[ $NVM_ROOT =~ ^/[A-Za-z0-9_./-]+$ && $NVM_ROOT != / ]] || fail 'Invalid NVM_ROOT.'
export DEBIAN_FRONTEND=noninteractive
apt-get install -y curl wget git ca-certificates bzip2 xz-utils
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
if [[ ! -x $CONDA_ROOT/bin/conda ]]; then
  curl --retry 3 -fL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o "$t/miniconda.sh"
  bash "$t/miniconda.sh" -b -p "$CONDA_ROOT"
fi
chown -R root:root "$CONDA_ROOT"; chmod -R a+rX,go-w "$CONDA_ROOT"
cat >/etc/profile.d/gpu-conda.sh <<PROFILE
export PATH="$CONDA_ROOT/condabin:\$PATH"
export CONDA_ENVS_PATH="\$HOME/.conda/envs"
PROFILE
bash "$ROOT_DIR/scripts/install_node.sh"
printf 'Shared tools installed. Login again; run source %s/etc/profile.d/conda.sh to activate Conda.\n' "$CONDA_ROOT"
