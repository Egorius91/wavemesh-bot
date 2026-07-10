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
    "Начните с раздела загрузки клиента, затем откройте «Мои ключи», скопируйте ссылку подключения "
    "и импортируйте её в выбранное приложение."
)

HELP_BUTTONS = json.dumps(
    [
        {"id": "btn_download_clients", "label": "📱 Скачать VPN-клиент", "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_clients"},
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
    "🍎 <b>iPhone / iPad</b>\n\n"
    "Для устройств Apple можно использовать Happ, Streisand или V2Box.\n\n"
    "Если приложение не отображается в App Store, проверьте регион Apple ID. "
    "Нажмите кнопку ниже, чтобы открыть подробную инструкцию."
)

DOWNLOAD_IOS_BUTTONS = json.dumps(
    [
        {"id": "btn_happ_ios",          "label": "Happ",                         "color": "secondary", "row": 0, "col": 0, "is_hidden": False, "action_type": "url", "action_value": HAPP_URL},
        {"id": "btn_streisand_ios",     "label": "Streisand",                    "color": "secondary", "row": 0, "col": 1, "is_hidden": False, "action_type": "url", "action_value": STREISAND_IOS_URL},
        {"id": "btn_v2box_ios",         "label": "V2Box",                        "color": "secondary", "row": 1, "col": 0, "is_hidden": False, "action_type": "url", "action_value": V2BOX_IOS_URL},
        {"id": "btn_appstore_region",   "label": "🍏 Как изменить регион App Store", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "url", "action_value": APP_STORE_REGION_GUIDE_URL},
        {"id": "btn_back_downloads",    "label": "⬅️ Назад",                     "color": "secondary", "row": 3, "col": 0, "is_hidden": False, "action_type": "internal", "action_value": "cmd_download_clients"},
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
        {"id": "btn_onboarding_support", "label": "💬 Написать в поддержку", "color": "secondary", "row": 2, "col": 0, "is_hidden": False, "action_type": "url", "action_value": SUPPORT_URL},
    ],
    ensure_ascii=False,
)

ONBOARDING_SUCCESS_TEXT = (
    "🎉 <b>Готово!</b>\n\n"
    "Подключение добавлено. Откройте OneXray, выберите его на главном экране "
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
    "onboarding_ios": (ONBOARDING_IOS_TEXT, ONBOARDING_IOS_BUTTONS, None, None),
    "onboarding_android": (ONBOARDING_ANDROID_TEXT, ONBOARDING_ANDROID_BUTTONS, None, None),
    "onboarding_windows": (ONBOARDING_WINDOWS_TEXT, ONBOARDING_WINDOWS_BUTTONS, None, None),
    "onboarding_macos": (ONBOARDING_MACOS_TEXT, ONBOARDING_MACOS_BUTTONS, None, None),
    "onboarding_connection": (ONBOARDING_CONNECTION_TEXT, None, None, None),
    "onboarding_troubleshoot": (ONBOARDING_TROUBLESHOOT_TEXT, ONBOARDING_TROUBLESHOOT_BUTTONS, None, None),
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

        update_custom_text = _needs_replacement(text_custom)
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
                text,
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
