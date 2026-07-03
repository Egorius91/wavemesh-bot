import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'ensure_subscription_schema',
    'create_subscription',
    'get_subscription_by_id',
    'get_active_subscription_by_key',
    'get_due_subscriptions',
    'mark_subscription_payment_succeeded',
    'mark_subscription_payment_failed',
    'cancel_subscription_at_period_end',
    'deactivate_subscription',
    'unlink_subscription_payment_method_by_key',
    'save_order_subscription_context',
    'get_subscription_for_order',
]


def _add_column_if_missing(conn, table: str, column_name: str, column_def: str) -> None:
    existing = {row['name'] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
        logger.info("Добавлена колонка %s.%s", table, column_name)


def ensure_subscription_schema() -> None:
    """Создаёт таблицы/колонки для подписок. Идемпотентно, безопасно при каждом вызове."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                vpn_key_id INTEGER,
                tariff_id INTEGER NOT NULL,
                provider TEXT NOT NULL DEFAULT 'yookassa',
                status TEXT NOT NULL DEFAULT 'active',
                payment_method_id TEXT,
                initial_payment_id TEXT,
                last_payment_id TEXT,
                billing_period_days INTEGER NOT NULL,
                next_charge_at DATETIME NOT NULL,
                last_charge_at DATETIME,
                failed_attempts INTEGER DEFAULT 0,
                cancel_at_period_end INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                cancelled_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id),
                FOREIGN KEY (tariff_id) REFERENCES tariffs(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_due ON subscriptions(status, next_charge_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_key ON subscriptions(vpn_key_id)")

        _add_column_if_missing(conn, 'payments', 'subscription_id', 'INTEGER')
        _add_column_if_missing(conn, 'payments', 'payment_method_id', 'TEXT')
        _add_column_if_missing(conn, 'payments', 'is_recurring', 'INTEGER DEFAULT 0')
        _add_column_if_missing(conn, 'payments', 'parent_payment_id', 'TEXT')


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def create_subscription(
    *,
    user_id: int,
    tariff_id: int,
    vpn_key_id: Optional[int],
    payment_method_id: str,
    billing_period_days: int,
    initial_payment_id: Optional[str] = None,
    provider: str = 'yookassa',
) -> int:
    ensure_subscription_schema()
    next_charge_at = datetime.now() + timedelta(days=int(billing_period_days))
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO subscriptions (
                user_id, vpn_key_id, tariff_id, provider, status,
                payment_method_id, initial_payment_id, last_payment_id,
                billing_period_days, next_charge_at, last_charge_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            user_id, vpn_key_id, tariff_id, provider,
            payment_method_id, initial_payment_id, initial_payment_id,
            int(billing_period_days), next_charge_at.strftime('%Y-%m-%d %H:%M:%S'),
        ))
        subscription_id = cursor.lastrowid
        logger.info("Создана подписка ID %s для user_id=%s tariff_id=%s", subscription_id, user_id, tariff_id)
        return subscription_id


def get_subscription_by_id(subscription_id: int) -> Optional[Dict[str, Any]]:
    ensure_subscription_schema()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        return _row_to_dict(row)


def get_active_subscription_by_key(vpn_key_id: int) -> Optional[Dict[str, Any]]:
    ensure_subscription_schema()
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM subscriptions
            WHERE vpn_key_id = ? AND status IN ('active', 'payment_failed')
            ORDER BY id DESC
            LIMIT 1
        """, (vpn_key_id,)).fetchone()
        return _row_to_dict(row)


def get_due_subscriptions(limit: int = 50) -> List[Dict[str, Any]]:
    ensure_subscription_schema()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT s.*, t.name AS tariff_name, t.price_rub, t.duration_days, t.traffic_limit_gb,
                   u.telegram_id AS user_telegram_id
            FROM subscriptions s
            JOIN tariffs t ON t.id = s.tariff_id
            JOIN users u ON u.id = s.user_id
            WHERE s.status = 'active'
              AND s.cancel_at_period_end = 0
              AND s.next_charge_at <= CURRENT_TIMESTAMP
              AND s.payment_method_id IS NOT NULL
              AND s.payment_method_id != ''
            ORDER BY s.next_charge_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]


def mark_subscription_payment_succeeded(
    subscription_id: int,
    *,
    payment_id: str,
    payment_method_id: Optional[str] = None,
) -> bool:
    ensure_subscription_schema()
    sub = get_subscription_by_id(subscription_id)
    if not sub:
        return False
    next_charge_at = datetime.now() + timedelta(days=int(sub['billing_period_days']))
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE subscriptions
            SET status = 'active',
                last_payment_id = ?,
                payment_method_id = COALESCE(NULLIF(?, ''), payment_method_id),
                last_charge_at = CURRENT_TIMESTAMP,
                next_charge_at = ?,
                failed_attempts = 0
            WHERE id = ?
        """, (payment_id, payment_method_id or '', next_charge_at.strftime('%Y-%m-%d %H:%M:%S'), subscription_id))
        return cursor.rowcount > 0


def mark_subscription_payment_failed(subscription_id: int, *, payment_id: Optional[str] = None) -> bool:
    ensure_subscription_schema()
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE subscriptions
            SET status = 'payment_failed',
                last_payment_id = COALESCE(NULLIF(?, ''), last_payment_id),
                failed_attempts = COALESCE(failed_attempts, 0) + 1
            WHERE id = ?
        """, (payment_id or '', subscription_id))
        return cursor.rowcount > 0


def cancel_subscription_at_period_end(subscription_id: int) -> bool:
    ensure_subscription_schema()
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE subscriptions
            SET cancel_at_period_end = 1, cancelled_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (subscription_id,))
        return cursor.rowcount > 0


def unlink_subscription_payment_method_by_key(vpn_key_id: int, user_id: int) -> bool:
    """Removes the saved recurring payment token for a user's key without touching paid access."""
    ensure_subscription_schema()
    with get_db() as conn:
        sub = conn.execute("""
            SELECT id
            FROM subscriptions
            WHERE vpn_key_id = ?
              AND user_id = ?
              AND status IN ('active', 'payment_failed')
              AND payment_method_id IS NOT NULL
              AND payment_method_id != ''
            ORDER BY id DESC
            LIMIT 1
        """, (vpn_key_id, user_id)).fetchone()
        if not sub:
            return False

        subscription_id = int(sub['id'])
        conn.execute("""
            UPDATE subscriptions
            SET payment_method_id = NULL,
                cancel_at_period_end = 1,
                cancelled_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (subscription_id,))
        conn.execute("""
            UPDATE payments
            SET payment_method_id = NULL
            WHERE subscription_id = ?
        """, (subscription_id,))
        logger.info(
            "Payment method unlinked for subscription %s, key %s",
            subscription_id,
            vpn_key_id,
        )
        return True


def deactivate_subscription(subscription_id: int, status: str = 'cancelled') -> bool:
    ensure_subscription_schema()
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE subscriptions
            SET status = ?, cancelled_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, subscription_id))
        return cursor.rowcount > 0


def save_order_subscription_context(
    order_id: str,
    *,
    subscription_id: Optional[int] = None,
    payment_method_id: Optional[str] = None,
    is_recurring: int = 0,
    parent_payment_id: Optional[str] = None,
) -> bool:
    ensure_subscription_schema()
    fields = []
    values = []
    if subscription_id is not None:
        fields.append('subscription_id = ?')
        values.append(subscription_id)
    if payment_method_id is not None:
        fields.append('payment_method_id = ?')
        values.append(payment_method_id)
    fields.append('is_recurring = ?')
    values.append(int(is_recurring))
    if parent_payment_id is not None:
        fields.append('parent_payment_id = ?')
        values.append(parent_payment_id)
    if not fields:
        return False
    values.append(order_id)
    with get_db() as conn:
        cursor = conn.execute(f"UPDATE payments SET {', '.join(fields)} WHERE order_id = ?", values)
        return cursor.rowcount > 0


def get_subscription_for_order(order_id: str) -> Optional[Dict[str, Any]]:
    ensure_subscription_schema()
    with get_db() as conn:
        row = conn.execute("""
            SELECT s.*
            FROM payments p
            JOIN subscriptions s ON s.id = p.subscription_id
            WHERE p.order_id = ?
            LIMIT 1
        """, (order_id,)).fetchone()
        return _row_to_dict(row)
