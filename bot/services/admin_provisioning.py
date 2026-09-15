"""Restartable SaaS adapter; dispatch is persisted before each external write."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging

from database.admin_provisioning import Journal, JournalConflict, connection_scope

logger = logging.getLogger(__name__)
_task = None


class ProvisioningWorker:
    def __init__(self, client, journal=None):
        self.client = client
        self.journal = journal or Journal()

    async def dashboard(self, row):
        result = await self.client.get_telegram_dashboard(row["telegram_id"])
        user = result.get("user")
        if (not isinstance(user, dict) or user.get("tenant_id") != self.client.tenant_id
                or not isinstance(user.get("user_id"), str) or not user["user_id"]
                or (row.get("saas_user_id") and user["user_id"] != row["saas_user_id"])):
            raise JournalConflict("SAAS_OWNER_CHANGED")
        return result

    @staticmethod
    def access(dashboard, row):
        matches = [a for a in dashboard.get("accesses", []) if isinstance(a, dict)
                   and a.get("legacy_key_id") == str(row["key_id"])]
        if len(matches) != 1 or matches[0].get("telegram_id") != str(row["telegram_id"]):
            raise JournalConflict("SAAS_ACCESS_BINDING_MISSING")
        return matches[0]

    async def reconcile(self, operation_id, *, explicit=False):
        row = self.journal.claim(operation_id, explicit=explicit)
        if not row:
            return self.journal.get(operation_id)
        try:
            if row["scope"] != connection_scope(self.client):
                raise JournalConflict("SERVICE_CREDENTIAL_CHANGED")
            if not self.journal.owner_exists(row):
                raise JournalConflict("LOCAL_OWNER_REMOVED")
            if row["phase"] == "PREPARED":
                self.journal.advance(row, "USER_DISPATCHED")
                await self.client.upsert_telegram_user(**json.loads(row["user_payload"]),
                                                      idempotency_key=row["request_key"]+"-user")
            if row["phase"] == "USER_DISPATCHED":
                dashboard = await self.dashboard(row)
                self.journal.advance(row, "USER_SYNCED", saas_user_id=dashboard["user"]["user_id"])
            if row["phase"] == "USER_SYNCED":
                self.journal.advance(row, "SHADOW_DISPATCHED")
                await self.client.sync_access_shadow(payload=json.loads(row["shadow_payload"]),
                                                     idempotency_key=row["request_key"]+"-shadow")
            if row["phase"] == "SHADOW_DISPATCHED":
                access = self.access(await self.dashboard(row), row)
                shadow = json.loads(row["shadow_payload"])
                if (access.get("authority") != "legacy_snapshot"
                        or datetime.fromisoformat(access["expires_at"].replace("Z", "+00:00")) != datetime.fromisoformat(shadow["expires_at"])
                        or str(access.get("traffic_limit_bytes")) != shadow["traffic_limit_bytes"]
                        or access.get("device_limit") != shadow["device_limit"]):
                    raise JournalConflict("SHADOW_BINDING_CHANGED")
                self.journal.advance(row, "SUBMIT_READY", access_id=access["access_id"])
            if row["phase"] == "SUBMIT_READY":
                # Never return to this phase after an intent was persisted, even if
                # the HTTP request may not have left the process before a crash.
                self.journal.advance(row, "SUBMIT_DISPATCHED")
                await self.client.create_access(**json.loads(row["payload"]), idempotency_key=row["request_key"])
            if row["phase"] in {"SUBMIT_DISPATCHED", "OBSERVED"}:
                result = await self.client.get_access_provisioning(row["request_key"])
                if result["submission"] != "OBSERVED":
                    pending = result["status"] == "PENDING" and self.journal.clock() - row["created_at"] < 900
                    status = "PENDING" if pending else ("TIMEOUT" if result["status"] in {"TIMEOUT", "PENDING"} else "MANUAL_REVIEW")
                    self.journal.release(row, status=status,
                                         error="SUBMISSION_UNCONFIRMED")
                    return self.journal.get(operation_id)
                if result["legacy_key_id"] != str(row["key_id"]):
                    raise JournalConflict("SAAS_ACCESS_BINDING_CHANGED")
                self.journal.advance(row, "OBSERVED", access_id=result["access_id"], command_id=result["command_id"],
                                     node_id=result["assigned_entry_node_id"], expires_at=result["expires_at"])
                if result["status"].upper() in {"FAILED", "REVOKED", "SUSPENDED", "EXPIRED"}:
                    self.journal.release(row, status="FAILED", error="SAAS_PROVISIONING_TERMINAL")
                    return self.journal.get(operation_id)
                access = self.access(await self.dashboard(row), row)
                if access["access_id"] != row["access_id"] or access.get("authority") != "managed":
                    raise JournalConflict("SAAS_ACCESS_BINDING_CHANGED")
                material = await self.client.get_access_material(row["access_id"])
                if material["ready"]:
                    if (access.get("status") != "ready" or not access.get("enabled")
                            or access.get("desired_version") != material["desired_version"]
                            or access.get("subscription_url") != material["subscription_url"]
                            or datetime.fromisoformat(access["expires_at"].replace("Z", "+00:00")) != datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))):
                        raise JournalConflict("MATERIAL_BINDING_CHANGED")
                    self.journal.finalize(row, material)
                    return self.journal.get(operation_id)
            status = "TIMEOUT" if self.journal.clock() - row["created_at"] >= 900 else "PENDING"
            self.journal.release(row, status=status, error="AWAITING_SAAS" if status == "TIMEOUT" else None)
        except JournalConflict as error:
            # Exception text is module-owned bounded code, never a remote message.
            if str(error) not in {"LEASE_LOST", "PHASE_CHANGED"}:
                try:
                    self.journal.release(row, status="MANUAL_REVIEW", error=str(error))
                except JournalConflict:
                    pass
        except Exception:
            # Includes transport/response/DB errors. No raw message or material is
            # logged or persisted. Leave dispatch phase intact for readback only.
            try:
                status = "TIMEOUT" if self.journal.clock() - row["created_at"] >= 900 else "PENDING"
                self.journal.release(row, status=status, error="RECONCILIATION_UNAVAILABLE")
            except Exception:
                logger.warning("Admin provisioning journal unavailable")
        return self.journal.get(operation_id)

    async def run_once(self):
        for operation_id in self.journal.due():
            await self.reconcile(operation_id)


def start_admin_provisioning_worker():
    global _task
    if _task is not None and not _task.done():
        return
    from bot.services.internal_api import internal_api_client
    from bot.services.runtime_mode import saas_client_mode_enabled
    if not saas_client_mode_enabled() or not internal_api_client.enabled:
        return

    async def run():
        worker = ProvisioningWorker(internal_api_client)
        while True:
            try:
                await worker.run_once()
            except Exception:
                logger.warning("Admin provisioning worker unavailable")
            await asyncio.sleep(5)

    _task = asyncio.create_task(run(), name="admin-provisioning")


async def stop_admin_provisioning_worker():
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
