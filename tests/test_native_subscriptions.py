import unittest

from bot.utils.subscriptions import (
    build_public_subscription_url,
    filter_public_subscription_inbounds,
    panel_bool,
)


class NativeSubscriptionURLTests(unittest.TestCase):
    def test_uses_node_builder_public_sub_uri_without_guessing_path(self):
        settings = {
            "subEnable": True,
            "subListen": "127.0.0.1",
            "subPort": 2096,
            "subPath": "/opaque/route/",
            "subDomain": "node.example.com",
            "subURI": "https://node.example.com/opaque/route/",
        }

        url = build_public_subscription_url(settings, "client id")

        self.assertEqual(
            url,
            "https://node.example.com/opaque/route/client%20id",
        )
        self.assertNotIn("/sub/", url)
        self.assertNotIn(":2096", url)

    def test_preserves_legacy_direct_subscription_server(self):
        settings = {
            "subEnable": "true",
            "subPort": "2096",
            "subPath": "legacy-subscriptions",
            "subDomain": "legacy.example.com",
            "subCertFile": "/cert.pem",
            "subKeyFile": "/key.pem",
        }

        self.assertEqual(
            build_public_subscription_url(settings, "abc123"),
            "https://legacy.example.com:2096/legacy-subscriptions/abc123",
        )

    def test_supports_relative_sub_uri_without_a_fixed_path(self):
        settings = {
            "subEnable": 1,
            "subPort": 443,
            "subDomain": "https://node.example.com",
            "subURI": "/custom/native/",
        }

        self.assertEqual(
            build_public_subscription_url(settings, "abc123"),
            "https://node.example.com/custom/native/abc123",
        )

    def test_rejects_disabled_or_incomplete_settings(self):
        self.assertIsNone(build_public_subscription_url({"subEnable": "false"}, "abc"))
        self.assertIsNone(build_public_subscription_url({"subEnable": True}, "abc"))
        self.assertFalse(panel_bool("false", default=True))


class NativeSubscriptionInboundTests(unittest.TestCase):
    def test_keeps_only_enabled_public_inbounds(self):
        inbounds = [
            {"id": 1, "remark": "Direct", "enable": True},
            {"id": 2, "remark": "Cascade", "enable": "1"},
            {"id": 3, "remark": "Auto Route"},
            {"id": 4, "remark": "--!Exit transport", "enable": True},
            {"id": 5, "remark": "Disabled route", "enable": False},
        ]

        result = filter_public_subscription_inbounds(inbounds)

        self.assertEqual([item["id"] for item in result], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
