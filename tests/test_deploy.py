import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.request
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("node_proxy", ROOT / "scripts/node_proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class DeploymentSelection(unittest.TestCase):
    def command(self, *args):
        return subprocess.run(["bash", str(ROOT / "deploy.sh"), *args], cwd=ROOT,
                              capture_output=True, text=True)

    def test_auto_excludes_optional_modules(self):
        result = self.command("auto", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        for script in ("setup_users", "install_driver", "install_tools", "install_pytorch"):
            self.assertIn(script + ".sh", result.stdout)
        for script in ("import_ssh_keys", "node_proxy", "prepare_clash"):
            self.assertNotIn(script, result.stdout)
        self.assertNotIn("switch_apt_source", result.stdout)
        self.assertIn("RUN apt-get update", result.stdout)

    def test_single_module_is_independent(self):
        result = self.command("1", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("setup_users.sh", result.stdout)
        self.assertNotIn("switch_apt_source", result.stdout)
        self.assertNotIn("install_driver", result.stdout)

    def test_invalid_and_missing_arguments(self):
        for args in (("10", "--dry-run"), ("auto", "--keys-dir"),
                     ("auto", "--proxy-url"), ("5", "--dry-run"),
                     ("auto", "--proxy-server"), ("6", "--proxy-server", "bad;host", "--dry-run"),
                     ("6", "--proxy-server", "192.0.2.10", "--dry-run"), ("6", "--dry-run"), ("auto", "1", "--dry-run")):
            result = self.command(*args)
            self.assertNotEqual(result.returncode, 0, args)
            self.assertNotIn("RUN", result.stdout)

    def test_explicit_keys_do_not_enable_proxy(self):
        with tempfile.TemporaryDirectory() as keys:
            result = self.command("12345", "--keys-dir", keys, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("import_ssh_keys.sh", result.stdout)
        self.assertNotIn("node_proxy", result.stdout)

    def test_proxy_runs_first_and_is_deduplicated(self):
        result = self.command("66631", "--proxy-url", "http://127.0.0.1:18888", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("node_proxy.py"), 1)
        self.assertLess(result.stdout.index("node_proxy.py"), result.stdout.index("RUN apt-get update"))
        self.assertLess(result.stdout.index("setup_users.sh"), result.stdout.index("install_tools.sh"))

    def test_proxy_server_installs_before_other_modules(self):
        result = self.command("12346", "--proxy-server", "192.0.2.10", "--proxy-client-ip", "192.0.2.11", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("node_proxy.py setup --server 192.0.2.10", result.stdout)
        self.assertNotIn("node_proxy.py configure", result.stdout)
        self.assertNotIn("import_ssh_keys", result.stdout)
        self.assertLess(result.stdout.index("node_proxy.py"), result.stdout.index("RUN apt-get update"))

    def test_noninteractive_no_selection_fails(self):
        result = self.command("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Specify auto", result.stderr)

    def test_node_and_agents_without_conda_or_driver(self):
        result = self.command("98", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install_node.sh", result.stdout)
        self.assertIn("install_agents.sh", result.stdout)
        self.assertNotIn("install_tools.sh", result.stdout)
        self.assertNotIn("install_driver.sh", result.stdout)
        self.assertNotIn("install_pytorch.sh", result.stdout)
        self.assertLess(result.stdout.index("install_node.sh"), result.stdout.index("install_agents.sh"))

    def test_combined_tools_does_not_repeat_node(self):
        result = self.command("398", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install_tools.sh", result.stdout)
        self.assertNotIn("install_node.sh", result.stdout)

    def test_shell_syntax(self):
        for file in ROOT.rglob("*.sh"):
            result = subprocess.run(["bash", "-n", str(file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{file}: {result.stderr}")


class ProxyConfiguration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        def mapped(value):
            value = str(value)
            if value.startswith(("/etc/", "/var/lib/")):
                return self.root / value.lstrip("/")
            return Path(value)
        self.path_patch = mock.patch.object(proxy, "Path", side_effect=mapped)
        self.path_patch.start()
        self.root_patch = mock.patch.object(proxy, "root")
        self.root_patch.start()
        self.run_patch = mock.patch.object(proxy, "run", return_value=SimpleNamespace(stdout="State Recv-Q Send-Q\n"))
        self.run = self.run_patch.start()
        self.env = self.root / "etc/environment"
        self.env.parent.mkdir(parents=True)
        self.env.write_text('KEEP="original"\nhttp_proxy="http://old-proxy:3128"\nNO_PROXY="cluster.local"\n')

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def test_config_preserves_other_environment_and_internal_bypass(self):
        proxy.configure("http://127.0.0.1:18888", ["mirror.example.com"], "cluster.example.com")
        text = self.env.read_text()
        self.assertIn('KEEP="original"', text)
        self.assertIn('http_proxy="http://127.0.0.1:18888"', text)
        self.assertIn("cluster.local", text)
        proxy.configure("http://127.0.0.1:18888", ["mirror.example.com"], "cluster.example.com")
        self.assertEqual(text, self.env.read_text())
        apt = (self.root / "etc/apt/apt.conf.d/80gpu-node-proxy").read_text()
        self.assertIn('Acquire::https::Proxy "http://127.0.0.1:18888"', apt)
        self.assertIn('Acquire::http::Proxy::mirror.example.com "DIRECT"', apt)

    def test_configure_does_not_require_network_or_public_tls(self):
        with mock.patch.object(urllib.request, "build_opener", side_effect=AssertionError("No public check")), \
             mock.patch.object(proxy.socket, "create_connection", side_effect=AssertionError("No connectivity check")):
            proxy.configure("http://127.0.0.1:18888")
        self.assertIn('http_proxy="http://127.0.0.1:18888"', self.env.read_text())

    def test_off_restores_previous_and_preserves_later_manual_change(self):
        proxy.configure("http://127.0.0.1:18888")
        self.env.write_text(self.env.read_text().replace('https_proxy="http://127.0.0.1:18888"',
                                                       'https_proxy="http://manual:3128"'))
        proxy.off()
        text = self.env.read_text()
        self.assertIn('http_proxy="http://old-proxy:3128"', text)
        self.assertIn('https_proxy="http://manual:3128"', text)
        self.assertIn('NO_PROXY="cluster.local"', text)
        self.assertIn('KEEP="original"', text)
        self.assertFalse((self.root / "etc/profile.d/gpu-node-proxy.sh").exists())

    def test_unsafe_urls_rejected(self):
        before = self.env.read_text()
        for url in ("https://proxy:80", "http://u:p@proxy:80", "http://proxy:80/path",
                    'http://proxy:80\nexport X=1'):
            with self.assertRaises(ValueError): proxy.configure(url)
        self.assertEqual(before, self.env.read_text())

    def test_server_is_loopback_only_and_key_is_restricted(self):
        user = SimpleNamespace(pw_uid=1, pw_gid=1)
        home = self.root / "var/lib/gpu-proxy"
        home.mkdir(parents=True)
        host_key = self.root / "etc/ssh/ssh_host_ed25519_key.pub"
        host_key.parent.mkdir(parents=True)
        host_key.write_text("ssh-ed25519 AAAAtest server")
        args = SimpleNamespace(client_ip="192.0.2.11", public_key="ssh-ed25519 AAAAtest client", port=18888)
        with mock.patch.object(proxy, "HOME", home), mock.patch.object(proxy, "account", return_value=user), \
             mock.patch.object(proxy, "own"), mock.patch.object(proxy.shutil, "which", return_value="/usr/bin/tinyproxy"):
            proxy.server(args)
        config = (self.root / "etc/tinyproxy/gpu.conf").read_text()
        self.assertIn("Listen 127.0.0.1", config)
        self.assertNotIn("0.0.0.0", config)
        auth = (home / ".ssh/authorized_keys").read_text()
        self.assertIn('from="192.0.2.11"', auth)
        self.assertIn('permitopen="127.0.0.1:18888"', auth)
        self.assertIn('command="/bin/false"', auth)

    def test_client_strict_host_check_and_autorestart(self):
        home = self.root / "var/lib/gpu-proxy"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh/node_proxy_ed25519").write_text("fake private key stays here")
        args = SimpleNamespace(server_address="192.0.2.10", host_key="ssh-ed25519 AAAAtest server",
                               port=18888, local_port=18888)
        with mock.patch.object(proxy, "HOME", home), mock.patch.object(proxy, "account"), \
             mock.patch.object(proxy, "own"), mock.patch.object(proxy.socket, "create_connection"):
            proxy.client(args)
        service = (self.root / "etc/systemd/system/gpu-node-proxy-tunnel.service").read_text()
        self.assertIn("StrictHostKeyChecking=yes", service)
        self.assertIn("Restart=always", service)
        self.assertIn("127.0.0.1:18888:127.0.0.1:18888", service)
        self.assertNotIn("fake private", service)

    def test_bootstrap_sends_only_public_key_metadata(self):
        args = SimpleNamespace(server="node1", client="node2", server_address="192.0.2.10",
                               client_ip="192.0.2.11", port=18888, local_port=18888)
        with mock.patch.object(proxy, "remote", side_effect=['{"public_key":"ssh-ed25519 AAAAclient"}',
                                                              '{"host_key":"ssh-ed25519 AAAAserver"}', "done"]) as remote:
            proxy.bootstrap(args)
        calls = remote.call_args_list
        self.assertEqual(calls[0].args, ("node2", "keygen"))
        self.assertIn("ssh-ed25519 AAAAclient", calls[1].args)
        self.assertIn("ssh-ed25519 AAAAserver", calls[2].args)
        self.assertNotIn("private_key", str(calls))

    def test_local_setup_requires_only_one_remote_connection(self):
        args = SimpleNamespace(server="192.0.2.10", server_address=None,
                               client_ip="192.0.2.11", port=18888, local_port=18888)
        with mock.patch.object(proxy, "client_key", return_value={"public_key": "ssh-ed25519 AAAAclient"}), \
             mock.patch.object(proxy, "remote", return_value='{"host_key":"ssh-ed25519 AAAAserver"}') as remote, \
             mock.patch.object(proxy, "client") as client:
            proxy.setup(args)
        remote.assert_called_once()
        self.assertEqual(remote.call_args.args[:2], ("192.0.2.10", "server"))
        client.assert_called_once_with(args)
        self.assertEqual(args.server_address, "192.0.2.10")
        self.assertEqual(args.host_key, "ssh-ed25519 AAAAserver")


if __name__ == "__main__":
    unittest.main()
