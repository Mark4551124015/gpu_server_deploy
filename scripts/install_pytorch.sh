#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
[[ -x $CONDA_ROOT/bin/conda ]] || fail 'Miniconda is missing: select module 3 first, or set CONDA_ROOT.'
env_path=$CONDA_ROOT/envs/pytorch
if [[ ! -x $env_path/bin/python ]]; then
  # conda-forge avoids silently accepting another channel's Terms of Service.
  "$CONDA_ROOT/bin/conda" create -y -p "$env_path" --override-channels -c conda-forge "python=$PYTHON_VERSION" pip
fi
"$env_path/bin/python" -m pip install "torch==$TORCH_VERSION" --index-url "$TORCH_INDEX_URL"
chown -R root:root "$env_path"; chmod -R a+rX,go-w "$env_path"
"$env_path/bin/python" -c 'import torch; print("torch", torch.__version__, "CUDA", torch.version.cuda, "NCCL", torch.distributed.is_nccl_available())'
printf 'Shared PyTorch: %s. GPU verification is separate and requires a loaded driver.\n' "$env_path"
