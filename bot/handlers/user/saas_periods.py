"""Bounded display of SaaS financial periods; never grants runtime access."""
from datetime import datetime, timezone

from bot.utils.text import escape_html


def utc_date(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def scheduled_periods_text(value):
    if value is None or value == []:
        return ""
    unavailable = "\n\nДаты оплаченных периодов не удалось отобразить полностью. Обновите доступ или обратитесь в поддержку."
    if not isinstance(value, list):
        return unavailable
    periods, seen = [], set()
    incomplete = len(value) > 100
    # The SaaS response is already ordered by nearest start. Bound parsing as well
    # as output; a malformed optional field must not hide access navigation.
    for item in value[:100]:
        if not isinstance(item, dict):
            incomplete = True
            continue
        period_id = item.get("subscription_id")
        start, end = utc_date(item.get("starts_at")), utc_date(item.get("expires_at"))
        if (not isinstance(period_id, str) or not 0 < len(period_id) <= 128
                or start is None or end is None or start >= end):
            incomplete = True
            continue
        if period_id in seen:
            continue
        seen.add(period_id)
        name = item.get("tariff_name")
        name = name[:80] if isinstance(name, str) else ""
        name = " ".join(name.split()) or "Тариф"
        periods.append((start, end, escape_html(name)))
    if not periods:
        return unavailable
    periods.sort(key=lambda period: period[0])
    text = "\n\n<b>Оплачено заранее</b>\nДаты и время — UTC."
    for start, end, name in periods[:3]:
        text += f"\n• {name}: {start:%d.%m.%Y %H:%M:%S} — {end:%d.%m.%Y %H:%M:%S}"
    if len(periods) > 3 or len(value) > 100:
        text += "\nПоказаны только первые периоды."
    text += "\nПовторно оплачивать эти периоды не нужно. Готовность конфигурации указана отдельно."
    if incomplete:
        text += unavailable
    return text
