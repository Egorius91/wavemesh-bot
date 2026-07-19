"""Page defaults and links for guided WaveMesh onboarding."""
from __future__ import annotations

import json

HAPP_IOS_GLOBAL_URL = "https://apps.apple.com/app/id6504287215"
HAPP_IOS_RU_URL = "https://apps.apple.com/app/id6783623643"
HAPP_ANDROID_GOOGLE_PLAY_URL = "https://play.google.com/store/apps/details?id=com.happproxy"
HAPP_ANDROID_APK_URL = "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk"
HAPP_DESKTOP_RELEASES_URL = "https://github.com/Happ-proxy/happ-desktop/releases/latest"
HAPP_WINDOWS_URL = "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe"
HAPP_MACOS_URL = "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.macOS.universal.dmg"

ONEXRAY_APP_STORE_URL = "https://apps.apple.com/us/app/onexray/id6745748773"
ONEXRAY_GOOGLE_PLAY_URL = "https://play.google.com/store/apps/details?id=net.yuandev.onexray"
ONEXRAY_INSTALL_URL = "https://onexray.com/docs/install/"

ONBOARDING_PAGE_KEYS = (
    "onboarding_ready",
    "onboarding_key_select",
    "onboarding_no_available_key",
    "onboarding_ios",
    "onboarding_android",
    "onboarding_windows",
    "onboarding_macos",
    "onboarding_happ_region",
    "onboarding_happ_install_ru",
    "onboarding_happ_install_global",
    "onboarding_happ_install_android",
    "onboarding_happ_install_windows",
    "onboarding_happ_install_macos",
    "onboarding_happ_connection",
    "onboarding_happ_connection_android",
    "onboarding_happ_connection_windows",
    "onboarding_happ_connection_macos",
    "onboarding_onexray_connection",
    "onboarding_troubleshoot",
    "onboarding_issue_enable",
    "onboarding_issue_no_traffic",
    "onboarding_issue_mobile",
    "onboarding_issue_stale",
    "onboarding_success",
)


def _buttons(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)


def _button(
    button_id: str,
    label: str,
    row: int,
    *,
    color: str = "secondary",
    action_type: str = "system",
    action_value: str | None = None,
    url: str | None = None,
) -> dict:
    item = {
        "id": button_id,
        "label": label,
        "color": color,
        "row": row,
        "col": 0,
        "is_hidden": False,
        "action_type": action_type,
        "action_value": action_value,
    }
    if url:
        item["action_type"] = "url"
        item["action_value"] = url
    return item


HELP_TEXT = (
    "🔐 <b>Справка WaveMesh VPN</b>\n\n"
    "Мастер настройки поможет установить приложение и добавить подключение "
    "на iPhone, Android, Windows или macOS.\n\n"
    "Основной рекомендуемый клиент — <b>HAPP</b>. OneXray доступен как дополнительный вариант."
)
HELP_BUTTONS = _buttons([
    _button(
        "btn_onboarding_start",
        "🧭 Настроить VPN",
        0,
        action_type="internal",
        action_value="cmd_onboarding_start",
    ),
    _button("btn_news", "📢 Новости", 1, action_type="url", url="https://t.me/WaveMeshVPN"),
    _button("btn_support", "💬 Поддержка", 2, action_type="url", url="https://t.me/wavemesh"),
    _button("btn_back_main", "🈴 На главную", 3, action_type="internal", action_value="cmd_back_main"),
])

ONBOARDING_READY_TEXT = (
    "✅ <b>Подключение готово</b>\n\n"
    "Осталось установить приложение и добавить в него ваше подключение. "
    "Обычно это занимает 2–3 минуты.\n\n"
    "Выберите устройство:"
)
ONBOARDING_READY_BUTTONS = _buttons([
    _button("btn_onboarding_ios", "🍎 iPhone / iPad", 0),
    _button("btn_onboarding_android", "🤖 Android", 1),
    _button("btn_onboarding_windows", "💻 Windows", 2),
    _button("btn_onboarding_macos", "🖥 macOS", 3),
    _button("btn_onboarding_advanced", "🛠 Для опытных пользователей", 4),
    _button("btn_my_keys", "🔑 Мои ключи", 5, action_type="internal", action_value="cmd_my_keys"),
])

ONBOARDING_KEY_SELECT_TEXT = (
    "🧭 <b>Какой ключ настроить?</b>\n\n"
    "У вас несколько активных подключений. Выберите нужный ключ."
)
ONBOARDING_KEY_SELECT_BUTTONS = _buttons([
    _button("btn_back_help", "⬅️ Назад", 0, action_type="internal", action_value="cmd_help"),
])

ONBOARDING_NO_AVAILABLE_KEY_TEXT = (
    "🧭 <b>Нет ключа для настройки</b>\n\n"
    "Для запуска мастера нужен активный настроенный VPN-ключ."
)
ONBOARDING_NO_AVAILABLE_KEY_BUTTONS = _buttons([
    _button("btn_my_keys", "🔑 Мои ключи", 0, action_type="internal", action_value="cmd_my_keys"),
    _button("btn_buy_key", "💳 Купить ключ", 1, action_type="internal", action_value="cmd_buy"),
    _button("btn_back_help", "⬅️ Назад", 2, action_type="internal", action_value="cmd_help"),
])

ONBOARDING_HAPP_REGION_TEXT = (
    "🍎 <b>HAPP для iPhone / iPad</b>\n\n"
    "У HAPP разные версии для российского и других регионов App Store. "
    "Выберите регион вашего Apple ID."
)
ONBOARDING_HAPP_REGION_BUTTONS = _buttons([
    _button("btn_onboarding_happ_ru", "🇷🇺 Россия", 0, color="primary"),
    _button("btn_onboarding_happ_global", "🌍 Другой регион", 1, color="primary"),
    _button("btn_onboarding_onexray", "OneXray — дополнительный вариант", 2),
    _button("btn_onboarding_back_device", "⬅️ Назад", 3),
])


def _happ_install_text(platform_name: str, hint: str) -> str:
    return (
        f"📲 <b>Шаг 1 из 3 · HAPP · {platform_name}</b>\n\n"
        f"{hint}\n\n"
        "После установки вернитесь в бот и нажмите «Приложение установлено»."
    )


def _install_buttons(primary_label: str, primary_url: str, backup: tuple[str, str] | None = None) -> str:
    items = [_button("btn_onboarding_install", primary_label, 0, color="primary", url=primary_url)]
    row = 1
    if backup:
        items.append(_button("btn_onboarding_backup", backup[0], row, url=backup[1]))
        row += 1
    items.extend([
        _button("btn_onboarding_happ_continue", "✅ Приложение установлено", row, color="success"),
        _button("btn_onboarding_onexray", "OneXray — дополнительный вариант", row + 1),
        _button("btn_onboarding_back_device", "⬅️ Назад", row + 2),
    ])
    return _buttons(items)

ONBOARDING_HAPP_INSTALL_RU_TEXT = _happ_install_text("iPhone / iPad · Россия", "Откройте российскую версию HAPP в App Store.")
ONBOARDING_HAPP_INSTALL_GLOBAL_TEXT = _happ_install_text("iPhone / iPad · другой регион", "Откройте глобальную версию HAPP в App Store.")
ONBOARDING_HAPP_INSTALL_ANDROID_TEXT = _happ_install_text("Android", "Установите HAPP из Google Play. APK оставлен как официальный запасной источник.")
ONBOARDING_HAPP_INSTALL_WINDOWS_TEXT = _happ_install_text("Windows", "Скачайте установщик HAPP с официальной страницы проекта.")
ONBOARDING_HAPP_INSTALL_MACOS_TEXT = _happ_install_text("macOS", "Скачайте HAPP с официальной страницы проекта.")

ONBOARDING_HAPP_INSTALL_RU_BUTTONS = _install_buttons("⬇️ Установить HAPP RU", HAPP_IOS_RU_URL)
ONBOARDING_HAPP_INSTALL_GLOBAL_BUTTONS = _install_buttons("⬇️ Установить HAPP Global", HAPP_IOS_GLOBAL_URL)
ONBOARDING_HAPP_INSTALL_ANDROID_BUTTONS = _install_buttons(
    "▶️ Установить из Google Play",
    HAPP_ANDROID_GOOGLE_PLAY_URL,
    ("📦 Скачать APK", HAPP_ANDROID_APK_URL),
)
ONBOARDING_HAPP_INSTALL_WINDOWS_BUTTONS = _install_buttons(
    "⬇️ Скачать HAPP для Windows",
    HAPP_WINDOWS_URL,
    ("📋 Страница релизов", HAPP_DESKTOP_RELEASES_URL),
)
ONBOARDING_HAPP_INSTALL_MACOS_BUTTONS = _install_buttons(
    "⬇️ Скачать HAPP для macOS",
    HAPP_MACOS_URL,
    ("📋 Страница релизов", HAPP_DESKTOP_RELEASES_URL),
)


def _onexray_install_text(platform_name: str) -> str:
    return (
        f"📱 <b>Дополнительный вариант · OneXray · {platform_name}</b>\n\n"
        "Основным рекомендуемым клиентом остаётся HAPP. "
        "Используйте OneXray, когда он удобнее на вашем устройстве.\n\n"
        "После установки вернитесь в бот и нажмите «Приложение установлено»."
    )


def _onexray_buttons(url: str) -> str:
    return _buttons([
        _button("btn_onboarding_onexray_install", "⬇️ Установить OneXray", 0, color="primary", url=url),
        _button("btn_onboarding_onexray_continue", "✅ Приложение установлено", 1, color="success"),
        _button("btn_onboarding_back_happ", "⬅️ Вернуться к HAPP", 2),
    ])

ONBOARDING_IOS_TEXT = _onexray_install_text("iPhone / iPad")
ONBOARDING_ANDROID_TEXT = _onexray_install_text("Android")
ONBOARDING_WINDOWS_TEXT = _onexray_install_text("Windows")
ONBOARDING_MACOS_TEXT = _onexray_install_text("macOS")
ONBOARDING_IOS_BUTTONS = _onexray_buttons(ONEXRAY_APP_STORE_URL)
ONBOARDING_ANDROID_BUTTONS = _onexray_buttons(ONEXRAY_GOOGLE_PLAY_URL)
ONBOARDING_WINDOWS_BUTTONS = _onexray_buttons(ONEXRAY_INSTALL_URL)
ONBOARDING_MACOS_BUTTONS = _onexray_buttons(ONEXRAY_APP_STORE_URL)


def _connection_text(app_name: str, platform_name: str, hint: str) -> str:
    return (
        f"🔗 <b>Шаг 2 из 3 · {app_name} · {platform_name}</b>\n\n"
        "1. Скопируйте ссылку подключения:\n%ключ%\n\n"
        f"2. {hint}\n"
        "3. Импортируйте ссылку из буфера обмена или отсканируйте QR-код.\n\n"
        "Выберите добавленное подключение и включите VPN."
    )

ONBOARDING_HAPP_CONNECTION_TEXT = _connection_text("HAPP", "iPhone / iPad", "Откройте HAPP и выберите добавление подписки")
ONBOARDING_HAPP_CONNECTION_ANDROID_TEXT = _connection_text("HAPP", "Android", "Откройте HAPP и выберите добавление подписки")
ONBOARDING_HAPP_CONNECTION_WINDOWS_TEXT = _connection_text("HAPP", "Windows", "Откройте HAPP и добавьте новую подписку")
ONBOARDING_HAPP_CONNECTION_MACOS_TEXT = _connection_text("HAPP", "macOS", "Откройте HAPP и добавьте новую подписку")
ONBOARDING_ONEXRAY_CONNECTION_TEXT = _connection_text("OneXray", "ваше устройство", "Откройте OneXray, нажмите ＋ и выберите Read Clipboard")

CONNECTION_BUTTONS = _buttons([
    _button("btn_onboarding_done", "✅ VPN включён", 0, color="success"),
    _button("btn_onboarding_problem", "🧰 Не получается", 1),
    _button("btn_onboarding_retry_install", "⬅️ Назад к установке", 2),
])

ONBOARDING_TROUBLESHOOT_TEXT = (
    "🧰 <b>Что именно не получилось?</b>\n\n"
    "Выберите ближайший вариант — бот вернёт вас к нужному шагу."
)
ONBOARDING_TROUBLESHOOT_BUTTONS = _buttons([
    _button("btn_onboarding_retry_install", "Не установилось приложение", 0),
    _button("btn_onboarding_retry_connection", "Не добавилось подключение", 1),
    _button("btn_onboarding_issue_enable", "VPN не включается", 2),
    _button("btn_onboarding_issue_no_traffic", "VPN включён, но сайты не открываются", 3),
    _button("btn_onboarding_issue_mobile", "Не работает по мобильной сети", 4),
    _button("btn_onboarding_issue_stale", "Раньше работало, теперь нет", 5),
    _button("btn_onboarding_support", "💬 Написать в поддержку", 6, action_type="url", url="https://t.me/wavemesh"),
])

ISSUE_BUTTONS = _buttons([
    _button("btn_onboarding_retry_connection", "🔗 Показать подключение снова", 0),
    _button("btn_onboarding_support", "💬 Написать в поддержку", 1, action_type="url", url="https://t.me/wavemesh"),
    _button("btn_onboarding_troubleshoot_back", "⬅️ Назад", 2),
])

ONBOARDING_ISSUE_ENABLE_TEXT = (
    "⚡ <b>VPN не включается</b>\n\n"
    "Проверьте, что подключение выбрано, разрешите создание VPN-конфигурации "
    "и временно выключите другие VPN или прокси. Затем перезапустите приложение."
)
ONBOARDING_ISSUE_NO_TRAFFIC_TEXT = (
    "🌐 <b>VPN включён, но сайты не открываются</b>\n\n"
    "Выключите VPN на несколько секунд, смените Wi‑Fi на мобильную сеть или наоборот, "
    "проверьте отсутствие другого VPN и повторите подключение."
)
ONBOARDING_ISSUE_MOBILE_TEXT = (
    "📶 <b>Не работает по мобильной сети</b>\n\n"
    "Перезапустите мобильные данные, проверьте разрешение приложения на работу через сеть "
    "и повторно включите VPN."
)
ONBOARDING_ISSUE_STALE_TEXT = (
    "♻️ <b>Раньше работало, теперь нет</b>\n\n"
    "Проверьте срок ключа, обновите подписку в приложении и повторно включите VPN."
)

ONBOARDING_SUCCESS_TEXT = (
    "🎉 <b>VPN подключён</b>\n\n"
    "Настройка завершена. Подключение сохранено в приложении и доступно для повторного использования."
)
ONBOARDING_SUCCESS_BUTTONS = _buttons([
    _button("btn_my_keys", "🔑 Мои ключи", 0, action_type="internal", action_value="cmd_my_keys"),
    _button("btn_back_main", "🏠 На главную", 1, action_type="internal", action_value="cmd_back_main"),
])

PAGE_DEFAULTS = {
    "onboarding_ready": (ONBOARDING_READY_TEXT, ONBOARDING_READY_BUTTONS, None, None),
    "onboarding_key_select": (ONBOARDING_KEY_SELECT_TEXT, ONBOARDING_KEY_SELECT_BUTTONS, None, None),
    "onboarding_no_available_key": (ONBOARDING_NO_AVAILABLE_KEY_TEXT, ONBOARDING_NO_AVAILABLE_KEY_BUTTONS, None, None),
    "onboarding_ios": (ONBOARDING_IOS_TEXT, ONBOARDING_IOS_BUTTONS, None, None),
    "onboarding_android": (ONBOARDING_ANDROID_TEXT, ONBOARDING_ANDROID_BUTTONS, None, None),
    "onboarding_windows": (ONBOARDING_WINDOWS_TEXT, ONBOARDING_WINDOWS_BUTTONS, None, None),
    "onboarding_macos": (ONBOARDING_MACOS_TEXT, ONBOARDING_MACOS_BUTTONS, None, None),
    "onboarding_happ_region": (ONBOARDING_HAPP_REGION_TEXT, ONBOARDING_HAPP_REGION_BUTTONS, None, None),
    "onboarding_happ_install_ru": (ONBOARDING_HAPP_INSTALL_RU_TEXT, ONBOARDING_HAPP_INSTALL_RU_BUTTONS, None, None),
    "onboarding_happ_install_global": (ONBOARDING_HAPP_INSTALL_GLOBAL_TEXT, ONBOARDING_HAPP_INSTALL_GLOBAL_BUTTONS, None, None),
    "onboarding_happ_install_android": (ONBOARDING_HAPP_INSTALL_ANDROID_TEXT, ONBOARDING_HAPP_INSTALL_ANDROID_BUTTONS, None, None),
    "onboarding_happ_install_windows": (ONBOARDING_HAPP_INSTALL_WINDOWS_TEXT, ONBOARDING_HAPP_INSTALL_WINDOWS_BUTTONS, None, None),
    "onboarding_happ_install_macos": (ONBOARDING_HAPP_INSTALL_MACOS_TEXT, ONBOARDING_HAPP_INSTALL_MACOS_BUTTONS, None, None),
    "onboarding_happ_connection": (ONBOARDING_HAPP_CONNECTION_TEXT, CONNECTION_BUTTONS, None, None),
    "onboarding_happ_connection_android": (ONBOARDING_HAPP_CONNECTION_ANDROID_TEXT, CONNECTION_BUTTONS, None, None),
    "onboarding_happ_connection_windows": (ONBOARDING_HAPP_CONNECTION_WINDOWS_TEXT, CONNECTION_BUTTONS, None, None),
    "onboarding_happ_connection_macos": (ONBOARDING_HAPP_CONNECTION_MACOS_TEXT, CONNECTION_BUTTONS, None, None),
    "onboarding_onexray_connection": (ONBOARDING_ONEXRAY_CONNECTION_TEXT, CONNECTION_BUTTONS, None, None),
    "onboarding_troubleshoot": (ONBOARDING_TROUBLESHOOT_TEXT, ONBOARDING_TROUBLESHOOT_BUTTONS, None, None),
    "onboarding_issue_enable": (ONBOARDING_ISSUE_ENABLE_TEXT, ISSUE_BUTTONS, None, None),
    "onboarding_issue_no_traffic": (ONBOARDING_ISSUE_NO_TRAFFIC_TEXT, ISSUE_BUTTONS, None, None),
    "onboarding_issue_mobile": (ONBOARDING_ISSUE_MOBILE_TEXT, ISSUE_BUTTONS, None, None),
    "onboarding_issue_stale": (ONBOARDING_ISSUE_STALE_TEXT, ISSUE_BUTTONS, None, None),
    "onboarding_success": (ONBOARDING_SUCCESS_TEXT, ONBOARDING_SUCCESS_BUTTONS, None, None),
}


def register_onboarding_pages() -> None:
    """Register onboarding pages before the normal branding startup pass."""
    from bot.services import branding
    from bot.services import page_context
    from bot.utils import message_editor

    branding.PAGE_DEFAULTS["help"] = (HELP_TEXT, HELP_BUTTONS, None, None)
    branding.PAGE_DEFAULTS.update(PAGE_DEFAULTS)

    markers = tuple(branding.LEGACY_MARKERS)
    for marker in ("Начните с раздела загрузки клиента", "cmd_download_clients"):
        if marker not in markers:
            markers += (marker,)
    branding.LEGACY_MARKERS = markers

    message_editor.PAGE_KEYS = tuple(dict.fromkeys((*message_editor.PAGE_KEYS, *ONBOARDING_PAGE_KEYS)))
    page_context.SUPPORTED_YAA_PAGE_KEYS = frozenset(
        set(page_context.SUPPORTED_YAA_PAGE_KEYS).union(ONBOARDING_PAGE_KEYS)
    )
