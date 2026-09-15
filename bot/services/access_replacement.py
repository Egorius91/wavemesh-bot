"""One confirmed dispatch, followed exclusively by original-operation readback."""
import asyncio
from datetime import datetime, timezone
import logging
import re

from database.access_replacement import ReplacementJournal
from database.admin_provisioning import JournalConflict, connection_scope
from bot.services.replacement_contract import TERMINAL_FAILURES, readback, reference

logger = logging.getLogger(__name__)
_task = None


class ReplacementWorker:
    def __init__(self, client, journal=None):
        self.client = client
        self.journal = journal or ReplacementJournal()

    async def ready_data(self, row, version):
        local = self.journal.binding(row["key_id"], row["telegram_id"], row["tenant_id"])
        allowed = {version} if row.get("phase") == "DONE" else {version, row.get("expected_version", version)}
        if (any(local[f] != row[f] for f in ("access_id", "node_id", "saas_user_id", "user_id"))
                or local["desired_version"] not in allowed):
            raise JournalConflict("REPLACEMENT_BINDING_CHANGED")
        dashboard = await self.client.get_telegram_dashboard(row["telegram_id"])
        user = dashboard.get("user")
        matches = [a for a in dashboard.get("accesses", []) if isinstance(a, dict) and a.get("access_id") == row["access_id"]]
        if (not isinstance(user, dict) or user.get("tenant_id") != row["tenant_id"] or user.get("user_id") != row["saas_user_id"]
                or len(matches) != 1 or matches[0].get("telegram_id") != str(row["telegram_id"])
                or matches[0].get("legacy_key_id") != str(row["key_id"])):
            raise JournalConflict("REPLACEMENT_BINDING_CHANGED")
        access = matches[0]
        if (access.get("authority") != "managed" or access.get("status") != "ready" or access.get("enabled") is not True
                or type(access.get("desired_version")) is not int or access["desired_version"] != version):
            raise JournalConflict("REPLACEMENT_NOT_READY")
        material = await self.client.get_access_material(row["access_id"])
        if (material.get("ready") is not True or material.get("access_id") != row["access_id"]
                or material.get("node_id") != row["node_id"] or type(material.get("desired_version")) is not int
                or material["desired_version"] != version or material.get("subscription_url") != access.get("subscription_url")):
            raise JournalConflict("REPLACEMENT_NOT_READY")
        expiry = datetime.fromisoformat(access["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise JournalConflict("REPLACEMENT_NOT_READY")
        for value in (access.get("traffic_limit_bytes"), access.get("traffic_used_bytes") or "0"):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,19}", value) or int(value) > 2**63-1:
                raise JournalConflict("REPLACEMENT_NOT_READY")
        return access, material

    async def prepare(self, callback_key, key_id, telegram_id, *, previous_id=None):
        scope = connection_scope(self.client)
        previous = self.journal.for_callback(callback_key, telegram_id, scope)
        if previous:
            return previous
        binding = self.journal.binding(key_id, telegram_id, self.client.tenant_id)
        active = self.journal.attach_active(callback_key, binding, scope)
        if active:
            return active
        await self.ready_data(binding, binding["desired_version"])
        return self.journal.prepare(callback_key=callback_key, scope=scope, binding=binding,
                                    expected_version=binding["desired_version"], previous_id=previous_id)

    async def reconcile(self, operation_id, *, explicit=False):
        row = self.journal.claim(operation_id, explicit=explicit)
        if not row:
            return self.journal.get(operation_id)
        try:
            if row["scope"] != connection_scope(self.client) or row["tenant_id"] != self.client.tenant_id:
                raise JournalConflict("REPLACEMENT_SCOPE_CHANGED")
            binding = self.journal.binding(row["key_id"], row["telegram_id"], row["tenant_id"])
            if any(binding[f] != row[f] for f in ("access_id", "node_id", "saas_user_id", "user_id")):
                raise JournalConflict("REPLACEMENT_BINDING_CHANGED")
            if row["phase"] == "QUEUED":
                await self.ready_data(row, row["expected_version"])
                self.journal.dispatch(row)
                response = None
                try:
                    response = reference(await self.client.replace_access(
                        access_id=row["access_id"], idempotency_key=row["request_key"],
                        expected_version=row["expected_version"]), row["expected_version"])
                except Exception:
                    pass  # Persisted dispatch is irreversible; read the same operation after any HTTP outcome.
                if response is not None:
                    self.journal.note_command(row, response["command_id"])
            result = readback(await self.client.get_access_replacement(row["access_id"], row["request_key"], row["expected_version"]),
                              row["access_id"], row["expected_version"])
            self.journal.note_request(row, result["request_id"])
            if result["submission"] != "OBSERVED":
                self.journal.release(row, status="TIMEOUT" if result["status"] != "PENDING" else "PENDING")
                return self.journal.get(operation_id)
            self.journal.observe(row, result)
            if result["status"] == "FAILED" and result["command_status"] in TERMINAL_FAILURES:
                self.journal.release(row, status="FAILED", terminal=True)
            elif result["status"] == "SUPERSEDED" and result["command_status"] == "SUCCEEDED":
                self.journal.release(row, status="SUPERSEDED", terminal=True)
            elif result["status"] == "READY":
                access, material = await self.ready_data(row, row["expected_version"]+1)
                self.journal.finalize(row, access, material)
            else:
                self.journal.release(row, status="TIMEOUT" if self.journal.clock()-row["created_at"] > 900 else "PENDING")
        except JournalConflict as error:
            if str(error) != "LEASE_LOST":
                try:
                    stale = row["phase"] == "QUEUED" and str(error) in {"REPLACEMENT_NOT_READY", "REPLACEMENT_VERSION_CHANGED"}
                    self.journal.release(row, status="STALE" if stale else "MANUAL_REVIEW", terminal=stale)
                except JournalConflict:
                    pass
        except Exception:
            try:
                self.journal.release(row, status="TIMEOUT")
            except Exception:
                logger.warning("Replacement journal unavailable")
        return self.journal.get(operation_id)

    async def run_once(self):
        for operation_id in self.journal.due():
            await self.reconcile(operation_id)


def start_access_replacement_worker():
    global _task
    if _task is not None and not _task.done():
        return
    from bot.services.internal_api import internal_api_client
    from bot.services.runtime_mode import saas_client_mode_enabled
    if not saas_client_mode_enabled() or not internal_api_client.enabled:
        return

    async def run():
        worker = ReplacementWorker(internal_api_client)
        while True:
            try:
                await worker.run_once()
            except Exception:
                logger.warning("Replacement worker unavailable")
            await asyncio.sleep(5)

    _task = asyncio.create_task(run(), name="access-replacement")


async def stop_access_replacement_worker():
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
