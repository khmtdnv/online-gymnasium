"""Ограничение тела файлового маршрута не расширяет обычный JSON API."""

import http.client
import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4


class HomeworkUploadProxyTests(unittest.TestCase):
    def test_both_proxy_configs_have_scoped_file_limits_and_timeouts(self):
        for name in ("nginx.conf", "nginx.dev.conf"):
            with self.subTest(name=name):
                config = (Path(__file__).parent / "web" / name).read_text()
                pattern = r"location ~ \^/api/v1/homework/\[0-9\]\+/\(answers/\[0-9\]\+/\)\?files/\[0-9\]\+\$ \{([^}]+)\}"
                match = re.search(pattern, config)
                self.assertIsNotNone(match)
                block = match.group(1)
                for directive in (
                    "client_max_body_size 11m;",
                    "client_body_timeout 300s;",
                    "proxy_connect_timeout 5s;",
                    "proxy_send_timeout 120s;",
                    "proxy_read_timeout 300s;",
                    "proxy_next_upstream off;",
                ):
                    self.assertIn(directive, block)
                self.assertIn("client_max_body_size 1m;", config)
                self.assertNotRegex(config, r"location\s+\^~\s+/api/v1/\s*\{")
                self.assertLess(
                    config.index(match.group(0)), config.index("location ~ /\\.")
                )


@unittest.skipUnless(
    os.getenv("OG_TEST_UPLOAD_PROXY") == "1", "Opt in to disposable Docker proxy test"
)
class HomeworkUploadProxyIntegrationTests(unittest.TestCase):
    def test_real_nginx_routes_and_actual_body_limits(self):
        """Поднимает только собственную сеть и два временных Nginx, без Compose/env."""
        suffix = uuid4().hex[:10]
        network = f"og-upload-proxy-test-{suffix}"
        upstream = f"og-upload-owner-test-{suffix}"
        proxy = f"og-upload-web-test-{suffix}"
        root = Path(__file__).parent.resolve() / "web"

        def docker(*args):
            return subprocess.run(
                ["docker", *args], check=True, capture_output=True, text=True
            ).stdout.strip()

        with tempfile.TemporaryDirectory(prefix="og-upload-proxy-") as directory:
            stub = Path(directory) / "stub.conf"
            stub.write_text(
                'server { listen 8000; client_max_body_size 20m; location / { return 200 "upstream"; } }'
            )
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
                    "-v",
                    f"{stub}:/etc/nginx/conf.d/default.conf:ro",
                    "nginx:1.30.5-alpine",
                )
                for config in ("nginx.conf", "nginx.dev.conf"):
                    with self.subTest(config=config):
                        proxy = (
                            f"og-upload-web-test-{suffix}-{config.replace('.', '-')}"
                        )
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
                            port = int(
                                docker("port", proxy, "80/tcp").rsplit(":", 1)[1]
                            )
                            docker("exec", proxy, "nginx", "-t")

                            def request(path, content, *, chunked=False, port=port):
                                connection = http.client.HTTPConnection(
                                    "127.0.0.1", port, timeout=10
                                )
                                try:
                                    connection.request(
                                        "PUT",
                                        path,
                                        body=content,
                                        headers={"Host": "localhost"},
                                        encode_chunked=chunked,
                                    )
                                    response = connection.getresponse()
                                    status, body = response.status, response.read()
                                    return status, body
                                finally:
                                    connection.close()

                            for attempt in range(20):
                                try:
                                    request("/api/v1/health", b"")
                                    break
                                except (ConnectionError, OSError):
                                    if attempt == 19:
                                        raise
                                    time.sleep(0.1)
                            self.assertEqual(
                                request(
                                    "/api/v1/homework/1/files/8",
                                    b"x" * (2 * 1024 * 1024),
                                ),
                                (200, b"upstream"),
                            )
                            self.assertEqual(
                                request(
                                    "/api/v1/homework/1/answers/3/files/8",
                                    b"x" * (2 * 1024 * 1024),
                                ),
                                (200, b"upstream"),
                            )
                            self.assertEqual(
                                request(
                                    "/api/v1/lessons/1/homework",
                                    b"x" * (2 * 1024 * 1024),
                                )[0],
                                413,
                            )
                            self.assertEqual(
                                request("/internal/homework/1/files/8", b"")[0], 404
                            )
                            # Chunked body has no Content-Length; actual limit still applies.
                            self.assertEqual(
                                request(
                                    "/api/v1/homework/1/files/8",
                                    iter([b"x" * 65536] * 177),
                                    chunked=True,
                                )[0],
                                413,
                            )
                        finally:
                            docker("stop", proxy)
            finally:
                docker("stop", upstream)
                docker("network", "rm", network)
