import unittest
from unittest.mock import AsyncMock

from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient


class InternalApiAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_material_negotiates_version_without_selecting_entry_credentials(self):
        from bot.services.service_subscription import service_material
        body = {"access_id": "access-12345678", "ready": True, "status": "ready", "desired_version": 2,
            "material_version": 2, "kind": "service_subscription", "subscription_url":
            "https://service.example.invalid/api/subscriptions/11111111-2222-4333-8444-555555555555/wvs1_" + "A" * 43}
        client = WaveMeshInternalApiClient(); client._request = AsyncMock(return_value=body)
        self.assertEqual(await client.get_access_material(body["access_id"]), service_material(body, body["access_id"]))
        client._request.assert_awaited_once_with("GET", "bot/accesses/access-12345678/material?material_version=2")
        for patch in ({"material_version": 3}, {"material_version": 2.0}, {"node_id": "first-entry"}, {"kind": "node_native"},
                      {"subscription_url": "https://private_canary@service.invalid/sub/private_canary"}):
            client._request = AsyncMock(return_value=body | patch)
            with self.assertRaises(InternalApiError) as caught: await client.get_access_material(body["access_id"])
            self.assertNotIn("private_canary", str(caught.exception))

    async def test_material_identity_cannot_inject_a_path_or_override_negotiation(self):
        client = WaveMeshInternalApiClient(); client._request = AsyncMock()
        for access_id in ("../other", "access?material_version=1", None):
            with self.assertRaises(InternalApiError): await client.get_access_material(access_id)
        client._request.assert_not_awaited()

    async def test_create_access_uses_stable_safe_payload(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "access_id": "access-12345678",
                "command_id": "command-12345678",
                "status": "materializing",
            }
        )

        result = await client.create_access(
            telegram_id=123456789,
            legacy_key_id=42,
            duration_days=1,
            traffic_limit_bytes=1024,
            device_limit=1,
            idempotency_key="admin-access-provision-42",
        )

        self.assertEqual(result["status"], "materializing")
        client._request.assert_awaited_once_with(
            "POST",
            "bot/accesses",
            json_body={
                "telegram_id": "123456789",
                "legacy_key_id": "42",
                "duration_days": 1,
                "traffic_limit_bytes": "1024",
                "device_limit": 1,
            },
            idempotency_key="admin-access-provision-42",
        )

    async def test_create_access_rejects_incomplete_response(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(return_value={"status": "materializing"})

        with self.assertRaises(InternalApiError):
            await client.create_access(
                telegram_id=123456789,
                legacy_key_id=42,
                duration_days=1,
                traffic_limit_bytes=0,
                device_limit=1,
            )

    async def test_get_access_material_accepts_pending_and_valid_ready_response(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            side_effect=[
                {
                    "access_id": "access-12345678",
                    "status": "materializing",
                    "ready": False,
                },
                {
                    "access_id": "access-12345678",
                    "status": "ready",
                    "ready": True,
                    "node_id": "node-1",
                    "desired_version": 2,
                    "panel_email": "wm_access_123",
                    "client_uuid": "f5ee70ce-8a27-4f15-b81e-edc8a8bd11c4",
                    "sub_id": "abcdefghijklmnop",
                    "primary_inbound_id": 9,
                    "protocol": "vless",
                    "subscription_url": "https://entry.example.invalid/sub/value",
                },
            ]
        )

        pending = await client.get_access_material("access-12345678")
        ready = await client.get_access_material("access-12345678")

        self.assertFalse(pending["ready"])
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["primary_inbound_id"], 9)
        for override in ({"subscription_url":"https://u:p@entry.invalid/sub/value"},
                         {"subscription_url":"https:///sub/value"}, {"subscription_url":123},
                         {"subscription_url":"https://entry.invalid/sub/value#fragment"},
                         {"subscription_url":"https://entry.invalid/sub/\nvalue"},
                         {"node_id":"../other"}, {"desired_version":True}, {"primary_inbound_id":True}):
            with self.subTest(override=override):
                client._request = AsyncMock(return_value=ready | override)
                with self.assertRaises(InternalApiError):
                    await client.get_access_material("access-12345678")

    async def test_get_access_material_rejects_incomplete_ready_response(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "access_id": "access-12345678",
                "status": "ready",
                "ready": True,
            }
        )

        with self.assertRaises(InternalApiError):
            await client.get_access_material("access-12345678")

    async def test_replace_access_requires_versioned_response(self):
        client = WaveMeshInternalApiClient()
        client._request = AsyncMock(
            return_value={
                "command_id": "command-12345678",
                "status": "pending",
                "desired_version": 2,
            }
        )

        result = await client.replace_access(
            access_id="access-12345678",
            idempotency_key="telegram-replace-10-2",
            expected_version=1,
        )

        self.assertEqual(result["desired_version"], 2)
        client._request.assert_awaited_once_with(
            "POST",
            "bot/accesses/access-12345678/replace",
            json_body={"expected_version": 1},
            idempotency_key="telegram-replace-10-2",
        )


if __name__ == "__main__":
    unittest.main()
