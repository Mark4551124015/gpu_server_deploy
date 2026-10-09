#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root; require_platform
[[ $DRIVER_BRANCH =~ ^[0-9]+$ ]] || fail 'DRIVER_BRANCH must be numeric.'
export DEBIAN_FRONTEND=noninteractive
packages=("nvidia-driver-$DRIVER_BRANCH-server" "nvidia-utils-$DRIVER_BRANCH-server"
          "nvidia-fabricmanager-$DRIVER_BRANCH" "libnvidia-nscq-$DRIVER_BRANCH")
for package in "${packages[@]}"; do
  candidate=$(apt-cache policy "$package" | awk '/Candidate:/ {print $2}')
  [[ -n $candidate && $candidate != '(none)' ]] || fail "No APT candidate for $package; check source or DRIVER_BRANCH."
done
apt-get install -y "linux-headers-$(uname -r)" "${packages[@]}"
systemctl enable nvidia-fabricmanager
# Starting against a previously loaded driver can fail until the next reboot.
printf 'Driver packages installed. Reboot manually, then verify nvidia-smi and Fabric Manager.\n'
