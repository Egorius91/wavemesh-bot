import logging
import re
from typing import Optional

from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'get_setting',
    'set_setting',
    'delete_setting',
    'is_update_notifications_enabled',
    'get_display_timezone',
    'set_display_timezone',
    'normalize_display_timezone',
    'is_crypto_enabled',
    'is_stars_enabled',
    'is_crypto_configured',
    'is_cards_enabled',
    'is_cards_configured',
    'is_yookassa_qr_enabled',
    'is_yookassa_qr_configured',
    'get_yookassa_credentials',
    'is_wata_enabled',
    'is_wata_configured',
    'get_wata_token',
    'is_platega_enabled',
    'is_platega_configured',
    'get_platega_credentials',
    'is_cardlink_enabled',
    'is_cardlink_configured',
    'get_cardlink_credentials',
    'is_trial_enabled',
    'get_trial_tariff_id',
    'is_demo_payment_enabled',
]

DEFAULT_DISPLAY_TIMEZONE = 'Europe/Moscow'
DISPLAY_TIMEZONE_SETTING = 'display_timezone'
UPDATE_NOTIFICATIONS_ENABLED_SETTING = 'update_notifications_enabled'

_TIMEZONE_ALIASES = {
    'москва': DEFAULT_DISPLAY_TIMEZONE,
    'мск': DEFAULT_DISPLAY_TIMEZONE,
    'moscow': DEFAULT_DISPLAY_TIMEZONE,
    'msk': DEFAULT_DISPLAY_TIMEZONE,
    'utc': 'UTC',
    'gmt': 'UTC',
}
_UTC_OFFSET_RE = re.compile(r'^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$')


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Получает значение настройки."""
    with get_db() as conn:
        cursor = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default


def set_setting(key: str, value: str) -> None:
    """Устанавливает значение настройки."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        logger.info("Настройка обновлена: %s", key)


def delete_setting(key: str) -> bool:
    """Удаляет настройку."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return cursor.rowcount > 0


def is_update_notifications_enabled() -> bool:
    """Возвращает состояние скрытых уведомлений о новых версиях."""
    return get_setting(UPDATE_NOTIFICATIONS_ENABLED_SETTING, '1') == '1'


def normalize_display_timezone(value: Optional[str]) -> str:
    """Нормализует скрытую настройку часового пояса для отображения дат."""
    raw = (value or '').strip()
    if not raw:
        return DEFAULT_DISPLAY_TIMEZONE

    key = raw.lower().replace('ё', 'е')
    compact_key = key.replace(' ', '')
    if key in _TIMEZONE_ALIASES:
        return _TIMEZONE_ALIASES[key]
    if compact_key in _TIMEZONE_ALIASES:
        return _TIMEZONE_ALIASES[compact_key]

    match = _UTC_OFFSET_RE.match(compact_key)
    if match:
        sign, hours_raw, minutes_raw = match.groups()
        hours = int(hours_raw)
        minutes = int(minutes_raw or '0')
        if hours <= 23 and minutes <= 59:
            return f'UTC{sign}{hours:02d}:{minutes:02d}'

    if '/' in raw and all(part for part in raw.split('/')):
        return raw

    return DEFAULT_DISPLAY_TIMEZONE


def get_display_timezone() -> str:
    """Возвращает часовой пояс, в котором бот показывает даты пользователям и админам."""
    return normalize_display_timezone(get_setting(DISPLAY_TIMEZONE_SETTING, DEFAULT_DISPLAY_TIMEZONE))


def set_display_timezone(value: str) -> str:
    """Сохраняет часовой пояс отображения и возвращает нормализованное значение."""
    timezone_value = normalize_display_timezone(value)
    set_setting(DISPLAY_TIMEZONE_SETTING, timezone_value)
    return timezone_value


def is_crypto_enabled() -> bool:
    """Проверяет, включены ли крипто-платежи."""
    return get_setting('crypto_enabled', '0') == '1'


def is_stars_enabled() -> bool:
    """Проверяет, включены ли Telegram Stars."""
    return get_setting('stars_enabled', '0') == '1'


def is_crypto_configured() -> bool:
    """Проверяет, настроены ли крипто-платежи полностью."""
    if not is_crypto_enabled():
        return False
    crypto_item_url = get_setting('crypto_item_url')
    return bool(crypto_item_url and crypto_item_url.strip())


def is_cards_enabled() -> bool:
    """Проверяет, включена ли оплата картами."""
    return get_setting('cards_enabled', '0') == '1'


def is_cards_configured() -> bool:
    """Проверяет, настроена ли оплата картами."""
    if not is_cards_enabled():
        return False
    token = get_setting('cards_provider_token')
    return bool(token and token.strip())


def is_yookassa_qr_enabled() -> bool:
    """Проверяет, включена ли QR-оплата через ЮКассу."""
    return get_setting('yookassa_qr_enabled', '0') == '1'


def is_yookassa_qr_configured() -> bool:
    """Проверяет, настроена ли QR-оплата через ЮКассу полностью."""
    if not is_yookassa_qr_enabled():
        return False
    shop_id = get_setting('yookassa_shop_id', '')
    secret_key = get_setting('yookassa_secret_key', '')
    return bool(shop_id and shop_id.strip() and secret_key and secret_key.strip())


def get_yookassa_credentials() -> tuple[str, str]:
    """Возвращает учётные данные ЮКасса для прямого API."""
    shop_id = get_setting('yookassa_shop_id', '')
    secret_key = get_setting('yookassa_secret_key', '')
    return shop_id, secret_key


def is_wata_enabled() -> bool:
    """Проверяет, включена ли оплата через WATA."""
    return get_setting('wata_enabled', '0') == '1'


def is_wata_configured() -> bool:
    """Проверяет, настроена ли оплата через WATA полностью."""
    if not is_wata_enabled():
        return False
    token = get_setting('wata_jwt_token', '')
    return bool(token and token.strip())


def get_wata_token() -> str:
    """Возвращает JWT-токен для WATA API."""
    return get_setting('wata_jwt_token', '') or ''


def is_platega_enabled() -> bool:
    """Проверяет, включена ли оплата через Platega."""
    return get_setting('platega_enabled', '0') == '1'


def is_platega_configured() -> bool:
    """Проверяет, настроена ли оплата через Platega полностью."""
    if not is_platega_enabled():
        return False
    merchant_id = get_setting('platega_merchant_id', '')
    secret = get_setting('platega_secret', '')
    return bool(merchant_id and merchant_id.strip() and secret and secret.strip())


def get_platega_credentials() -> tuple[str, str]:
    """Возвращает учётные данные Platega для прямого API."""
    merchant_id = get_setting('platega_merchant_id', '')
    secret = get_setting('platega_secret', '')
    return merchant_id, secret


def is_cardlink_enabled() -> bool:
    """Проверяет, включена ли оплата через Cardlink."""
    return get_setting('cardlink_enabled', '0') == '1'


def is_cardlink_configured() -> bool:
    """Проверяет, настроена ли оплата через Cardlink полностью."""
    if not is_cardlink_enabled():
        return False
    shop_id = get_setting('cardlink_shop_id', '')
    token = get_setting('cardlink_api_token', '')
    return bool(shop_id and shop_id.strip() and token and token.strip())


def get_cardlink_credentials() -> tuple[str, str]:
    """Возвращает учётные данные Cardlink для прямого API."""
    shop_id = get_setting('cardlink_shop_id', '')
    token = get_setting('cardlink_api_token', '')
    return shop_id, token


def is_trial_enabled() -> bool:
    """Включена ли функция пробной подписки."""
    return get_setting('trial_enabled', '0') == '1'


def get_trial_tariff_id() -> Optional[int]:
    """Возвращает ID тарифа для пробной подписки."""
    val = get_setting('trial_tariff_id', '')
    return int(val) if val and val.isdigit() else None


def is_demo_payment_enabled() -> bool:
    """Включена ли демонстрационная оплата РФ картой."""
    return get_setting('demo_payment_enabled', '0') == '1'
