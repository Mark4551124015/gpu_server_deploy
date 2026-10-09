#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
DIR=${1:-${SSH_KEYS_DIR:-}}
[[ -d $DIR ]] || fail 'Usage: bash scripts/import_ssh_keys.sh PUBLIC_KEYS_DIR [USER ...]'
shift || true
targets=("$@")
if ((${#targets[@]} == 0)); then read -r -a targets <<< "$USERS"; fi
# Validate all requested files before changing any account.
for u in "${targets[@]}"; do
  [[ $u =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "Invalid username: $u"
  id "$u" &>/dev/null || fail "No user: $u; select module 1 first."
  [[ -s $DIR/$u.pub ]] || fail "Missing: $DIR/$u.pub"
  key_count=0
  while IFS= read -r line || [[ -n $line ]]; do
    [[ -z $line || $line == \#* ]] && continue
    [[ $line == ssh-* || $line == ecdsa-* || $line == sk-* ]] || fail "Expected a public key in $u.pub"
    ssh-keygen -lf /dev/stdin <<< "$line" >/dev/null || fail "Invalid key in $u.pub"
    key_count=$((key_count + 1))
  done < "$DIR/$u.pub"
  ((key_count > 0)) || fail "No public keys in $u.pub"
done
for u in "${targets[@]}"; do
  user_home=$(getent passwd "$u" | cut -d: -f6); group=$(id -gn "$u")
  install -d -m 700 -o "$u" -g "$group" "$user_home/.ssh"
  target=$user_home/.ssh/authorized_keys
  [[ ! -f $target || -f $target.before-gpu-import ]] || cp -a "$target" "$target.before-gpu-import"
  touch "$target"
  while IFS= read -r line || [[ -n $line ]]; do
    [[ -z $line || $line == \#* ]] && continue
    grep -Fxq -- "$line" "$target" || printf '\n%s\n' "$line" >> "$target"
  done < "$DIR/$u.pub"
  chown "$u:$group" "$target"; chmod 600 "$target"
  printf 'Imported: %s\n' "$u"
done
