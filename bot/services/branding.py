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

# Pages whose text/buttons are product-critical and should always follow
# branding.py rather than stale admin-customized DB values.
FORCE_REFRESH_PAGES = {
    "documents",
    "help",
    "download_clients",
    "download_ios",
    "download_android",
    "download_windows",
    "download_macos",
}

MAIN_TEXT = (
    "🌊 <b>Добро пожаловать в WaveMesh VPN</b>\n\n"
    "Быстрый и стабильный VPN-доступ для ваших устройств.\n"
    "Выберите тариф, получите ключ и подключайтесь за пару минут.\n\n"
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
    "main": (MAIN_TEXT, MAIN_BUTTONS),
    "help": (HELP_TEXT, HELP_BUTTONS),
    "download_clients": (DOWNLOAD_CLIENTS_TEXT, DOWNLOAD_CLIENTS_BUTTONS),
    "download_ios": (DOWNLOAD_IOS_TEXT, DOWNLOAD_IOS_BUTTONS),
    "download_android": (DOWNLOAD_ANDROID_TEXT, DOWNLOAD_ANDROID_BUTTONS),
    "download_windows": (DOWNLOAD_WINDOWS_TEXT, DOWNLOAD_WINDOWS_BUTTONS),
    "download_macos": (DOWNLOAD_MACOS_TEXT, DOWNLOAD_MACOS_BUTTONS),
    "documents": (DOCUMENTS_TEXT, DOCUMENTS_BUTTONS),
    "prepayment": (PREPAYMENT_TEXT, None),
    "trial": (TRIAL_TEXT, None),
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


def _update_page(page_key: str, text: str, buttons: str | None) -> None:
    with get_db() as conn:
        force_refresh = page_key in FORCE_REFRESH_PAGES

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
            INSERT OR IGNORE INTO pages (page_key, text_default, buttons_default)
            VALUES (?, ?, ?)
            """,
            (page_key, text, buttons_to_insert),
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

        update_custom_text = force_refresh or _needs_replacement(text_custom)
        update_custom_buttons = buttons is not None and (force_refresh or _needs_replacement(buttons_custom))

        conn.execute(
            """
            UPDATE pages
            SET text_default = ?,
                buttons_default = ?,
                text_custom = CASE WHEN ? THEN ? ELSE text_custom END,
                buttons_custom = CASE WHEN ? THEN ? ELSE buttons_custom END,
                updated_at = CURRENT_TIMESTAMP
            WHERE page_key = ?
            """,
            (
                text,
                next_buttons,
                1 if update_custom_text else 0,
                text,
                1 if update_custom_buttons else 0,
                next_buttons,
                page_key,
            ),
        )


def apply_wavemesh_branding_defaults() -> None:
    """Apply WaveMesh user-facing defaults to the pages table."""
    for page_key, (text, buttons) in PAGE_DEFAULTS.items():
        _update_page(page_key, text, buttons)

    logger.info("WaveMesh branding defaults applied to core user pages")
