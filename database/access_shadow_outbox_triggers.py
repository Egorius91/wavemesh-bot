"""Transactional SQLite triggers for universal access-shadow outbox capture.

The triggers persist a sanitized snapshot in the same transaction as every
``vpn_keys`` INSERT or UPDATE. DELETE remains handled by the dedicated
transactional tombstone wrapper added in PR #23.
"""

from __future__ import annotations

from typing import Any

from bot.services.access_shadow_outbox import ensure_access_shadow_outbox_schema
from database.connection import get_db

_TRIGGER_SQL = r"""
CREATE TRIGGER IF NOT EXISTS trg_access_shadow_outbox_vpn_keys_insert
AFTER INSERT ON vpn_keys
BEGIN
    INSERT INTO access_shadow_outbox
        (event_key, legacy_key_id, reason, payload_json)
    SELECT
        'insert:' || NEW.id || ':' || lower(hex(randomblob(16))),
        NEW.id,
        'mutation_insert',
        json_object(
            'telegram_id', u.telegram_id,
            'legacy_key_id', NEW.id,
            'username', u.username,
            'display_name', trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, '')),
            'is_bot_blocked', CASE WHEN coalesce(u.is_bot_blocked, 0) <> 0 THEN 1 ELSE 0 END,
            'expires_at', CASE
                WHEN NEW.expires_at IS NULL OR NEW.expires_at = '' THEN NULL
                ELSE replace(NEW.expires_at, ' ', 'T') || '.000Z'
            END,
            'enabled', CASE
                WHEN (NEW.expires_at IS NULL OR NEW.expires_at > CURRENT_TIMESTAMP)
                 AND (coalesce(NEW.traffic_limit, 0) <= 0
                      OR coalesce(NEW.traffic_used, 0) < coalesce(NEW.traffic_limit, 0))
                THEN 1 ELSE 0
            END,
            'configured', CASE
                WHEN NEW.server_id IS NOT NULL
                 AND coalesce(NEW.client_uuid, '') <> ''
                 AND coalesce(NEW.panel_email, '') <> ''
                THEN 1 ELSE 0
            END,
            'subscription_ready', CASE WHEN coalesce(NEW.sub_id, '') <> '' THEN 1 ELSE 0 END,
            'device_limit', CASE
                WHEN coalesce(t.max_ips, 0) BETWEEN 1 AND 100 THEN t.max_ips ELSE 1
            END,
            'traffic_limit_bytes', cast(max(0, coalesce(NEW.traffic_limit, 0)) AS TEXT),
            'traffic_used_bytes', cast(max(0, coalesce(NEW.traffic_used, 0)) AS TEXT)
        )
    FROM users u
    LEFT JOIN tariffs t ON t.id = NEW.tariff_id
    WHERE u.id = NEW.user_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_access_shadow_outbox_vpn_keys_update
AFTER UPDATE ON vpn_keys
WHEN
    OLD.user_id IS NOT NEW.user_id OR
    OLD.server_id IS NOT NEW.server_id OR
    OLD.tariff_id IS NOT NEW.tariff_id OR
    OLD.panel_email IS NOT NEW.panel_email OR
    OLD.client_uuid IS NOT NEW.client_uuid OR
    OLD.sub_id IS NOT NEW.sub_id OR
    OLD.expires_at IS NOT NEW.expires_at OR
    OLD.traffic_limit IS NOT NEW.traffic_limit OR
    OLD.traffic_used IS NOT NEW.traffic_used
BEGIN
    INSERT INTO access_shadow_outbox
        (event_key, legacy_key_id, reason, payload_json)
    SELECT
        'update:' || NEW.id || ':' || lower(hex(randomblob(16))),
        NEW.id,
        'mutation_update',
        json_object(
            'telegram_id', u.telegram_id,
            'legacy_key_id', NEW.id,
            'username', u.username,
            'display_name', trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, '')),
            'is_bot_blocked', CASE WHEN coalesce(u.is_bot_blocked, 0) <> 0 THEN 1 ELSE 0 END,
            'expires_at', CASE
                WHEN NEW.expires_at IS NULL OR NEW.expires_at = '' THEN NULL
                ELSE replace(NEW.expires_at, ' ', 'T') || '.000Z'
            END,
            'enabled', CASE
                WHEN (NEW.expires_at IS NULL OR NEW.expires_at > CURRENT_TIMESTAMP)
                 AND (coalesce(NEW.traffic_limit, 0) <= 0
                      OR coalesce(NEW.traffic_used, 0) < coalesce(NEW.traffic_limit, 0))
                THEN 1 ELSE 0
            END,
            'configured', CASE
                WHEN NEW.server_id IS NOT NULL
                 AND coalesce(NEW.client_uuid, '') <> ''
                 AND coalesce(NEW.panel_email, '') <> ''
                THEN 1 ELSE 0
            END,
            'subscription_ready', CASE WHEN coalesce(NEW.sub_id, '') <> '' THEN 1 ELSE 0 END,
            'device_limit', CASE
                WHEN coalesce(t.max_ips, 0) BETWEEN 1 AND 100 THEN t.max_ips ELSE 1
            END,
            'traffic_limit_bytes', cast(max(0, coalesce(NEW.traffic_limit, 0)) AS TEXT),
            'traffic_used_bytes', cast(max(0, coalesce(NEW.traffic_used, 0)) AS TEXT)
        )
    FROM users u
    LEFT JOIN tariffs t ON t.id = NEW.tariff_id
    WHERE u.id = NEW.user_id;
END;
"""


def ensure_access_shadow_outbox_triggers(conn: Any | None = None) -> None:
    """Create the outbox table and universal mutation triggers idempotently."""
    if conn is not None:
        ensure_access_shadow_outbox_schema(conn)
        conn.executescript(_TRIGGER_SQL)
        return
    with get_db() as owned_conn:
        ensure_access_shadow_outbox_schema(owned_conn)
        owned_conn.executescript(_TRIGGER_SQL)
