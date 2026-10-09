#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root'; exit 1; }
BACKUP=/etc/apt/gpu-source-backup
LIST=/etc/apt/sources.list
case "${1:-}" in
 ustc)
  if [[ ! -e $BACKUP/.saved ]]; then
    mkdir -p "$BACKUP"
    [[ ! -e $LIST ]] || cp -a "$LIST" "$BACKUP/sources.list"
    [[ ! -d /etc/apt/sources.list.d ]] || cp -a /etc/apt/sources.list.d "$BACKUP/"
    touch "$BACKUP/.saved"
  fi
  [[ ! -f $LIST ]] || cp -an "$LIST" "${LIST}.bk" || true
  # Disable Ubuntu entries from all original .list/.sources files; keep third-party repositories.
  mkdir -p /etc/apt/sources.list.d
  find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0 |
    while IFS= read -r -d '' file; do
      if grep -Eq 'https?://[^/[:space:]]+/ubuntu/?([[:space:]]|$)' "$file"; then
        mv "$file" "${file}.gpu-disabled"
      fi
    done
  cat > "$LIST" <<'SOURCES'
deb https://mirrors.ustc.edu.cn/ubuntu/ jammy main restricted universe multiverse
deb https://mirrors.ustc.edu.cn/ubuntu/ jammy-updates main restricted universe multiverse
deb https://mirrors.ustc.edu.cn/ubuntu/ jammy-security main restricted universe multiverse
deb https://mirrors.ustc.edu.cn/ubuntu/ jammy-backports main restricted universe multiverse
SOURCES
  apt-get update
  ;;
 restore)
  [[ -e $BACKUP/.saved ]] || { echo 'Missing backup'; exit 1; }
  if [[ -f $BACKUP/sources.list ]]; then cp -a "$BACKUP/sources.list" "$LIST"; else rm -f "$LIST"; fi
  find /etc/apt/sources.list.d -maxdepth 1 -type f -name '*.gpu-disabled' -delete
  if [[ -d $BACKUP/sources.list.d ]]; then cp -a "$BACKUP/sources.list.d/." /etc/apt/sources.list.d/; fi
  apt-get update || echo 'Warning: original mirror update failed; source configuration restored.'
  ;;
 status)
  grep -RhsE '^(deb |URIs:)' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null || true
  ;;
 *) echo "Usage: bash $0 {ustc|restore|status}"; exit 2;;
esac
