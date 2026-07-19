import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .connection import get_db

logger = logging.getLogger(__name__)

CHARGE_LEAD_MINUTES = 15
GRACE_PERIOD_HOURS = 24
PENDING_POLL_SECONDS = 300
MAX_FAILED_ATTEMPTS = 4
RETRY_OFFSETS_HOURS = (1, 6, 24)
RETRY_MIN_DELAYS_HOURS = (1, 5, 18)

__all__ = [
    'ensure_subscription_schema',
    'create_subscription',
    'get_subscription_by_id',
    'get_active_subscription_by_key',
    'get_due_subscriptions',
    'get_open_recurring_order',
    'reschedule_subscription_check',
    'mark_subscription_transient_error',
    'record_subscription_payment_failure',
    'finalize_recurring_payment',
    'mark_subscription_payment_succeeded',
    'mark_subscription_payment_failed',
    'cancel_subscription_at_period_end',
    'deactivate_subscription',
    'unlink_subscription_payment_method_by_key',
    'save_order_subscription_context',
    'get_subscription_for_order',
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _format_datetime(value: Any) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        raise ValueError(f'Некорректная дата: {value!r}')
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _add_column_if_missing(conn, table: str, column_name: str, column_def: str) -> bool:
    existing = {row['name'] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column_name in existing:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
    logger.info("Добавлена колонка %s.%s", table, column_name)
    return True


def ensure_subscription_schema() -> None:
    """Creates and upgrades the recurring-subscription schema idempotently."""
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
                period_end_at DATETIME,
                grace_until DATETIME,
                next_charge_at DATETIME NOT NULL,
                last_charge_at DATETIME,
                failed_attempts INTEGER DEFAULT 0,
                last_failure_reason TEXT,
                cancel_at_period_end INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                cancelled_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (vpn_key_id) REFERENCES vpn_keys(id),
                FOREIGN KEY (tariff_id) REFERENCES tariffs(id)
            )
        """)
        added_period_end = _add_column_if_missing(conn, 'subscriptions', 'period_end_at', 'DATETIME')
        _add_column_if_missing(conn, 'subscriptions', 'grace_until', 'DATETIME')
        _add_column_if_missing(conn, 'subscriptions', 'last_failure_reason', 'TEXT')

        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_due ON subscriptions(status, next_charge_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_key ON subscriptions(vpn_key_id)")

        _add_column_if_missing(conn, 'payments', 'subscription_id', 'INTEGER')
        _add_column_if_missing(conn, 'payments', 'payment_method_id', 'TEXT')
        _add_column_if_missing(conn, 'payments', 'is_recurring', 'INTEGER DEFAULT 0')
        _add_column_if_missing(conn, 'payments', 'parent_payment_id', 'TEXT')

        # Upgrade subscriptions created by the first recurring-billing version.
        # Missing anchors are always repaired so an interrupted previous startup
        # cannot leave a partially upgraded row.
        conn.execute("""
            UPDATE subscriptions
            SET period_end_at = COALESCE(
                (SELECT vk.expires_at FROM vpn_keys vk WHERE vk.id = subscriptions.vpn_key_id),
                datetime(next_charge_at, '+' || ? || ' minutes')
            )
            WHERE period_end_at IS NULL
        """, (CHARGE_LEAD_MINUTES,))
        conn.execute("""
            UPDATE subscriptions
            SET grace_until = datetime(period_end_at, '+' || ? || ' hours')
            WHERE period_end_at IS NOT NULL
              AND grace_until IS NULL
        """, (GRACE_PERIOD_HOURS,))
        if added_period_end:
            conn.execute("""
                UPDATE subscriptions
                SET next_charge_at = datetime(period_end_at, '-' || ? || ' minutes')
                WHERE status = 'active'
                  AND COALESCE(failed_attempts, 0) = 0
                  AND period_end_at IS NOT NULL
            """, (CHARGE_LEAD_MINUTES,))


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _period_end_for_subscription(conn, subscription: Dict[str, Any], now: datetime) -> datetime:
    period_end = _parse_datetime(subscription.get('period_end_at'))
    if period_end is not None:
        return period_end

    key_id = subscription.get('vpn_key_id')
    if key_id:
        row = conn.execute("SELECT expires_at FROM vpn_keys WHERE id = ?", (key_id,)).fetchone()
        if row:
            key_expiry = _parse_datetime(row['expires_at'])
            if key_expiry is not None:
                return key_expiry

    next_charge = _parse_datetime(subscription.get('next_charge_at'))
    if next_charge is not None:
        return next_charge + timedelta(minutes=CHARGE_LEAD_MINUTES)

    return now + timedelta(days=int(subscription.get('billing_period_days') or 30))


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
    now = _utc_now()
    with get_db() as conn:
        period_end = None
        if vpn_key_id:
            row = conn.execute("SELECT expires_at FROM vpn_keys WHERE id = ?", (vpn_key_id,)).fetchone()
            period_end = _parse_datetime(row['expires_at']) if row else None
        if period_end is None:
            period_end = now + timedelta(days=int(billing_period_days))
        next_charge_at = period_end - timedelta(minutes=CHARGE_LEAD_MINUTES)
        grace_until = period_end + timedelta(hours=GRACE_PERIOD_HOURS)

        cursor = conn.execute("""
            INSERT INTO subscriptions (
                user_id, vpn_key_id, tariff_id, provider, status,
                payment_method_id, initial_payment_id, last_payment_id,
                billing_period_days, period_end_at, grace_until,
                next_charge_at, last_charge_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            user_id, vpn_key_id, tariff_id, provider,
            payment_method_id, initial_payment_id, initial_payment_id,
            int(billing_period_days), _format_datetime(period_end),
            _format_datetime(grace_until), _format_datetime(next_charge_at),
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
            WHERE s.status IN ('active', 'payment_failed')
              AND s.cancel_at_period_end = 0
              AND s.next_charge_at <= CURRENT_TIMESTAMP
              AND s.payment_method_id IS NOT NULL
              AND s.payment_method_id != ''
            ORDER BY s.next_charge_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]


def get_open_recurring_order(subscription_id: int) -> Optional[Dict[str, Any]]:
    ensure_subscription_schema()
    with get_db() as conn:
        row = conn.execute("""
            SELECT *
            FROM payments
            WHERE subscription_id = ?
              AND is_recurring = 1
              AND payment_type = 'yookassa_recurring'
              AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
        """, (subscription_id,)).fetchone()
        return _row_to_dict(row)


def reschedule_subscription_check(subscription_id: int, *, delay_seconds: int = PENDING_POLL_SECONDS) -> bool:
    ensure_subscription_schema()
    next_check = _utc_now() + timedelta(seconds=max(1, int(delay_seconds)))
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET next_charge_at = ? WHERE id = ?",
            (_format_datetime(next_check), subscription_id),
        )
        return cursor.rowcount > 0


def mark_subscription_transient_error(subscription_id: int, reason: str = '') -> bool:
    ensure_subscription_schema()
    next_check = _utc_now() + timedelta(seconds=PENDING_POLL_SECONDS)
    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE subscriptions
            SET next_charge_at = ?,
                last_failure_reason = NULLIF(?, '')
            WHERE id = ?
              AND status IN ('active', 'payment_failed')
        """, (_format_datetime(next_check), str(reason or '')[:500], subscription_id))
        return cursor.rowcount > 0


def record_subscription_payment_failure(
    subscription_id: int,
    *,
    payment_id: Optional[str] = None,
    reason: str = '',
) -> Optional[Dict[str, Any]]:
    """Records one definitive charge failure and returns retry/grace details."""
    ensure_subscription_schema()
    now = _utc_now()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        if not row:
            return None
        sub = dict(row)
        period_end = _period_end_for_subscription(conn, sub, now)
        grace_until = period_end + timedelta(hours=GRACE_PERIOD_HOURS)
        attempts = int(sub.get('failed_attempts') or 0) + 1
        final = attempts >= MAX_FAILED_ATTEMPTS

        if final:
            status = 'expired'
            next_charge = grace_until
            cancel_at_period_end = 1
            cancelled_at = _format_datetime(now)
        else:
            offset_index = attempts - 1
            planned = period_end + timedelta(hours=RETRY_OFFSETS_HOURS[offset_index])
            minimum = now + timedelta(hours=RETRY_MIN_DELAYS_HOURS[offset_index])
            next_charge = max(planned, minimum)
            status = 'payment_failed'
            cancel_at_period_end = 0
            cancelled_at = None

        conn.execute("""
            UPDATE subscriptions
            SET status = ?,
                last_payment_id = COALESCE(NULLIF(?, ''), last_payment_id),
                failed_attempts = ?,
                period_end_at = ?,
                grace_until = ?,
                next_charge_at = ?,
                last_failure_reason = NULLIF(?, ''),
                cancel_at_period_end = ?,
                cancelled_at = ?
            WHERE id = ?
        """, (
            status, payment_id or '', attempts,
            _format_datetime(period_end), _format_datetime(grace_until),
            _format_datetime(next_charge), str(reason or '')[:500],
            cancel_at_period_end, cancelled_at, subscription_id,
        ))
        return {
            'subscription_id': subscription_id,
            'failed_attempts': attempts,
            'final': final,
            'status': status,
            'period_end_at': _format_datetime(period_end),
            'grace_until': _format_datetime(grace_until),
            'next_charge_at': _format_datetime(next_charge),
        }


def finalize_recurring_payment(
    order_id: str,
    subscription_id: int,
    *,
    payment_id: str,
    payment_method_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Atomically marks the order paid and advances the paid subscription period."""
    ensure_subscription_schema()
    now = _utc_now()
    with get_db() as conn:
        payment = conn.execute(
            "SELECT id, status FROM payments WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        sub_row = conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?",
            (subscription_id,),
        ).fetchone()
        if not payment or not sub_row:
            return None

        sub = dict(sub_row)
        processed_now = payment['status'] != 'paid'
        if payment['status'] not in ('pending', 'paid'):
            return None

        if processed_now:
            old_period_end = _period_end_for_subscription(conn, sub, now)
            new_period_end = max(old_period_end, now) + timedelta(
                days=int(sub.get('billing_period_days') or 30)
            )
            next_charge = new_period_end - timedelta(minutes=CHARGE_LEAD_MINUTES)
            grace_until = new_period_end + timedelta(hours=GRACE_PERIOD_HOURS)

            conn.execute("""
                UPDATE payments
                SET status = 'paid',
                    paid_at = CURRENT_TIMESTAMP,
                    yookassa_payment_id = COALESCE(NULLIF(?, ''), yookassa_payment_id),
                    payment_method_id = COALESCE(NULLIF(?, ''), payment_method_id)
                WHERE order_id = ? AND status = 'pending'
            """, (payment_id or '', payment_method_id or '', order_id))
            conn.execute("""
                UPDATE subscriptions
                SET status = 'active',
                    last_payment_id = ?,
                    payment_method_id = COALESCE(NULLIF(?, ''), payment_method_id),
                    last_charge_at = CURRENT_TIMESTAMP,
                    period_end_at = ?,
                    grace_until = ?,
                    next_charge_at = ?,
                    failed_attempts = 0,
                    last_failure_reason = NULL,
                    cancel_at_period_end = 0,
                    cancelled_at = NULL
                WHERE id = ?
            """, (
                payment_id, payment_method_id or '',
                _format_datetime(new_period_end), _format_datetime(grace_until),
                _format_datetime(next_charge), subscription_id,
            ))
            key_id = sub.get('vpn_key_id')
            if key_id:
                conn.execute(
                    "UPDATE vpn_keys SET expires_at = ? WHERE id = ?",
                    (_format_datetime(new_period_end), key_id),
                )
        else:
            refreshed = conn.execute(
                "SELECT period_end_at, grace_until, next_charge_at, vpn_key_id FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            if not refreshed:
                return None
            new_period_end = _parse_datetime(refreshed['period_end_at']) or now
            grace_until = _parse_datetime(refreshed['grace_until']) or (
                new_period_end + timedelta(hours=GRACE_PERIOD_HOURS)
            )
            next_charge = _parse_datetime(refreshed['next_charge_at']) or (
                new_period_end - timedelta(minutes=CHARGE_LEAD_MINUTES)
            )

        return {
            'subscription_id': subscription_id,
            'vpn_key_id': sub.get('vpn_key_id'),
            'tariff_id': sub.get('tariff_id'),
            'processed_now': processed_now,
            'period_end_at': _format_datetime(new_period_end),
            'grace_until': _format_datetime(grace_until),
            'next_charge_at': _format_datetime(next_charge),
        }


def mark_subscription_payment_succeeded(
    subscription_id: int,
    *,
    payment_id: str,
    payment_method_id: Optional[str] = None,
) -> bool:
    """Compatibility helper for callers that do not own a recurring order."""
    ensure_subscription_schema()
    now = _utc_now()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        if not row:
            return False
        sub = dict(row)
        old_period_end = _period_end_for_subscription(conn, sub, now)
        new_period_end = max(old_period_end, now) + timedelta(days=int(sub['billing_period_days']))
        next_charge = new_period_end - timedelta(minutes=CHARGE_LEAD_MINUTES)
        grace_until = new_period_end + timedelta(hours=GRACE_PERIOD_HOURS)
        cursor = conn.execute("""
            UPDATE subscriptions
            SET status = 'active',
                last_payment_id = ?,
                payment_method_id = COALESCE(NULLIF(?, ''), payment_method_id),
                last_charge_at = CURRENT_TIMESTAMP,
                period_end_at = ?,
                grace_until = ?,
                next_charge_at = ?,
                failed_attempts = 0,
                last_failure_reason = NULL,
                cancel_at_period_end = 0,
                cancelled_at = NULL
            WHERE id = ?
        """, (
            payment_id, payment_method_id or '', _format_datetime(new_period_end),
            _format_datetime(grace_until), _format_datetime(next_charge), subscription_id,
        ))
        if cursor.rowcount and sub.get('vpn_key_id'):
            conn.execute(
                "UPDATE vpn_keys SET expires_at = ? WHERE id = ?",
                (_format_datetime(new_period_end), sub['vpn_key_id']),
            )
        return cursor.rowcount > 0


def mark_subscription_payment_failed(subscription_id: int, *, payment_id: Optional[str] = None) -> bool:
    return record_subscription_payment_failure(
        subscription_id,
        payment_id=payment_id,
    ) is not None


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
    """Removes the saved recurring payment token without touching paid access."""
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
        logger.info("Payment method unlinked for subscription %s, key %s", subscription_id, vpn_key_id)
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
