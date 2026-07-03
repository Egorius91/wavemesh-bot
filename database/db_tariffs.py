import sqlite3
import logging
import secrets
import string
import datetime
from typing import Optional, List, Dict, Any, Tuple
from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'get_all_tariffs',
    'get_tariff_by_id',
    'add_tariff',
    'update_tariff',
    'update_tariff_field',
    'toggle_tariff_active',
    'get_tariffs_count',
    'get_admin_tariff',
]

_TARIFF_RECURRING_COLUMNS = {
    'billing_type': "TEXT DEFAULT 'one_time'",
    'is_recurring': 'INTEGER DEFAULT 0',
    'billing_period_days': 'INTEGER DEFAULT 0',
    'recurring_provider': "TEXT DEFAULT 'yookassa_qr'",
}


def _ensure_tariff_recurring_columns() -> None:
    """Гарантирует наличие колонок подписок в tariffs без отдельной миграции."""
    with get_db() as conn:
        existing = {row['name'] for row in conn.execute("PRAGMA table_info(tariffs)").fetchall()}
        for column, column_def in _TARIFF_RECURRING_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE tariffs ADD COLUMN {column} {column_def}")
                logger.info("Добавлена колонка tariffs.%s", column)


def _tariff_select_columns() -> str:
    _ensure_tariff_recurring_columns()
    return (
        "id, name, duration_days, price_cents, price_stars, price_rub, "
        "display_order, is_active, traffic_limit_gb, group_id, max_ips, "
        "billing_type, is_recurring, billing_period_days, recurring_provider"
    )


def _normalize_billing_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return row
    row.setdefault('billing_type', 'recurring' if row.get('is_recurring') else 'one_time')
    row.setdefault('is_recurring', 1 if row.get('billing_type') == 'recurring' else 0)
    row.setdefault('billing_period_days', row.get('duration_days') or 0)
    row.setdefault('recurring_provider', 'yookassa_qr')
    return row


def get_all_tariffs(include_hidden: bool = False) -> List[Dict[str, Any]]:
    """
    Получает список всех тарифов.
    
    Args:
        include_hidden: Включать скрытые тарифы (is_active = 0)
        
    Returns:
        Список словарей с данными тарифов
    """
    columns = _tariff_select_columns()
    with get_db() as conn:
        if include_hidden:
            cursor = conn.execute(f"""
                SELECT {columns}
                FROM tariffs
                ORDER BY display_order, id
            """)
        else:
            cursor = conn.execute(f"""
                SELECT {columns}
                FROM tariffs
                WHERE is_active = 1
                ORDER BY display_order, id
            """)
        return [_normalize_billing_fields(dict(row)) for row in cursor.fetchall()]


def get_tariff_by_id(tariff_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает тариф по ID.
    
    Args:
        tariff_id: ID тарифа
        
    Returns:
        Словарь с данными тарифа или None
    """
    columns = _tariff_select_columns()
    with get_db() as conn:
        cursor = conn.execute(f"""
            SELECT {columns}
            FROM tariffs
            WHERE id = ?
        """, (tariff_id,))
        row = cursor.fetchone()
        return _normalize_billing_fields(dict(row)) if row else None


def add_tariff(
    name: str,
    duration_days: int,
    price_cents: int,
    price_stars: int,
    price_rub: int = 0,
    display_order: int = 0,
    traffic_limit_gb: int = 0,
    group_id: int = 1,
    max_ips: int = 1,
    billing_type: str = 'one_time',
    is_recurring: int = 0,
    billing_period_days: int = 0,
    recurring_provider: str = 'yookassa_qr',
) -> int:
    """
    Добавляет новый тариф.
    
    Args:
        name: Название тарифа
        duration_days: Длительность в днях
        price_cents: Цена в центах (USDT * 100)
        price_stars: Цена в Telegram Stars
        price_rub: Цена в рублях
        display_order: Порядок отображения
        traffic_limit_gb: Лимит трафика в ГБ (0 = безлимит)
        group_id: ID группы тарифов (по умолчанию 1 — «Основная»)
        max_ips: Лимит устройств (IP-адресов) (по умолчанию 1)
        billing_type: one_time или recurring
        is_recurring: 1 для тарифа-подписки
        billing_period_days: период автосписания в днях
        recurring_provider: провайдер автосписания
        
    Returns:
        ID созданного тарифа
    """
    _ensure_tariff_recurring_columns()
    billing_type = 'recurring' if billing_type == 'recurring' or is_recurring else 'one_time'
    is_recurring = 1 if billing_type == 'recurring' else 0
    billing_period_days = billing_period_days or duration_days

    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO tariffs (
                name, duration_days, price_cents, price_stars, price_rub,
                display_order, is_active, traffic_limit_gb, group_id, max_ips,
                billing_type, is_recurring, billing_period_days, recurring_provider
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, duration_days, price_cents, price_stars, price_rub,
            display_order, traffic_limit_gb, group_id, max_ips,
            billing_type, is_recurring, billing_period_days, recurring_provider,
        ))
        tariff_id = cursor.lastrowid
        logger.info(
            "Добавлен тариф: %s (ID: %s, billing_type: %s, период: %s дн.)",
            name, tariff_id, billing_type, billing_period_days,
        )
        return tariff_id


def update_tariff(tariff_id: int, **fields) -> bool:
    """
    Обновляет поля тарифа.
    
    Args:
        tariff_id: ID тарифа
        **fields: Поля для обновления
        
    Returns:
        True если обновление успешно
    """
    _ensure_tariff_recurring_columns()
    allowed_fields = {
        'name', 'duration_days', 'price_cents', 'price_stars', 'price_rub',
        'display_order', 'is_active', 'group_id', 'traffic_limit_gb', 'max_ips',
        'billing_type', 'is_recurring', 'billing_period_days', 'recurring_provider',
    }
    fields = {k: v for k, v in fields.items() if k in allowed_fields}
    
    if not fields:
        return False

    if fields.get('billing_type') == 'recurring':
        fields['is_recurring'] = 1
    elif fields.get('billing_type') == 'one_time':
        fields['is_recurring'] = 0
    
    set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [tariff_id]
    
    with get_db() as conn:
        cursor = conn.execute(f"""
            UPDATE tariffs
            SET {set_clause}
            WHERE id = ?
        """, values)
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Обновлён тариф ID {tariff_id}: {list(fields.keys())}")
        return success


def update_tariff_field(tariff_id: int, field: str, value: Any) -> bool:
    """
    Обновляет одно поле тарифа.
    
    Args:
        tariff_id: ID тарифа
        field: Название поля
        value: Новое значение
        
    Returns:
        True если обновление успешно
    """
    return update_tariff(tariff_id, **{field: value})


def toggle_tariff_active(tariff_id: int) -> Optional[bool]:
    """
    Переключает активность тарифа (скрыть/показать).
    
    Args:
        tariff_id: ID тарифа
        
    Returns:
        Новый статус (True = активен) или None если тариф не найден
    """
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return None
    
    new_status = 0 if tariff['is_active'] else 1
    
    with get_db() as conn:
        conn.execute("""
            UPDATE tariffs
            SET is_active = ?
            WHERE id = ?
        """, (new_status, tariff_id))
        status_text = "активирован" if new_status else "скрыт"
        logger.info(f"Тариф ID {tariff_id}: {status_text}")
        return bool(new_status)


def get_tariffs_count() -> int:
    """
    Возвращает количество активных тарифов.
    
    Returns:
        Количество активных тарифов
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM tariffs WHERE is_active = 1")
        row = cursor.fetchone()
        return row['cnt'] if row else 0


def get_admin_tariff() -> Optional[Dict[str, Any]]:
    """
    Получает скрытый Admin Tariff для админского добавления ключей.
    
    Если тариф не существует, создаёт его автоматически.
    
    Returns:
        Словарь с данными тарифа
    """
    _ensure_tariff_recurring_columns()
    columns = _tariff_select_columns()
    with get_db() as conn:
        cursor = conn.execute(f"""
            SELECT {columns}
            FROM tariffs
            WHERE name = 'Admin Tariff'
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row:
            return _normalize_billing_fields(dict(row))
        
        # Если тариф не найден, создаём его
        cursor = conn.execute("""
            INSERT INTO tariffs (
                name, duration_days, price_cents, price_stars, price_rub,
                display_order, is_active, max_ips, billing_type, is_recurring,
                billing_period_days, recurring_provider
            )
            VALUES ('Admin Tariff', 30, 0, 0, 0, 999, 0, 1, 'one_time', 0, 30, 'yookassa_qr')
        """)
        logger.info("Создан Admin Tariff")
        
        return {
            'id': cursor.lastrowid,
            'name': 'Admin Tariff',
            'duration_days': 30,
            'price_cents': 0,
            'price_stars': 0,
            'price_rub': 0,
            'display_order': 999,
            'is_active': 0,
            'max_ips': 1,
            'billing_type': 'one_time',
            'is_recurring': 0,
            'billing_period_days': 30,
            'recurring_provider': 'yookassa_qr',
        }
