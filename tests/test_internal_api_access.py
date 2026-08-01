import unittest
from unittest.mock import AsyncMock

from bot.services.internal_api import InternalApiError, WaveMeshInternalApiClient


class InternalApiAccessTests(unittest.IsolatedAsyncioTestCase):
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
        )

        self.assertEqual(result["desired_version"], 2)
        client._request.assert_awaited_once_with(
            "POST",
            "bot/accesses/access-12345678/replace",
            json_body={},
            idempotency_key="telegram-replace-10-2",
        )


if __name__ == "__main__":
    unittest.main()
