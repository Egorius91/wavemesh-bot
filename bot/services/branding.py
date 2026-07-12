"""WaveMesh branding defaults.

This module keeps user-visible texts and links independent from the original
project. It is intentionally idempotent and safe to run on every bot startup.
"""

from __future__ import annotations

import json
import logging

from database.connection import get_db

logger = logging.getLogger(__name__)

PROJECT_NAME = "WaveMesh VPN"
SUPPORT_USERNAME = "@wavemesh"
SUPPORT_URL = "https://t.me/wavemesh"
NEWS_URL = "https://t.me/WaveMeshVPN"

PRIVACY_POLICY_URL = "https://telegra.ph/Politika-konfidencialnosti-WaveMesh-VPN-07-01"
USER_AGREEMENT_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-WaveMesh-VPN-07-01"
REFUND_POLICY_URL = "https://telegra.ph/Pravila-vozvrata-denezhnyh-sredstv-WaveMesh-VPN-07-01"

HAPP_URL = "https://happ.info/"
HAPP_IOS_GLOBAL_URL = "https://apps.apple.com/app/id6504287215"
HAPP_IOS_RU_URL = "https://apps.apple.com/app/id6783623643"
STREISAND_IOS_URL = "https://apps.apple.com/us/app/streisand/id6450534064"
V2BOX_IOS_URL = "https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690"
HIDDIFY_URL = "https://hiddify.com/"
HIDDIFY_RELEASES_URL = "https://github.com/hiddify/hiddify-app/releases"
V2RAYNG_RELEASES_URL = "https://github.com/2dust/v2rayNG/releases"
APP_STORE_REGION_GUIDE_URL = "https://telegra.ph/Kak-izmenit-region-App-Store-dlya-ustanovki-VPN-klientov-07-01-5"
ONEXRAY_APP_STORE_URL = "https://apps.apple.com/us/app/onexray/id6745748773"
ONEXRAY_GOOGLE_PLAY_URL = "https://play.google.com/store/apps/details?id=net.yuandev.onexray"
ONEXRAY_INSTALL_URL = "https://onexray.com/docs/install/"

MAIN_TEXT = (
    "🌊 <b>WaveMesh VPN</b>\n\n"
    "Спокойный и надёжный VPN-доступ для телефона, компьютера и планшета.\n\n"
    "Подключение занимает пару минут: выберите тариф, получите личный ключ "
    "и добавьте его в удобный VPN-клиент.\n\n"
    "Работает на iPhone, Android, Windows и macOS. Если возникнут трудности, "
    f"поддержка {SUPPORT_USERNAME} поможет с настройкой.\n\n"
    "%тарифы%"
)

MAIN_BUTTONS = json.dumps(
    [
        {"id": "btn_my_keys",   "label": "🔑 Мои ключи",        "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_my_keys"},
        {"id": "btn_buy_key",   "label": "💳 Купить ключ",       "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_buy"},
        {"id": "btn_trial",     "label": "🎁 Пробный доступ",    "color": "secondary", "row": 1, "col": 0, "is_hidden": True,  "action_type": "internal", "action_value": "cmd_trial"},
        {"id": "btn_referral",  "label": "🔗 Реферальная ссылка", "color": "secondary", "row": 2, "col": 0, "is_hidden": True,  "action_type": "internal", "action_value": "cmd_referral"},
        {"id": "btn_help",      "label": "❓ Справка",            "color": "secondary", "row": 2, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_help"},
        {"id": "btn_documents", "label": "📄 Документы",         "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_documents"},
    ],
    ensure_ascii=False,
)

HELP_TEXT = (
    "🔐 <b>Справка WaveMesh VPN</b>\n\n"
    "Здесь собраны основные инструкции для подключения и управления доступом.\n\n"
    "Чтобы установить приложение и добавить подключение, запустите мастер настройки. "
    "Он проведёт вас по шагам для вашего устройства."
)

HELP_BUTTONS = json.dumps(
    [
        {"id": "btn_onboarding_start", "label": "🧭 Настроить VPN", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_onboarding_start"},
        {"id": "btn_news",             "label": "📢 Новости",             "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "url", "action_value": NEWS_URL},
        {"id": "btn_support",          "label": "💬 Поддержка",           "color": "secondary", "row": 1, "col": 1, "is_hidden": False, "action_type": "url", "action_value": SUPPORT_URL},
        {"id": "btn_back_main",        "label": "🈴 На главную",          "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_back_main"},
    ],
    ensure_ascii=False,
)

DOWNLOAD_CLIENTS_TEXT = (
    "📱 <b>Скачать VPN-клиент</b>\n\n"
    "Выберите платформу, на которой хотите подключить WaveMesh VPN.\n\n"
    "После установки приложения откройте раздел «Мои ключи», скопируйте ссылку подключения "
    "и импортируйте её в выбранный клиент."
)

DOWNLOAD_CLIENTS_BUTTONS = json.dumps(
    [
        {"id": "btn_download_ios",     "label": "🍎 iPhone / iPad", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_ios"},
        {"id": "btn_download_android", "label": "🤖 Android",        "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_android"},
        {"id": "btn_download_windows", "label": "💻 Windows",        "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_windows"},
        {"id": "btn_download_macos",   "label": "🖥 macOS",          "color": "secondary", "row": 1, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_macos"},
        {"id": "btn_back_help",        "label": "⬅️ Назад",          "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_help"},
    ],
    ensure_ascii=False,
)

DOWNLOAD_IOS_TEXT = (
    "🍎 <b>iPhone / iPad · другие приложения</b>\n\n"
    "Если HAPP недоступен, можно использовать Streisand или V2Box.\n\n"
    "Если приложение не отображается в App Store, проверьте регион Apple ID. "
    "Нажмите кнопку ниже, чтобы открыть подробную инструкцию."
)

DOWNLOAD_IOS_BUTTONS = json.dumps(
    [
        {"id": "btn_streisand_ios",     "label": "Streisand",                    "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": STREISAND_IOS_URL},
        {"id": "btn_v2box_ios",         "label": "V2Box",                        "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "url", "action_value": V2BOX_IOS_URL},
        {"id": "btn_appstore_region",   "label": "🍏 Как изменить регион App Store", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "url", "action_value": APP_STORE_REGION_GUIDE_URL},
        {"id": "btn_onboarding_alt_continue_ios", "label": "✅ Приложение установлено", "color": "success", "row": 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_alt_other_back", "label": "⬅️ Назад",              "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_back_downloads",    "label": "⬅️ Назад",                     "color": "secondary", "row": 4, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_clients"},
    ],
    ensure_ascii=False,
)

ONBOARDING_HAPP_REGION_TEXT = (
    "🍎 <b>HAPP для iPhone / iPad</b>\n\n"
    "У HAPP разные версии для российского и других регионов App Store. "
    "Выберите регион, который указан в вашем Apple ID."
)

ONBOARDING_HAPP_REGION_BUTTONS = json.dumps(
    [
        {"id": "btn_onboarding_happ_ru", "label": "🇷🇺 Россия", "color": "primary", "row": 0, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_happ_global", "label": "🌍 Другой регион", "color": "primary", "row": 0, "col": 1, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_happ_other", "label": "Другие приложения", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_happ_back_primary", "label": "⬅️ Назад", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
    ],
    ensure_ascii=False,
)


def _onboarding_happ_install_text(region_name: str) -> str:
    return (
        f"📲 <b>Установите HAPP · {region_name}</b>\n\n"
        "Кнопка ниже откроет нужную версию приложения в App Store.\n\n"
        "Когда HAPP установится, вернитесь в бот и нажмите "
        "«Приложение установлено»."
    )


def _onboarding_happ_install_buttons(install_url: str, *, include_global: bool) -> str:
    buttons = [
        {"id": "btn_onboarding_happ_install", "label": "⬇️ Установить HAPP", "color": "primary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": install_url},
        {"id": "btn_onboarding_happ_continue", "label": "✅ Приложение установлено", "color": "success", "row": 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
    ]
    next_row = 2
    if include_global:
        buttons.append(
            {"id": "btn_onboarding_happ_global", "label": "🌍 Открыть HAPP Global", "color": "secondary", "row": next_row, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None}
        )
        next_row += 1
    buttons.extend([
        {"id": "btn_onboarding_happ_other", "label": "Другие приложения", "color": "secondary", "row": next_row, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_appstore_region", "label": "🍏 Как изменить регион App Store", "color": "secondary", "row": next_row + 1, "col": 0, "is_hidden": False, "action_type": "url", "action_value": APP_STORE_REGION_GUIDE_URL},
        {"id": "btn_onboarding_happ_back_region", "label": "⬅️ Назад", "color": "secondary", "row": next_row + 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
    ])
    return json.dumps(buttons, ensure_ascii=False)


ONBOARDING_HAPP_INSTALL_RU_TEXT = _onboarding_happ_install_text("Россия")
ONBOARDING_HAPP_INSTALL_GLOBAL_TEXT = _onboarding_happ_install_text("другой регион")
ONBOARDING_HAPP_INSTALL_RU_BUTTONS = _onboarding_happ_install_buttons(
    HAPP_IOS_RU_URL,
    include_global=True,
)
ONBOARDING_HAPP_INSTALL_GLOBAL_BUTTONS = _onboarding_happ_install_buttons(
    HAPP_IOS_GLOBAL_URL,
    include_global=False,
)

ONBOARDING_HAPP_CONNECTION_TEXT = (
    "🔗 <b>Шаг 2 из 3 · Добавьте подключение в HAPP</b>\n\n"
    "1. Нажмите на ссылку ниже, чтобы скопировать её:\n"
    "%ключ%\n\n"
    "2. Откройте HAPP и выберите добавление или импорт подключения.\n"
    "3. Импортируйте ссылку из буфера обмена. Название команды может немного "
    "отличаться в версиях RU и Global.\n\n"
    "Также можно открыть сканер QR-кода в HAPP и отсканировать изображение выше.\n\n"
    "После добавления выберите подключение и включите VPN."
)

ONBOARDING_HAPP_CONNECTION_BUTTONS = json.dumps(
    [
        {"id": "btn_onboarding_happ_done", "label": "✅ VPN включён", "color": "success", "row": 0, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_happ_help", "label": "🧰 Не получается", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_happ_back_install", "label": "⬅️ Назад", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
    ],
    ensure_ascii=False,
)

DOWNLOAD_ANDROID_TEXT = (
    "🤖 <b>Android</b>\n\n"
    "Для Android подойдут Happ, v2rayNG или Hiddify.\n\n"
    "После установки приложения скопируйте ключ в боте и импортируйте его в клиент."
)

DOWNLOAD_ANDROID_BUTTONS = json.dumps(
    [
        {"id": "btn_happ_android",       "label": "Happ",            "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": HAPP_URL},
        {"id": "btn_v2rayng_android",    "label": "v2rayNG",         "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "url", "action_value": V2RAYNG_RELEASES_URL},
        {"id": "btn_hiddify_android",    "label": "Hiddify",         "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "url", "action_value": HIDDIFY_URL},
        {"id": "btn_back_downloads",     "label": "⬅️ Назад",        "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_clients"},
    ],
    ensure_ascii=False,
)

DOWNLOAD_WINDOWS_TEXT = (
    "💻 <b>Windows</b>\n\n"
    "Для Windows рекомендуем Happ или Hiddify.\n\n"
    "Скачивайте приложение только с официального сайта или страницы релизов проекта."
)

DOWNLOAD_WINDOWS_BUTTONS = json.dumps(
    [
        {"id": "btn_happ_windows",       "label": "Happ",             "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": HAPP_URL},
        {"id": "btn_hiddify_windows",    "label": "Hiddify Releases", "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "url", "action_value": HIDDIFY_RELEASES_URL},
        {"id": "btn_back_downloads",     "label": "⬅️ Назад",         "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_clients"},
    ],
    ensure_ascii=False,
)

DOWNLOAD_MACOS_TEXT = (
    "🖥 <b>macOS</b>\n\n"
    "Для macOS рекомендуем Happ или Hiddify.\n\n"
    "Скачивайте приложение только с официального сайта или страницы релизов проекта."
)

DOWNLOAD_MACOS_BUTTONS = json.dumps(
    [
        {"id": "btn_happ_macos",         "label": "Happ",             "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": HAPP_URL},
        {"id": "btn_hiddify_macos",      "label": "Hiddify Releases", "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "url", "action_value": HIDDIFY_RELEASES_URL},
        {"id": "btn_back_downloads",     "label": "⬅️ Назад",         "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_clients"},
    ],
    ensure_ascii=False,
)

ONBOARDING_READY_TEXT = (
    "✅ <b>Подключение готово</b>\n\n"
    "Осталось установить приложение и добавить в него ваше подключение. "
    "Обычно это занимает 2–3 минуты.\n\n"
    "Выберите устройство:"
)

ONBOARDING_READY_BUTTONS = json.dumps(
    [
        {"id": "btn_onboarding_ios", "label": "🍎 iPhone / iPad", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_android", "label": "🤖 Android", "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_windows", "label": "💻 Windows", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_macos", "label": "🖥 macOS", "color": "secondary", "row": 1, "col": 1, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_advanced", "label": "🛠 Для опытных пользователей", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_my_keys", "label": "🔑 Мои ключи", "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_my_keys"},
    ],
    ensure_ascii=False,
)

ONBOARDING_KEY_SELECT_TEXT = (
    "🧭 <b>Какой ключ настроить?</b>\n\n"
    "У вас несколько активных подключений. Выберите ключ, который хотите добавить на устройство."
)

ONBOARDING_KEY_SELECT_BUTTONS = json.dumps(
    [
        {"id": "btn_back_help", "label": "⬅️ Назад", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_help"},
    ],
    ensure_ascii=False,
)

ONBOARDING_NO_AVAILABLE_KEY_TEXT = (
    "🧭 <b>Нет ключа для настройки</b>\n\n"
    "Для запуска мастера нужен активный и настроенный VPN-ключ. "
    "Откройте «Мои ключи» или приобретите новый доступ."
)

ONBOARDING_NO_AVAILABLE_KEY_BUTTONS = json.dumps(
    [
        {"id": "btn_my_keys", "label": "🔑 Мои ключи", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_my_keys"},
        {"id": "btn_buy_key", "label": "💳 Купить ключ", "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_buy"},
        {"id": "btn_back_help", "label": "⬅️ Назад", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_help"},
    ],
    ensure_ascii=False,
)


def _onboarding_platform_text(platform_name: str, install_hint: str) -> str:
    return (
        f"📱 <b>Шаг 1 из 3 · {platform_name}</b>\n\n"
        "Установите <b>OneXray</b> — приложение для подключения WaveMesh VPN.\n\n"
        f"{install_hint}\n\n"
        "Когда приложение установится, вернитесь в бот и нажмите "
        "«Приложение установлено»."
    )


def _onboarding_platform_buttons(
    install_url: str,
    continue_button_id: str,
    alternate_button_id: str,
) -> str:
    return json.dumps(
        [
            {"id": "btn_onboarding_install", "label": "⬇️ Установить OneXray", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": install_url},
            {"id": continue_button_id, "label": "✅ Приложение установлено", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
            {"id": alternate_button_id, "label": "Другой вариант приложения", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
            {"id": "btn_onboarding_back", "label": "⬅️ Назад", "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        ],
        ensure_ascii=False,
    )


ONBOARDING_IOS_TEXT = _onboarding_platform_text(
    "iPhone / iPad",
    "Кнопка ниже откроет официальную страницу OneXray в App Store.",
)
ONBOARDING_ANDROID_TEXT = _onboarding_platform_text(
    "Android",
    "Кнопка ниже откроет официальную страницу OneXray в Google Play.",
)
ONBOARDING_WINDOWS_TEXT = _onboarding_platform_text(
    "Windows",
    "Кнопка ниже откроет официальную инструкцию установки OneXray для Windows.",
)
ONBOARDING_MACOS_TEXT = _onboarding_platform_text(
    "macOS",
    "Кнопка ниже откроет официальную страницу OneXray в App Store.",
)

ONBOARDING_IOS_BUTTONS = _onboarding_platform_buttons(
    ONEXRAY_APP_STORE_URL, "btn_onboarding_continue_ios", "btn_onboarding_alt_ios"
)
ONBOARDING_ANDROID_BUTTONS = _onboarding_platform_buttons(
    ONEXRAY_GOOGLE_PLAY_URL, "btn_onboarding_continue_android", "btn_onboarding_alt_android"
)
ONBOARDING_WINDOWS_BUTTONS = _onboarding_platform_buttons(
    ONEXRAY_INSTALL_URL, "btn_onboarding_continue_windows", "btn_onboarding_alt_windows"
)
ONBOARDING_MACOS_BUTTONS = _onboarding_platform_buttons(
    ONEXRAY_APP_STORE_URL, "btn_onboarding_continue_macos", "btn_onboarding_alt_macos"
)

ONBOARDING_CONNECTION_TEXT = (
    "🔗 <b>Шаг 2 из 3 · Добавьте подключение</b>\n\n"
    "1. Нажмите на ссылку ниже, чтобы скопировать её:\n"
    "%ключ%\n\n"
    "2. Откройте OneXray и нажмите <b>＋</b> на главном экране.\n"
    "3. Выберите <b>Read Clipboard</b>. Либо откройте сканер QR-кода "
    "и отсканируйте изображение выше.\n\n"
    "После добавления выберите подключение и включите VPN."
)

ONBOARDING_CONNECTION_ALTERNATIVE_TEXT = (
    "🔗 <b>Шаг 2 из 3 · Добавьте подключение</b>\n\n"
    "1. Откройте установленный VPN-клиент.\n"
    "2. Найдите добавление нового подключения: обычно это кнопка <b>＋</b>, "
    "<b>Добавить</b> или <b>Импортировать</b>.\n"
    "3. Импортируйте ссылку из буфера обмена:\n"
    "%ключ%\n\n"
    "Также можно открыть сканер QR-кода в приложении и отсканировать изображение выше. "
    "Названия пунктов могут отличаться в разных VPN-клиентах.\n\n"
    "После добавления выберите подключение и включите VPN."
)

ONBOARDING_TROUBLESHOOT_TEXT = (
    "🧰 <b>Что именно не получилось?</b>\n\n"
    "Выберите ближайший вариант — бот вернёт вас к нужному шагу.\n\n"
    "Если подключение добавилось, но сайты не открываются, сначала выключите VPN, "
    "смените Wi‑Fi на мобильную сеть или наоборот и включите VPN снова."
)

ONBOARDING_TROUBLESHOOT_BUTTONS = json.dumps(
    [
        {"id": "btn_onboarding_retry_install", "label": "Не установилось приложение", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_retry_connection", "label": "Не добавилось подключение", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_issue_enable", "label": "VPN не включается", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_issue_no_traffic", "label": "VPN включён, но сайты не открываются", "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_issue_mobile", "label": "Не работает по мобильной сети", "color": "secondary", "row": 4, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_issue_stale", "label": "Раньше работало, теперь нет", "color": "secondary", "row": 5, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_onboarding_support", "label": "💬 Написать в поддержку", "color": "secondary", "row": 6, "col": 0, "is_hidden": False, "action_type": "url", "action_value": SUPPORT_URL},
    ],
    ensure_ascii=False,
)


def _onboarding_issue_buttons(*, include_mobile_issue: bool = False) -> str:
    buttons = [
        {"id": "btn_onboarding_retry_connection", "label": "🔗 Показать подключение снова", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
    ]
    next_row = 1
    if include_mobile_issue:
        buttons.append(
            {"id": "btn_onboarding_issue_mobile", "label": "Не работает только по мобильной сети", "color": "secondary", "row": next_row, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None}
        )
        next_row += 1
    buttons.extend([
        {"id": "btn_onboarding_support", "label": "💬 Написать в поддержку", "color": "secondary", "row": next_row, "col": 0, "is_hidden": False, "action_type": "url", "action_value": SUPPORT_URL},
        {"id": "btn_onboarding_troubleshoot_back", "label": "⬅️ Назад", "color": "secondary", "row": next_row + 1, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
    ])
    return json.dumps(buttons, ensure_ascii=False)


ONBOARDING_ISSUE_ENABLE_TEXT = (
    "⚡ <b>VPN не включается</b>\n\n"
    "1. Убедитесь, что добавленное подключение выбрано в приложении.\n"
    "2. Нажмите кнопку включения VPN ещё раз.\n"
    "3. Если телефон спрашивает разрешение на добавление VPN-конфигурации — разрешите.\n"
    "4. Временно выключите другие VPN, прокси и приложения-фильтры.\n\n"
    "После этого полностью закройте VPN-клиент, откройте его снова и повторите подключение."
)

ONBOARDING_ISSUE_NO_TRAFFIC_TEXT = (
    "🌐 <b>VPN включён, но сайты не открываются</b>\n\n"
    "1. Выключите VPN на несколько секунд и включите снова.\n"
    "2. Переключитесь с Wi‑Fi на мобильную сеть или наоборот.\n"
    "3. Убедитесь, что одновременно не включён другой VPN или прокси.\n"
    "4. Проверьте несколько разных сайтов или приложений.\n\n"
    "Если проблема только на мобильной сети, выберите соответствующий пункт ниже."
)

ONBOARDING_ISSUE_MOBILE_TEXT = (
    "📶 <b>Не работает по мобильной сети</b>\n\n"
    "1. Выключите Wi‑Fi и убедитесь, что мобильный интернет работает без VPN.\n"
    "2. Включите авиарежим на 10 секунд, затем выключите его.\n"
    "3. Откройте VPN-клиент и подключитесь снова.\n"
    "4. Проверьте, разрешена ли приложению работа через мобильные данные.\n\n"
    "Если по Wi‑Fi подключение работает, а по мобильной сети нет, сообщите об этом поддержке."
)

ONBOARDING_ISSUE_STALE_TEXT = (
    "🔄 <b>Раньше работало, теперь нет</b>\n\n"
    "1. Перезапустите VPN-клиент и обновите подключение или подписку внутри приложения.\n"
    "2. Переключите сеть между Wi‑Fi и мобильным интернетом.\n"
    "3. Если профиль не обновляется, добавьте подключение повторно по кнопке ниже.\n\n"
    "Не удаляйте старый профиль, пока новый не появится в приложении."
)

ONBOARDING_ISSUE_ENABLE_BUTTONS = _onboarding_issue_buttons()
ONBOARDING_ISSUE_NO_TRAFFIC_BUTTONS = _onboarding_issue_buttons(include_mobile_issue=True)
ONBOARDING_ISSUE_MOBILE_BUTTONS = _onboarding_issue_buttons()
ONBOARDING_ISSUE_STALE_BUTTONS = _onboarding_issue_buttons()

ONBOARDING_SUCCESS_TEXT = (
    "🎉 <b>Готово!</b>\n\n"
    "Подключение добавлено. Откройте выбранный VPN-клиент, выберите подключение "
    "и включите VPN.\n\n"
    "Если сайты открываются — настройка завершена."
)

ONBOARDING_SUCCESS_BUTTONS = json.dumps(
    [
        {"id": "btn_onboarding_problem", "label": "🧰 Не работает", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "system", "action_value": None},
        {"id": "btn_my_keys", "label": "🔑 Мои ключи", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_my_keys"},
        {"id": "btn_back_main", "label": "🏠 На главную", "color": "secondary", "row": 1, "col": 1, "is_hidden": False, "action_type": "internal", "action_value": "cmd_back_main"},
    ],
    ensure_ascii=False,
)

DOCUMENTS_TEXT = (
    "📄 <b>Документы WaveMesh VPN</b>\n\n"
    "Перед использованием сервиса рекомендуем ознакомиться с основными документами.\n\n"
    "Здесь собраны:\n\n"
    "• Пользовательское соглашение — условия использования сервиса.\n"
    "• Политика конфиденциальности — сведения об обработке пользовательских данных.\n"
    "• Правила возврата денежных средств — порядок рассмотрения обращений по вопросам возврата оплаты.\n\n"
    f"Если у вас возникли вопросы, вы всегда можете обратиться в поддержку {SUPPORT_USERNAME}."
)

DOCUMENTS_BUTTONS = json.dumps(
    [
        {"id": "btn_privacy_policy", "label": "🔒 Политика конфиденциальности", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": PRIVACY_POLICY_URL},
        {"id": "btn_user_agreement", "label": "📄 Пользовательское соглашение", "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "url", "action_value": USER_AGREEMENT_URL},
        {"id": "btn_refund_policy", "label": "💳 Правила возврата", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "url", "action_value": REFUND_POLICY_URL},
        {"id": "btn_back_main",      "label": "🈴 На главную",                  "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_back_main"},
    ],
    ensure_ascii=False,
)

PREPAYMENT_TEXT = (
    "💳 <b>Купить ключ WaveMesh VPN</b>\n\n"
    "🔐 <b>Что вы получаете:</b>\n"
    "• доступ к VPN-серверам и поддерживаемым протоколам;\n"
    "• личный ключ для подключения;\n"
    "• управление подпиской прямо в Telegram;\n"
    "• поддержку по вопросам подключения.\n\n"
    "⚠️ <b>Важно:</b>\n"
    "• ключ предназначен для личного использования;\n"
    "• стабильность соединения может зависеть от устройства, сети и выбранного клиента;\n"
    "• если возникнут трудности с подключением, напишите в поддержку.\n\n"
    "<i>Выберите удобный способ оплаты ниже.</i>"
)

TRIAL_TEXT = (
    "🎁 <b>Пробный доступ WaveMesh VPN</b>\n\n"
    "Пробный период позволяет проверить подключение и скорость перед покупкой.\n\n"
    "Нажмите кнопку ниже, чтобы активировать тестовый доступ.\n\n"
    "<i>Пробный период предоставляется один раз на аккаунт.</i>"
)

PAGE_DEFAULTS = {
    "main": (MAIN_TEXT, MAIN_BUTTONS, None, None),
    "help": (HELP_TEXT, HELP_BUTTONS, None, None),
    "download_clients": (DOWNLOAD_CLIENTS_TEXT, DOWNLOAD_CLIENTS_BUTTONS, None, None),
    "download_ios": (DOWNLOAD_IOS_TEXT, DOWNLOAD_IOS_BUTTONS, None, None),
    "download_android": (DOWNLOAD_ANDROID_TEXT, DOWNLOAD_ANDROID_BUTTONS, None, None),
    "download_windows": (DOWNLOAD_WINDOWS_TEXT, DOWNLOAD_WINDOWS_BUTTONS, None, None),
    "download_macos": (DOWNLOAD_MACOS_TEXT, DOWNLOAD_MACOS_BUTTONS, None, None),
    "onboarding_ready": (ONBOARDING_READY_TEXT, ONBOARDING_READY_BUTTONS, None, None),
    "onboarding_key_select": (ONBOARDING_KEY_SELECT_TEXT, ONBOARDING_KEY_SELECT_BUTTONS, None, None),
    "onboarding_no_available_key": (ONBOARDING_NO_AVAILABLE_KEY_TEXT, ONBOARDING_NO_AVAILABLE_KEY_BUTTONS, None, None),
    "onboarding_ios": (ONBOARDING_IOS_TEXT, ONBOARDING_IOS_BUTTONS, None, None),
    "onboarding_android": (ONBOARDING_ANDROID_TEXT, ONBOARDING_ANDROID_BUTTONS, None, None),
    "onboarding_windows": (ONBOARDING_WINDOWS_TEXT, ONBOARDING_WINDOWS_BUTTONS, None, None),
    "onboarding_macos": (ONBOARDING_MACOS_TEXT, ONBOARDING_MACOS_BUTTONS, None, None),
    "onboarding_connection": (ONBOARDING_CONNECTION_TEXT, None, None, None),
    "onboarding_connection_alternative": (ONBOARDING_CONNECTION_ALTERNATIVE_TEXT, None, None, None),
    "onboarding_happ_region": (ONBOARDING_HAPP_REGION_TEXT, ONBOARDING_HAPP_REGION_BUTTONS, None, None),
    "onboarding_happ_install_ru": (ONBOARDING_HAPP_INSTALL_RU_TEXT, ONBOARDING_HAPP_INSTALL_RU_BUTTONS, None, None),
    "onboarding_happ_install_global": (ONBOARDING_HAPP_INSTALL_GLOBAL_TEXT, ONBOARDING_HAPP_INSTALL_GLOBAL_BUTTONS, None, None),
    "onboarding_happ_connection": (ONBOARDING_HAPP_CONNECTION_TEXT, ONBOARDING_HAPP_CONNECTION_BUTTONS, None, None),
    "onboarding_troubleshoot": (ONBOARDING_TROUBLESHOOT_TEXT, ONBOARDING_TROUBLESHOOT_BUTTONS, None, None),
    "onboarding_issue_enable": (ONBOARDING_ISSUE_ENABLE_TEXT, ONBOARDING_ISSUE_ENABLE_BUTTONS, None, None),
    "onboarding_issue_no_traffic": (ONBOARDING_ISSUE_NO_TRAFFIC_TEXT, ONBOARDING_ISSUE_NO_TRAFFIC_BUTTONS, None, None),
    "onboarding_issue_mobile": (ONBOARDING_ISSUE_MOBILE_TEXT, ONBOARDING_ISSUE_MOBILE_BUTTONS, None, None),
    "onboarding_issue_stale": (ONBOARDING_ISSUE_STALE_TEXT, ONBOARDING_ISSUE_STALE_BUTTONS, None, None),
    "onboarding_success": (ONBOARDING_SUCCESS_TEXT, ONBOARDING_SUCCESS_BUTTONS, None, None),
    "documents": (DOCUMENTS_TEXT, DOCUMENTS_BUTTONS, None, None),
    "prepayment": (PREPAYMENT_TEXT, None, None, None),
    "trial": (TRIAL_TEXT, None, None, None),
}

LEGACY_MARKERS = (
    "plushkin",
    "Yadreno",
    "yadreno",
    "VPN-бот",
    "telegra.ph/Kak-nastroit-VPN-Gajd-za-2-minuty-01-23",
    "telegra.ph/Politika-konfidencialnosti-WaveMesh-VPN\"",
    "telegra.ph/Polzovatelskoe-soglashenie-WaveMesh-VPN\"",
)


def _needs_replacement(value: str | None) -> bool:
    if not value:
        return True
    return any(marker in value for marker in LEGACY_MARKERS)


ONBOARDING_ALT_BUTTON_IDS = {
    "onboarding_ios": "btn_onboarding_alt_ios",
    "onboarding_android": "btn_onboarding_alt_android",
    "onboarding_windows": "btn_onboarding_alt_windows",
    "onboarding_macos": "btn_onboarding_alt_macos",
}

ONBOARDING_PLAIN_BUTTON_IDS = {
    "onboarding_ready": {
        "btn_onboarding_ios",
        "btn_onboarding_android",
    },
    "onboarding_ios": {
        "btn_onboarding_install",
        "btn_onboarding_continue_ios",
    },
    "onboarding_android": {
        "btn_onboarding_install",
        "btn_onboarding_continue_android",
    },
    "onboarding_windows": {
        "btn_onboarding_install",
        "btn_onboarding_continue_windows",
    },
    "onboarding_macos": {
        "btn_onboarding_install",
        "btn_onboarding_continue_macos",
    },
    "onboarding_troubleshoot": {
        "btn_onboarding_support",
    },
}

ONBOARDING_ISSUE_BUTTON_IDS = {
    "btn_onboarding_issue_enable",
    "btn_onboarding_issue_no_traffic",
    "btn_onboarding_issue_mobile",
    "btn_onboarding_issue_stale",
}


def _migrate_onboarding_alt_button(page_key: str, buttons_json: str | None) -> str | None:
    """Move old onboarding alternative buttons out of the global download flow."""
    new_button_id = ONBOARDING_ALT_BUTTON_IDS.get(page_key)
    if not new_button_id or not buttons_json:
        return buttons_json

    try:
        buttons = json.loads(buttons_json)
    except (TypeError, json.JSONDecodeError):
        return buttons_json

    changed = False
    for button in buttons if isinstance(buttons, list) else []:
        if not isinstance(button, dict):
            continue
        if button.get("id") != "btn_onboarding_alternative":
            continue

        button["id"] = new_button_id
        button["action_type"] = "system"
        button["action_value"] = None
        changed = True

    if not changed:
        return buttons_json
    return json.dumps(buttons, ensure_ascii=False)


def _migrate_onboarding_button_ux(page_key: str, buttons_json: str | None) -> str | None:
    """Normalize onboarding buttons for Telegram clients and remove stale actions."""
    if not buttons_json:
        return buttons_json

    plain_button_ids = ONBOARDING_PLAIN_BUTTON_IDS.get(page_key, set())
    remove_my_keys = page_key == "onboarding_troubleshoot"
    if not plain_button_ids and not remove_my_keys:
        return buttons_json

    try:
        buttons = json.loads(buttons_json)
    except (TypeError, json.JSONDecodeError):
        return buttons_json
    if not isinstance(buttons, list):
        return buttons_json

    changed = False
    migrated_buttons = []
    for button in buttons:
        if not isinstance(button, dict):
            migrated_buttons.append(button)
            continue

        button_id = button.get("id")
        if remove_my_keys and button_id == "btn_my_keys":
            changed = True
            continue
        if button_id in plain_button_ids and button.get("color") != "secondary":
            button["color"] = "secondary"
            changed = True
        migrated_buttons.append(button)

    if not changed:
        return buttons_json
    return json.dumps(migrated_buttons, ensure_ascii=False)


def _migrate_onboarding_troubleshoot_buttons(
    page_key: str,
    buttons_json: str | None,
) -> str | None:
    """Expand only the legacy two-option troubleshooting keyboard once."""
    if page_key != "onboarding_troubleshoot" or not buttons_json:
        return buttons_json

    try:
        buttons = json.loads(buttons_json)
    except (TypeError, json.JSONDecodeError):
        return buttons_json
    if not isinstance(buttons, list):
        return buttons_json

    existing_ids = {
        button.get("id")
        for button in buttons
        if isinstance(button, dict)
    }
    if existing_ids & ONBOARDING_ISSUE_BUTTON_IDS:
        return buttons_json
    if not {
        "btn_onboarding_retry_install",
        "btn_onboarding_retry_connection",
    }.issubset(existing_ids):
        return buttons_json

    default_buttons = json.loads(ONBOARDING_TROUBLESHOOT_BUTTONS)
    issue_buttons = [
        button
        for button in default_buttons
        if button.get("id") in ONBOARDING_ISSUE_BUTTON_IDS
    ]
    for button in buttons:
        if isinstance(button, dict) and button.get("id") == "btn_onboarding_support":
            button["row"] = 6

    buttons.extend(issue_buttons)
    return json.dumps(buttons, ensure_ascii=False)


def _migrate_download_ios_happ_flow(
    page_key: str,
    buttons_json: str | None,
) -> str | None:
    """Remove the legacy HAPP link and add onboarding-aware fallback actions."""
    if page_key != "download_ios" or not buttons_json:
        return buttons_json

    try:
        buttons = json.loads(buttons_json)
    except (TypeError, json.JSONDecodeError):
        return buttons_json
    if not isinstance(buttons, list):
        return buttons_json

    existing_ids = {
        button.get("id")
        for button in buttons
        if isinstance(button, dict)
    }
    if "btn_happ_ios" not in existing_ids:
        return buttons_json

    buttons = [
        button
        for button in buttons
        if not isinstance(button, dict) or button.get("id") != "btn_happ_ios"
    ]
    defaults = json.loads(DOWNLOAD_IOS_BUTTONS)
    required_ids = {
        "btn_onboarding_alt_continue_ios",
        "btn_onboarding_alt_other_back",
    }
    buttons.extend(
        button for button in defaults if button.get("id") in required_ids
    )
    return json.dumps(buttons, ensure_ascii=False)


def _migrate_help_onboarding_button(page_key: str, buttons_json: str | None) -> str | None:
    """Replace the legacy client-download entry with the guided setup entry."""
    if page_key != "help" or not buttons_json:
        return buttons_json

    try:
        buttons = json.loads(buttons_json)
    except (TypeError, json.JSONDecodeError):
        return buttons_json
    if not isinstance(buttons, list):
        return buttons_json

    changed = False
    for button in buttons:
        if not isinstance(button, dict):
            continue
        if (
            button.get("id") != "btn_download_clients"
            and button.get("action_value") != "cmd_download_clients"
        ):
            continue

        button.update({
            "id": "btn_onboarding_start",
            "label": "🧭 Настроить VPN",
            "color": "secondary",
            "action_type": "internal",
            "action_value": "cmd_onboarding_start",
        })
        changed = True

    if not changed:
        return buttons_json
    return json.dumps(buttons, ensure_ascii=False)


def _migrate_help_onboarding_text(page_key: str, text_custom: str | None) -> str | None:
    """Replace only the known legacy Help copy that points to the old flow."""
    if page_key != "help" or not text_custom:
        return text_custom
    legacy_help_markers = (
        "Начните с раздела загрузки клиента",
        "Скачать VPN-клиент",
    )
    if any(marker in text_custom for marker in legacy_help_markers):
        return HELP_TEXT
    return text_custom


def _migrate_download_ios_happ_text(
    page_key: str,
    text_custom: str | None,
) -> str | None:
    """Replace only the known legacy copy that recommends HAPP in the fallback list."""
    if page_key != "download_ios" or not text_custom:
        return text_custom
    if "Happ, Streisand" in text_custom or "HAPP, Streisand" in text_custom:
        return DOWNLOAD_IOS_TEXT
    return text_custom


def _migrate_onboarding_success_text(page_key: str, text_custom: str | None) -> str | None:
    """Make the known OneXray-specific success copy client-neutral."""
    if page_key != "onboarding_success" or not text_custom:
        return text_custom
    if "Откройте OneXray" in text_custom:
        return ONBOARDING_SUCCESS_TEXT
    return text_custom


def _update_page(
    page_key: str,
    text: str,
    buttons: str | None,
    image: str | None = None,
    media_type: str | None = None,
) -> None:
    with get_db() as conn:
        if buttons is None:
            existing = conn.execute(
                "SELECT buttons_default FROM pages WHERE page_key = ?",
                (page_key,),
            ).fetchone()
            buttons_to_insert = existing["buttons_default"] if existing else "[]"
        else:
            buttons_to_insert = buttons

        conn.execute(
            """
            INSERT OR IGNORE INTO pages (
                page_key,
                text_default,
                buttons_default,
                image_default,
                media_type_default
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (page_key, text, buttons_to_insert, image, media_type),
        )

        row = conn.execute(
            """
            SELECT text_custom, buttons_custom, buttons_default
            FROM pages
            WHERE page_key = ?
            """,
            (page_key,),
        ).fetchone()

        text_custom = row["text_custom"] if row else None
        buttons_custom = row["buttons_custom"] if row else None
        current_buttons_default = row["buttons_default"] if row else buttons_to_insert
        next_buttons = buttons if buttons is not None else current_buttons_default
        next_buttons_custom = _migrate_onboarding_alt_button(page_key, buttons_custom)
        next_buttons_custom = _migrate_onboarding_button_ux(page_key, next_buttons_custom)
        next_buttons_custom = _migrate_onboarding_troubleshoot_buttons(
            page_key,
            next_buttons_custom,
        )
        next_buttons_custom = _migrate_download_ios_happ_flow(
            page_key,
            next_buttons_custom,
        )
        next_buttons_custom = _migrate_help_onboarding_button(page_key, next_buttons_custom)
        next_text_custom = _migrate_help_onboarding_text(page_key, text_custom)
        next_text_custom = _migrate_download_ios_happ_text(
            page_key,
            next_text_custom,
        )
        next_text_custom = _migrate_onboarding_success_text(page_key, next_text_custom)

        update_custom_text = (
            _needs_replacement(text_custom)
            or next_text_custom != text_custom
        )
        update_custom_buttons = (
            buttons is not None
            and (
                _needs_replacement(buttons_custom)
                or next_buttons_custom != buttons_custom
            )
        )

        conn.execute(
            """
            UPDATE pages
            SET text_default = ?,
                buttons_default = ?,
                image_default = ?,
                media_type_default = ?,
                text_custom = CASE WHEN ? THEN ? ELSE text_custom END,
                buttons_custom = CASE WHEN ? THEN ? ELSE buttons_custom END,
                updated_at = CURRENT_TIMESTAMP
            WHERE page_key = ?
            """,
            (
                text,
                next_buttons,
                image,
                media_type,
                1 if update_custom_text else 0,
                next_text_custom if next_text_custom != text_custom else text,
                1 if update_custom_buttons else 0,
                next_buttons_custom if next_buttons_custom != buttons_custom else next_buttons,
                page_key,
            ),
        )


def apply_wavemesh_branding_defaults() -> None:
    """Apply WaveMesh user-facing defaults to the pages table."""
    for page_key, (text, buttons, image, media_type) in PAGE_DEFAULTS.items():
        _update_page(page_key, text, buttons, image, media_type)

    logger.info("WaveMesh branding defaults applied to core user pages")
