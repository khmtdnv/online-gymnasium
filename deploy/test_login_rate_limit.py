"""Проверяет ограничения попыток входа на настоящем временном Nginx."""

import http.client
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(os.getenv("OG_TEST_LOGIN_PROXY") == "1", "Needs disposable Docker")
class LoginRateLimitTests(unittest.TestCase):
    def test_both_proxies_limit_login_but_not_other_api(self):
        suffix = uuid4().hex[:10]
        network = f"og-login-test-{suffix}"
        upstream = f"og-login-upstream-{suffix}"
        root = Path(__file__).parent.resolve() / "web"

        def docker(*args):
            return subprocess.run(
                ["docker", *args], check=True, capture_output=True, text=True
            ).stdout.strip()

        with tempfile.TemporaryDirectory(prefix="og-login-test-") as directory:
            stub = Path(directory) / "stub.conf"
            stub.write_text('server { listen 8000; location / { return 200 "ok"; } }')
            docker("network", "create", network)
            try:
                docker(
                    "run",
                    "--rm",
                    "-d",
                    "--name",
                    upstream,
                    "--network",
                    network,
                    "--network-alias",
                    "gateway-api",
                    "--network-alias",
                    "backoffice-api",
                    "-v",
                    f"{stub}:/etc/nginx/conf.d/default.conf:ro",
                    "nginx:1.30.5-alpine",
                )
                for config in ("nginx.conf", "nginx.dev.conf"):
                    proxy = f"og-login-proxy-{suffix}-{config.replace('.', '-')}"
                    docker(
                        "run",
                        "--rm",
                        "-d",
                        "--name",
                        proxy,
                        "--network",
                        network,
                        "-p",
                        "127.0.0.1::80",
                        "-v",
                        f"{root / config}:/etc/nginx/conf.d/default.conf:ro",
                        "-v",
                        f"{root / 'proxy-headers.conf'}:/etc/nginx/og-proxy-headers.conf:ro",
                        "nginx:1.30.5-alpine",
                    )
                    try:
                        port = int(docker("port", proxy, "80/tcp").rsplit(":", 1)[1])
                        docker("exec", proxy, "nginx", "-t")

                        def request(path, target_port=port):
                            conn = http.client.HTTPConnection(
                                "127.0.0.1", target_port, timeout=5
                            )
                            try:
                                conn.request(
                                    "POST",
                                    path,
                                    body=b"{}",
                                    headers={"Host": "localhost"},
                                )
                                response = conn.getresponse()
                                response.read()
                                return response.status
                            finally:
                                conn.close()

                        for path in ("/api/v1/auth/login", "/admin/login/"):
                            statuses = [request(path) for _ in range(30)]
                            self.assertIn(200, statuses, (config, path, statuses))
                            self.assertIn(429, statuses, (config, path, statuses))
                        self.assertEqual(request("/api/v1/health"), 200)
                    finally:
                        docker("stop", proxy)
            finally:
                docker("stop", upstream)
                docker("network", "rm", network)
