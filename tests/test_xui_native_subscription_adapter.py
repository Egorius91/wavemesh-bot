import sys
import types
import unittest
from unittest.mock import AsyncMock


try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    sys.modules["aiohttp"] = types.SimpleNamespace(
        ClientSession=object,
        ClientTimeout=object,
        TCPConnector=object,
        CookieJar=object,
        ClientError=Exception,
    )

if "config" not in sys.modules:
    sys.modules["config"] = types.SimpleNamespace(RETRY_CONFIG={})

from bot.services.panels.xui import XUIClient


class XUINativeSubscriptionAdapterTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, cached_settings=None):
        client = object.__new__(XUIClient)
        client._panel_settings = cached_settings
        client.host = "panel.internal"
        client.server_id = 7
        client.server = {"id": 7, "name": "staging-node"}
        return client

    async def test_refreshes_public_prefix_before_each_delivery(self):
        client = self.make_client(
            {"subEnable": True, "subURI": "https://old.example/old-path/"}
        )
        client.get_panel_settings = AsyncMock(
            return_value={
                "subEnable": True,
                "subURI": "https://node.example/new-opaque-path/",
            }
        )

        url = await client.build_subscription_url("client-id")

        self.assertEqual(
            url,
            "https://node.example/new-opaque-path/client-id",
        )
        client.get_panel_settings.assert_awaited_once_with(force_refresh=True)

    async def test_uses_cached_settings_when_refresh_is_temporarily_unavailable(self):
        client = self.make_client(
            {"subEnable": True, "subURI": "https://node.example/stable-path/"}
        )
        client.get_panel_settings = AsyncMock(return_value=None)

        url = await client.build_subscription_url("client-id")

        self.assertEqual(url, "https://node.example/stable-path/client-id")


if __name__ == "__main__":
    unittest.main()
