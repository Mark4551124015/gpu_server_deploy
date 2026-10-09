#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root'; exit 1; }
apt-get install -y git curl ca-certificates
install -d -m 700 /opt/gpu-admin
if [[ ! -d /opt/gpu-admin/clash-for-linux/.git ]]; then
 git clone --depth 1 https://github.com/wnlen/clash-for-linux.git /opt/gpu-admin/clash-for-linux
fi
echo 'Review the project code and .env before installing:'
echo 'cd /opt/gpu-admin/clash-for-linux && bash install.sh system'
echo 'Do not expose controller port 9090 or enable global TUN/iptables on the GPU interconnect.'
