#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
for u in $USERS; do
  [[ $u =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "Invalid username: $u"
done
[[ " $USERS " == *" $ADMIN_USER "* ]] || fail 'ADMIN_USER must be included in USERS.'
command -v sudo >/dev/null || apt-get install -y sudo
for u in $USERS; do
  id "$u" &>/dev/null || useradd -m -s /bin/bash "$u"
  if [[ $u == "$ADMIN_USER" ]]; then usermod -aG sudo "$u"
  else gpasswd -d "$u" sudo >/dev/null 2>&1 || true; fi
  if [[ $SET_PASSWORDS == 1 ]]; then passwd "$u"; chage -d 0 "$u"; fi
done
printf 'Users configured; existing SSH keys/password login are preserved.\n'
printf 'Review other admin grants: /etc/sudoers.d, sudo -l -U USER, adm group.\n'
