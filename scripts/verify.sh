#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
status=0
check() { printf '\nCHECK:'; printf ' %q' "$@"; printf '\n'; "$@" || status=1; }
check nvidia-smi -L
check nvidia-smi topo -m
check systemctl is-active nvidia-fabricmanager
for u in $USERS; do check id "$u"; done
check "$CONDA_ROOT/envs/pytorch/bin/python" -c 'import torch; print(torch.__version__, torch.version.cuda); assert torch.cuda.is_available(); print("GPUs:", torch.cuda.device_count()); assert torch.cuda.device_count() == 8; x=torch.ones(16,device="cuda"); print(x.sum().item())'
exit "$status"
