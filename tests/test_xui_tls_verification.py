"""Real loopback TLS proof; all identities, certificates and payloads are synthetic."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest

from aiohttp import web


# A fresh interpreter loads its CA before importing aiohttp's cached SSL context.
# It never imports an owner's config.py or inherits provider/runner credentials.
CLIENT = r'''
import asyncio, json, sys, types
from unittest.mock import AsyncMock
sys.modules["config"] = types.SimpleNamespace(RETRY_CONFIG={
    "max_attempts": 1, "delays": [0], "timeout_seconds": 10,
})
from bot.services.panels.xui import XUIClient, API_PROFILE_LEGACY
from urllib.parse import urlsplit

async def main():
    args = json.loads(sys.argv[1])
    url = urlsplit(args["panel"])
    client = XUIClient({"id": 1, "name": "synthetic TLS fixture", "host": url.hostname,
        "port": url.port, "protocol": url.scheme, "web_base_path": "",
        "login": "fixture-user", "password": "fixture-password", "api_token": "fixture-token"})
    result = {}
    try:
        op = args["operation"]
        if op == "cookie":
            await client._login_with_cookie(fetch_token=False)
            result["ok"] = (await client._request("GET", "/panel/api/inbounds/list", retry=False))["success"]
        elif op == "bearer":
            result["ok"] = await client._try_bearer_validate()
            client.panel_mode, client.is_authenticated = "bearer", True
            result["read"] = (await client._request("GET", "/panel/api/inbounds/list", retry=False))["success"]
        elif op == "subscription":
            client._ensure_api_profile = AsyncMock(return_value=API_PROFILE_LEGACY)
            client.build_subscription_url = AsyncMock(return_value=args["public"])
            result["ok"] = await client.get_subscription_link("fixture-sub") == "vless://synthetic-fixture"
        elif op == "backup":
            await client._ensure_session()
            client.panel_mode, client.is_authenticated = "bearer", True
            result["ok"] = await client.get_database_backup() == b"SQLite format 3\x00synthetic fixture"
        elif op == "reset":
            result["first"], _ = await client._raw_json_request("GET", "/panel/api/server/status")
            old = client.session
            await client._reset_session()
            result["old_closed"] = old.closed
            client.base_url = args["second"]
            result["second"], _ = await client._raw_json_request("GET", "/panel/api/server/status")
    except Exception as error:
        result["error"] = type(error).__name__
    finally:
        result["token_intact"] = client.api_token == "fixture-token"
        await client.close()
    print(json.dumps(result))

asyncio.run(main())
'''


class XUITLSVerificationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="xui-synthetic-tls-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.empty_roots = cls.directory / "empty-roots"
        cls.empty_roots.mkdir()
        openssl = shutil.which("openssl")
        if not openssl:
            raise RuntimeError("openssl is required for the synthetic TLS fixture")

        def run(*args):
            subprocess.run([openssl, *args], cwd=cls.directory, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-sha256",
            "-subj", "/CN=Synthetic test-only CA", "-keyout", "ca.key", "-out", "ca.pem")
        for name, san in [("matching", "IP:127.0.0.1"), ("wrong-name", "DNS:other.example.invalid")]:
            run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256", "-subj", "/CN=" + name,
                "-keyout", name + ".key", "-out", name + ".csr")
            (cls.directory / (name + ".ext")).write_text(
                "subjectAltName=" + san + "\nextendedKeyUsage=serverAuth\n", encoding="ascii")
            run("x509", "-req", "-in", name + ".csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                "-CAcreateserial", "-days", "2", "-sha256", "-extfile", name + ".ext", "-out", name + ".pem")
        for key in cls.directory.glob("*.key"):
            key.chmod(0o600)

    async def asyncSetUp(self):
        self.runners = []

    async def asyncTearDown(self):
        for runner in self.runners:
            await runner.cleanup()

    async def server(self, certificate="matching", csrf=False):
        received = []

        async def handle(request):
            received.append((request.method, request.path))
            if request.path == "/csrf-token":
                return web.json_response({"obj": "fixture-csrf"}) if csrf else web.Response(status=404)
            if request.path == "/login":
                body = await request.json()
                valid = body == {"username": "fixture-user", "password": "fixture-password"}
                valid = valid and (not csrf or request.headers.get("X-CSRF-Token") == "fixture-csrf")
                response = web.json_response({"success": valid})
                if valid:
                    response.set_cookie("session", "fixture-cookie", httponly=True)
                return response
            if request.path == "/sub/redirect":
                raise web.HTTPFound("/sub/fixture")
            if request.path == "/sub/fixture":
                return web.Response(text="vless://synthetic-fixture")
            if request.path == "/panel/api/server/status":
                return web.json_response({"success": True, "obj": {}})
            authorized = (request.headers.get("Authorization") == "Bearer fixture-token"
                          or request.cookies.get("session") == "fixture-cookie")
            if not authorized:
                return web.json_response({"success": False}, status=401)
            if request.path == "/panel/api/inbounds/list":
                return web.json_response({"success": True, "obj": []})
            if request.path == "/panel/api/server/getDb":
                return web.Response(body=b"SQLite format 3\x00synthetic fixture")
            return web.Response(status=404)

        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handle)
        runner = web.AppRunner(app)
        self.runners.append(runner)
        await runner.setup()
        context = None
        if certificate:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.directory / (certificate + ".pem"), self.directory / (certificate + ".key"))
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        return ("https" if certificate else "http") + f"://127.0.0.1:{port}", received

    async def request(self, panel, operation, trusted=True, **extra):
        env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
               if key in os.environ}
        env.update(SSL_CERT_FILE=str(self.directory / "ca.pem") if trusted else os.devnull,
                   SSL_CERT_DIR=str(self.empty_roots), PYTHONDONTWRITEBYTECODE="1")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-B", "-c", CLIENT, json.dumps({"panel": panel, "operation": operation, **extra}),
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        finally:
            if process.returncode is None:
                process.kill()
                await process.communicate()
        self.assertEqual(process.returncode, 0, stderr.decode())
        return json.loads(stdout)

    async def test_untrusted_login_sends_no_http_or_password(self):
        url, received = await self.server()
        result = await self.request(url, "cookie", trusted=False)
        self.assertIn("error", result)
        self.assertEqual(received, [])

    async def test_untrusted_bearer_sends_no_http_and_retains_token(self):
        url, received = await self.server()
        result = await self.request(url, "bearer", trusted=False)
        self.assertIn("error", result)
        self.assertTrue(result["token_intact"])
        self.assertEqual(received, [])

    async def test_trusted_ca_does_not_disable_hostname_matching(self):
        url, received = await self.server("wrong-name")
        result = await self.request(url, "cookie")
        self.assertIn("error", result)
        self.assertEqual(received, [])

    async def test_trusted_legacy_cookie_and_ip_cookie_jar(self):
        url, received = await self.server()
        self.assertTrue((await self.request(url, "cookie"))["ok"])
        self.assertIn(("GET", "/panel/api/inbounds/list"), received)

    async def test_trusted_csrf_cookie_login_and_read(self):
        url, received = await self.server(csrf=True)
        self.assertTrue((await self.request(url, "cookie"))["ok"])
        self.assertIn(("POST", "/login"), received)

    async def test_trusted_bearer_validation_and_authenticated_read(self):
        url, _ = await self.server()
        result = await self.request(url, "bearer")
        self.assertTrue(result["ok"])
        self.assertTrue(result["read"])

    async def test_untrusted_separate_public_subscription_is_not_returned(self):
        panel, _ = await self.server(certificate=None)
        public, received = await self.server()
        result = await self.request(panel, "subscription", trusted=False, public=public + "/sub/fixture")
        self.assertFalse(result["ok"])
        self.assertEqual(received, [])

    async def test_trusted_public_subscription_keeps_same_origin_redirect(self):
        panel, _ = await self.server(certificate=None)
        public, received = await self.server()
        result = await self.request(panel, "subscription", public=public + "/sub/redirect")
        self.assertTrue(result["ok"])
        self.assertEqual(received, [("GET", "/sub/redirect"), ("GET", "/sub/fixture")])

    async def test_untrusted_backup_sends_no_http(self):
        url, received = await self.server()
        result = await self.request(url, "backup", trusted=False)
        self.assertIn("error", result)
        self.assertEqual(received, [])

    async def test_trusted_backup_uses_verified_session(self):
        url, _ = await self.server()
        self.assertTrue((await self.request(url, "backup"))["ok"])

    async def test_explicit_plain_http_cookie_behavior_remains_supported(self):
        url, _ = await self.server(certificate=None)
        self.assertTrue((await self.request(url, "cookie"))["ok"])

    async def test_session_reset_recreates_verified_tls(self):
        good, _ = await self.server()
        bad, received = await self.server("wrong-name")
        result = await self.request(good, "reset", second=bad)
        self.assertEqual(result["first"], 200)
        self.assertEqual(result["second"], 0)
        self.assertTrue(result["old_closed"])
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
