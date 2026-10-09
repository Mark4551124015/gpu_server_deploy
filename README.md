# GPU deployment

Selectable setup scripts for Ubuntu 22.04 x86_64 GPU servers. Run as root.
Each node uses its own local configuration.

## Quick start

```bash
git clone https://github.com/YOUR_ORG/gpu-deploy.git
cd gpu-deploy
cp config.example.env config.env
# Edit config.env before running.
bash deploy.sh auto --dry-run
sudo bash deploy.sh auto
```

`auto` selects `1234`. Run `bash deploy.sh` for the menu, or pass any combination of digits.
Execution follows dependency order. There is no automatic reboot; driver changes may require one.

| Module | Action |
| --- | --- |
| 1 | Create users and grant the configured administrator sudo access |
| 2 | Install NVIDIA driver, Fabric Manager and NSCQ |
| 3 | Install shared Miniconda, NVM, Node.js LTS and npm |
| 4 | Install shared PyTorch; requires module 3 or existing Miniconda |
| 5 | Import user SSH public keys |
| 6 | Install a proxy tunnel or configure an existing HTTP proxy |
| 7 | Download Clash source; does not install or start it |
| 8 | Install shared Codex and pi; requires Node.js |
| 9 | Install NVM, Node.js LTS and npm only |

Public-key import and proxy setup are optional. `auto` does not select them.
Set package versions in `config.env`; use the same versions on both nodes.

## Users and shared tools

Set `USERS` and `ADMIN_USER` in `config.env`. Password setup is off by default.
For module 5, provide a directory containing one `<username>.pub` file per configured user:

```bash
sudo bash deploy.sh 5 --keys-dir /root/public-keys
```

To install Node.js and the coding agents without Miniconda:

```bash
sudo bash deploy.sh 98
```

Programs are shared under `/opt`. Codex configuration and sessions stay in each user's
`~/.codex`; pi configuration and sessions stay in `~/.pi/agent`. Each user signs in separately.

## Optional proxy

Node 1 needs internet access. From Node 2, with root SSH access to Node 1:

```bash
sudo bash deploy.sh 6 --proxy-server NODE1_IP --proxy-client-ip NODE2_IP
```

Replace both placeholders with the actual addresses. This installs a loopback-only
Tinyproxy service on Node 1 and a persistent SSH tunnel on Node 2. Module 6 runs before
package installation when combined with other modules, for example `12346`.

For an existing proxy:

```bash
sudo bash deploy.sh 6 --proxy-url http://127.0.0.1:18888
```

Keep internal APT mirrors outside the proxy by setting their hostnames in `config.env`:

```bash
APT_DIRECT_HOSTS="mirror.example.com"
NO_PROXY_EXTRA="cluster.example.com"
```

APT sources stay unchanged by default. Set `APT_SOURCE=ustc` to use the USTC Ubuntu
mirror during installation. `RESTORE_APT_SOURCE=1` restores the original sources afterward.
Proxy configuration does not perform a public internet or TLS connectivity check.

```bash
sudo python3 scripts/node_proxy.py status
sudo python3 scripts/node_proxy.py off
```

Log in again after changing proxy settings.

## Two-node smoke test

Both nodes need working drivers, eight visible GPUs and the same PyTorch environment.
Choose an interface reachable from the other node. Allow TCP between the two node
addresses in host firewalls and cloud security groups, including port 29500 and the
ports used by NCCL. Restrict these rules to the peer addresses.

Run on both nodes, replacing `NODE1_IP` and `INTERFACE`. Set `NODE_RANK=0` on Node 1
and `NODE_RANK=1` on Node 2:

```bash
export MASTER_ADDR=NODE1_IP
export NODE_RANK=0
export NCCL_SOCKET_IFNAME=INTERFACE
/opt/conda/envs/pytorch/bin/torchrun \
  --nnodes=2 --nproc-per-node=8 --node-rank="$NODE_RANK" \
  --master-addr="$MASTER_ADDR" --master-port=29500 scripts/torch_smoke.py
```

Success prints `PASS` for all 16 ranks, `all_reduce=136.0` and `DDP=OK`.
The test checks NCCL communication and one distributed training step.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

These local tests check selection, shell syntax and mocked proxy configuration.
They do not verify real server deployment or GPU communication.

## Publishing

Keep `config.env`, credentials, keys, logs and user sessions out of Git.
This public copy uses placeholder accounts, example addresses and a fresh Git history.
Review staged files before pushing:

```bash
git diff --cached
git remote add origin https://github.com/YOUR_ORG/gpu-deploy.git
git push -u origin main
```
