from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from database import db_keys_shadow as hooks
from database import db_keys_shadow_outbox as durable_delete


@dataclass(frozen=True)
class DummySnapshot:
    legacy_key_id: int
    enabled: bool
    configured: bool
    subscription_ready: bool


class DbKeysShadowHookTests(unittest.TestCase):
    def test_requests_exports_shadow_wrappers(self) -> None:
        from database import requests

        self.assertIs(requests.extend_vpn_key, hooks.extend_vpn_key)
        self.assertIs(requests.bulk_update_traffic, hooks.bulk_update_traffic)
        self.assertIs(requests.delete_vpn_key, durable_delete.delete_vpn_key)

    def test_extend_schedules_only_after_success(self) -> None:
        with (
            patch.object(hooks._db, "extend_vpn_key", return_value=True),
            patch.object(hooks, "_schedule_key") as schedule,
        ):
            self.assertTrue(hooks.extend_vpn_key(7, 30))
            schedule.assert_called_once_with(7, reason="extend")

        with (
            patch.object(hooks._db, "extend_vpn_key", return_value=False),
            patch.object(hooks, "_schedule_key") as schedule,
        ):
            self.assertFalse(hooks.extend_vpn_key(7, 30))
            schedule.assert_not_called()

    def test_create_initial_schedules_new_key(self) -> None:
        with (
            patch.object(hooks._db, "create_initial_vpn_key", return_value=42),
            patch.object(hooks, "_schedule_key") as schedule,
        ):
            key_id = hooks.create_initial_vpn_key(11, 3, 30, 0)

        self.assertEqual(key_id, 42)
        schedule.assert_called_once_with(42, reason="create_initial")

    def test_bulk_traffic_schedules_each_unique_key_once(self) -> None:
        updates = [(100, 3), (200, 3), (300, 4)]
        with (
            patch.object(hooks._db, "bulk_update_traffic") as update,
            patch.object(hooks, "_schedule_key") as schedule,
        ):
            hooks.bulk_update_traffic(updates)

        update.assert_called_once_with(updates)
        self.assertEqual(
            schedule.call_args_list,
            [
                unittest.mock.call(3, reason="traffic_bulk"),
                unittest.mock.call(4, reason="traffic_bulk"),
            ],
        )

    def test_legacy_delete_wrapper_still_builds_tombstone(self) -> None:
        snapshot = DummySnapshot(
            legacy_key_id=9,
            enabled=True,
            configured=True,
            subscription_ready=True,
        )
        with (
            patch.object(hooks, "_capture_snapshot", return_value=snapshot),
            patch.object(hooks._db, "delete_vpn_key", return_value=True),
            patch.object(hooks, "_schedule_snapshot") as schedule,
        ):
            self.assertTrue(hooks.delete_vpn_key(9))

        tombstone = schedule.call_args.args[0]
        self.assertEqual(tombstone.legacy_key_id, 9)
        self.assertFalse(tombstone.enabled)
        self.assertFalse(tombstone.configured)
        self.assertFalse(tombstone.subscription_ready)

    def test_tariff_schedules_only_after_success(self) -> None:
        with (
            patch.object(
                hooks._db,
                "update_vpn_key_tariff_and_traffic_limit",
                return_value=True,
            ),
            patch.object(hooks, "_schedule_key") as schedule,
        ):
            self.assertTrue(
                hooks.update_vpn_key_tariff_and_traffic_limit(5, 8, 1024)
            )

        schedule.assert_called_once_with(5, reason="tariff")

    def test_referral_extension_schedules_selected_key(self) -> None:
        with (
            patch.object(hooks, "_first_active_key_id", return_value=6),
            patch.object(
                hooks._db,
                "add_days_to_first_active_key",
                return_value=True,
            ),
            patch.object(hooks, "_schedule_key") as schedule,
        ):
            self.assertTrue(hooks.add_days_to_first_active_key(99, 7))
        schedule.assert_called_once_with(6, reason="referral_extend")


if __name__ == "__main__":
    unittest.main()
