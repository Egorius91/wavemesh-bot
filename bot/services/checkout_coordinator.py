"""Restart-safe initial recurring checkout coordinator for private Telegram UI.

No scheduler, TTL retry, runtime write or business-state authority lives here.
"""
import json

from bot.services.checkout_contract import TERMINAL, identity, tariff
from bot.services.internal_api import InternalApiError
from database.admin_provisioning import JournalConflict, connection_scope
from database.checkout_intents import CheckoutJournal


class CheckoutCoordinator:
    def __init__(self, client, journal=None):
        self.client = client
        self.journal = journal or CheckoutJournal()

    async def context(self, actor):
        if type(actor) is not int or actor <= 0:
            raise JournalConflict("INVALID_CHECKOUT_ACTOR")
        dashboard = await self.client.get_telegram_dashboard(actor)
        user = dashboard.get("user") if isinstance(dashboard, dict) else None
        owner = identity(user.get("user_id") if isinstance(user, dict) else None)
        return owner, connection_scope(self.client), dashboard

    async def prepare(self, actor, callback_key, tariff_id, *, access_id=None, previous=None):
        owner, scope, dashboard = await self.context(actor)
        prior = self.journal.for_callback(callback_key, actor, scope, owner)
        if prior:
            return {"operation": prior, "current": None}
        active = self.journal.active(actor, scope, owner)
        if active:
            # Attach the message to the original operation, including changed selection.
            row = self.journal.attach(callback_key, active["id"], actor, scope, owner)
            return {"operation": row, "current": None}
        current = await self.client.get_current_checkout(owner)
        if current:
            if previous != current["order_id"] or current["payment_status"] not in TERMINAL:
                return {"operation": None, "current": current}
        elif previous is not None:
            raise JournalConflict("CHECKOUT_PREDECESSOR_MISSING")
        self._target(dashboard, access_id)
        catalog = await self.client.list_tariffs()
        matches = [item for item in catalog if isinstance(item, dict) and item.get("tariff_id") == tariff_id]
        if len(matches) != 1:
            raise JournalConflict("CHECKOUT_TARIFF_UNAVAILABLE")
        selected = tariff(matches[0])
        row = self.journal.prepare(callback_key=callback_key, actor=actor, scope=scope, owner=owner, tariff=selected,
                                   access_id=access_id, previous=previous)
        return {"operation": row, "current": None}

    @staticmethod
    def _target(dashboard, access_id):
        if access_id is None:
            return
        identity(access_id)
        accesses = dashboard.get("accesses")
        matches = [a for a in accesses if isinstance(a, dict) and a.get("access_id") == access_id] if isinstance(accesses, list) else []
        if len(matches) != 1:
            raise JournalConflict("CHECKOUT_TARGET_CHANGED")

    async def confirm(self, actor, operation_id):
        owner, scope, dashboard = await self.context(actor)
        row = self.journal.owned(operation_id, actor, scope, owner)
        if row["phase"] != "PREPARED":
            return await self.recover(actor, operation_id)
        payload = json.loads(row["payload"])
        self._target(dashboard, payload.get("access_id"))
        current = await self.client.get_current_checkout(owner)
        previous = payload.get("expected_previous_order_id")
        if (previous is None and current is not None or previous is not None and
                (current is None or current["order_id"] != previous or current["payment_status"] not in TERMINAL)):
            # This operation is still provably local; show current, never silently rebase.
            return {"operation": row, "current": current, "original": None, "unresolved": True}
        # Commit before the only network POST. A failed/ambiguous commit cannot dispatch.
        if self.journal.claim_confirmed(operation_id, actor, scope, owner):
            try:
                await self.client.create_order(**payload, idempotency_key=row["request_key"])
            except InternalApiError as error:
                if error.status == 409 and error.code == "CHECKOUT_ADMISSION_REQUIRED":
                    self.journal.rejected(operation_id, actor, scope, owner)
                # Every other response, including invalid/lost success, stays unknown.
            # A cancellation or unexpected exception leaves DISPATCHED for GET recovery.
        return await self.recover(actor, operation_id)

    async def cancel(self, actor, operation_id):
        owner, scope, _ = await self.context(actor)
        self.journal.cancel(operation_id, actor, scope, owner)
        return self.journal.owned(operation_id, actor, scope, owner)

    async def recover(self, actor, operation_id=None):
        owner, scope, _ = await self.context(actor)
        row = (self.journal.owned(operation_id, actor, scope, owner) if operation_id
               else self.journal.active(actor, scope, owner))
        original = None
        missing = False
        if row and row["phase"] not in {"PREPARED", "CANCELLED"}:
            try:
                original = await self.client.get_checkout(owner, row["request_key"])
            except InternalApiError as error:
                if error.status != 404 or error.code != "CHECKOUT_NOT_FOUND":
                    raise
                missing = True
        current = await self.client.get_current_checkout(owner)
        if original and not current:
            raise JournalConflict("CHECKOUT_CURRENT_MISSING")
        if row:
            if connection_scope(self.client) != scope:
                raise JournalConflict("CHECKOUT_OWNER_CHANGED")
            self.journal.observe(row["id"], actor, scope, owner, original)
            if missing and await self.client.get_checkout_rejection(owner, row["request_key"]):
                if connection_scope(self.client) != scope:
                    raise JournalConflict("CHECKOUT_OWNER_CHANGED")
                self.journal.prove_rejected(row["id"], actor, scope, owner)
            row = self.journal.owned(row["id"], actor, scope, owner)
        unresolved = bool(row and row["phase"] not in {"TERMINAL", "CANCELLED", "PREPARED"}
                          and (not original or current["order_id"] != original["order_id"]))
        return {"operation": row, "original": original, "current": current, "unresolved": unresolved}
