#!/usr/bin/env python3
"""Optional HTTP proxy and SSH tunnel; independent of user-key deployment."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import sys
import urllib.parse

ACCOUNT = "gpu-proxy"
HOME = Path("/var/lib/gpu-proxy")
SERVICE = "gpu-node-proxy"
TUNNEL = "gpu-node-proxy-tunnel"
PROXY_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY")
MARKER = "# Managed by gpu-deploy/node_proxy.py"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def root():
    if os.geteuid() != 0:
        raise ValueError("Run this subcommand as root (bootstrap can run on the admin computer).")


def port(value):
    value = int(value)
    if not 1024 <= value <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1024 and 65535")
    return value


def host(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise argparse.ArgumentTypeError("Use an SSH alias, DNS hostname or IPv4 address")
    return value


def write(path, content, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def account():
    try:
        user = pwd.getpwnam(ACCOUNT)
    except KeyError:
        run("useradd", "--system", "--create-home", "--home-dir", str(HOME), "--shell", "/bin/sh", ACCOUNT)
        user = pwd.getpwnam(ACCOUNT)
    if user.pw_dir != str(HOME):
        raise ValueError(f"Existing {ACCOUNT} account has an unexpected home directory")
    return user


def own(path, user):
    os.chown(path, user.pw_uid, user.pw_gid)


def enable(unit):
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", unit)
    run("systemctl", "restart", unit)
    run("systemctl", "is-active", "--quiet", unit)


def configure(url, direct_hosts=None, extra_bypass=None):
    root()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP proxy URL without embedded credentials: http://HOST:PORT")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Proxy URL must not contain a path, query or fragment")
    if any(c in url for c in '\n\r\"\' \\'):
        raise ValueError("Invalid proxy URL characters")
    # Configuration must not depend on reaching a public website.
    if direct_hosts is None:
        direct_hosts = os.environ.get("APT_DIRECT_HOSTS", "").split()
    direct_hosts = [host(value) for value in direct_hosts]
    if extra_bypass is None:
        extra_bypass = os.environ.get("NO_PROXY_EXTRA", "")
    if any(c in extra_bypass for c in '\n\r\"\' \\'):
        raise ValueError("Invalid no_proxy entries")
    bypass = ",".join(["localhost", "127.0.0.1", "::1", *direct_hosts])
    if extra_bypass:
        bypass += "," + extra_bypass
    environment = Path("/etc/environment")
    backup = Path("/etc/environment.before-gpu-proxy")
    if environment.exists() and not backup.exists():
        shutil.copy2(environment, backup)
    lines = environment.read_text().splitlines() if environment.exists() else []
    # Preserve pre-existing NO_PROXY entries, including site-specific internal services.
    for line in lines:
        if line.split("=", 1)[0].strip() in ("no_proxy", "NO_PROXY") and "=" in line:
            bypass += "," + line.split("=", 1)[1].strip().strip("\"'")
    bypass = ",".join(dict.fromkeys(bypass.split(",")))
    values = {key: bypass if key.lower() == "no_proxy" else url for key in PROXY_KEYS}
    lines = [line for line in lines if line.split("=", 1)[0].strip() not in PROXY_KEYS]
    environment.write_text("\n".join(lines + [f'{k}="{v}"' for k, v in values.items()]) + "\n")
    write("/etc/profile.d/gpu-node-proxy.sh", MARKER + "\n" +
          "\n".join(f"export {key}={shlex.quote(value)}" for key, value in values.items()) + "\n")
    apt_config = MARKER.replace("#", "//", 1) + f'\nAcquire::http::Proxy "{url}";\nAcquire::https::Proxy "{url}";\n'
    for mirror in direct_hosts:
        for scheme in ("http", "https"):
            apt_config += f'Acquire::{scheme}::Proxy::{mirror} "DIRECT";\n'
    write("/etc/apt/apt.conf.d/80gpu-node-proxy", apt_config)
    write("/var/lib/gpu-deploy/proxy-environment.json", json.dumps(values), 0o600)
    print("Proxy configured (no public connectivity check). Login again or source /etc/profile.d/gpu-node-proxy.sh")


def client_key():
    root()
    user = account()
    folder = HOME / ".ssh"
    folder.mkdir(mode=0o700, exist_ok=True)
    own(folder, user)
    key = folder / "node_proxy_ed25519"
    if not key.exists():
        run("runuser", "-u", ACCOUNT, "--", "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
    return {"public_key": key.with_suffix(".pub").read_text().strip()}


def keygen():
    print(json.dumps(client_key()))


def server(args):
    root()
    address = str(ipaddress.IPv4Address(args.client_ip))
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?", args.public_key):
        raise ValueError("Expected the client's dedicated Ed25519 public key")
    if not shutil.which("tinyproxy"):
        run("apt-get", "update")
        run("apt-get", "install", "-y", "tinyproxy", env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    # Do not replace an unrelated listener, including an older manually set proxy.
    listening = run("ss", "-lnt", "sport", "=", f":{args.port}", stdout=subprocess.PIPE).stdout
    unit = Path(f"/etc/systemd/system/{SERVICE}.service")
    if len(listening.strip().splitlines()) > 1 and not unit.exists():
        raise ValueError(f"Port {args.port} is already in use; choose --port")
    user = account()
    folder = HOME / ".ssh"
    folder.mkdir(mode=0o700, exist_ok=True); own(folder, user)
    # A dedicated account; shell/agent/X11 are disabled. Reverse forwards are
    # limited to privileged port 1, which this unprivileged account cannot bind.
    auth = (f'from="{address}",restrict,port-forwarding,permitopen="127.0.0.1:{args.port}",'
            f'permitlisten="127.0.0.1:1",command="/bin/false" {args.public_key}\n')
    write(folder / "authorized_keys", auth, 0o600); own(folder / "authorized_keys", user)
    write("/etc/tinyproxy/gpu.conf", f"""User tinyproxy
Group tinyproxy
Port {args.port}
Listen 127.0.0.1
Timeout 600
Syslog On
LogLevel Warning
MaxClients 100
Allow 127.0.0.1
ConnectPort 443
ViaProxyName "gpu-node-proxy"
""")
    write(f"/etc/systemd/system/{SERVICE}.service", """[Unit]
Description=GPU node HTTP proxy (loopback only)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/tinyproxy -d -c /etc/tinyproxy/gpu.conf
Restart=always
RestartSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
""")
    enable(SERVICE)
    public_host_key = Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().strip()
    print(json.dumps({"host_key": public_host_key}))


def client(args):
    root()
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?", args.host_key):
        raise ValueError("Expected Node 1's verified Ed25519 host key")
    user = account()
    key = HOME / ".ssh/node_proxy_ed25519"
    if not key.exists():
        raise ValueError("Run keygen on the client first")
    listening = run("ss", "-lnt", "sport", "=", f":{args.local_port}", stdout=subprocess.PIPE).stdout
    unit = Path(f"/etc/systemd/system/{TUNNEL}.service")
    if len(listening.strip().splitlines()) > 1 and not unit.exists():
        raise ValueError(f"Local port {args.local_port} is already in use; choose --local-port")
    known_hosts = HOME / ".ssh/node_proxy_known_hosts"
    write(known_hosts, f"{args.server_address} {args.host_key}\n", 0o600); own(known_hosts, user)
    cmd = ["/usr/bin/ssh", "-N", "-T", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
           "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
           "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
           "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-i", str(key),
           "-L", f"127.0.0.1:{args.local_port}:127.0.0.1:{args.port}",
           f"{ACCOUNT}@{args.server_address}"]
    # Arguments are validated and contain no whitespace or systemd %-specifiers.
    write(f"/etc/systemd/system/{TUNNEL}.service", f"""[Unit]
Description=GPU node proxy SSH tunnel
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User={ACCOUNT}
ExecStart={' '.join(cmd)}
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
""")
    enable(TUNNEL)
    # Only wait for the local SSH listener, without requesting any public site.
    import time
    for attempt in range(5):
        try:
            with socket.create_connection(("127.0.0.1", args.local_port), timeout=5):
                pass
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(1)
    configure(f"http://127.0.0.1:{args.local_port}")


def remote(alias, *args):
    command = shlex.join(["python3", "-", *args])
    result = run("ssh", "-o", "ConnectTimeout=15", "-o", "ClearAllForwardings=yes", "-l", "root",
                 alias, command, input=Path(__file__).read_text(), stdout=subprocess.PIPE)
    print(result.stdout, end="")
    return result.stdout


def last_json(output):
    for line in reversed(output.splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass
    raise ValueError("Remote provisioning did not return public-key metadata")


def bootstrap(args):
    # Run from admin workstation; root credentials follow existing SSH config.
    keys = last_json(remote(args.client, "keygen"))
    info = last_json(remote(args.server, "server", "--client-ip", args.client_ip,
                            "--public-key", keys["public_key"], "--port", str(args.port)))
    remote(args.client, "client", "--server-address", args.server_address,
           "--host-key", info["host_key"], "--port", str(args.port), "--local-port", str(args.local_port))
    print("SSH proxy ready; private keys stayed on the client.")


def setup(args):
    """Run on Node 2; install Node 1 remotely without requiring SSH to localhost."""
    root()
    keys = client_key()
    info = last_json(remote(args.server, "server", "--client-ip", args.client_ip,
                            "--public-key", keys["public_key"], "--port", str(args.port)))
    if not args.server_address:
        args.server_address = args.server
    args.host_key = info["host_key"]
    client(args)
    print("Node 1 proxy installed and this node's tunnel configured.")


def off():
    root()
    if Path(f"/etc/systemd/system/{TUNNEL}.service").exists():
        run("systemctl", "disable", "--now", TUNNEL)
    state = Path("/var/lib/gpu-deploy/proxy-environment.json")
    if state.exists():
        installed = json.loads(state.read_text())
        environment = Path("/etc/environment")
        lines = environment.read_text().splitlines()
        previous_file = Path("/etc/environment.before-gpu-proxy")
        previous = previous_file.read_text().splitlines() if previous_file.exists() else []
        removed = set()
        kept = []
        for line in lines:
            key, sep, value = line.partition("=")
            if sep and key.strip() in installed and value.strip().strip("\"'") == installed[key.strip()]:
                removed.add(key.strip())
            else:
                kept.append(line)
        kept.extend(line for line in previous if line.split("=", 1)[0].strip() in removed)
        environment.write_text("\n".join(kept) + "\n")
        state.unlink()
    for path in ("/etc/profile.d/gpu-node-proxy.sh", "/etc/apt/apt.conf.d/80gpu-node-proxy"):
        target = Path(path)
        if target.exists():
            target.unlink()
    print("Client proxy disabled. Login again; existing terminal environment is unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    sub = commands.add_parser("bootstrap", help="Provision both nodes from the administrator's computer")
    sub.add_argument("--server", type=host, required=True, help="Node 1 SSH alias")
    sub.add_argument("--client", type=host, required=True, help="Node 2 SSH alias (ProxyJump supported)")
    sub.add_argument("--server-address", type=host, required=True)
    sub.add_argument("--client-ip", required=True)
    sub.add_argument("--port", type=port, default=18888)
    sub.add_argument("--local-port", type=port, default=18888)
    sub = commands.add_parser("setup", help="Run on Node 2: install Node 1 proxy and the local tunnel (root)")
    sub.add_argument("--server", type=host, required=True, help="Node 1 root SSH IP or alias")
    sub.add_argument("--server-address", type=host, help="Node 1 address reachable from the tunnel user")
    sub.add_argument("--client-ip", required=True)
    sub.add_argument("--port", type=port, default=18888)
    sub.add_argument("--local-port", type=port, default=18888)
    commands.add_parser("keygen", help="Generate the dedicated client tunnel key")
    sub = commands.add_parser("server", help="Configure Node 1 (root)")
    sub.add_argument("--client-ip", required=True)
    sub.add_argument("--public-key", required=True)
    sub.add_argument("--port", type=port, default=18888)
    sub = commands.add_parser("client", help="Configure Node 2 (root)")
    sub.add_argument("--server-address", type=host, required=True)
    sub.add_argument("--host-key", required=True)
    sub.add_argument("--port", type=port, default=18888)
    sub.add_argument("--local-port", type=port, default=18888)
    sub = commands.add_parser("configure", help="Configure an HTTP proxy without a public connectivity test (root)")
    sub.add_argument("--url", required=True)
    sub.add_argument("--direct-host", action="append", help="Internal APT mirror hostname; repeat as needed")
    sub.add_argument("--no-proxy-extra", help="Additional comma-separated bypass entries")
    commands.add_parser("off", help="Disable client tunnel and restore proxy environment (root)")
    commands.add_parser("server-off", help="Stop the dedicated Node 1 service (root)")
    commands.add_parser("status", help="Show proxy services and environment")
    args = parser.parse_args()
    if args.action in ("bootstrap", "setup"):
        ipaddress.IPv4Address(args.client_ip)
        if args.action == "bootstrap": bootstrap(args)
        else: setup(args)
    elif args.action == "keygen": keygen()
    elif args.action == "server": server(args)
    elif args.action == "client": client(args)
    elif args.action == "configure": configure(args.url, args.direct_host, args.no_proxy_extra)
    elif args.action == "off": off()
    elif args.action == "server-off":
        root(); run("systemctl", "disable", "--now", SERVICE)
    elif args.action == "status":
        for unit in (SERVICE, TUNNEL):
            subprocess.run(["systemctl", "is-active", unit], check=False)
        print(Path("/etc/profile.d/gpu-node-proxy.sh").read_text()
              if Path("/etc/profile.d/gpu-node-proxy.sh").exists() else "No managed proxy environment")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, argparse.ArgumentTypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
